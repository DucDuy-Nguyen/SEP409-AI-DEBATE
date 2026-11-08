"""
Tao bo du lieu danh gia verify, ghi data/eval/verify_set.jsonl (docs/RAG_STEP2_SPEC.md muc 2.1).

- in_kb: claim split test cua 3 chu de trong kho, lay mau phan tang --per-label claim moi nhan.
  Supported -> SUPPORTED, Refuted -> CONTRADICTED, NEI -> NOT_FOUND.
- out_of_kb: claim Supported/Refuted split test cua cac bai KHONG nap vao kho (topic khac 3 chu de). Gan topic truy van
  ngau nhien trong 3 chu de; nhan ky vong NOT_FOUND vi kho khong co bai do.

Thu tu dong duoc xao (seed co dinh) de 1 lo verify khong toan claim cung nhan.

Cach dung:
    python scripts/rag/build_verify_set.py
    python scripts/rag/build_verify_set.py --per-label 50 --out-of-kb 50
"""
import argparse
import hashlib
import json
import random
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from datasets import load_dataset

sys.stdout.reconfigure(encoding="utf-8")

SERVICE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = SERVICE_DIR / "data"
KB_PATH = DATA_DIR / "vifactcheck_3topics.jsonl"
OUTPUT_PATH = DATA_DIR / "eval" / "verify_set.jsonl"

SEED = 42
TOPICS = ("education", "environment", "technology")
EXPECTED_BY_LABEL = {"Supported": "SUPPORTED", "Refuted": "CONTRADICTED", "NEI": "NOT_FOUND"}
# labels cua dataset goc, xem scripts/rag/filter_vifactcheck.py
DATASET_LABELS = {0: "Supported", 1: "Refuted", 2: "NEI"}


def _article_id(url: str) -> str:
    # Giong filter_vifactcheck.article_id_from_url
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def build_in_kb(per_label: int, rng: random.Random) -> list[dict]:
    by_label: dict[str, list[dict]] = {label: [] for label in EXPECTED_BY_LABEL}
    with KB_PATH.open(encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            if record["split"] == "test":
                by_label[record["label"]].append(record)

    rows = []
    for label, pool in by_label.items():
        pool.sort(key=lambda record: record["claim_id"])
        if len(pool) < per_label:
            raise SystemExit(f"Nhan {label} chi co {len(pool)} claim, khong du {per_label}")
        for record in rng.sample(pool, per_label):
            rows.append(
                {
                    "set": "in_kb",
                    "claim_id": record["claim_id"],
                    "topic": record["topic"],
                    "claim": unicodedata.normalize("NFC", record["claim"]),
                    "dataset_label": label,
                    "expected": EXPECTED_BY_LABEL[label],
                    "article_id": record["article_id"],
                    "gold_evidence": unicodedata.normalize("NFC", record["gold_evidence"] or ""),
                    "source_topic": record["source_topic"],
                }
            )
    return rows


def build_out_of_kb(count: int, rng: random.Random) -> list[dict]:
    kb_urls = set()
    with KB_PATH.open(encoding="utf-8") as lines:
        for line in lines:
            kb_urls.add(json.loads(line)["url"])

    test_split = load_dataset("tranthaihoa/vifactcheck", cache_dir=str(DATA_DIR))["test"]
    pool = [
        row for row in test_split
        if row["Url"] not in kb_urls and DATASET_LABELS[row["labels"]] in ("Supported", "Refuted")
    ]
    pool.sort(key=lambda row: row["index"])
    if len(pool) < count:
        raise SystemExit(f"Chi co {len(pool)} claim ngoai kho, khong du {count}")

    rows = []
    for row in rng.sample(pool, count):
        rows.append(
            {
                "set": "out_of_kb",
                "claim_id": row["index"],
                "topic": rng.choice(TOPICS),
                "claim": unicodedata.normalize("NFC", row["Statement"]),
                "dataset_label": DATASET_LABELS[row["labels"]],
                "expected": "NOT_FOUND",
                "article_id": _article_id(row["Url"]),
                "gold_evidence": unicodedata.normalize("NFC", row["Evidence"] or ""),
                "source_topic": row["Topic"],
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-label", type=int, default=50)
    parser.add_argument("--out-of-kb", type=int, default=50)
    args = parser.parse_args()

    rng = random.Random(SEED)
    in_kb = build_in_kb(args.per_label, rng)
    out_of_kb = build_out_of_kb(args.out_of_kb, rng)
    rng.shuffle(in_kb)
    rng.shuffle(out_of_kb)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as output:
        for row in in_kb + out_of_kb:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"in_kb: {len(in_kb)} claim, nhan {dict(Counter(r['expected'] for r in in_kb))}, "
          f"topic {dict(Counter(r['topic'] for r in in_kb))}")
    print(f"out_of_kb: {len(out_of_kb)} claim, nhan goc {dict(Counter(r['dataset_label'] for r in out_of_kb))}, "
          f"topic truy van {dict(Counter(r['topic'] for r in out_of_kb))}, "
          f"topic goc {dict(Counter(r['source_topic'] for r in out_of_kb).most_common(8))}")
    print(f"Da ghi {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
