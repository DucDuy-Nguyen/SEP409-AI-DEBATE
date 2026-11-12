"""
Do retrieval tren claim split test (chi Supported + Refuted), KHONG goi LLM.

- article_hit@k: trong top k co fact card thuoc dung bai bao cua claim.
- evidence_hit@k: trong top k co fact card chua gold evidence (khop sau khi chuan hoa khoang trang,
  hoac fact chua >= 80% token cua gold).
- evidence_reachable: claim co it nhat 1 fact card cua CHINH bai bao chua duoc gold. Day la tran cua
  evidence_hit theo cach chunk hien tai (gold trai qua nhieu doan thi khong doan nao chua du).
- empty_results: so claim mode do khong tra ve gi.

Moi mode chi retrieve voi k lon nhat roi cat prefix: top k nho hon chinh la phan dau cua danh sach.

Cach dung:
    python scripts/rag/eval_retrieval.py
"""
import json
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.rag.chunker import chunk_text
from app.rag.embedder import Embedder
from app.rag.retriever import retrieve
from app.rag.store import FactStore

sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
INPUT_PATH = DATA_DIR / "vifactcheck_3topics.jsonl"
RESULTS_DIR = DATA_DIR / "results"

MODES = ("vector", "keyword", "hybrid")
K_VALUES = (1, 3, 5, 10)
EVIDENCE_TOKEN_THRESHOLD = 0.8
EVAL_LABELS = {"Supported", "Refuted"}

_TOKEN = re.compile(r"\w+")


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def contains_evidence(fact_content: str, gold_evidence: str) -> bool:
    fact, gold = _normalize(fact_content), _normalize(gold_evidence)
    if not gold:
        return False
    if gold in fact:
        return True
    gold_tokens = _TOKEN.findall(gold)
    if not gold_tokens:
        return False
    fact_tokens = set(_TOKEN.findall(fact))
    return sum(token in fact_tokens for token in gold_tokens) / len(gold_tokens) >= EVIDENCE_TOKEN_THRESHOLD


class _PrecomputedEmbedder:
    """Tra embedding da encode san cua claim, de retrieve khong encode lai o moi mode."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def encode(self, texts):
        return [self._vectors[text] for text in texts]


def _empty_bucket() -> dict:
    return {
        "claims": 0,
        "evidence_reachable": 0,
        "modes": {
            mode: {
                "empty_results": 0,
                "article_hit": {k: 0 for k in K_VALUES},
                "evidence_hit": {k: 0 for k in K_VALUES},
            }
            for mode in MODES
        },
    }


def _print_tables(buckets: dict[str, dict]) -> None:
    header = " | ".join(f"@{k}" for k in K_VALUES)
    for name in ("education", "environment", "technology", "TONG"):
        bucket = buckets[name]
        claims = bucket["claims"]
        if not claims:
            continue
        print(f"\n### {name}: {claims} claim, evidence_reachable {bucket['evidence_reachable'] / claims:.3f}")
        print(f"mode | do do | {header} | claim khong co ket qua")
        for mode in MODES:
            stats = bucket["modes"][mode]
            for metric in ("article_hit", "evidence_hit"):
                cells = " | ".join(f"{stats[metric][k] / claims:.3f}" for k in K_VALUES)
                print(f"{mode} | {metric} | {cells} | {stats['empty_results']}")


def main() -> None:
    claims = []
    with INPUT_PATH.open(encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            if record["split"] == "test" and record["label"] in EVAL_LABELS:
                record["claim"] = unicodedata.normalize("NFC", record["claim"])
                claims.append(record)
    print(f"{len(claims)} claim split test (Supported + Refuted)")

    started = time.perf_counter()
    embedder = Embedder()
    texts = list({claim["claim"] for claim in claims})
    precomputed = _PrecomputedEmbedder(dict(zip(texts, embedder.encode(texts))))
    print(f"Embed claim: {time.perf_counter() - started:.1f}s")

    buckets: dict[str, dict] = defaultdict(_empty_bucket)
    max_k = max(K_VALUES)
    with FactStore() as store:
        for claim in claims:
            expected_ref = f"vifactcheck:{claim['article_id']}"
            reachable = any(
                contains_evidence(chunk, claim["gold_evidence"])
                for chunk in chunk_text(unicodedata.normalize("NFC", claim["context"]))
            )
            targets = (buckets[claim["topic"]], buckets["TONG"])
            for bucket in targets:
                bucket["claims"] += 1
                bucket["evidence_reachable"] += reachable

            for mode in MODES:
                facts = retrieve(claim["claim"], claim["topic"], max_k, mode, store, precomputed)
                refs = store.dataset_refs_for_facts([fact.fact_id for fact in facts]) if facts else {}
                article_flags = [refs.get(fact.fact_id) == expected_ref for fact in facts]
                evidence_flags = [contains_evidence(fact.content, claim["gold_evidence"]) for fact in facts]
                for bucket in targets:
                    stats = bucket["modes"][mode]
                    stats["empty_results"] += not facts
                    for k in K_VALUES:
                        stats["article_hit"][k] += any(article_flags[:k])
                        stats["evidence_hit"][k] += any(evidence_flags[:k])

    _print_tables(buckets)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / f"retrieval_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps(buckets, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDa ghi {output_path}")


if __name__ == "__main__":
    main()
