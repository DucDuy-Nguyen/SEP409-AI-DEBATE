"""
Nap data/vifactcheck_3topics.jsonl vao kho fact: moi bai bao 1 knowledge_source + cac fact_card da embed.

Chay lai khong bi trung: moi bai xoa source cu cung dataset_ref roi insert lai, commit theo tung bai.
Bai khong con trong file (doi nguong filter) cung bi xoa. --skip-existing de chay tiep khi bi ngat giua chung.

Cach dung:
    python scripts/rag/ingest_vifactcheck.py
    python scripts/rag/ingest_vifactcheck.py --skip-existing
"""
import argparse
import json
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.rag.chunker import chunk_text
from app.rag.embedder import Embedder
from app.rag.schemas import FactCard
from app.rag.store import FactStore

sys.stdout.reconfigure(encoding="utf-8")

INPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "vifactcheck_3topics.jsonl"
DATASET_REF_PREFIX = "vifactcheck:"


def load_articles() -> dict[str, dict]:
    articles: dict[str, dict] = {}
    with INPUT_PATH.open(encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            articles.setdefault(record["article_id"], record)
    return articles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-existing", action="store_true", help="Bo qua bai da co trong DB thay vi nap lai")
    args = parser.parse_args()

    articles = load_articles()
    wanted_refs = {f"{DATASET_REF_PREFIX}{article_id}" for article_id in articles}
    embedder = Embedder()
    embed_seconds = 0.0
    inserted_sources = 0
    skipped_sources = 0
    facts_by_topic: Counter = Counter()

    with FactStore() as store:
        stale = store.dataset_refs_with_prefix(DATASET_REF_PREFIX) - wanted_refs
        for dataset_ref in stale:
            store.delete_source_by_dataset_ref(dataset_ref)
        store.commit()
        existing = store.dataset_refs_with_prefix(DATASET_REF_PREFIX) if args.skip_existing else set()

        for position, (article_id, article) in enumerate(articles.items(), start=1):
            dataset_ref = f"{DATASET_REF_PREFIX}{article_id}"
            if dataset_ref in existing:
                skipped_sources += 1
                continue

            # Dataset co ca van ban khong o dang NFC; Postgres so token theo byte nen phai chuan hoa
            chunks = chunk_text(unicodedata.normalize("NFC", article["context"]))
            started = time.perf_counter()
            embeddings = embedder.encode(chunks)
            embed_seconds += time.perf_counter() - started

            citation = f"{article['author']} - {article['url']}"
            store.delete_source_by_dataset_ref(dataset_ref)
            source_id = store.insert_source(
                topic=article["topic"], source_type="dataset", url=article["url"], dataset_ref=dataset_ref
            )
            store.insert_facts(
                source_id,
                [
                    FactCard(content=chunk, topic=article["topic"], citation=citation, embedding=embedding)
                    for chunk, embedding in zip(chunks, embeddings)
                ],
            )
            store.commit()
            inserted_sources += 1
            facts_by_topic[article["topic"]] += len(chunks)
            if position % 20 == 0:
                print(f"{position}/{len(articles)} bai, embed {embed_seconds:.0f}s", flush=True)

        print(f"Lan chay nay: nap {inserted_sources} source, bo qua {skipped_sources}, xoa {len(stale)} source cu.")
        print(f"Fact card vua nap theo topic: {dict(facts_by_topic)}")
        print(f"Thoi gian embed: {embed_seconds:.1f}s")
        print(f"Tong trong DB: {store.count_facts_by_topic()}")


if __name__ == "__main__":
    main()
