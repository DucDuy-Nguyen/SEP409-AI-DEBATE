"""
Danh gia verify tren data/eval/verify_set.jsonl (docs/RAG_STEP2_SPEC.md muc 3.1). GOI LLM THAT (ton token).

- Mac dinh: fact = retrieve hybrid top settings.rag_top_k nhu luong that.
- --oracle: fact = gold evidence cua ViFactCheck (chi in_kb), de tach loi do retrieval hay do verify.
- Do: accuracy, macro F1, F1 tung nhan, confusion 3x3 (in_kb theo chu de va tong); out_of_kb: ty le NOT_FOUND;
  false_contradiction_rate (thuc te SUPPORTED/NOT_FOUND ma bi gan CONTRADICTED); coerced, retry, token.

Chay --limit 10 truoc de uoc tinh token. Ket qua: data/results/verify_<mode>_<timestamp>.json, ban chay day du
(khong --limit) duoc chep sang docs/rag_results/.

Cach dung:
    python scripts/rag/eval_verify.py --set all --limit 10
    python scripts/rag/eval_verify.py --set all
    python scripts/rag/eval_verify.py --set in_kb --oracle
"""
import argparse
import json
import shutil
import sys
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

SERVICE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVICE_DIR))

from app.config import get_settings
from app.rag.llm_usage import LLMCallStats
from app.rag.schemas import RetrievedFact
from app.rag.verifier import VERIFY_BATCH_SIZE, verify_with_facts

sys.stdout.reconfigure(encoding="utf-8")

INPUT_PATH = SERVICE_DIR / "data" / "eval" / "verify_set.jsonl"
RESULTS_DIR = SERVICE_DIR / "data" / "results"
DOCS_RESULTS_DIR = SERVICE_DIR / "docs" / "rag_results"

LABELS = ("SUPPORTED", "CONTRADICTED", "NOT_FOUND")
ERROR_LABEL = "ERROR"  # Lo verify loi sau khi da retry: khong tinh la du doan nao
# Nhan chi do code gan (muc 3.21.2): ViFactCheck khong co nhan tuong ung, nen KHONG gop vao 3 nhan khi so,
# dem rieng va loai khoi accuracy / F1 / false_contradiction
CONFLICTING_LABEL = "CONFLICTING"
EXTRA_COLUMNS = (CONFLICTING_LABEL, ERROR_LABEL)
# Ke hoach day du cua spec: in_kb retrieve + in_kb oracle + out_of_kb, dung de uoc tinh tong token
FULL_PLAN_CLAIMS = 150 + 150 + 50
TOKEN_BUDGET = 300_000


def load_rows(selected_set: str, limit: int | None) -> list[dict]:
    rows = []
    with INPUT_PATH.open(encoding="utf-8") as lines:
        for line in lines:
            row = json.loads(line)
            if selected_set in ("all", row["set"]):
                rows.append(row)
    return rows[:limit] if limit else rows


def oracle_facts(row: dict) -> list[RetrievedFact]:
    if not row["gold_evidence"].strip():
        return []
    return [RetrievedFact(fact_id=uuid5(NAMESPACE_URL, f"vifactcheck-gold:{row['claim_id']}"),
                          content=row["gold_evidence"], score=1.0)]


def retrieve_facts(rows: list[dict]) -> list[list[RetrievedFact]]:
    from app.rag.embedder import Embedder
    from app.rag.retriever import retrieve
    from app.rag.store import FactStore

    settings = get_settings()
    texts = list(dict.fromkeys(row["claim"] for row in rows))
    started = time.perf_counter()
    vectors = dict(zip(texts, Embedder().encode(texts)))
    print(f"Embed {len(texts)} claim: {time.perf_counter() - started:.0f}s", flush=True)

    class _Precomputed:
        def encode(self, batch):
            return [vectors[text] for text in batch]

    with FactStore() as store:
        return [retrieve(row["claim"], row["topic"], settings.rag_top_k, "hybrid", store, _Precomputed()) for row in rows]


def _row_key(row: dict) -> str:
    return f"{row['set']}:{row['claim_id']}"


def load_checkpoint(path: Path) -> tuple[dict[str, dict], LLMCallStats]:
    """Claim da co ket qua (bo qua ERROR de chay lai) va stats cong don toi lo cuoi, gom ca token cua lo loi."""
    done: dict[str, dict] = {}
    stats = LLMCallStats()
    if not path.exists():
        return done, stats
    with path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # Dong cuoi bi cut khi tien trinh bi ngat giua luc ghi: bo qua, cac claim cua no se duoc chay lai
                print(f"Canh bao: bo qua dong {number} hong trong checkpoint {path}", flush=True)
                continue
            stats = LLMCallStats(**record["stats"])
            for prediction in record["predictions"]:
                if prediction["predicted"] != ERROR_LABEL:
                    done[_row_key(prediction)] = prediction
    return done, stats


def append_checkpoint(path: Path, predictions: list[dict], stats: LLMCallStats) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"predictions": predictions, "stats": asdict(stats)}, ensure_ascii=False) + "\n")


def classification_metrics(pairs: list[tuple[str, str]]) -> dict:
    """
    pairs = (nhan dung, nhan du doan). Du doan ERROR tinh la sai. Du doan CONFLICTING hien o cot rieng cua confusion
    nhung bi loai khoi accuracy / F1 (khong so duoc voi nhan ViFactCheck); so luong o `conflicting`.
    """
    confusion = {gold: {pred: 0 for pred in LABELS + EXTRA_COLUMNS} for gold in LABELS}
    for gold, pred in pairs:
        confusion[gold][pred] += 1
    conflicting = {gold: confusion[gold][CONFLICTING_LABEL] for gold in LABELS}
    pairs = [(gold, pred) for gold, pred in pairs if pred != CONFLICTING_LABEL]
    per_label = {}
    for label in LABELS:
        tp = confusion[label][label]
        predicted = sum(confusion[gold][label] for gold in LABELS)
        actual = sum(confusion[label].values()) - confusion[label][CONFLICTING_LABEL]
        precision = tp / predicted if predicted else 0.0
        recall = tp / actual if actual else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[label] = {"precision": precision, "recall": recall, "f1": f1, "support": actual}
    present = [label for label in LABELS if per_label[label]["support"]]
    return {
        "n": len(pairs),
        "accuracy": sum(gold == pred for gold, pred in pairs) / len(pairs) if pairs else 0.0,
        "macro_f1": sum(per_label[label]["f1"] for label in present) / len(present) if present else 0.0,
        "per_label": per_label,
        "confusion": confusion,
        "conflicting": {"total": sum(conflicting.values()), "by_gold": conflicting},
    }


def false_contradiction(pairs: list[tuple[str, str]]) -> dict:
    eligible = [pred for gold, pred in pairs if gold in ("SUPPORTED", "NOT_FOUND") and pred != CONFLICTING_LABEL]
    wrong = sum(pred == "CONTRADICTED" for pred in eligible)
    return {"count": wrong, "eligible": len(eligible), "rate": wrong / len(eligible) if eligible else 0.0}


def _print_metrics(name: str, metrics: dict) -> None:
    f1 = " ".join(f"{label}={metrics['per_label'][label]['f1']:.3f}" for label in LABELS)
    print(f"\n### {name}: n={metrics['n']} (khong tinh CONFLICTING) accuracy={metrics['accuracy']:.3f} "
          f"macro_f1={metrics['macro_f1']:.3f} | F1 {f1} | CONFLICTING {metrics['conflicting']}")
    print("dung \\ du doan | " + " | ".join(LABELS + EXTRA_COLUMNS))
    for gold in LABELS:
        print(f"{gold} | " + " | ".join(str(metrics["confusion"][gold][pred]) for pred in LABELS + EXTRA_COLUMNS))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=("in_kb", "out_of_kb", "all"), default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--oracle", action="store_true", help="Fact = gold evidence (chi in_kb)")
    parser.add_argument("--resume", action="store_true",
                        help="Chay tiep tu checkpoint cua lan truoc (bo qua claim da xong, chay lai claim bi ERROR)")
    args = parser.parse_args()
    if args.oracle and args.set != "in_kb":
        parser.error("--oracle chi dung voi --set in_kb (out_of_kb khong co gold evidence trong kho)")

    mode = "oracle" if args.oracle else "retrieve"
    rows = load_rows(args.set, args.limit)
    print(f"mode={mode} set={args.set} {len(rows)} claim, provider={get_settings().llm_provider}, "
          f"reasoning_effort={get_settings().groq_reasoning_effort or 'default'}", flush=True)
    facts_per_row = [oracle_facts(row) for row in rows] if args.oracle else retrieve_facts(rows)

    checkpoint = RESULTS_DIR / f"verify_{mode}_{args.set}{f'_limit{args.limit}' if args.limit else ''}_checkpoint.jsonl"
    done, stats = load_checkpoint(checkpoint) if args.resume else ({}, LLMCallStats())
    if not args.resume:
        checkpoint.unlink(missing_ok=True)
    elif done:
        print(f"Chay tiep tu checkpoint: {len(done)} claim da xong, {stats.total_tokens} token da dung", flush=True)

    pending = [(row, facts) for row, facts in zip(rows, facts_per_row) if _row_key(row) not in done]
    started = time.perf_counter()
    for start in range(0, len(pending), VERIFY_BATCH_SIZE):
        batch = pending[start : start + VERIFY_BATCH_SIZE]
        batch_rows = [row for row, _ in batch]
        try:
            results = verify_with_facts([row["claim"] for row in batch_rows], [facts for _, facts in batch], stats=stats)
            batch_predictions = [
                {**row, "predicted": result.label.value, "fact_ids": result.fact_ids, "fact_stances": result.fact_stances,
                 "reason": result.reason, "coerced": result.coerced,
                 "downgraded": result.downgraded,
                 "unsupported_details": result.unsupported_details,
                 "details": [d.model_dump() for d in result.details],
                 "retrieved": [{"fact_id": str(f.fact_id), "content": f.content[:300]} for f in result.retrieved]}
                for row, result in zip(batch_rows, results)
            ]
        except Exception as exc:  # Ca loi mang: 1 lo loi khong lam mat ket qua cac lo khac, --resume se chay lai lo nay
            print(f"Lo {start // VERIFY_BATCH_SIZE + 1} loi: {type(exc).__name__}: {exc}", flush=True)
            # Traceback ra stderr de loi lap trinh (KeyError...) khong bi lan vao loi mang/LLM
            traceback.print_exc()
            batch_predictions = [{**row, "predicted": ERROR_LABEL, "reason": f"{type(exc).__name__}: {exc}"}
                                 for row in batch_rows]
        append_checkpoint(checkpoint, batch_predictions, stats)
        for prediction in batch_predictions:
            done[_row_key(prediction)] = prediction
        print(f"{len(done)}/{len(rows)} claim, {stats.total_tokens} token", flush=True)
    elapsed = time.perf_counter() - started
    # Giu thu tu cua verify_set de bao cao on dinh giua cac lan chay
    predictions = [done[_row_key(row)] for row in rows]

    settings = get_settings()
    report: dict = {"mode": mode, "set": args.set, "limit": args.limit, "n": len(rows), "seconds": round(elapsed, 1),
                    "model": settings.groq_model if settings.llm_provider == "groq" else settings.llm_provider,
                    "reasoning_effort": settings.groq_reasoning_effort or "default",
                    "tokens_per_claim": round(stats.total_tokens / len(rows), 1) if rows else 0.0}
    in_kb = [p for p in predictions if p["set"] == "in_kb"]
    out_kb = [p for p in predictions if p["set"] == "out_of_kb"]

    if in_kb:
        by_topic = defaultdict(list)
        for p in in_kb:
            by_topic[p["topic"]].append((p["expected"], p["predicted"]))
        report["in_kb"] = {"TONG": classification_metrics([(p["expected"], p["predicted"]) for p in in_kb])}
        for topic in sorted(by_topic):
            report["in_kb"][topic] = classification_metrics(by_topic[topic])
        for name, metrics in report["in_kb"].items():
            _print_metrics(f"in_kb {name}", metrics)

    if out_kb:
        # out_of_kb khong co bai goc trong kho: CONFLICTING dem rieng, khong tinh la sai
        wrong = [p for p in out_kb if p["predicted"] not in ("NOT_FOUND", CONFLICTING_LABEL)]
        report["out_of_kb"] = {
            "n": len(out_kb),
            "not_found_rate": sum(p["predicted"] == "NOT_FOUND" for p in out_kb) / len(out_kb),
            "predicted": dict(Counter(p["predicted"] for p in out_kb)),
            "wrong": [{key: p[key] for key in ("claim_id", "topic", "source_topic", "claim", "predicted", "reason", "fact_ids")}
                      for p in wrong],
        }
        print(f"\n### out_of_kb: n={len(out_kb)} ty le NOT_FOUND={report['out_of_kb']['not_found_rate']:.3f} "
              f"du doan {report['out_of_kb']['predicted']}")
        for p in wrong:
            print(f"  SAI {p['predicted']} | {p['claim'][:120]} | {p['reason'][:160]}")

    report["false_contradiction"] = {
        name: false_contradiction([(p["expected"], p["predicted"]) for p in subset])
        for name, subset in (("in_kb", in_kb), ("out_of_kb", out_kb), ("all", predictions)) if subset
    }
    report["llm"] = {"requests": stats.requests, "llm_calls": stats.llm_calls, "retries": stats.retries,
                     "coerced": stats.coerced, "downgraded": stats.downgraded, "prompt_tokens": stats.prompt_tokens,
                     "completion_tokens": stats.completion_tokens, "total_tokens": stats.total_tokens,
                     "calls_without_usage": stats.calls_without_usage,
                     "errors": sum(p["predicted"] == ERROR_LABEL for p in predictions)}
    print(f"\nfalse_contradiction_rate: { {k: round(v['rate'], 3) for k, v in report['false_contradiction'].items()} }")
    print(f"LLM: {report['llm']}")

    # Uoc tinh chi co nghia o lan chay thu --limit, truoc khi chay day du
    if args.limit and rows and stats.total_tokens:
        per_claim = stats.total_tokens / len(rows)
        report["estimate"] = {"tokens_per_claim": per_claim, "full_plan_claims": FULL_PLAN_CLAIMS,
                              "full_plan_tokens": round(per_claim * FULL_PLAN_CLAIMS)}
        print(f"Uoc tinh: {per_claim:.0f} token/claim -> ke hoach day du {FULL_PLAN_CLAIMS} claim ~ "
              f"{per_claim * FULL_PLAN_CLAIMS:,.0f} token (nguong {TOKEN_BUDGET:,})")
        if per_claim * FULL_PLAN_CLAIMS > TOKEN_BUDGET:
            print("VUOT NGUONG: dung lai, bao nguoi dung truoc khi chay day du.")
    if stats.calls_without_usage:
        print(f"Canh bao: {stats.calls_without_usage} lan goi khong co usage, so token o tren thieu.")

    report["predictions"] = predictions
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"_limit{args.limit}" if args.limit else ""
    output_path = RESULTS_DIR / f"verify_{mode}{suffix}_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDa ghi {output_path}")
    if not args.limit:
        DOCS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_path, DOCS_RESULTS_DIR / output_path.name)
        print(f"Da chep sang {DOCS_RESULTS_DIR / output_path.name}")
    # Xong tron ven thi bo checkpoint; con claim ERROR thi giu de --resume chay lai
    if not any(p["predicted"] == ERROR_LABEL for p in predictions):
        checkpoint.unlink(missing_ok=True)
    else:
        print(f"Con claim ERROR: chay lai voi --resume (checkpoint {checkpoint})")


if __name__ == "__main__":
    main()
