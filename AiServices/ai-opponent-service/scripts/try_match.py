"""
Script THU CONG: chay CA TRAN 6 luot voi LLM THAT qua dung tang service cua API (Case Planning + POST .../turns).
Ton token that -> khong nam trong pytest. CAN Postgres dev dang chay + `alembic upgrade head`.

    python -m scripts.try_match --motion-id M01 --learner-side pro                       # TURN_GENERATOR_VERSION
    python -m scripts.try_match --motion-id M01 --learner-side con --generator turn_baseline_v1
    python -m scripts.try_match --motion-id M01 --learner-side pro --reasoning-effort low   # so sanh muc suy luan

- Bai noi learner lay tu experiments/fixtures/match_<motion_id>_<learner_side>.json (co dinh, khong phan hoi AI).
- ai_side = phe con lai. Session moi moi lan chay (external_session_id "try-match-...").
- Bo sinh: --generator (turn_baseline_v1 | turn_full_v1 | turn_full_v2), mac dinh TURN_GENERATOR_VERSION.
- --reasoning-effort (low | medium | high): ghi de TURN_REASONING_EFFORT cho cac luot noi (Case Planning van theo
  CASE_PLAN_REASONING_EFFORT).
- In transcript day du + mode + so tu moi luot AI; turn_full_* in them learner_claims / target_premise / ai_points;
  moi luot in so lan thu lai + ly do. Cuoi tran: tong thoi gian cho 429.
- Luot AI THAT BAI -> in loi + cac lan goi cua luot do, DUNG GON (khong traceback), van ghi file transcript do dang.
- Stance Reviewer (turn_full_*): in verdict moi luot, ca cac lan thu bi reject (side_flip).
- Ghi experiments/matches/<timestamp>_<motion_id>_learner-<side>_<generator>[_effort-<x>].json.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import dispose_engine, get_engine
from app.llm.client import get_llm_client
from app.opponent import match_format as mf
from app.opponent import service, turn_service
from app.opponent.models import (
    DebateSide,
    LLMCallPurpose,
    OpponentDifficulty,
    OpponentLLMCall,
    OpponentSession,
    OpponentTurn,
)
from app.opponent.schemas import CreateSessionRequest, CreateTurnRequest, LearnerSpeechIn

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "experiments" / "fixtures"
OUT_DIR = ROOT / "experiments" / "matches"
GENERATORS = ["turn_baseline_v1", "turn_full_v1", "turn_full_v2"]


def load_fixture(motion_id: str, learner_side: str, fixtures_dir: Path = FIXTURES_DIR) -> dict:
    data = json.loads((fixtures_dir / f"match_{motion_id}_{learner_side}.json").read_text(encoding="utf-8"))
    ai_side = DebateSide.CON if learner_side == "pro" else DebateSide.PRO
    expected = mf.turns_of(mf.Speaker.LEARNER, ai_side)
    got = [s["turn_index"] for s in data["speeches"]]
    if got != expected:
        raise ValueError(f"Fixture learner {learner_side} phai co cac luot {expected}, dang co {got}")
    return data


def _header(turn_index: int, speaker: str, side: DebateSide, extra: str = "") -> str:
    spec = mf.turn_spec(turn_index)
    return f"\n===== Luot {turn_index} · {spec.round_type.value} · {speaker} ({side.value}){extra} ====="


def _verdict(c: OpponentLLMCall) -> str:
    """ ' · reviewer=side_flip [P2, weighing]' neu dong co ket qua Stance Reviewer."""
    if c.reviewer_verdict is None:
        return ""
    detail = c.reviewer_detail or {}
    ids = detail.get("flipped_ids") or detail.get("unclear_ids") or []
    extra = f" loi: {detail['reviewer_error'][:120]}" if "reviewer_error" in detail else ""
    return f" · reviewer={c.reviewer_verdict.value}" + (f" {ids}" if ids else "") + extra


def _call_line(c: OpponentLLMCall) -> str:
    who = "reviewer" if c.purpose == LLMCallPurpose.STANCE_REVIEW else "sinh"
    if c.rate_limit_wait_ms:
        return f"  - lan {c.attempt} ({who}): {c.failure_kind} (cho {c.rate_limit_wait_ms} ms)"
    status = c.failure_kind or "ok"
    return (f"  - lan {c.attempt} ({who}): {status}{_verdict(c)}"
            + (f" — {(c.error or '')[:300]}" if c.error else "")
            + f" [tokens_out={c.tokens_out}, reasoning={c.reasoning_tokens}, finish={c.finish_reason}]")


async def rate_limit_wait_total(db: AsyncSession, session_id) -> tuple[int, int]:
    """(tong ms cho 429, so lan cho) cua CA tran — Case Planning + moi luot noi."""
    total, count = (await db.execute(
        select(func.coalesce(func.sum(OpponentLLMCall.rate_limit_wait_ms), 0), func.count(OpponentLLMCall.rate_limit_wait_ms))
        .where(OpponentLLMCall.session_id == session_id)
    )).one()
    return int(total), int(count)


async def run_match(
    db: AsyncSession, settings: Settings, fixture: dict, learner_side: DebateSide, difficulty: OpponentDifficulty,
    external_id: str, client_factory, reviewer_factory, out=print,
) -> dict:
    """
    Chay ca tran. KHONG nem loi: tra {"ok", "transcript", "failed_turn", "error", "rate_limit_wait_ms",
    "rate_limit_waits"}. Luot AI that bai -> in loi + cac lan goi (turn_id NULL) cua luot do roi dung.
    """
    ai_side = DebateSide.CON if learner_side == DebateSide.PRO else DebateSide.PRO
    result = {"ok": False, "transcript": [], "failed_turn": None, "error": None,
              "rate_limit_wait_ms": 0, "rate_limit_waits": 0}
    req = CreateSessionRequest(
        external_session_id=external_id, motion=fixture["motion"], learner_side=learner_side, ai_side=ai_side,
        difficulty=difficulty,
    )
    try:
        session, _ = await service.create_session_and_plan(db, req, client_factory, settings, reviewer_factory)
    except Exception as e:  # noqa: BLE001 — script thu: in loi roi dung gon
        result["error"] = f"Case Planning: {type(e).__name__}: {e}"
        out(f"\n=> Case Planning THAT BAI: {type(e).__name__}: {e}")
        await _print_waits(db, external_id, result, out)
        return result
    session_id = session.id
    generator = settings.turn_generator_version
    out(f"Case Planning: {session.status.value}" + (" (baseline KHONG dung case file)" if generator == "turn_baseline_v1" else ""))

    transcript = result["transcript"]
    learner = {s["turn_index"]: s for s in fixture["speeches"]}
    pending: list[LearnerSpeechIn] = []
    for spec in mf.MATCH_FORMAT:
        t = spec.turn_index
        if mf.speaker_of(t, ai_side) == mf.Speaker.LEARNER:
            s = learner[t]
            pending.append(LearnerSpeechIn(**s))
            out(_header(t, "LEARNER", learner_side, f" · {mf.word_count(s['text'])} tu"))
            out(s["text"])
            transcript.append({"turn_index": t, "round_type": spec.round_type.value, "speaker": "learner",
                               "text": s["text"], "word_count": mf.word_count(s["text"])})
            continue
        # id cac loi goi da co: loi goi cua luot that bai = phan moi (chua co turn_id, lan voi reviewer cua Case Planning)
        before = set((await db.scalars(select(OpponentLLMCall.id).where(OpponentLLMCall.session_id == session_id))).all())
        try:
            outcome, _ = await turn_service.generate_turn(
                db, external_id, CreateTurnRequest(turn_index=t, new_learner_speeches=pending), client_factory, settings,
                reviewer_factory,
            )
        except Exception as e:  # noqa: BLE001 — in loi, dung gon
            result["failed_turn"], result["error"] = t, f"{type(e).__name__}: {e}"
            out(_header(t, "AI", ai_side) + f"\n=> LUOT {t} THAT BAI: {type(e).__name__}: {e}")
            # Cac lan goi cua luot that bai (chua gan turn_id vi chua co dong opponent_turns), ke ca reviewer
            failed = [c for c in (await db.scalars(select(OpponentLLMCall).where(
                OpponentLLMCall.session_id == session_id).order_by(OpponentLLMCall.attempt))).all() if c.id not in before]
            if failed:
                out(f"[cac lan goi cua luot {t}] {len(failed)}")
                for c in failed:
                    out(_call_line(c))
            transcript.append({"turn_index": t, "round_type": spec.round_type.value, "speaker": "ai", "failed": True,
                               "error": result["error"],
                               "calls": [{"attempt": c.attempt, "purpose": c.purpose.value,
                                          "failure_kind": c.failure_kind, "error": c.error,
                                          "reviewer_verdict": c.reviewer_verdict.value if c.reviewer_verdict else None,
                                          "tokens_out": c.tokens_out, "reasoning_tokens": c.reasoning_tokens,
                                          "finish_reason": c.finish_reason, "rate_limit_wait_ms": c.rate_limit_wait_ms}
                                         for c in failed]})
            await _print_waits(db, external_id, result, out)
            return result
        pending = []
        turn = await db.scalar(select(OpponentTurn).where(OpponentTurn.session_id == session_id, OpponentTurn.turn_index == t))
        calls = (await db.scalars(select(OpponentLLMCall).where(OpponentLLMCall.turn_id == turn.id)
                                  .order_by(OpponentLLMCall.attempt))).all()
        # Lan goi khong thanh cong = 1 lan thu lai (noi dung) hoac 1 lan cho 429 — in ro ly do tung lan.
        retries = [{"attempt": c.attempt, "purpose": c.purpose.value, "failure_kind": c.failure_kind,
                    "error": (c.error or "")[:300],
                    "reviewer_verdict": c.reviewer_verdict.value if c.reviewer_verdict else None,
                    "retry_feedback": c.retry_feedback, "rate_limit_wait_ms": c.rate_limit_wait_ms,
                    "tokens_out": c.tokens_out, "reasoning_tokens": c.reasoning_tokens, "finish_reason": c.finish_reason}
                   for c in calls if not c.success]
        final = next((c for c in reversed(calls) if c.success and c.purpose == LLMCallPurpose.TURN), None)
        target = mf.target_words(spec.round_type, settings)
        out(_header(t, "AI", ai_side, f" · mode={outcome.mode.value} · {turn.word_count} tu (muc tieu {target})"
                    f" · {turn.latency_ms} ms · cho 429 {(turn.rate_limit_wait_ms or 0) / 1000:.1f}s · tokens {turn.tokens_in}/{turn.tokens_out}"
                    + (f" (suy luan {final.reasoning_tokens})" if final is not None and final.reasoning_tokens else "")))
        if turn.ai_points is not None:  # turn_full_*
            out(f"[learner_claims] {turn.learner_claims}")
            out(f"[premises] {turn.premises}")
            out(f"[target_premise] {turn.target_premise}")
            out(f"[ai_points] {turn.ai_points}")
        reviewed = final is not None and final.reviewer_verdict is not None
        out("[reviewer] " + (_verdict(final).removeprefix(" · reviewer=") if reviewed else "(khong review)"))
        out(f"[lan thu lai] {len(retries)}")
        for c in calls:  # moi lan goi (ke ca reviewer) co loi / co ket qua review
            if not c.success or c.reviewer_verdict is not None:
                out(_call_line(c))
        if final is not None and (final.speech_checks or final.vague_evidence):
            out(f"[chi log] bang chung LOW: {[h['match'] for h in final.vague_evidence or []]} | {final.speech_checks}")
        out(outcome.speech_text)
        transcript.append({"turn_index": t, "round_type": spec.round_type.value, "speaker": "ai",
                           "mode": outcome.mode.value, "text": outcome.speech_text, "word_count": turn.word_count,
                           "target_words": target, "latency_ms": turn.latency_ms, "tokens_in": turn.tokens_in,
                           "tokens_out": turn.tokens_out, "rate_limit_wait_ms": turn.rate_limit_wait_ms, "learner_claims": turn.learner_claims,
                           "premises": turn.premises, "target_premise": turn.target_premise,
                           "ai_points": turn.ai_points, "retries": retries,
                           "reasoning_tokens": final.reasoning_tokens if final else None,
                           "reviewer_verdict": final.reviewer_verdict.value if final and final.reviewer_verdict else None,
                           "reviewer_detail": final.reviewer_detail if final else None,
                           "vague_evidence": final.vague_evidence if final else None,
                           "speech_checks": final.speech_checks if final else None})
    result["ok"] = True
    await _print_waits(db, external_id, result, out)
    return result


async def _print_waits(db: AsyncSession, external_id: str, result: dict, out) -> None:
    session_id = await db.scalar(select(OpponentSession.id).where(OpponentSession.external_session_id == external_id))
    if session_id is None:
        return
    total_ms, count = await rate_limit_wait_total(db, session_id)
    result["rate_limit_wait_ms"], result["rate_limit_waits"] = total_ms, count
    out(f"\nTong cho 429 ca tran: {total_ms / 1000:.1f}s ({count} lan)")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Chay thu ca tran 6 luot voi LLM that")
    parser.add_argument("--motion-id", default="M01")
    parser.add_argument("--learner-side", choices=["pro", "con"], default="pro")
    parser.add_argument("--difficulty", choices=[d.value for d in OpponentDifficulty], default="medium")
    parser.add_argument("--generator", choices=GENERATORS, default=None,
                        help="Bo sinh bai noi (mac dinh: TURN_GENERATOR_VERSION)")
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default=None,
                        help="Ghi de TURN_REASONING_EFFORT cho cac luot noi (Groq gpt-oss; mac dinh: khong gui)")
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    fixture = load_fixture(args.motion_id, args.learner_side, args.fixtures_dir)
    learner_side = DebateSide(args.learner_side)
    ai_side = DebateSide.CON if learner_side == DebateSide.PRO else DebateSide.PRO
    settings = get_settings()
    update = {}
    if args.generator:
        update["turn_generator_version"] = args.generator
    if args.reasoning_effort:
        update["turn_reasoning_effort"] = args.reasoning_effort
    settings = settings.model_copy(update=update) if update else settings
    generator, effort = settings.turn_generator_version, settings.turn_reasoning_effort
    external_id = f"try-match-{args.motion_id}-{learner_side.value}-{datetime.now():%Y%m%d-%H%M%S}"

    def client_factory():
        return get_llm_client(settings)

    def reviewer_factory():
        if not settings.stance_review_enabled:
            return None
        return get_llm_client(settings, provider=settings.stance_review_provider, model=settings.stance_review_model)

    try:
        probe = client_factory()
    except (RuntimeError, ValueError) as e:
        print(f"Khong tao duoc LLM client: {e}")
        return 1
    print(f"Motion: {fixture['motion']} | learner {learner_side.value} / AI {ai_side.value} | {args.difficulty}")
    print(f"Planner / luot noi: {probe.provider}/{probe.model} | bo sinh {generator} "
          f"temperature={settings.turn_temperature} reasoning_effort={effort or '(mac dinh provider)'} "
          f"max_tokens={settings.turn_max_tokens} | session {external_id}")

    try:
        async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
            result = await run_match(db, settings, fixture, learner_side, OpponentDifficulty(args.difficulty),
                                     external_id, client_factory, reviewer_factory)
    finally:
        await dispose_engine()  # dong ket noi TRUOC khi event loop dong (tranh loi "Event loop is closed" luc thoat)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_effort-{effort}" if effort else ""
    out = args.out_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{args.motion_id}_learner-{learner_side.value}_{generator}{suffix}.json"
    out.write_text(json.dumps({
        "external_session_id": external_id, "motion_id": args.motion_id, "motion": fixture["motion"],
        "learner_side": learner_side.value, "ai_side": ai_side.value, "difficulty": args.difficulty,
        "generator_version": generator, "model": probe.model, "temperature": settings.turn_temperature,
        "reasoning_effort": effort, "turn_max_tokens": settings.turn_max_tokens,
        "completed": result["ok"], "failed_turn": result["failed_turn"], "error": result["error"],
        "rate_limit_wait_ms": result["rate_limit_wait_ms"], "rate_limit_waits": result["rate_limit_waits"],
        "transcript": result["transcript"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ai = [(x["turn_index"], x.get("mode"), x.get("word_count")) for x in result["transcript"] if x["speaker"] == "ai"]
    print(f"\nAI: {ai}")
    print(f"Da ghi {out}" + ("" if result["ok"] else " (tran DO DANG)"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
