"""
Chay thu goi y phan bac (WF-02) voi LLM THAT tren cac tran DA CO trong DB dev (vd tao bang scripts/try_match.py).
Dung cho buoc kiem tra chat luong thu cong (spec muc 8): moi session, xin goi y cho MOI luot learner co luot AI truoc
no da sinh, in ra de cham 4 cau (nham dung noi dung AI da noi? dung phe learner? khong viet ho? khong bia so lieu?).

    python -m scripts.try_hint try-match-M01-pro-20261002-001051 [session khac ...] [--out experiments/hints/x.jsonl]

request_id moi lan chay khac nhau (khong dung lai ket qua cu). Ghi JSONL: moi hint 1 dong + 4 cot cham de trong.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.llm.client import get_llm_client
from app.opponent import hint_service, match_format as mf, service
from app.opponent.models import OpponentSpeech, Speaker
from app.opponent.schemas import CreateHintRequest

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "experiments" / "hints"
QUALITY_COLUMNS = ("q_targets_ai_speech", "q_learner_side", "q_not_written_for_learner", "q_no_fabricated_numbers")


async def run(external_ids: list[str], out_path: Path) -> int:
    settings = get_settings()

    def client_factory():
        return get_llm_client(settings)

    def reviewer_factory():
        if not settings.stance_review_enabled:
            return None
        return get_llm_client(settings, provider=settings.stance_review_provider, model=settings.stance_review_model)

    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    failures = 0
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as db:
        for ext in external_ids:
            session = await service.get_session_by_external_id(db, ext)
            done = set(await db.scalars(select(OpponentSpeech.turn_index).where(OpponentSpeech.session_id == session.id)))
            for t in mf.turns_of(Speaker.LEARNER, session.ai_side):
                try:
                    target = hint_service.target_turn_for(t, session.ai_side)
                except hint_service.HintRequestError:
                    continue
                if target not in done:
                    continue
                req = CreateHintRequest(request_id=f"try-hint-{stamp}-{t}", learner_turn_index=t)
                print(f"\n===== {ext} | learner {session.learner_side.value} luot {t} (phan bac luot {target}) =====")
                row = {"external_session_id": ext, "learner_turn_index": t, "target_turn_index": target,
                       "learner_side": session.learner_side.value, "motion": session.motion}
                try:
                    outcome, _ = await hint_service.generate_hint(db, ext, req, client_factory, settings, reviewer_factory)
                except Exception as e:  # noqa: BLE001 — ghi lai de cham, chay tiep
                    failures += 1
                    print(f"  THAT BAI: {type(e).__name__}: {e}")
                    row["error"] = f"{type(e).__name__}: {e}"
                else:
                    hint = outcome.hint
                    for i, s in enumerate(hint.strategies, 1):
                        print(f"  [{i}] {s['title']} ({s['attack_type']})\n      nham: {s['target_claim']}\n"
                              f"      huong: {s['direction']}\n      dan chung: {s['evidence_to_look_for']}")
                    print(f"  tokens in/out {hint.tokens_in}/{hint.tokens_out}, {hint.latency_ms} ms")
                    row |= {"hint_id": str(hint.id), "strategies": hint.strategies, "tokens_in": hint.tokens_in,
                            "tokens_out": hint.tokens_out, "latency_ms": hint.latency_ms, "llm_model": hint.llm_model}
                row |= {c: None for c in QUALITY_COLUMNS}
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
    await dispose_engine()
    print(f"\nDa ghi {out_path} ({failures} that bai)")
    return 0 if failures == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Chay thu goi y phan bac voi LLM that (DB dev)")
    p.add_argument("external_session_ids", nargs="+")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    out = args.out or OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_hints.jsonl"
    return asyncio.run(run(args.external_session_ids, out))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
