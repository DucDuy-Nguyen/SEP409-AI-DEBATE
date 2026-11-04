"""
Giai doan 3d — chay stress test do vung lap truong (dev log muc 3.1). GOI LLM THAT (Groq + Anthropic) — ton tien.

    python -m scripts.run_pressure_eval --limit 1                       # smoke test: 1 hoi thoai moi nhanh
    python -m scripts.run_pressure_eval --arms A,B,C,D,E,F --motions P1,P3,C1,C4,V1,V4 \\
        --strategies moi_nhuong_bo,ap_luc_xa_hoi --rounds 5 --concurrency 2
    python -m scripts.run_pressure_eval --resume --out experiments/pressure_eval/<file>.jsonl   # chay tiep

- Moi hoi thoai 1 dong JSONL (moi bai noi, verdict giam khao, moi loi goi LLM: token, latency, chi phi, loi).
- --resume: bo qua hoi thoai DA XONG (co dong trong file, theo dialogue_id = arm|motion|side|strategy).
- Thu tu XEN KE nhanh (moi cau hinh -> A, B, C, ... ) de tai provider phan bo deu.
- Case file: batch case_plan_v7_x3, repeat_round 1, chi ready + reviewer pass (cau hinh khac bi bo, in ra).
- Giai doan 3e (muc 3.3): --arms LE,LM,LH --case-batch <batch medium> --replicates 2. Mac dinh van A-F, 1 lan.
- --replicates N >= 2: moi to hop chay N lan doc lap, dialogue_id them |r{k}; --resume bo qua replicate da xong. N = 1: id khong
  hau to (nhu file 3d), nen file chay voi N = 1 khong resume tiep duoc thanh N = 2.
"""
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.llm.client import get_llm_client
from scripts.pressure_common import (
    ARMS,
    DEFAULT_ARMS,
    UNCONFIRMED_PRICES,
    DEFAULT_CASE_BATCH,
    DEFAULT_MOTIONS,
    DEFAULT_ROUNDS,
    OUT_DIR,
    STRATEGIES,
    Factories,
    JudgeConfig,
    SimConfig,
    build_specs,
    latest_records,
    load_case_configs,
    needs_rerun,
    run_dialogue,
)

logger = logging.getLogger(__name__)


def done_ids(path: Path) -> set[str]:
    """
    dialogue_id DA XONG (bo dong hong / dang ghi do). Ban ghi CUOI cua moi id dung vi loi HA TANG (provider, mang, 429,
    het budget, learner gia lap loi) KHONG tinh la xong -> --resume chay lai (muc 3.1 sua doi 4); report giu ban ghi cuoi.
    """
    records = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                record["dialogue_id"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            records.append(record)
    return {r["dialogue_id"] for r in latest_records(records) if not needs_rerun(r)}


async def run_all(specs, settings, factories, out_path: Path, *, concurrency: int = 2, resume: bool = False,
                  sim: SimConfig | None = None, judge: JudgeConfig | None = None, rounds: int = DEFAULT_ROUNDS,
                  out=print) -> dict:
    skip = done_ids(out_path) if resume else set()
    todo = [s for s in specs if s.dialogue_id not in skip]
    out(f"Tong {len(specs)} hoi thoai; bo qua {len(specs) - len(todo)} da xong; chay {len(todo)} -> {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sem, lock = asyncio.Semaphore(max(1, concurrency)), asyncio.Lock()
    counts = {"completed": 0, "ai_failed": 0, "sim_failed": 0, "error": 0}

    async def one(spec):
        async with sem:
            try:
                record = await run_dialogue(spec, settings, factories, sim, judge, rounds)
            except Exception as e:  # noqa: BLE001 — loi bat ngo cua harness: ghi log, KHONG ghi dong (resume chay lai)
                logger.exception("Hoi thoai %s loi harness", spec.dialogue_id)
                counts["error"] += 1
                out(f"  [LOI HARNESS] {spec.dialogue_id}: {type(e).__name__}: {e}")
                return
            async with lock:
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            counts[record["status"]] = counts.get(record["status"], 0) + 1
            m = record["metrics"]
            out(f"  {spec.dialogue_id}: {record['status']}"
                + (f" (vong {record['failed_round']}: {record['failure_kind']})" if record["failed_round"] is not None else "")
                + f" ToF={m['tof']} NoF={m['nof']} sim_flip={m['sim_flips']}")

    # create_task theo thu tu -> semaphore giu thu tu bat dau (xen ke nhanh)
    await asyncio.gather(*(asyncio.create_task(one(s)) for s in todo))
    out(f"Xong: {counts}")
    return counts


def make_factories(settings, sim: SimConfig, judge: JudgeConfig) -> Factories:
    return Factories(
        ai=lambda: get_llm_client(settings),
        reviewer=lambda: get_llm_client(settings, provider=settings.stance_review_provider,
                                        model=settings.stance_review_model),
        sim=lambda: get_llm_client(settings, provider=sim.provider, model=sim.model),
        judge=lambda: get_llm_client(settings, provider=judge.provider, model=judge.model),
    )


def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stress test do vung lap truong (Giai doan 3d) — LLM THAT")
    p.add_argument("--arms", default=",".join(DEFAULT_ARMS), help=f"Mac dinh A-F; co the chon: {','.join(ARMS)}")
    p.add_argument("--motions", default=",".join(DEFAULT_MOTIONS))
    p.add_argument("--strategies", default=",".join(STRATEGIES))
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--limit", type=int, default=None, help="N hoi thoai moi nhanh (smoke test)")
    p.add_argument("--replicates", type=int, default=1, help="So lan chay doc lap moi to hop (cung case file, khac lan sinh)")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--out", type=Path, default=None, help="File JSONL (bat buoc khi --resume)")
    p.add_argument("--case-batch", type=Path, default=DEFAULT_CASE_BATCH)
    p.add_argument("--case-rounds", default="1,2,3",
                   help="Thu tu repeat_round de chon case file DAU TIEN dat (ready + reviewer pass)")
    p.add_argument("--sim-provider", default=SimConfig.provider)
    p.add_argument("--sim-model", default=SimConfig.model)
    p.add_argument("--sim-temperature", type=float, default=SimConfig.temperature)
    p.add_argument("--sim-effort", default=SimConfig.reasoning_effort)
    p.add_argument("--judge-provider", default=JudgeConfig.provider,
                   help="anthropic (mac dinh) | groq (du phong: --judge-model openai/gpt-oss-120b)")
    p.add_argument("--judge-model", default=JudgeConfig.model)
    p.add_argument("--judge-effort", default=None, help="Chi Groq (vd medium)")
    args = p.parse_args(argv)

    arms, strategies = _csv(args.arms), _csv(args.strategies)
    bad = [a for a in arms if a not in ARMS] + [s for s in strategies if s not in STRATEGIES]
    if bad:
        p.error(f"Nhanh / chien thuat khong hop le: {bad}")
    if args.resume and args.out is None:
        p.error("--resume can --out <file JSONL dang chay>")
    if args.replicates < 1:
        p.error("--replicates phai >= 1")
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    configs, notes = load_case_configs(args.case_batch, _csv(args.motions),
                                       tuple(int(x) for x in _csv(args.case_rounds)))
    for n in notes:
        print(f"[CASE FILE] {n}")
    for c in configs:
        print(f"  {c.motion_id} {c.ai_side.value}: repeat_round {c.case_source['repeat_round']} "
              f"(run_index {c.case_source['run_index']}, {c.difficulty.value})")
    print(f"Gia CHUA XAC NHAN: {', '.join(UNCONFIRMED_PRICES)} (kiem tra groq.com/pricing)")
    specs = build_specs(configs, arms, strategies, args.limit, args.replicates)
    settings = get_settings()
    sim = SimConfig(args.sim_provider, args.sim_model, args.sim_temperature, args.sim_effort)
    judge = JudgeConfig(args.judge_provider, args.judge_model, reasoning_effort=args.judge_effort)
    out_path = args.out or OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_pressure.jsonl"
    counts = asyncio.run(run_all(specs, settings, make_factories(settings, sim, judge), out_path,
                                 concurrency=args.concurrency, resume=args.resume, sim=sim, judge=judge,
                                 rounds=args.rounds))
    return 0 if counts.get("error", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
