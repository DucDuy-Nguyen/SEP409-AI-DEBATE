"""
Danh gia RAG Evidence buoc 3 tren bo cap lap luan dung / bia (docs/RAG_STEP3_SPEC.md muc 5). GOI LLM THAT (ton token).

Cham ca 2 ban (true, fake) cua moi cap o 2 dieu kien: RAG tat va RAG bat (15 cap -> 60 lan cham), qua dung luong
POST /evaluate: app.services.evidence_evaluator.evaluate_argument_with_evidence. Stage "opening", khong co doi phuong.

Do: diem Evidence trung binh true vs fake o tung dieu kien, chenh lech theo cap + Wilcoxon signed-rank; so cap fake co
CONTRADICTED, so lan luat mem kich hoat, so cap true bi CONTRADICTED (tru oan); tac dong phu len 4 tieu chi con lai
(RAG bat - RAG tat tren cung lap luan); do tre (embed, tach claim, retrieve + verify, cham); token.

Checkpoint sau moi lan cham, `--resume` chay tiep (bo qua lan da xong, chay lai lan bi ERROR).
Chay `--limit 2` truoc (2 cap = 8 lan cham) de uoc tinh token cho ca bo.

Cach dung:
    python scripts/rag/eval_evidence_pairs.py --limit 2
    python scripts/rag/eval_evidence_pairs.py
    python scripts/rag/eval_evidence_pairs.py --resume
"""
import argparse
import json
import shutil
import statistics
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVICE_DIR))

from app.config import get_settings
from app.rag import pipeline
from app.rag.llm_usage import LLMCallStats
from app.schemas import ArgumentEvaluationRequest, DebateSide, DebateStage
from app.services.evidence_evaluator import evaluate_argument_with_evidence
from app.services.llm_client import LLMClient, get_llm_client

sys.stdout.reconfigure(encoding="utf-8")

PAIRS_PATH = SERVICE_DIR / "docs" / "rag_eval" / "evidence_pairs.jsonl"
RESULTS_DIR = SERVICE_DIR / "data" / "results"
DOCS_RESULTS_DIR = SERVICE_DIR / "docs" / "rag_results"

VERSIONS = ("true", "fake")
CONDITIONS = ("rag_off", "rag_on")
OTHER_CRITERIA = ("Logic", "Relevance", "Structure", "Persuasiveness")
TOKEN_BUDGET = 400_000
TOTAL_PAIRS = 15


class TrackingClient(LLMClient):
    """Client cham diem: cong token cua moi lan goi (ke ca lan retry vi JSON loi)."""

    def __init__(self, inner: LLMClient):
        self.inner = inner
        self.prompt_tokens = self.completion_tokens = self.calls = 0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.inner.last_usage = None
        try:
            return self.inner.generate(system_prompt, user_prompt)
        finally:
            usage = self.inner.last_usage
            if usage is not None:
                self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
                self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0


class TimedEmbedder:
    def __init__(self, inner):
        self.inner, self.seconds = inner, 0.0

    def encode(self, texts):
        started = time.perf_counter()
        try:
            return self.inner.encode(texts)
        finally:
            self.seconds += time.perf_counter() - started


def _timed(function, timings: dict, key: str):
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            timings[key] = timings.get(key, 0.0) + time.perf_counter() - started

    return wrapper


def grade_once(pair: dict, version: str, condition: str, base_settings, embedder) -> dict:
    settings = base_settings.model_copy(update={"rag_enabled": condition == "rag_on"})
    request = ArgumentEvaluationRequest(
        motion=pair["motion"], side=DebateSide(pair["side"]), stage=DebateStage.OPENING,
        argument_text=pair[f"argument_{version}"], topic=pair["topic"],
    )
    timings: dict[str, float] = {}
    rag_stats = LLMCallStats()
    timed_embedder = TimedEmbedder(embedder)
    original_extract, original_verify = pipeline.extract_claims, pipeline.verify_claims
    # Do tre tung buoc ma van chay dung pipeline.check_evidence cua luong that
    pipeline.extract_claims = _timed(original_extract, timings, "extract")
    pipeline.verify_claims = _timed(original_verify, timings, "retrieve_verify")

    def checker(argument_text, motion, topic, check_settings):
        return pipeline.check_evidence(argument_text, motion, topic, check_settings, embedder=timed_embedder, stats=rag_stats)

    client = TrackingClient(get_llm_client(settings))
    started = time.perf_counter()
    try:
        result = evaluate_argument_with_evidence(request, settings, client, checker)
    finally:
        pipeline.extract_claims, pipeline.verify_claims = original_extract, original_verify
    total = time.perf_counter() - started

    embed = timed_embedder.seconds
    rag_seconds = timings.get("extract", 0.0) + timings.get("retrieve_verify", 0.0)
    check = result.evidence_check
    return {
        "pair_id": pair["pair_id"], "topic": pair["topic"], "version": version, "condition": condition,
        "scores": {c.name: c.score for c in result.criteria},
        "overall_score": result.overall_score,
        "evidence_reasoning": next(c.reasoning for c in result.criteria if c.name == "Evidence"),
        "evidence_check": check.model_dump() if check else None,
        "seconds": {"total": round(total, 2), "embed": round(embed, 2), "extract": round(timings.get("extract", 0.0), 2),
                    "retrieve_verify_excl_embed": round(timings.get("retrieve_verify", 0.0) - embed, 2),
                    "grade": round(total - rag_seconds, 2)},
        "tokens": {"grade_prompt": client.prompt_tokens, "grade_completion": client.completion_tokens,
                   "grade_calls": client.calls, "rag": rag_stats.total_tokens, "rag_stats": asdict(rag_stats)},
    }


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------


def _key(record: dict) -> str:
    return f"{record['pair_id']}:{record['version']}:{record['condition']}"


def load_checkpoint(path: Path) -> dict[str, dict]:
    done: dict[str, dict] = {}
    if not path.exists():
        return done
    for number, line in enumerate(path.open(encoding="utf-8"), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            print(f"Canh bao: bo qua dong {number} hong trong checkpoint {path}", flush=True)
            continue
        if "error" not in record:
            done[_key(record)] = record
    return done


def append_checkpoint(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Bao cao
# ---------------------------------------------------------------------------


def _mean(values: list[float]):
    return round(statistics.fmean(values), 3) if values else None


def _tokens(record: dict) -> int:
    t = record["tokens"]
    return t["grade_prompt"] + t["grade_completion"] + t["rag"]


def _labels(record: dict) -> list[str]:
    check = record.get("evidence_check") or {}
    return [claim["label"] for claim in check.get("claims", [])]


def build_report(records: dict[str, dict], pair_ids: list[str]) -> dict:
    from scipy.stats import wilcoxon

    def get(pair_id, version, condition):
        return records.get(f"{pair_id}:{version}:{condition}")

    report: dict = {"pairs": len(pair_ids), "gradings": len(records), "conditions": {}}
    for condition in CONDITIONS:
        complete = [p for p in pair_ids if get(p, "true", condition) and get(p, "fake", condition)]
        true_scores = [get(p, "true", condition)["scores"]["Evidence"] for p in complete]
        fake_scores = [get(p, "fake", condition)["scores"]["Evidence"] for p in complete]
        diffs = [t - f for t, f in zip(true_scores, fake_scores)]
        test = None
        if any(diffs):
            statistic, p_value = wilcoxon(true_scores, fake_scores, zero_method="wilcox")
            test = {"statistic": float(statistic), "p_value": float(p_value), "nonzero_pairs": sum(d != 0 for d in diffs)}
        condition_records = [r for r in records.values() if r["condition"] == condition]
        report["conditions"][condition] = {
            "complete_pairs": len(complete),
            "evidence_mean_true": _mean(true_scores),
            "evidence_mean_fake": _mean(fake_scores),
            "per_pair_diff": dict(zip(complete, diffs)),
            "mean_diff": _mean(diffs),
            "wilcoxon": test,
            "overall_mean_true": _mean([get(p, "true", condition)["overall_score"] for p in complete]),
            "overall_mean_fake": _mean([get(p, "fake", condition)["overall_score"] for p in complete]),
            "seconds_mean": {key: _mean([r["seconds"][key] for r in condition_records])
                             for key in ("total", "embed", "extract", "retrieve_verify_excl_embed", "grade")},
            "tokens_total": sum(_tokens(r) for r in condition_records),
            "tokens_mean": _mean([_tokens(r) for r in condition_records]),
        }

    rag_on = [r for r in records.values() if r["condition"] == "rag_on"]
    fake_on = {r["pair_id"]: r for r in rag_on if r["version"] == "fake"}
    true_on = {r["pair_id"]: r for r in rag_on if r["version"] == "true"}
    report["fake_with_contradicted"] = sorted(p for p, r in fake_on.items() if "CONTRADICTED" in _labels(r))
    report["fake_not_detected"] = sorted(p for p, r in fake_on.items() if "CONTRADICTED" not in _labels(r))
    report["true_with_contradicted"] = sorted(p for p, r in true_on.items() if "CONTRADICTED" in _labels(r))
    report["soft_cap_triggered"] = sorted(_key(r) for r in rag_on if (r.get("evidence_check") or {}).get("evidence_capped"))
    report["evidence_check_status"] = {
        status: sum((r.get("evidence_check") or {}).get("status") == status for r in rag_on)
        for status in ("checked", "no_claims", "unavailable")
    }

    side_effects = {name: [] for name in OTHER_CRITERIA}
    for pair_id in pair_ids:
        for version in VERSIONS:
            on, off = get(pair_id, version, "rag_on"), get(pair_id, version, "rag_off")
            if on and off:
                for name in OTHER_CRITERIA:
                    side_effects[name].append(on["scores"][name] - off["scores"][name])
    report["side_effect_on_minus_off"] = {name: _mean(values) for name, values in side_effects.items()}
    return report


def print_report(report: dict) -> None:
    print("\n| Dieu kien | Evidence true | Evidence fake | Chenh TB (true-fake) | Wilcoxon p | Overall true | Overall fake | Token TB/lan | Thoi gian TB (s) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for condition, c in report["conditions"].items():
        p_value = c["wilcoxon"]["p_value"] if c["wilcoxon"] else None
        print(f"| {condition} | {c['evidence_mean_true']} | {c['evidence_mean_fake']} | {c['mean_diff']} | "
              f"{'-' if p_value is None else round(p_value, 4)} | {c['overall_mean_true']} | {c['overall_mean_fake']} | "
              f"{c['tokens_mean']} | {c['seconds_mean']['total']} |")
    for condition, c in report["conditions"].items():
        print(f"{condition} chenh theo cap: {c['per_pair_diff']}")
        print(f"{condition} thoi gian TB: {c['seconds_mean']} | token tong {c['tokens_total']}")
    for key in ("fake_with_contradicted", "fake_not_detected", "true_with_contradicted", "soft_cap_triggered",
                "evidence_check_status", "side_effect_on_minus_off"):
        print(f"{key}: {report[key]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="So cap dau tien (uoc tinh token)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="Xoa checkpoint cu va cham lai tu dau (ton token)")
    args = parser.parse_args()

    pairs = [json.loads(line) for line in PAIRS_PATH.open(encoding="utf-8") if line.strip()]
    pairs = pairs[: args.limit] if args.limit else pairs
    pair_ids = [p["pair_id"] for p in pairs]
    checkpoint = RESULTS_DIR / f"evidence_pairs{f'_limit{args.limit}' if args.limit else ''}_checkpoint.jsonl"
    if checkpoint.exists() and not (args.resume or args.fresh):
        # Khong tu xoa: checkpoint co the chua hang tram nghin token da cham
        raise SystemExit(f"Da co checkpoint {checkpoint}: chay voi --resume de chay tiep, hoac --fresh de cham lai tu dau")
    if args.fresh:
        checkpoint.unlink(missing_ok=True)
    done = load_checkpoint(checkpoint)
    if done:
        print(f"Chay tiep tu checkpoint: {len(done)} lan cham da xong", flush=True)

    from app.rag.embedder import get_default_embedder

    embedder = get_default_embedder()
    embedder.encode(["khoi dong model"])  # Load model truoc, de do tre khong tinh thoi gian load lan dau
    base_settings = get_settings()

    for pair in pairs:
        for version in VERSIONS:
            for condition in CONDITIONS:
                key = f"{pair['pair_id']}:{version}:{condition}"
                if key in done:
                    continue
                try:
                    record = grade_once(pair, version, condition, base_settings, embedder)
                    done[key] = record
                except Exception as exc:  # 1 lan cham loi khong lam mat cac lan khac; --resume chay lai
                    print(f"{key} loi: {type(exc).__name__}: {exc}", flush=True)
                    traceback.print_exc()
                    record = {"pair_id": pair["pair_id"], "version": version, "condition": condition,
                              "error": f"{type(exc).__name__}: {exc}"}
                append_checkpoint(checkpoint, record)
                tokens = sum(_tokens(r) for r in done.values())
                print(f"{len(done)}/{len(pairs) * 4} lan cham, {tokens} token", flush=True)

    report = build_report(done, pair_ids)
    total_tokens = sum(_tokens(r) for r in done.values())
    report["tokens_total"] = total_tokens
    report["model"] = base_settings.groq_model if base_settings.llm_provider == "groq" else base_settings.llm_provider
    print_report(report)
    print(f"\nTong token: {total_tokens}")
    if args.limit:
        estimate = total_tokens / len(pairs) * TOTAL_PAIRS
        report["estimate_full_tokens"] = round(estimate)
        print(f"Uoc tinh ca bo {TOTAL_PAIRS} cap: {estimate:,.0f} token (nguong {TOKEN_BUDGET:,})")
        if estimate > TOKEN_BUDGET:
            print("VUOT NGUONG: dung lai, bao nguoi dung truoc khi chay day du.")

    errors = [key for key in (f"{p}:{v}:{c}" for p in pair_ids for v in VERSIONS for c in CONDITIONS) if key not in done]
    report["missing_or_error"] = errors
    report["records"] = list(done.values())
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_limit{args.limit}" if args.limit else ""
    output_path = RESULTS_DIR / f"evidence_pairs{suffix}_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Da ghi {output_path}")
    if errors:
        print(f"Con {len(errors)} lan cham chua xong/loi: chay lai voi --resume")
    else:
        checkpoint.unlink(missing_ok=True)
        if not args.limit:
            DOCS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output_path, DOCS_RESULTS_DIR / output_path.name)
            print(f"Da chep sang {DOCS_RESULTS_DIR / output_path.name}")


if __name__ == "__main__":
    main()
