"""
Goi y phan bac (WF-02): POST /opponent/sessions/{external_session_id}/hints — luong DB. Phan thuan: hint.py.

Thu tu kiem tra (generate_hint):
1. session khong co -> 404; chua READY -> 409.
2. request_id da co: cung input (learner_turn_index + learner_draft) -> tra ban da luu (200, KHONG goi LLM); khac -> 409.
   Lam TRUOC kiem tra luot de goi lai dung request cu luon duoc 200.
3. learner_turn_index sai format / la luot cua AI / chua co luot AI nao truoc no -> 400.
4. luot AI target chua duoc sinh (khong co trong opponent_speeches) -> 409.
5. Goi LLM; that bai / het budget -> 502. Request dong thoi cung request_id -> IntegrityError -> doc lai, so input nhu buoc 2.

KHONG doc case file / ledger (hint.py, spec muc 4): ngu canh hint lay TU opponent_speeches (bai noi cong khai).
"""
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.llm.client import LLMClient
from app.opponent import match_format as mf
from app.opponent.hint import HintContext, HintResult, PublicSpeech, run_hint
from app.opponent.match_format import InvalidTurnError, RoundType, Speaker
from app.opponent.models import OpponentHint, OpponentLLMCall, OpponentSession, OpponentSpeech, SessionStatus
from app.opponent.schemas import CreateHintRequest
from app.opponent.service import LLMCallError, get_session_by_external_id
from app.opponent.turn_generators import TurnCall, TurnFailure

logger = logging.getLogger(__name__)


class HintRequestError(ValueError):
    """learner_turn_index khong phai luot cua learner / chua co luot AI truoc no -> 400."""


class HintConflictError(Exception):
    """Session chua READY, luot target chua sinh, hoac request_id da dung voi input khac -> 409."""


class HintGenerationError(Exception):
    """LLM tra ve goi y khong hop le sau moi lan thu / het budget -> 502."""


@dataclass
class HintOutcome:
    hint: OpponentHint
    round_type: RoundType


def target_turn_for(learner_turn_index: int, ai_side) -> int:
    """
    Luot AI GAN NHAT truoc luot learner. Loi -> HintRequestError (400). Dung lai match_format (khong viet lai thu tu):
    learner pro: 1 -> loi, 3 -> 2, 6 -> 5; learner con: 2 -> 1, 4 -> 3, 5 -> 3.
    """
    try:
        if mf.speaker_of(learner_turn_index, ai_side) != Speaker.LEARNER:
            raise HintRequestError(f"Luot {learner_turn_index} la luot cua AI, khong phai cua learner")
    except InvalidTurnError as e:
        raise HintRequestError(str(e)) from e
    earlier = [t for t in mf.turns_of(Speaker.AI, ai_side) if t < learner_turn_index]
    if not earlier:
        raise HintRequestError(f"Chua co luot AI nao truoc luot {learner_turn_index} de phan bac")
    return max(earlier)


def build_context(session: OpponentSession, learner_turn_index: int, target_turn_index: int,
                  speeches: dict[int, OpponentSpeech], learner_draft: str | None) -> HintContext:
    """
    Chi bai noi cong khai: target nguyen van; MOI luot khac truoc luot learner (ca hai ben, hint.py rut gon) — vd learner
    con luot 5 (target 3) van thay bai luot 4 cua chinh minh.
    """
    def public(s: OpponentSpeech) -> PublicSpeech:
        return PublicSpeech(s.turn_index, s.round_type, s.speaker, s.text)

    return HintContext(
        motion=session.motion, learner_side=session.learner_side, learner_turn_index=learner_turn_index,
        learner_round_type=mf.turn_spec(learner_turn_index).round_type,
        target=public(speeches[target_turn_index]),
        history=[public(s) for t, s in sorted(speeches.items()) if t < learner_turn_index and t != target_turn_index],
        learner_draft=learner_draft,
    )


async def _existing_hint(db: AsyncSession, session_id: uuid.UUID, request_id: str) -> OpponentHint | None:
    return await db.scalar(
        select(OpponentHint)
        .where(OpponentHint.session_id == session_id, OpponentHint.request_id == request_id)
        .execution_options(populate_existing=True)
    )


def _replay(hint: OpponentHint, req: CreateHintRequest) -> HintOutcome:
    if hint.learner_turn_index != req.learner_turn_index or hint.learner_draft != req.learner_draft:
        raise HintConflictError(
            f"request_id '{req.request_id}' da duoc dung voi input khac "
            f"(learner_turn_index {hint.learner_turn_index}, learner_draft khac hoac khong khop)"
        )
    return HintOutcome(hint, mf.turn_spec(hint.learner_turn_index).round_type)


def _llm_call_rows(session_id: uuid.UUID, calls: list[TurnCall], hint_id: uuid.UUID | None) -> list[OpponentLLMCall]:
    return [
        OpponentLLMCall(
            session_id=session_id, hint_id=hint_id, purpose=c.purpose, attempt=c.attempt,
            prompt_version=c.prompt_version, llm_provider=c.llm_provider, llm_model=c.llm_model,
            temperature=c.temperature, system_prompt=c.system_prompt, user_prompt=c.user_prompt,
            raw_output=c.raw_output, success=c.success, error=c.error, latency_ms=c.latency_ms,
            failure_kind=c.failure_kind, tokens_in=c.tokens_in, tokens_out=c.tokens_out,
            rate_limit_wait_ms=c.rate_limit_wait_ms, retry_feedback=c.retry_feedback, speech_checks=c.speech_checks,
            reasoning_tokens=c.reasoning_tokens, finish_reason=c.finish_reason, reasoning_effort=c.reasoning_effort,
            reviewer_verdict=c.reviewer_verdict, reviewer_detail=c.reviewer_detail,
        )
        for c in calls
    ]


async def generate_hint(
    db: AsyncSession,
    external_session_id: str,
    req: CreateHintRequest,
    client_factory: Callable[[], LLMClient],
    settings: Settings,
    reviewer_factory: Callable[[], LLMClient | None] | None = None,
) -> tuple[HintOutcome, bool]:
    """Tra ve (ket qua, created). created=False: request_id da co (idempotent)."""
    session = await get_session_by_external_id(db, external_session_id)  # SessionNotFoundError -> 404
    if session.status != SessionStatus.READY:
        raise HintConflictError(f"Session chua san sang (status={session.status.value})")
    # Khoa theo (session, request_id) toi het transaction: 2 request dong thoi cung request_id -> request sau CHO, roi
    # thay ban da luu (200) thay vi goi LLM lan 2 (SystemService tra tien token). Lock nha khi commit / rollback.
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"hint:{session.id}:{req.request_id}", 0))))
    existing = await _existing_hint(db, session.id, req.request_id)
    if existing is not None:
        return _replay(existing, req), False

    target_turn_index = target_turn_for(req.learner_turn_index, session.ai_side)
    rows = await db.scalars(select(OpponentSpeech).where(
        OpponentSpeech.session_id == session.id, OpponentSpeech.turn_index < req.learner_turn_index))
    speeches = {s.turn_index: s for s in rows}
    if target_turn_index not in speeches:
        raise HintConflictError(f"Luot AI {target_turn_index} (can phan bac) chua duoc sinh")

    client = client_factory()  # LLMNotConfiguredError -> 503, truoc khi ghi gi vao DB
    reviewer_client = reviewer_factory() if reviewer_factory is not None else None
    context = build_context(session, req.learner_turn_index, target_turn_index, speeches, req.learner_draft)
    session_id = session.id  # doc truoc: sau rollback, doi tuong ORM co the bi expire
    result: HintResult = await run_hint(context, client, settings, reviewer_client)
    logger.info("Hint %s luot %d: %s, tokens in/out %s/%s", req.request_id, req.learner_turn_index,
                "ok" if result.strategies else result.failure_kind, result.tokens("tokens_in"), result.tokens("tokens_out"))

    if result.strategies is None:
        db.add_all(_llm_call_rows(session_id, result.calls, None))  # log giu lai de debug (hint_id NULL)
        await db.commit()
        logger.error("Goi y that bai (%s): %s", result.failure_kind, result.error)
        if result.failure_kind == TurnFailure.PROVIDER_ERROR:
            raise LLMCallError(result.error)
        raise HintGenerationError(result.error)

    hint = OpponentHint(
        session_id=session_id, request_id=req.request_id, learner_turn_index=req.learner_turn_index,
        target_turn_index=target_turn_index, learner_draft=req.learner_draft, strategies=result.strategies,
        prompt_version=result.prompt_version, llm_provider=result.llm_provider, llm_model=result.llm_model,
        temperature=result.temperature, tokens_in=result.tokens("tokens_in"), tokens_out=result.tokens("tokens_out"),
        latency_ms=result.latency_ms,
    )
    try:
        db.add(hint)
        await db.flush()
        db.add_all(_llm_call_rows(session_id, result.calls, hint.id))
        await db.commit()
    except IntegrityError as e:
        if "uq_opponent_hints_session_request" not in str(e.orig):
            raise
        # Request dong thoi cung request_id luu truoc -> bo ban vua sinh, tra / so voi ban da luu.
        logger.warning("Hint request_id %s cua session %s da duoc request khac luu truoc", req.request_id,
                       external_session_id)
        await db.rollback()
        db.add_all(_llm_call_rows(session_id, result.calls, None))
        await db.commit()
        winner = await _existing_hint(db, session_id, req.request_id)
        if winner is None:  # ban kia chua thay duoc / da bi xoa -> de client goi lai
            raise HintConflictError(f"request_id '{req.request_id}' dang duoc xu ly dong thoi, vui long goi lai") from e
        return _replay(winner, req), False
    return HintOutcome(hint, context.learner_round_type), True
