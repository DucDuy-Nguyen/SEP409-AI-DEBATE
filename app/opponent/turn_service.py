"""
Luot tranh luan (Giai doan 3a): POST /opponent/sessions/{external_session_id}/turns.

Main Flow gui turn_index (luot cua AI) + moi bai noi cua learner KE TU luot AI truoc do. Service luu snapshot bai
learner vao opponent_speeches, sinh bai noi AI bang bo sinh theo TURN_GENERATOR_VERSION, luu bai noi AI +
opponent_turns + log moi lan goi LLM (opponent_llm_calls, purpose=turn, turn_id).

Kiem tra (xem generate_turn): 400 sai format / sai nguoi noi; 409 session chua READY, thieu luot truoc, bai learner
khac snapshot da luu, luot AI da co nhung request khac. Idempotent: luot AI da co + bai learner khop -> tra lai ket
qua cu, KHONG goi LLM.
"""
import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.llm.client import LLMClient
from app.opponent import match_format as mf
from app.opponent.match_format import InvalidTurnError, RoundType, Speaker, TurnMode
from app.opponent.models import (
    LLMCallPurpose,
    OpponentLLMCall,
    OpponentSession,
    OpponentSpeech,
    OpponentTurn,
    SessionStatus,
)
from app.opponent.schemas import CreateTurnRequest
from app.opponent.service import LLMCallError, get_case_file, get_session_by_external_id
from app.opponent.turn_generators import (
    Ledger,
    SpeechItem,
    TurnCall,
    TurnContext,
    TurnFailure,
    BASELINE_V1,
    TurnResult,
    get_turn_generator,
)

logger = logging.getLogger(__name__)


class TurnRequestError(ValueError):
    """Request sai format tran / sai nguoi noi -> 400."""


class TurnConflictError(Exception):
    """Trang thai khong cho phep (chua READY, thieu luot truoc, khac snapshot) -> 409."""


class TurnGenerationError(Exception):
    """Bo sinh tra ve bai noi khong hop le sau moi lan thu -> 502."""


class TurnBudgetExceededError(Exception):
    """Sinh 1 luot vuot TURN_TOTAL_BUDGET_SECONDS -> 504."""


@dataclass
class TurnOutcome:
    turn_index: int
    round_type: RoundType
    mode: TurnMode
    speech_text: str


def _validate_request(session: OpponentSession, req: CreateTurnRequest) -> None:
    """Chi kiem tra theo format tran (khong DB). Loi -> TurnRequestError (400)."""
    try:
        mf.turn_mode(req.turn_index, session.ai_side)  # ton tai + la luot cua AI
    except InvalidTurnError as e:
        raise TurnRequestError(str(e)) from e
    seen: set[int] = set()
    for sp in req.new_learner_speeches:
        try:
            spec = mf.turn_spec(sp.turn_index)
        except InvalidTurnError as e:
            raise TurnRequestError(f"new_learner_speeches: {e}") from e
        if spec.round_type != sp.round_type:
            raise TurnRequestError(
                f"new_learner_speeches: luot {sp.turn_index} la {spec.round_type.value}, khong phai {sp.round_type.value}"
            )
        if mf.speaker_of(sp.turn_index, session.ai_side) != Speaker.LEARNER:
            raise TurnRequestError(f"new_learner_speeches: luot {sp.turn_index} la luot cua AI, khong phai learner")
        if sp.turn_index >= req.turn_index:
            raise TurnRequestError(
                f"new_learner_speeches: luot {sp.turn_index} khong nam truoc luot AI {req.turn_index}"
            )
        if sp.turn_index in seen:
            raise TurnRequestError(f"new_learner_speeches: luot {sp.turn_index} bi gui 2 lan")
        seen.add(sp.turn_index)


async def _speeches(db: AsyncSession, session_id: uuid.UUID) -> dict[int, OpponentSpeech]:
    rows = await db.scalars(
        select(OpponentSpeech).where(OpponentSpeech.session_id == session_id).execution_options(populate_existing=True)
    )
    return {s.turn_index: s for s in rows}


async def _existing_turn(db: AsyncSession, session_id: uuid.UUID, turn_index: int) -> OpponentTurn | None:
    return await db.scalar(
        select(OpponentTurn)
        .where(OpponentTurn.session_id == session_id, OpponentTurn.turn_index == turn_index)
        .execution_options(populate_existing=True)
    )


def _snapshot_mismatches(req: CreateTurnRequest, stored: dict[int, OpponentSpeech]) -> list[int]:
    """Luot learner trong request da luu nhung KHAC noi dung da luu."""
    return [sp.turn_index for sp in req.new_learner_speeches if sp.turn_index in stored and stored[sp.turn_index].text != sp.text]


async def _replay_existing(
    db: AsyncSession, turn: OpponentTurn, req: CreateTurnRequest, stored: dict[int, OpponentSpeech]
) -> TurnOutcome:
    """Luot AI da co: request phai khop snapshot (moi bai learner gui kem da luu, cung noi dung) -> ket qua cu."""
    missing = [sp.turn_index for sp in req.new_learner_speeches if sp.turn_index not in stored]
    different = _snapshot_mismatches(req, stored)
    if missing or different:
        raise TurnConflictError(
            f"Luot {turn.turn_index} da duoc sinh voi bai noi learner khac request "
            f"(khac noi dung: {different or '-'}, chua tung gui: {missing or '-'})"
        )
    speech = await db.get(OpponentSpeech, turn.speech_id)
    return TurnOutcome(turn.turn_index, turn.round_type, turn.mode, speech.text)


def _llm_call_rows(session_id: uuid.UUID, calls: list[TurnCall], turn_id: uuid.UUID | None) -> list[OpponentLLMCall]:
    return [
        OpponentLLMCall(
            session_id=session_id,
            turn_id=turn_id,
            purpose=c.purpose,
            attempt=c.attempt,
            prompt_version=c.prompt_version,
            llm_provider=c.llm_provider,
            llm_model=c.llm_model,
            temperature=c.temperature,
            system_prompt=c.system_prompt,
            user_prompt=c.user_prompt,
            raw_output=c.raw_output,
            success=c.success,
            error=c.error,
            latency_ms=c.latency_ms,
            failure_kind=c.failure_kind,
            tokens_in=c.tokens_in,
            tokens_out=c.tokens_out,
            rate_limit_wait_ms=c.rate_limit_wait_ms,
            retry_feedback=c.retry_feedback,
            key_repairs=c.key_repairs,
            vague_evidence=c.vague_evidence,
            speech_checks=c.speech_checks,
            reasoning_tokens=c.reasoning_tokens,
            finish_reason=c.finish_reason,
            reasoning_effort=c.reasoning_effort,
            reviewer_verdict=c.reviewer_verdict,
            reviewer_detail=c.reviewer_detail,
        )
        for c in calls
    ]


async def build_ledger(db: AsyncSession, session_id: uuid.UUID, before_turn: int) -> Ledger:
    """
    Dung lai tu opponent_turns MOI luot (khong luu bang rieng): learner_claims, ai_points, target_premise cua cac luot
    AI truoc before_turn, theo thu tu luot. Luot baseline (cac cot NULL) bi bo qua.
    """
    turns = (await db.scalars(
        select(OpponentTurn)
        .where(OpponentTurn.session_id == session_id, OpponentTurn.turn_index < before_turn)
        .order_by(OpponentTurn.turn_index)
    )).all()
    ledger = Ledger()
    for t in turns:
        ledger.learner_claims += [c for c in (t.learner_claims or []) if isinstance(c, str)]
        ledger.ai_points += [p for p in (t.ai_points or []) if isinstance(p, str)]
        if t.target_premise:
            ledger.attacked_premises.append(t.target_premise)
    return ledger


def _sum(values: list[int | None]) -> int | None:
    known = [v for v in values if v is not None]
    return sum(known) if known else None


async def _run_generator(
    context: TurnContext, mode: TurnMode, client: LLMClient, settings: Settings, reviewer_client: LLMClient | None = None
) -> TurnResult:
    """Chay bo sinh trong TURN_TOTAL_BUDGET_SECONDS. Het budget -> TurnResult that bai (failure budget_exceeded)."""
    generator = get_turn_generator(settings, client, reviewer_client)
    try:
        return await asyncio.wait_for(generator.generate(mode, context), timeout=settings.turn_total_budget_seconds)
    except TimeoutError:
        # Thread dang goi LLM (neu co) KHONG bi huy, ket qua bi bo qua (giong Case Planning).
        caller = generator.caller
        error = f"{TurnFailure.BUDGET_EXCEEDED}: het {settings.turn_total_budget_seconds}s cho luot {context.turn_index}"
        # Lan goi dang cho LLM luc bi huy van duoc LLMCaller ghi (finally) nhung chua co ket qua / loi -> danh dau.
        for call in caller.calls:
            if not call.success and call.error is None:
                call.error, call.failure_kind = error, TurnFailure.BUDGET_EXCEEDED
        return TurnResult(
            text=None, mode=mode, generator_version=generator.version, llm_provider=client.provider,
            llm_model=client.model, temperature=generator.temperature, calls=caller.calls, error=error,
            failure_kind=TurnFailure.BUDGET_EXCEEDED,
        )


async def generate_turn(
    db: AsyncSession,
    external_session_id: str,
    req: CreateTurnRequest,
    client_factory: Callable[[], LLMClient],
    settings: Settings,
    reviewer_factory: Callable[[], LLMClient | None] | None = None,
) -> tuple[TurnOutcome, bool]:
    """Tra ve (ket qua, created). created=False: luot da co (idempotent) hoac request khac vua sinh xong truoc."""
    session = await get_session_by_external_id(db, external_session_id)  # SessionNotFoundError -> 404
    if session.status != SessionStatus.READY:
        raise TurnConflictError(f"Session chua san sang (status={session.status.value}), can Case Planning xong truoc")
    _validate_request(session, req)
    mode = mf.turn_mode(req.turn_index, session.ai_side)
    round_type = mf.turn_spec(req.turn_index).round_type

    stored = await _speeches(db, session.id)
    existing = await _existing_turn(db, session.id, req.turn_index)
    if existing is not None:
        return await _replay_existing(db, existing, req, stored), False

    different = _snapshot_mismatches(req, stored)
    if different:
        raise TurnConflictError(f"Bai noi learner o luot {different} khac ban da luu")
    provided = {sp.turn_index for sp in req.new_learner_speeches}
    missing = [t for t in range(1, req.turn_index) if t not in stored and t not in provided]
    if missing:
        raise TurnConflictError(f"Thieu bai noi cua cac luot truoc: {missing}")

    # Lay LLM client TRUOC khi ghi DB: thieu key -> 503, khong de lai bai learner mo coi. Stance Reviewer chi cho
    # turn_full_v* (baseline giu ngay tho: KHONG review, muc 2.11); factory tra None neu STANCE_REVIEW_ENABLED=false.
    client = client_factory()
    reviews = settings.turn_generator_version != BASELINE_V1 and reviewer_factory is not None
    reviewer_client = reviewer_factory() if reviews else None

    new = [sp for sp in req.new_learner_speeches if sp.turn_index not in stored]
    if new:
        # ON CONFLICT DO NOTHING: request dong thoi co the vua ghi cung luot -> doc lai va so noi dung.
        await db.execute(
            pg_insert(OpponentSpeech)
            .values([
                {"session_id": session.id, "turn_index": sp.turn_index, "round_type": sp.round_type,
                 "speaker": Speaker.LEARNER, "text": sp.text}
                for sp in new
            ])
            .on_conflict_do_nothing(constraint="uq_opponent_speeches_session_turn")
        )
        await db.commit()
        stored = await _speeches(db, session.id)
        different = _snapshot_mismatches(req, stored)
        if different:
            raise TurnConflictError(f"Bai noi learner o luot {different} khac ban da luu (request dong thoi)")

    case_file = await get_case_file(db, session.id)
    context = TurnContext(
        motion=session.motion, ai_side=session.ai_side, learner_side=session.learner_side,
        difficulty=session.difficulty, turn_index=req.turn_index, round_type=round_type,
        target_words=mf.target_words(round_type, settings),
        history=[
            SpeechItem(s.turn_index, s.round_type, s.speaker, s.text)
            for t, s in sorted(stored.items()) if t < req.turn_index
        ],
        case_file=case_file.content if case_file else None,
        ledger=await build_ledger(db, session.id, req.turn_index),
    )
    session_id = session.id  # doc truoc: sau rollback, doi tuong ORM co the bi expire
    result = await _run_generator(context, mode, client, settings, reviewer_client)
    logger.info("Luot %d (%s): tong cho 429 %.1fs", req.turn_index, "ok" if result.text else result.failure_kind,
                result.rate_limit_wait_ms / 1000)

    if result.text is None:
        db.add_all(_llm_call_rows(session_id, result.calls, None))  # log van giu lai de debug (turn_id NULL)
        await db.commit()
        logger.error("Sinh luot %d that bai (%s): %s", req.turn_index, result.failure_kind, result.error)
        if result.failure_kind == TurnFailure.BUDGET_EXCEEDED:
            raise TurnBudgetExceededError(result.error)
        if result.failure_kind == TurnFailure.PROVIDER_ERROR:
            raise LLMCallError(result.error)
        raise TurnGenerationError(result.error)

    speech = OpponentSpeech(
        session_id=session_id, turn_index=req.turn_index, round_type=round_type, speaker=Speaker.AI, text=result.text
    )
    turn = OpponentTurn(
        session_id=session_id, turn_index=req.turn_index, round_type=round_type, mode=mode,
        generator_version=result.generator_version, llm_provider=result.llm_provider, llm_model=result.llm_model,
        temperature=result.temperature, learner_claims=result.learner_claims, premises=result.premises,
        target_premise=result.target_premise, ai_points=result.ai_points, word_count=result.word_count,
        latency_ms=sum(c.latency_ms for c in result.calls),
        tokens_in=_sum([c.tokens_in for c in result.calls]), tokens_out=_sum([c.tokens_out for c in result.calls]),
        rate_limit_wait_ms=result.rate_limit_wait_ms,
    )
    try:
        db.add(speech)
        await db.flush()
        turn.speech_id = speech.id
        db.add(turn)
        await db.flush()
        db.add_all(_llm_call_rows(session_id, result.calls, turn.id))
        await db.commit()
    except IntegrityError as e:
        if "uq_opponent_speeches_session_turn" not in str(e.orig) and "uq_opponent_turns_session_turn" not in str(e.orig):
            raise
        # Request khac sinh xong cung luot truoc -> bo bai vua sinh, tra ban da luu. Log LLM van ghi (turn_id NULL).
        logger.warning("Luot %d cua session %s da duoc request khac sinh truoc", req.turn_index, external_session_id)
        await db.rollback()
        db.add_all(_llm_call_rows(session_id, result.calls, None))
        await db.commit()
        winner = await _existing_turn(db, session_id, req.turn_index)
        return await _replay_existing(db, winner, req, await _speeches(db, session_id)), False

    return TurnOutcome(req.turn_index, round_type, mode, result.text), True
