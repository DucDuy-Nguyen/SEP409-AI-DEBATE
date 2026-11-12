"""
Danh gia RAG Evidence buoc 3 tren bo cap lap luan dung / bia (docs/RAG_STEP3_SPEC.md muc 5). GOI LLM THAT (ton token).

Cham ca 2 ban (true, fake) cua moi cap qua dung luong POST /evaluate (app.services.evidence_evaluator.
evaluate_argument_with_evidence), stage "opening", khong co doi phuong. Dieu kien: `rag_off` va/hoac `rag_on`
(--conditions). Voi phuong an D (dev log muc 3.21) luot cham RAG bat dung dung prompt cu, nen diem goc
(evidence_score_before) chinh la diem khong co RAG cua cung lan cham, diem sau khi code dieu chinh la evidence_score_after.

Do: Evidence true vs fake (truoc / sau dieu chinh), chenh theo cap + Wilcoxon signed-rank (exact); so cap fake co
CONTRADICTED, so ban true bi tru; tac dong phu len 4 tieu chi con lai (neu chay ca 2 dieu kien); do tre (tong, cham,
embed, tach claim, retrieve + verify; kiem chung chay song song voi cham); token.

Checkpoint sau moi lan cham: `--resume` chay tiep, `--fresh` cham lai tu dau. Chay `--limit 2` truoc de uoc tinh token.

Cach dung:
    python scripts/rag/eval_evidence_pairs.py --conditions rag_on --limit 2 --budget 300000
    python scripts/rag/eval_evidence_pairs.py --conditions rag_on
    python scripts/rag/eval_evidence_pairs.py --conditions rag_on --resume
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
ALL_CONDITIONS = ("rag_off", "rag_on")
OTHER_CRITERIA = ("Logic", "Relevance", "Structure", "Persuasiveness")
TOTAL_PAIRS = 15


class TrackingClient(LLMClient):
    """Client cham diem: cong token va thoi gian cua moi lan goi (ke ca lan retry vi JSON loi)."""

    def __init__(self, inner: LLMClient):
        self.inner = inner
        self.prompt_tokens = self.completion_tokens = self.calls = 0
        self.seconds = 0.0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        self.inner.last_usage = None
        started = time.perf_counter()
        try:
            return self.inner.generate(system_prompt, user_prompt)
        finally:
            self.seconds += time.perf_counter() - started
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
    # Do tre tung buoc ma van chay dung pipeline.check_evidence cua luong that (trong thread kiem chung)
    pipeline.extract_claims = _timed(original_extract, timings, "extract")
    pipeline.verify_claims = _timed(original_verify, timings, "retrieve_verify")

    def checker(argument_text, motion, topic, check_settings):
        started = time.perf_counter()
        try:
            return pipeline.check_evidence(argument_text, motion, topic, check_settings, embedder=timed_embedder, stats=rag_stats)
        finally:
            timings["rag_total"] = time.perf_counter() - started

    client = TrackingClient(get_llm_client(settings))
    started = time.perf_counter()
    try:
        result = evaluate_argument_with_evidence(request, settings, client, checker)
    finally:
        pipeline.extract_claims, pipeline.verify_claims = original_extract, original_verify
    total = time.perf_counter() - started

    embed = timed_embedder.seconds
    check = result.evidence_check
    return {
        "pair_id": pair["pair_id"], "topic": pair["topic"], "version": version, "condition": condition,
        "scores": {c.name: c.score for c in result.criteria},
        "overall_score": result.overall_score,
        "evidence_reasoning": next(c.reasoning for c in result.criteria if c.name == "Evidence"),
        "suggestions": result.suggestions,
        "evidence_check": check.model_dump() if check else None,
        "seconds": {"total": round(total, 2), "grade": round(client.seconds, 2), "rag_total": round(timings.get("rag_total", 0.0), 2),
                    "embed": round(embed, 2), "extract": round(timings.get("extract", 0.0), 2),
                    "retrieve_verify_excl_embed": round(timings.get("retrieve_verify", 0.0) - embed, 2)},
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


def _mean(values):
    values = list(values)
    return round(statistics.fmean(values), 3) if values else None


def _tokens(record: dict) -> int:
    t = record["tokens"]
    return t["grade_prompt"] + t["grade_completion"] + t["rag"]


def _labels(record: dict) -> list[str]:
    return [claim["label"] for claim in (record.get("evidence_check") or {}).get("claims", [])]


def compare(true_scores: dict[str, float], fake_scores: dict[str, float]) -> dict:
    """Evidence true vs fake theo cap + Wilcoxon signed-rank exact (bo cap chenh 0, zero_method='wilcox')."""
    from scipy.stats import wilcoxon

    pairs = sorted(set(true_scores) & set(fake_scores))
    diffs = {p: true_scores[p] - fake_scores[p] for p in pairs}
    test = None
    if any(diffs.values()):
        t, f = [true_scores[p] for p in pairs], [fake_scores[p] for p in pairs]
        exact = wilcoxon(t, f, zero_method="wilcox", method="exact")
        approx = wilcoxon(t, f, zero_method="wilcox", method="approx")
        test = {"statistic": float(exact.statistic), "p_exact": float(exact.pvalue), "p_approx": float(approx.pvalue),
                "nonzero_pairs": sum(d != 0 for d in diffs.values())}
    return {"pairs": len(pairs), "mean_true": _mean(true_scores[p] for p in pairs),
            "mean_fake": _mean(fake_scores[p] for p in pairs), "mean_diff": _mean(diffs.values()),
            "per_pair_diff": diffs, "wilcoxon": test}


def build_report(records: dict[str, dict], pair_ids: list[str], conditions: tuple[str, ...]) -> dict:
    def get(pair_id, version, condition):
        return records.get(f"{pair_id}:{version}:{condition}")

    def by_pair(version, condition, value):
        return {p: value(get(p, version, condition)) for p in pair_ids if get(p, version, condition)}

    report: dict = {"pairs": len(pair_ids), "gradings": len(records), "conditions": {}}
    for condition in conditions:
        rows = [r for r in records.values() if r["condition"] == condition]
        section = {
            "evidence": compare(by_pair("true", condition, lambda r: r["scores"]["Evidence"]),
                                by_pair("fake", condition, lambda r: r["scores"]["Evidence"])),
            "overall": compare(by_pair("true", condition, lambda r: r["overall_score"]),
                               by_pair("fake", condition, lambda r: r["overall_score"])),
            "seconds_mean": {key: _mean(r["seconds"][key] for r in rows)
                             for key in ("total", "grade", "rag_total", "embed", "extract", "retrieve_verify_excl_embed")},
            "tokens_total": sum(_tokens(r) for r in rows),
            "tokens_mean": _mean(_tokens(r) for r in rows),
        }
        if condition == "rag_on":
            # Phuong an D: diem goc cua cung lan cham, truoc khi code dieu chinh
            section["evidence_before_adjust"] = compare(
                by_pair("true", condition, lambda r: r["evidence_check"]["evidence_score_before"]),
                by_pair("fake", condition, lambda r: r["evidence_check"]["evidence_score_before"]),
            )
            fake_on = {r["pair_id"]: r for r in rows if r["version"] == "fake"}
            true_on = {r["pair_id"]: r for r in rows if r["version"] == "true"}
            section["fake_with_contradicted"] = sorted(p for p, r in fake_on.items() if "CONTRADICTED" in _labels(r))
            section["fake_not_detected"] = sorted(p for p, r in fake_on.items() if "CONTRADICTED" not in _labels(r))
            section["true_with_contradicted"] = sorted(p for p, r in true_on.items() if "CONTRADICTED" in _labels(r))
            section["true_penalized"] = sorted(
                p for p, r in true_on.items()
                if r["evidence_check"]["evidence_score_after"] < r["evidence_check"]["evidence_score_before"]
            )
            section["status"] = {s: sum(r["evidence_check"]["status"] == s for r in rows)
                                 for s in ("checked", "no_claims", "unavailable")}
        report["conditions"][condition] = section

    if set(conditions) == set(ALL_CONDITIONS):
        side = {name: [] for name in OTHER_CRITERIA}
        for pair_id in pair_ids:
            for version in VERSIONS:
                on, off = get(pair_id, version, "rag_on"), get(pair_id, version, "rag_off")
                if on and off:
                    for name in OTHER_CRITERIA:
                        side[name].append(on["scores"][name] - off["scores"][name])
        report["side_effect_on_minus_off"] = {name: _mean(v) for name, v in side.items()}
    return report


def print_report(report: dict) -> None:
    def row(label, c):
        w = c["wilcoxon"]
        p = f"{w['p_exact']:.6f} (approx {w['p_approx']:.4f})" if w else "-"
        return f"| {label} | {c['mean_true']} | {c['mean_fake']} | {c['mean_diff']} | {p} |"

    print("\n| Do do | true | fake | chenh TB | Wilcoxon p |")
    print("|---|---|---|---|---|")
    for condition, c in report["conditions"].items():
        if "evidence_before_adjust" in c:
            print(row(f"{condition} Evidence goc (truoc dieu chinh)", c["evidence_before_adjust"]))
        print(row(f"{condition} Evidence", c["evidence"]))
        print(row(f"{condition} overall", c["overall"]))
    for condition, c in report["conditions"].items():
        print(f"\n{condition} chenh Evidence theo cap: {c['evidence']['per_pair_diff']}")
        print(f"{condition} thoi gian TB: {c['seconds_mean']} | token tong {c['tokens_total']}, TB/lan {c['tokens_mean']}")
        for key in ("fake_with_contradicted", "fake_not_detected", "true_with_contradicted", "true_penalized", "status"):
            if key in c:
                print(f"{condition} {key}: {c[key]}")
    if "side_effect_on_minus_off" in report:
        print(f"side_effect_on_minus_off: {report['side_effect_on_minus_off']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="So cap dau tien (uoc tinh token)")
    parser.add_argument("--conditions", nargs="+", choices=ALL_CONDITIONS, default=list(ALL_CONDITIONS))
    parser.add_argument("--budget", type=int, default=400_000, help="Nguong token khi uoc tinh tu --limit")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fresh", action="store_true", help="Xoa checkpoint cu va cham lai tu dau (ton token)")
    args = parser.parse_args()
    conditions = tuple(c for c in ALL_CONDITIONS if c in args.conditions)

    pairs = [json.loads(line) for line in PAIRS_PATH.open(encoding="utf-8") if line.strip()]
    pairs = pairs[: args.limit] if args.limit else pairs
    pair_ids = [p["pair_id"] for p in pairs]
    tag = f"{'_'.join(conditions)}{f'_limit{args.limit}' if args.limit else ''}"
    checkpoint = RESULTS_DIR / f"evidence_pairs_{tag}_checkpoint.jsonl"
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
    planned = len(pairs) * len(VERSIONS) * len(conditions)

    for pair in pairs:
        for version in VERSIONS:
            for condition in conditions:
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
                print(f"{len(done)}/{planned} lan cham, {sum(_tokens(r) for r in done.values())} token", flush=True)

    report = build_report(done, pair_ids, conditions)
    total_tokens = sum(_tokens(r) for r in done.values())
    report.update({"tokens_total": total_tokens, "conditions_run": list(conditions),
                   "model": base_settings.groq_model if base_settings.llm_provider == "groq" else base_settings.llm_provider,
                   "evidence_bonus": base_settings.rag_evidence_bonus})
    print_report(report)
    print(f"\nTong token: {total_tokens}")
    if args.limit:
        estimate = total_tokens / len(pairs) * TOTAL_PAIRS
        report["estimate_full_tokens"] = round(estimate)
        print(f"Uoc tinh ca bo {TOTAL_PAIRS} cap: {estimate:,.0f} token (nguong {args.budget:,})")
        if estimate > args.budget:
            print("VUOT NGUONG: dung lai, bao nguoi dung truoc khi chay day du.")

    expected = [f"{p}:{v}:{c}" for p in pair_ids for v in VERSIONS for c in conditions]
    report["missing_or_error"] = [key for key in expected if key not in done]
    report["records"] = list(done.values())
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / f"evidence_pairs_{tag}_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Da ghi {output_path}")
    if report["missing_or_error"]:
        print(f"Con {len(report['missing_or_error'])} lan cham chua xong/loi: chay lai voi --resume")
    else:
        checkpoint.unlink(missing_ok=True)
        if not args.limit:
            DOCS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output_path, DOCS_RESULTS_DIR / output_path.name)
            print(f"Da chep sang {DOCS_RESULTS_DIR / output_path.name}")


if __name__ == "__main__":
    main()
