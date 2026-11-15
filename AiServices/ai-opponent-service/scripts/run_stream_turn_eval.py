"""
Script THU CONG (LLM that, ton token): so sanh toc do + do on dinh giua turn_full_v3 (JSON strict, khong stream) va
turn_full_v4_stream o cac muc suy luan, tren CUNG case file. CAN Postgres + `alembic upgrade head` (DATABASE_URL).

    python -m scripts.run_stream_turn_eval                                   # 3 cau hinh x fixture M01 (pro, con)
    python -m scripts.run_stream_turn_eval --configs v4_low --fixtures M01_con

- Moi fixture: Case Planning 1 lan, roi NHAN BAN session + case file cho tung cau hinh (khac nhau chi o bo sinh /
  muc suy luan). Bai learner lay tu experiments/fixtures (co dinh, khong phan hoi AI).
- Moi luot AI ghi: first_text_s (stream: delta dau tien; v3: luc co ket qua), done_s, gen_ms (tong latency cac lan goi
  SINH, khong tinh cho 429), review_ms, rate_limit_wait_ms, attempts + ly do bi loai, reasoning_tokens, so tu, bai noi.
- Ghi experiments/stream_eval/<timestamp>.jsonl (1 dong / luot) + in bang tong hop.
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.llm.client import get_llm_client
from app.opponent import match_format as mf
from app.opponent import service, turn_service
from app.opponent.models import (
    DebateSide,
    LLMCallPurpose,
    OpponentCaseFile,
    OpponentDifficulty,
    OpponentLLMCall,
    OpponentSession,
    OpponentTurn,
)
from app.opponent.schemas import CreateSessionRequest, CreateTurnRequest, LearnerSpeechIn
from app.opponent.turn_generators import FULL_V3, FULL_V4_STREAM
from scripts.try_match import load_fixture

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "experiments" / "stream_eval"
CONFIGS = {
    "v3_medium": (FULL_V3, {"turn_reasoning_effort": "medium"}),
    "v4_medium": (FULL_V4_STREAM, {"turn_stream_reasoning_effort": "medium"}),
    "v4_low": (FULL_V4_STREAM, {"turn_stream_reasoning_effort": "low"}),
}
_SKIP_COLUMNS = {"id", "external_session_id", "session_id", "created_at", "updated_at"}


def _copy(model, row, **extra):
    return model(**{c.key: getattr(row, c.key) for c in model.__table__.columns if c.key not in _SKIP_COLUMNS}, **extra)


async def _clone_session(db, src_id, external_id) -> None:
    src = await db.get(OpponentSession, src_id)
    clone = _copy(OpponentSession, src, external_session_id=external_id)
    db.add(clone)
    await db.flush()
    case = await db.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == src_id))
    db.add(_copy(OpponentCaseFile, case, session_id=clone.id))
    await db.commit()


async def _turn_stats(db, external_id, turn_index) -> dict:
    sid = await db.scalar(select(OpponentSession.id).where(OpponentSession.external_session_id == external_id))
    turn = await db.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid, OpponentTurn.turn_index == turn_index))
    q = select(OpponentLLMCall).where(OpponentLLMCall.session_id == sid)
    q = q.where(OpponentLLMCall.turn_id == turn.id) if turn else q.where(OpponentLLMCall.turn_id.is_(None))
    calls = (await db.scalars(q.order_by(OpponentLLMCall.attempt))).all()
    gen = [c for c in calls if c.purpose == LLMCallPurpose.TURN and not c.rate_limit_wait_ms]
    rev = [c for c in calls if c.purpose == LLMCallPurpose.STANCE_REVIEW]
    return {
        "ok": turn is not None,
        "word_count": turn.word_count if turn else None,
        "gen_ms": sum(c.latency_ms for c in gen),
        "review_ms": sum(c.latency_ms for c in rev),
        "rate_limit_wait_ms": sum(c.rate_limit_wait_ms or 0 for c in calls),
        "generation_attempts": len(gen),
        "rejections": [c.failure_kind for c in gen if c.failure_kind],
        "reviewer_verdicts": [c.reviewer_verdict.value for c in rev if c.reviewer_verdict],
        "reasoning_tokens": [c.reasoning_tokens for c in gen],
        "ai_points": turn.ai_points if turn else None,
    }


async def run(configs: list[str], fixtures: list[str], difficulty: str, pause: float, out_path: Path) -> list[dict]:
    base = get_settings()
    rows: list[dict] = []
    maker = async_sessionmaker(get_engine(), expire_on_commit=False)
    for fx in fixtures:
        motion_id, learner_side = fx.split("_")
        fixture = load_fixture(motion_id, learner_side)
        ai_side = DebateSide.CON if learner_side == "pro" else DebateSide.PRO
        source_ext = f"stream-eval-{fx}-{uuid.uuid4().hex[:8]}"

        def client_factory(s=base):
            return get_llm_client(s)

        def reviewer_factory(s=base):
            return get_llm_client(s, provider=s.stance_review_provider, model=s.stance_review_model)

        async with maker() as db:
            req = CreateSessionRequest(external_session_id=source_ext, motion=fixture["motion"], ai_side=ai_side,
                                       learner_side=DebateSide(learner_side), difficulty=OpponentDifficulty(difficulty))
            session, _ = await service.create_session_and_plan(db, req, client_factory, base, reviewer_factory)
            source_id = session.id
            print(f"[{fx}] Case Planning: {session.status.value}", flush=True)

        for name in configs:
            version, update = CONFIGS[name]
            settings = base.model_copy(update=update)
            ext = f"{source_ext}-{name}"
            async with maker() as db:
                await _clone_session(db, source_id, ext)
            ai_turns = mf.turns_of(mf.Speaker.AI, ai_side)
            previous_ai = 0
            for t in ai_turns:
                # Chi bai learner KE TU luot AI truoc (bai cu da luu; gui lai bai truoc luot AI -> 400)
                speeches = [LearnerSpeechIn(**s) for s in fixture["speeches"] if previous_ai < s["turn_index"] < t]
                previous_ai = t
                started = time.perf_counter()
                marks: dict = {}

                def on_event(event, marks=marks, started=started):
                    if event["type"] == "delta" and "first" not in marks:
                        marks["first"] = time.perf_counter() - started
                    if event["type"] == "attempt" and event.get("attempt", 0) and event["attempt"] > 1:
                        marks.setdefault("restarts", 0)
                        marks["restarts"] += 1

                error = None
                async with maker() as db:
                    try:
                        outcome, _ = await turn_service.generate_turn(
                            db, ext, CreateTurnRequest(turn_index=t, new_learner_speeches=speeches),
                            lambda s=settings: get_llm_client(s), settings,
                            lambda s=settings: get_llm_client(s, provider=s.stance_review_provider,
                                                              model=s.stance_review_model),
                            generator_version=version, on_event=on_event,
                        )
                        text = outcome.speech_text
                    except Exception as e:  # noqa: BLE001 — ghi lai roi chay tiep
                        error, text = f"{type(e).__name__}: {e}"[:500], None
                done = time.perf_counter() - started
                async with maker() as db:
                    stats = await _turn_stats(db, ext, t)
                row = {
                    "fixture": fx, "config": name, "generator": version, "turn_index": t,
                    "round_type": mf.turn_spec(t).round_type.value,
                    "first_text_s": round(marks.get("first", done), 2), "done_s": round(done, 2),
                    "restarts_seen": marks.get("restarts", 0), "error": error, **stats, "speech_text": text,
                }
                rows.append(row)
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"[{fx}] {name} luot {t}: first {row['first_text_s']}s done {row['done_s']}s "
                      f"gen {row['gen_ms']}ms review {row['review_ms']}ms 429 {row['rate_limit_wait_ms']}ms "
                      f"bi loai {row['rejections']} {'LOI ' + error if error else ''}", flush=True)
                await asyncio.sleep(pause)
    return rows


def summary(rows: list[dict]) -> None:
    print("\ncau hinh   | luot | that bai | first_text_s (median) | done_s (median) | gen_s (median) | lan bi loai | 429 (s)")
    for name in dict.fromkeys(r["config"] for r in rows):
        rs = [r for r in rows if r["config"] == name]
        med = lambda k: statistics.median(x[k] for x in rs)  # noqa: E731
        print(f"{name:10} | {len(rs):4} | {sum(not r['ok'] for r in rs):8} | {med('first_text_s'):21} | {med('done_s'):15} "
              f"| {statistics.median(r['gen_ms'] for r in rs) / 1000:14.1f} | {sum(len(r['rejections']) for r in rs):11} "
              f"| {sum(r['rate_limit_wait_ms'] for r in rs) / 1000:.1f}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--configs", default=",".join(CONFIGS))
    parser.add_argument("--fixtures", default="M01_con,M01_pro")
    parser.add_argument("--difficulty", default="medium", choices=[d.value for d in OpponentDifficulty])
    parser.add_argument("--pause", type=float, default=15.0, help="nghi giua cac luot (giam 429 cua Groq free tier)")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    try:
        rows = await run(args.configs.split(","), args.fixtures.split(","), args.difficulty, args.pause, out_path)
    finally:
        await dispose_engine()
    summary(rows)
    print(f"\nKet qua: {out_path}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
