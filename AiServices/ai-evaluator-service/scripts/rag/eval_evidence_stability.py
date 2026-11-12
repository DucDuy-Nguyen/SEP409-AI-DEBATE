"""
Do do on dinh cua phan kiem chung (dev log muc 3.21.2). GOI LLM THAT (ton token), nhung CHI lap phan kiem chung:
diem goc (Evidence truoc dieu chinh) lay lai tu lan chay phuong an D (`--base`), khong cham lai.

Moi lan lap: chay pipeline.check_evidence (tach claim + verify, luong hien tai co CONFLICTING) cho 30 lap luan
(15 cap x true/fake), roi ap `adjust_evidence` offline. Bao tung lan va trung binh +/- SD: Evidence TB that/bia,
Wilcoxon exact, so ban that bi tru, so ban bia bi phat hien (co it nhat 1 CONTRADICTED), so claim CONFLICTING; liet ke
moi ban that bi tru o bat ky lan nao kem claim va fact.

Checkpoint sau moi lap luan: `--resume` chay tiep, `--fresh` chay lai tu dau.

Cach dung:
    python scripts/rag/eval_evidence_stability.py --estimate        # 1 lap luan, in uoc tinh token cho ca dot
    python scripts/rag/eval_evidence_stability.py --runs 3
    python scripts/rag/eval_evidence_stability.py --runs 3 --resume
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
from app.rag.llm_usage import LLMCallStats
from app.services.evidence_evaluator import adjust_evidence, summarize

sys.stdout.reconfigure(encoding="utf-8")

PAIRS_PATH = SERVICE_DIR / "docs" / "rag_eval" / "evidence_pairs.jsonl"
DEFAULT_BASE = SERVICE_DIR / "docs" / "rag_results" / "evidence_pairs_rag_on_20261108_165841.json"
RESULTS_DIR = SERVICE_DIR / "data" / "results"
DOCS_RESULTS_DIR = SERVICE_DIR / "docs" / "rag_results"
CHECKPOINT = RESULTS_DIR / "evidence_stability_checkpoint.jsonl"
VERSIONS = ("true", "fake")


def load_base(path: Path) -> dict[str, int]:
    """Evidence truoc dieu chinh cua tung lap luan, tu lan chay phuong an D."""
    report = json.loads(path.read_text(encoding="utf-8"))
    return {
        f"{r['pair_id']}:{r['version']}": r["evidence_check"]["evidence_score_before"]
        for r in report["records"] if r["condition"] == "rag_on"
    }


def check_once(pair: dict, version: str, settings, embedder) -> dict:
    from app.rag.pipeline import check_evidence

    stats = LLMCallStats()
    started = time.perf_counter()
    result = check_evidence(pair[f"argument_{version}"], pair["motion"], pair["topic"], settings, embedder=embedder, stats=stats)
    summary = summarize(result)
    return {"seconds": round(time.perf_counter() - started, 2), "tokens": stats.total_tokens, "stats": asdict(stats),
            "claims": [claim.model_dump() for claim in summary.claims]}


def load_checkpoint() -> dict[str, dict]:
    done = {}
    if CHECKPOINT.exists():
        for number, line in enumerate(CHECKPOINT.open(encoding="utf-8"), start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(f"Canh bao: bo qua dong {number} hong trong checkpoint", flush=True)
                continue
            if "error" not in record:
                done[record["key"]] = record
    return done


def _sd(values: list[float]) -> float:
    return round(statistics.stdev(values), 3) if len(values) > 1 else 0.0


def run_metrics(run: int, records: dict[str, dict], base: dict[str, int], pair_ids: list[str]) -> dict:
    from scipy.stats import wilcoxon

    after, penalized, detected, conflicting = {}, [], [], 0
    for pair_id in pair_ids:
        for version in VERSIONS:
            record = records[f"{run}:{pair_id}:{version}"]
            labels = [claim["label"] for claim in record["claims"]]
            score, rule = adjust_evidence(base[f"{pair_id}:{version}"], labels)
            after[f"{pair_id}:{version}"] = score
            conflicting += labels.count("CONFLICTING")
            if version == "true" and score < base[f"{pair_id}:{version}"]:
                penalized.append({"run": run, "pair_id": pair_id, "before": base[f"{pair_id}:{version}"], "after": score,
                                  "rule": rule, "claims": [c for c in record["claims"] if c["label"] == "CONTRADICTED"]})
            if version == "fake" and "CONTRADICTED" in labels:
                detected.append(pair_id)
    true_scores = [after[f"{p}:true"] for p in pair_ids]
    fake_scores = [after[f"{p}:fake"] for p in pair_ids]
    test = None
    if any(t != f for t, f in zip(true_scores, fake_scores)):
        exact = wilcoxon(true_scores, fake_scores, zero_method="wilcox", method="exact")
        test = {"statistic": float(exact.statistic), "p_exact": float(exact.pvalue),
                "nonzero_pairs": sum(t != f for t, f in zip(true_scores, fake_scores))}
    rows = [records[f"{run}:{p}:{v}"] for p in pair_ids for v in VERSIONS]
    return {
        "run": run,
        "evidence_mean_true": round(statistics.fmean(true_scores), 3),
        "evidence_mean_fake": round(statistics.fmean(fake_scores), 3),
        "mean_diff": round(statistics.fmean(t - f for t, f in zip(true_scores, fake_scores)), 3),
        "wilcoxon": test,
        "true_penalized": len(penalized),
        "fake_detected": len(detected),
        "fake_not_detected": sorted(set(pair_ids) - set(detected)),
        "conflicting_claims": conflicting,
        "tokens": sum(r["tokens"] for r in rows),
        "seconds_mean": round(statistics.fmean(r["seconds"] for r in rows), 2),
        "penalized_detail": penalized,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--estimate", action="store_true", help="Chi chay 1 lap luan, in uoc tinh token")
    parser.add_argument("--budget", type=int, default=500_000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    pairs = [json.loads(line) for line in PAIRS_PATH.open(encoding="utf-8") if line.strip()]
    pair_ids = [p["pair_id"] for p in pairs]
    base = load_base(args.base)
    missing_base = [f"{p}:{v}" for p in pair_ids for v in VERSIONS if f"{p}:{v}" not in base]
    if missing_base:
        raise SystemExit(f"Thieu diem goc trong {args.base}: {missing_base}")

    from app.rag.embedder import get_default_embedder

    embedder = get_default_embedder()
    embedder.encode(["khoi dong model"])
    settings = get_settings().model_copy(update={"rag_enabled": True})

    if args.estimate:
        record = check_once(pairs[0], "true", settings, embedder)
        estimate = record["tokens"] * len(pairs) * len(VERSIONS) * args.runs
        print(f"1 lap luan ({pairs[0]['pair_id']}:true): {record['tokens']} token, {record['seconds']} s, "
              f"{len(record['claims'])} claim {[c['label'] for c in record['claims']]}")
        print(f"Uoc tinh {args.runs} lan x {len(pairs) * len(VERSIONS)} lap luan: {estimate:,} token (nguong {args.budget:,})")
        if estimate > args.budget:
            print("VUOT NGUONG: dung lai, bao nguoi dung.")
        return

    if CHECKPOINT.exists() and not (args.resume or args.fresh):
        raise SystemExit(f"Da co checkpoint {CHECKPOINT}: chay voi --resume de chay tiep, hoac --fresh de chay lai")
    if args.fresh:
        CHECKPOINT.unlink(missing_ok=True)
    done = load_checkpoint()
    planned = args.runs * len(pairs) * len(VERSIONS)
    for run in range(1, args.runs + 1):
        for pair in pairs:
            for version in VERSIONS:
                key = f"{run}:{pair['pair_id']}:{version}"
                if key in done:
                    continue
                try:
                    record = {"key": key, **check_once(pair, version, settings, embedder)}
                    done[key] = record
                except Exception as exc:  # 1 lap luan loi khong lam mat cac lap luan khac
                    print(f"{key} loi: {type(exc).__name__}: {exc}", flush=True)
                    traceback.print_exc()
                    record = {"key": key, "error": f"{type(exc).__name__}: {exc}"}
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                with CHECKPOINT.open("a", encoding="utf-8") as output:
                    output.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"{len(done)}/{planned} lap luan, {sum(r['tokens'] for r in done.values())} token", flush=True)

    missing = [f"{r}:{p}:{v}" for r in range(1, args.runs + 1) for p in pair_ids for v in VERSIONS if f"{r}:{p}:{v}" not in done]
    if missing:
        print(f"Con {len(missing)} lap luan loi/chua xong: chay lai voi --resume")
        return

    runs = [run_metrics(run, done, base, pair_ids) for run in range(1, args.runs + 1)]
    keys = ("evidence_mean_true", "evidence_mean_fake", "mean_diff", "true_penalized", "fake_detected", "conflicting_claims")
    summary = {key: {"mean": round(statistics.fmean(r[key] for r in runs), 3), "sd": _sd([r[key] for r in runs])} for key in keys}
    p_values = [r["wilcoxon"]["p_exact"] for r in runs if r["wilcoxon"]]
    summary["p_exact"] = {"mean": round(statistics.fmean(p_values), 6) if p_values else None, "max": max(p_values) if p_values else None}

    print("\n| Lan | Evidence that | Evidence bia | Chenh TB | Wilcoxon exact p | That bi tru | Bia bi phat hien | Claim CONFLICTING | Token |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in runs:
        p = f"{r['wilcoxon']['p_exact']:.6f}" if r["wilcoxon"] else "-"
        print(f"| {r['run']} | {r['evidence_mean_true']} | {r['evidence_mean_fake']} | {r['mean_diff']} | {p} | "
              f"{r['true_penalized']} | {r['fake_detected']}/15 | {r['conflicting_claims']} | {r['tokens']} |")
    print(f"| TB +/- SD | " + " | ".join(
        f"{summary[k]['mean']} +/- {summary[k]['sd']}" for k in ("evidence_mean_true", "evidence_mean_fake", "mean_diff")
    ) + f" | max {summary['p_exact']['max']} | " + " | ".join(
        f"{summary[k]['mean']} +/- {summary[k]['sd']}" for k in ("true_penalized", "fake_detected", "conflicting_claims")
    ) + f" | {sum(r['tokens'] for r in runs)} |")
    for r in runs:
        print(f"lan {r['run']}: bia khong bi phat hien {r['fake_not_detected']}")
        for item in r["penalized_detail"]:
            print(f"  THAT BI TRU {item['pair_id']} {item['before']} -> {item['after']}")
            for claim in item["claims"]:
                print(f"    claim: {claim['claim']}\n    ly do: {claim['reason']}")
                for citation in claim["citations"]:
                    print(f"    fact [{citation.get('stance')}] {citation['fact_id'][:8]}: {citation['content'][:220]}")

    output = {"runs": runs, "summary": summary, "base_file": str(args.base.name), "records": list(done.values()),
              "tokens_total": sum(r["tokens"] for r in runs)}
    output_path = RESULTS_DIR / f"evidence_stability_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    DOCS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, DOCS_RESULTS_DIR / output_path.name)
    CHECKPOINT.unlink(missing_ok=True)
    print(f"\nDa ghi {output_path} va chep sang {DOCS_RESULTS_DIR / output_path.name}")


if __name__ == "__main__":
    main()
