"""
Batch runner Case Planning — goi LLM THAT (ton token), KHONG dung DB, KHONG nam trong pytest.

Moi motion chay 2 lan (ai_side = pro, con); difficulty xoay vong easy -> medium -> hard theo thu tu
lan chay. Moi lan chay ghi NGAY 1 dong JSONL (mat dien giua chung van con du lieu da chay):
    experiments/case_plan/<timestamp>_<prompt_version>.jsonl
kem file tong hop <cung ten>.summary.json. Thu muc experiments/ la du lieu cho bao cao — KHONG gitignore.

TPM free tier Groq = 8000 token/phut, moi lan goi Case Planning xin ~4000 (tinh ca max_tokens) -> toi da ~2 lan
Case Planning / phut cho TOAN he thong. Mac dinh nghi 35s giua cac lan chay. KHONG chay 2 batch cung luc.

Chay tu thu muc goc service:
    python -m scripts.run_case_plan_batch                       # 10 motion x 2 phe = 20 lan
    python -m scripts.run_case_plan_batch --limit 1             # thu nhanh: 1 motion x 2 phe
    python -m scripts.run_case_plan_batch --prompt-version v3   # chay prompt v3 (mac dinh theo CASE_PLAN_PROMPT_VERSION)
    python -m scripts.run_case_plan_batch --only-failed experiments/case_plan/<file>.jsonl  # chay lai cac cau hinh llm_error
So sanh 2 file ket qua: python -m scripts.compare_case_plan_batches <a.jsonl> <b.jsonl>
"""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from app.core.config import Settings, get_settings
from app.llm.client import LLMClient, get_llm_client
from app.opponent.models import DebateSide, LLMCallPurpose, OpponentDifficulty, ReviewerVerdict
from app.opponent.service import SIDE_FLIP_NEUTRAL_RETRY, AttemptRecord, CasePlanOutcome, FailureKind, generate_case_file

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MOTIONS = ROOT / "experiments" / "motions_v1.json"
DEFAULT_OUT_DIR = ROOT / "experiments" / "case_plan"
DEFAULT_PAUSE_SECONDS = 35.0  # TPM 8000 / ~4000 token moi lan goi Case Planning
DIFFICULTY_CYCLE = [OpponentDifficulty.EASY, OpponentDifficulty.MEDIUM, OpponentDifficulty.HARD]


def load_motions(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["motions"]


def load_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_runs(motions: list[dict]) -> list[dict]:
    """Moi motion x (pro, con); difficulty xoay vong theo chi so lan chay."""
    runs = []
    for motion in motions:
        for ai_side in (DebateSide.PRO, DebateSide.CON):
            runs.append(
                {
                    "run_index": len(runs),
                    "motion_id": motion["id"],
                    "motion": motion["motion"],
                    "ai_side": ai_side,
                    "learner_side": DebateSide.CON if ai_side == DebateSide.PRO else DebateSide.PRO,
                    "difficulty": DIFFICULTY_CYCLE[len(runs) % len(DIFFICULTY_CYCLE)],
                }
            )
    return runs


def runs_from_failed(records: list[dict]) -> list[dict]:
    """Cau hinh (motion, phe, do kho) cua cac lan chay llm_error trong 1 file JSONL cu — giu run_index goc."""
    return [
        {
            "run_index": r["run_index"],
            "motion_id": r["motion_id"],
            "motion": r["motion"],
            "ai_side": DebateSide(r["ai_side"]),
            "learner_side": DebateSide(r["learner_side"]),
            "difficulty": OpponentDifficulty(r["difficulty"]),
        }
        for r in records
        if r["final_status"] == "llm_error"
    ]


def final_status(outcome: CasePlanOutcome) -> str:
    if outcome.case_file is not None:
        return "ready"
    if outcome.budget_exceeded:
        return "budget_exceeded"
    if outcome.llm_error is not None:
        return "llm_error"
    return "invalid_output"  # het so lan thu: sai JSON/schema/so luan diem/"Giả sử"/cum cam/side_flip


def attempt_to_dict(a: AttemptRecord) -> dict:
    return {
        "attempt": a.attempt,
        "purpose": a.purpose.value,
        "latency_ms": a.latency_ms,
        "success": a.success,
        "error": a.error,
        "schema_rejected": a.schema_rejected,
        "failure_kind": a.failure_kind,
        "retry_feedback": a.retry_feedback,
        "reviewer_verdict": a.reviewer_verdict.value if a.reviewer_verdict else None,
        "reviewer_detail": a.reviewer_detail,
        "vague_evidence": a.vague_evidence,
        "tokens_in": a.tokens_in,
        "tokens_out": a.tokens_out,
        "rate_limit_wait_ms": a.rate_limit_wait_ms,
        "key_repairs": a.key_repairs,
        "raw_output": a.raw_output,
    }


# ---- 2 chi so TACH RIENG: retry vi noi dung vs cho vi 429 ----


def content_retries(record: dict) -> int:
    """
    So lan THU LAI Case Planning vi output khong hop le (schema, validator, cum cam, side_flip...).
    = so lan thu case_plan co retry_feedback (phan hoi chi sinh ra khi thuc su retry) hoac retry trung tinh sau side_flip
    (khong co phan hoi, danh dau o reviewer_detail.retry — muc 2.4m). Cho 429 KHONG tinh.
    """
    return sum(
        1 for a in record["attempts"] if a["purpose"] == LLMCallPurpose.CASE_PLAN.value and (
            a.get("retry_feedback") or (a.get("reviewer_detail") or {}).get("retry") == SIDE_FLIP_NEUTRAL_RETRY
        )
    )


def rate_limit_waits(record: dict) -> tuple[int, float | None]:
    """
    (so lan cho vi 429, tong giay da cho). File cu (chua co rate_limit_wait_ms): dem cac lan 429, giay = None.
    """
    attempts = record["attempts"]
    if any("rate_limit_wait_ms" in a for a in attempts):
        waits = [a["rate_limit_wait_ms"] for a in attempts if a.get("rate_limit_wait_ms") is not None]
        return len(waits), round(sum(waits) / 1000, 1)
    return sum(1 for a in attempts if a.get("failure_kind") == FailureKind.RATE_LIMITED), None


def run_record(
    run: dict, outcome: CasePlanOutcome, total_latency_ms: int, settings: Settings, rerun_of: str | None = None
) -> dict:
    final_plan = next(
        (a for a in reversed(outcome.attempts) if a.purpose == LLMCallPurpose.CASE_PLAN and a.success), None
    )
    record = {
        "run_index": run["run_index"],
        "motion_id": run["motion_id"],
        "motion": run["motion"],
        "ai_side": run["ai_side"].value,
        "learner_side": run["learner_side"].value,
        "difficulty": run["difficulty"].value,
        "prompt_version": outcome.prompt_version,
        "provider": outcome.llm_provider,
        "model": outcome.llm_model,
        "reviewer_model": outcome.reviewer_model,
        "temperature": outcome.temperature,
        "case_plan_max_tokens": settings.case_plan_max_tokens,
        "json_schema": settings.case_plan_use_json_schema,
        "rerun_of": rerun_of,
        "final_status": final_status(outcome),
        "total_latency_ms": total_latency_ms,
        "final_reviewer_verdict": (
            final_plan.reviewer_verdict.value if final_plan and final_plan.reviewer_verdict else None
        ),
        "final_vague_evidence": final_plan.vague_evidence if final_plan else None,
        "attempts": [attempt_to_dict(a) for a in outcome.attempts],
        "case_file": outcome.case_file.model_dump(mode="json") if outcome.case_file else None,
    }
    waits, wait_seconds = rate_limit_waits(record)
    record.update(content_retries=content_retries(record), rate_limit_waits=waits, rate_limit_wait_seconds=wait_seconds)
    return record


def _call_line(a: dict) -> str:
    status = "ok" if a["success"] else (a["failure_kind"] or "loi")
    wait = f" -> cho {a['rate_limit_wait_ms'] / 1000:.1f}s" if a.get("rate_limit_wait_ms") is not None else ""
    return (
        f"      #{a['attempt']:<2} {a['purpose']:<13} in={a['tokens_in'] if a['tokens_in'] is not None else '-':>5} "
        f"out={a['tokens_out'] if a['tokens_out'] is not None else '-':>5} {a['latency_ms']:>6} ms  {status}{wait}"
    )


async def run_batch(
    runs: list[dict],
    client: LLMClient,
    reviewer_client: LLMClient | None,
    settings: Settings,
    out_path: Path,
    pause_seconds: float = 0,
    log=print,
    rerun_of: str | None = None,
) -> list[dict]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for i, run in enumerate(runs):
        if i and pause_seconds:
            await asyncio.sleep(pause_seconds)
        started = time.perf_counter()
        outcome = await generate_case_file(
            run["motion"], run["ai_side"], run["learner_side"], run["difficulty"], client, settings, reviewer_client
        )
        record = run_record(run, outcome, int((time.perf_counter() - started) * 1000), settings, rerun_of)
        with out_path.open("a", encoding="utf-8") as f:  # ghi ngay tung dong
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        records.append(record)
        wait_text = f"{record['rate_limit_wait_seconds']}s" if record["rate_limit_wait_seconds"] is not None else "?"
        log(
            f"[{i + 1}/{len(runs)}] {run['motion_id']} {run['ai_side'].value:<3} {run['difficulty'].value:<6} "
            f"-> {record['final_status']:<15} retry_noi_dung={record['content_retries']} "
            f"cho_429={record['rate_limit_waits']} ({wait_text}) {record['total_latency_ms']} ms"
        )
        for a in record["attempts"]:
            log(_call_line(a))
    return records


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0


def summarize(records: list[dict]) -> dict:
    attempts = [a for r in records for a in r["attempts"]]
    plan_attempts = [a for a in attempts if a["purpose"] == LLMCallPurpose.CASE_PLAN.value]
    statuses: dict[str, int] = {}
    for r in records:
        statuses[r["final_status"]] = statuses.get(r["final_status"], 0) + 1
    retries = [content_retries(r) for r in records]
    waits = [rate_limit_waits(r) for r in records]
    wait_seconds = [s for _, s in waits if s is not None]
    plan_tokens_out = [a["tokens_out"] for a in plan_attempts if a.get("tokens_out") is not None]
    return {
        "runs": len(records),
        "success": statuses.get("ready", 0),
        "final_status": statuses,
        "side_flip_caught": sum(1 for a in plan_attempts if a["reviewer_verdict"] == ReviewerVerdict.SIDE_FLIP.value),
        "runs_with_side_flip": sum(
            1 for r in records if any(a["reviewer_verdict"] == ReviewerVerdict.SIDE_FLIP.value for a in r["attempts"])
        ),
        "final_unclear": sum(1 for r in records if r["final_reviewer_verdict"] == ReviewerVerdict.UNCLEAR.value),
        "schema_rejected": sum(1 for a in attempts if a["schema_rejected"]),
        "case_files_with_vague_evidence": sum(
            1 for r in records if r["case_file"] is not None and r["final_vague_evidence"]
        ),
        "banned_phrase_rejected": sum(1 for a in plan_attempts if a.get("failure_kind") == FailureKind.BANNED_PHRASE),
        "key_repaired": sum(1 for a in plan_attempts if a.get("key_repairs")),
        "content_retries": sum(retries),
        "avg_content_retries": _avg(retries),
        "rate_limit_waits": sum(n for n, _ in waits),
        "rate_limit_wait_seconds": round(sum(wait_seconds), 1) if wait_seconds else None,
        "case_plan_calls": len(plan_attempts),
        "case_plan_tokens_out_avg": round(_avg(plan_tokens_out)) if plan_tokens_out else None,
        "case_plan_tokens_out_max": max(plan_tokens_out) if plan_tokens_out else None,
        "case_plan_max_tokens": records[0].get("case_plan_max_tokens") if records else None,
        "avg_latency_ms": round(_avg([r["total_latency_ms"] for r in records])),
    }


def format_summary(summary: dict) -> str:
    wait_s = summary["rate_limit_wait_seconds"]
    rows = [
        ("So lan chay", summary["runs"]),
        ("Thanh cong (co case file)", f"{summary['success']}/{summary['runs']}"),
        ("Trang thai cuoi", ", ".join(f"{k}={v}" for k, v in sorted(summary["final_status"].items()))),
        ("side_flip bi reviewer bat (lan thu)", summary["side_flip_caught"]),
        ("  - so lan chay co side_flip", summary["runs_with_side_flip"]),
        ("Case file cuoi reviewer 'unclear'", summary["final_unclear"]),
        ("Groq tu choi schema (lan thu)", summary["schema_rejected"]),
        ("Case file co vague_evidence", summary["case_files_with_vague_evidence"]),
        ("Bi reject do bang chung mo ho HIGH (lan thu)", summary["banned_phrase_rejected"]),
        ("Tu sua ten truong, khong goi lai LLM", summary["key_repaired"]),
        ("content_retries (tong / tb lan chay)", f"{summary['content_retries']} / {summary['avg_content_retries']}"),
        ("rate_limit_waits (lan / tong giay)", f"{summary['rate_limit_waits']} / {wait_s if wait_s is not None else '?'}s"),
        ("Tong lan goi case_plan (ke ca 429)", summary["case_plan_calls"]),
        (
            "tokens_out case_plan (tb / max)",
            f"{summary['case_plan_tokens_out_avg']} / {summary['case_plan_tokens_out_max']} "
            f"(max_tokens={summary['case_plan_max_tokens']})",
        ),
        ("Latency trung binh / lan chay", f"{summary['avg_latency_ms']} ms"),
    ]
    width = max(len(k) for k, _ in rows)
    value_width = max(30, max(len(str(v)) for _, v in rows))
    line = "+" + "-" * (width + 2) + "+" + "-" * (value_width + 2) + "+"
    body = "\n".join(f"| {k:<{width}} | {str(v):<{value_width}} |" for k, v in rows)
    return f"{line}\n{body}\n{line}"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Batch Case Planning voi LLM that")
    parser.add_argument("--motions", type=Path, default=DEFAULT_MOTIONS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="Chi chay N motion dau (moi motion 2 lan)")
    parser.add_argument(
        "--pause", type=float, default=DEFAULT_PAUSE_SECONDS,
        help=f"Giay nghi giua cac lan chay (mac dinh {DEFAULT_PAUSE_SECONDS:.0f}s: TPM free tier 8000)",
    )
    parser.add_argument("--no-review", action="store_true", help="Tat Stance Reviewer")
    parser.add_argument(
        "--prompt-version", choices=["v3", "v4", "v5"], default=None,
        help="Prompt Case Planning (mac dinh: CASE_PLAN_PROMPT_VERSION; voi --only-failed: prompt cua file cu)",
    )
    parser.add_argument(
        "--only-failed", type=Path, default=None, metavar="FILE.jsonl",
        help="Chi chay lai cac cau hinh bi llm_error trong file JSONL cu (bo qua --motions / --limit)",
    )
    args = parser.parse_args()

    settings = get_settings()
    rerun_of = None
    if args.only_failed:
        old = load_records(args.only_failed)
        runs = runs_from_failed(old)
        rerun_of = args.only_failed.name
        old_version = old[0]["prompt_version"] if old else settings.case_plan_prompt_version
        version = f"case_plan_{args.prompt_version}" if args.prompt_version else old_version
        if version != old_version:
            print(f"CANH BAO: file cu dung {old_version}, dang chay lai bang {version} — ket qua KHONG so sanh truc tiep duoc.")
        settings = settings.model_copy(update={"case_plan_prompt_version": version})
        if not runs:
            print(f"{args.only_failed} khong co lan chay llm_error nao.")
            return 0
    else:
        if args.prompt_version:
            settings = settings.model_copy(update={"case_plan_prompt_version": f"case_plan_{args.prompt_version}"})
        runs = build_runs(load_motions(args.motions)[: args.limit])

    client = get_llm_client(settings)
    reviewer_client = None
    if settings.stance_review_enabled and not args.no_review:
        reviewer_client = get_llm_client(
            settings, provider=settings.stance_review_provider, model=settings.stance_review_model
        )

    suffix = "_rerun" if rerun_of else ""
    out_path = args.out_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{settings.case_plan_prompt_version}{suffix}.jsonl"
    print(
        f"{len(runs)} lan chay | prompt {settings.case_plan_prompt_version} | planner {client.provider}/{client.model} | "
        f"reviewer {reviewer_client.model if reviewer_client else 'TAT'} | pause {args.pause:.0f}s"
        + (f" | chay lai llm_error cua {rerun_of}" if rerun_of else "")
        + f" | -> {out_path}"
    )

    records = await run_batch(
        runs, client, reviewer_client, settings, out_path, pause_seconds=args.pause, rerun_of=rerun_of
    )
    summary = summarize(records)
    out_path.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + format_summary(summary))
    return 0 if summary["success"] == summary["runs"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
