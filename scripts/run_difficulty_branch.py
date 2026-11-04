"""
Giai doan 3e, Phan 2 (dev log muc 3.3) — RE NHANH tu hoi thoai nhanh LM. GOI LLM THAT — ton tien.

    python -m scripts.run_difficulty_branch experiments/pressure_eval/<file LM>.jsonl --concurrency 2
    python -m scripts.run_difficulty_branch <file LM>.jsonl --resume --out experiments/difficulty_eval/<file>.jsonl

- Voi moi hoi thoai LM completed va moi snapshot_round thuoc {1, 3}: trang thai = transcript toi het bai learner cua vong
  do (lich su AI la cua medium). Tu do sinh DUNG MOT bai easy va mot bai hard bang bo sinh v7 day du (reviewer + validator,
  nhu nhanh LE / LH). Bai medium lay tu chinh hoi thoai goc.
- Hoi thoai khong completed, hoac khong co bai medium o vong do -> bo trang thai va liet ke (dong "skipped" o file .skipped.json).
- Luot het lan thu (vd side_flip) -> status "branch_failed": khong dung cho pairwise, bao rieng theo cap. Loi ha tang
  (provider, mang, het budget) -> "branch_infra": --resume chay lai trang thai do.
- Moi trang thai 1 dong JSONL: ba bai, target_premise, points_addressed, tung lan thu (content_attempt, failure_kind).
"""
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.core.config import get_settings
from app.llm.client import get_llm_client
from app.opponent.match_format import word_count
from app.opponent.models import DebateSide, OpponentDifficulty, RoundType, Speaker
from app.opponent.turn_generators import SpeechItem
from scripts.eval_common import load_jsonl
from scripts.pressure_common import (
    ARMS,
    INFRA,
    Factories,
    _ai_summary,
    _ai_turn,
    _State,
    DialogueSpec,
    ROOT,
    attempt_rows,
    failure_category,
    latest_records,
    update_ledger,
)

logger = logging.getLogger(__name__)
OUT_DIR = ROOT / "experiments" / "difficulty_eval"
SOURCE_ARM = "LM"
SNAPSHOT_ROUNDS = (1, 3)
BRANCH_ARMS = {"easy": "LE", "hard": "LH"}
OK, BRANCH_FAILED, BRANCH_INFRA = "ok", "branch_failed", "branch_infra"


def state_id(dialogue: str, snapshot_round: int) -> str:
    return f"{dialogue}|r{snapshot_round}"


def build_state(record: dict, snapshot_round: int) -> _State | None:
    """
    Dung lai _State NHU LUC bo sinh medium nhan duoc o vong snapshot_round: transcript toi het bai learner vong do, ledger
    tu cac bai AI TRUOC vong do. Thieu bai nao tren duong di -> None.
    """
    state = _State()

    def speak(speaker: Speaker, round_no: int, text: str) -> None:
        rt = RoundType.OPENING if round_no == 0 else RoundType.REBUTTAL
        state.transcript.append(SpeechItem(len(state.transcript) + 1, rt, speaker, text))

    for rd in sorted(record.get("rounds", []), key=lambda r: r["round"]):
        n = rd["round"]
        if n > snapshot_round:
            break
        learner = (rd.get("learner") or {}).get("text")
        if learner:
            speak(Speaker.LEARNER, n, learner)
        if n == snapshot_round:
            return state if learner else None
        ai = rd.get("ai") or {}
        if not ai.get("text"):
            return None
        speak(Speaker.AI, n, ai["text"])
        update_ledger(state.ledger, SimpleNamespace(
            learner_claims=None, premises=ai.get("premises"), ai_points=ai.get("ai_points"),
            target_premise=ai.get("target_premise"),
        ))
    return None


def spec_from_record(record: dict, arm: str) -> DialogueSpec:
    return DialogueSpec(
        arm=arm, motion_id=record["motion_id"], motion=record["motion"], motion_type=record["motion_type"],
        ai_side=DebateSide(record["ai_side"]), strategy=record["strategy"],
        difficulty=OpponentDifficulty(record["case_difficulty"]), case_file=record["case_file"],
        case_source=record["case_source"], burden_pro=record["burden_pro"], burden_con=record["burden_con"],
    )


def _medium_ai(record: dict, snapshot_round: int) -> dict | None:
    for rd in record.get("rounds", []):
        if rd["round"] == snapshot_round:
            return rd.get("ai") if (rd.get("ai") or {}).get("text") else None
    return None


def plan_states(records: list[dict], snapshot_rounds=SNAPSHOT_ROUNDS) -> tuple[list[tuple[dict, int]], list[dict]]:
    """([(ban ghi LM, vong)], cac trang thai bi bo + ly do). Moi dialogue_id giu ban ghi CUOI."""
    todo, skipped = [], []
    for r in latest_records([x for x in records if x.get("arm") == SOURCE_ARM]):
        for snap in snapshot_rounds:
            sid = state_id(r["dialogue_id"], snap)
            if r.get("status") != "completed":
                skipped.append({"state_id": sid, "reason": f"hoi thoai {r.get('status')} (vong {r.get('failed_round')})"})
            elif _medium_ai(r, snap) is None:
                skipped.append({"state_id": sid, "reason": f"khong co bai medium o vong {snap}"})
            elif build_state(r, snap) is None:
                skipped.append({"state_id": sid, "reason": f"khong dung lai duoc transcript toi vong {snap}"})
            else:
                todo.append((r, snap))
    return todo, skipped


def level_entry(ai: dict, status: str = OK) -> dict:
    """Thong tin 1 bai o 1 cap (ca lan bi loai)."""
    return {
        "status": status, "text": ai.get("text"), "word_count": ai.get("word_count"),
        "target_premise": ai.get("target_premise"), "points_addressed": ai.get("points_addressed"),
        "generator_version": ai.get("generator_version"), "failure_kind": ai.get("failure_kind"), "error": ai.get("error"),
        "attempts": attempt_rows(ai), "latency_ms": ai.get("latency_ms"), "tokens_in": ai.get("tokens_in"),
        "tokens_out": ai.get("tokens_out"), "calls": ai.get("calls", []),
    }


async def branch_state(record: dict, snapshot_round: int, settings, factories: Factories) -> dict:
    """1 trang thai -> 1 ban ghi. KHONG nem loi nghiep vu (het lan thu -> status)."""
    levels = {"medium": level_entry(_medium_ai(record, snapshot_round))}
    for level, arm_name in BRANCH_ARMS.items():
        # Moi cap dung trang thai rieng: 2 bai re nhanh tu CUNG 1 diem, khong thay nhau
        state = build_state(record, snapshot_round)
        result, calls = await _ai_turn(spec_from_record(record, arm_name), ARMS[arm_name], state, factories, settings,
                                       snapshot_round)
        ai = _ai_summary(result, calls)
        status = OK if result.text else (BRANCH_INFRA if failure_category(result.failure_kind) == INFRA else BRANCH_FAILED)
        levels[level] = level_entry(ai, status)
    learner = next(rd["learner"]["text"] for rd in record["rounds"] if rd["round"] == snapshot_round)
    return {
        "state_id": state_id(record["dialogue_id"], snapshot_round), "dialogue_id": record["dialogue_id"],
        "snapshot_round": snapshot_round, "motion_id": record["motion_id"], "motion": record["motion"],
        "motion_type": record["motion_type"], "ai_side": record["ai_side"], "strategy": record["strategy"],
        "burden_pro": record["burden_pro"], "burden_con": record["burden_con"],
        "case_difficulty": record["case_difficulty"], "learner_text": learner, "learner_word_count": word_count(learner),
        "levels": levels, "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def needs_rerun(state: dict) -> bool:
    return any(v["status"] == BRANCH_INFRA for v in state["levels"].values())


def latest_states(states: list[dict]) -> list[dict]:
    last: dict[str, dict] = {}
    for s in states:
        last.pop(s["state_id"], None)
        last[s["state_id"]] = s
    return list(last.values())


def done_ids(path: Path) -> set[str]:
    states = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                state = json.loads(line)
                state["state_id"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            states.append(state)
    return {s["state_id"] for s in latest_states(states) if not needs_rerun(s)}


async def run_all(records: list[dict], settings, factories: Factories, out_path: Path, *, concurrency: int = 2,
                  resume: bool = False, snapshot_rounds=SNAPSHOT_ROUNDS, out=print) -> dict:
    plan, skipped = plan_states(records, snapshot_rounds)
    done = done_ids(out_path) if resume else set()
    todo = [(r, s) for r, s in plan if state_id(r["dialogue_id"], s) not in done]
    out(f"{len(plan)} trang thai; bo {len(skipped)}; da xong {len(plan) - len(todo)}; chay {len(todo)} -> {out_path}")
    for s in skipped:
        out(f"  [BO] {s['state_id']}: {s['reason']}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.with_suffix(".skipped.json").write_text(json.dumps(skipped, ensure_ascii=False, indent=2), encoding="utf-8")
    sem, lock = asyncio.Semaphore(max(1, concurrency)), asyncio.Lock()
    counts = {OK: 0, BRANCH_FAILED: 0, BRANCH_INFRA: 0, "error": 0}

    async def one(record, snap):
        sid = state_id(record["dialogue_id"], snap)
        async with sem:
            try:
                state = await branch_state(record, snap, settings, factories)
            except Exception as e:  # noqa: BLE001 — loi harness: khong ghi dong (resume chay lai)
                logger.exception("Trang thai %s loi harness", sid)
                counts["error"] += 1
                out(f"  [LOI HARNESS] {sid}: {type(e).__name__}: {e}")
                return
            async with lock:
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(state, ensure_ascii=False) + "\n")
            statuses = {k: v["status"] for k, v in state["levels"].items()}
            for level in BRANCH_ARMS:
                counts[statuses[level]] += 1
            out(f"  {sid}: {statuses}")

    await asyncio.gather(*(asyncio.create_task(one(r, s)) for r, s in todo))
    out(f"Xong: {counts}")
    return counts


def make_factories(settings) -> Factories:
    def unused():
        raise AssertionError("Re nhanh khong goi learner gia lap / giam khao")

    return Factories(
        ai=lambda: get_llm_client(settings),
        reviewer=lambda: get_llm_client(settings, provider=settings.stance_review_provider,
                                        model=settings.stance_review_model),
        sim=unused, judge=unused,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Re nhanh easy / hard tu hoi thoai nhanh LM (Giai doan 3e) — LLM THAT")
    p.add_argument("files", nargs="+", type=Path, help="JSONL cua run_pressure_eval co nhanh LM")
    p.add_argument("--rounds", default=",".join(str(r) for r in SNAPSHOT_ROUNDS), help="snapshot_round")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)
    if args.resume and args.out is None:
        p.error("--resume can --out <file JSONL dang chay>")
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    records = [r for f in args.files for r in load_jsonl(f)]
    settings = get_settings()
    out_path = args.out or OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_branch.jsonl"
    counts = asyncio.run(run_all(records, settings, make_factories(settings), out_path, concurrency=args.concurrency,
                                 resume=args.resume, snapshot_rounds=tuple(int(x) for x in args.rounds.split(","))))
    return 0 if counts["error"] == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
