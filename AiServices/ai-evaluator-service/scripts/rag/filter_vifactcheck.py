"""
Loc ViFactCheck ra 3 chu de (education, environment, technology), ghi data/vifactcheck_3topics.jsonl.

Cot dataset da xem bang explore_vifactcheck.py: index, Statement, Context, Topic, Author, Url, labels, Evidence.
- Dataset khong co id bai bao. Url va Context khop 1-1 (1041 bai) nen article_id = hash cua Url.
- Dataset gold rieng khong ton tai; gold evidence nam o cot Evidence ngay trong dataset chinh.

Moi bai bao chi gan 1 topic: uu tien cot Topic goc, sau do moi den so lan trung keyword tren Context.

Cach dung:
    python scripts/rag/filter_vifactcheck.py
    python scripts/rag/filter_vifactcheck.py --min-keyword-hits 5 --dry-run
"""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from datasets import load_dataset

sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUTPUT_PATH = DATA_DIR / "vifactcheck_3topics.jsonl"

# labels theo thu tu cua dataset: doc dong mau, 0 = Evidence ung ho, 1 = bac bo, 2 = khong du thong tin
LABEL_NAMES = {0: "Supported", 1: "Refuted", 2: "NEI"}

# So sanh sau khi chuan hoa NFC + chu thuong, vi dataset viet ca "Giao duc" lan "GIAO DUC" (co dau)
EDUCATION_SOURCE_TOPICS = {"giáo dục", "giáo dục - hướng nghiệp"}
TECHNOLOGY_SOURCE_TOPICS = {"công nghệ", "khoa học công nghệ", "khoa học", "số hóa"}

TECHNOLOGY_KEYWORDS = [
    "công nghệ", "trí tuệ nhân tạo", "chatgpt", "chuyển đổi số", "điện thoại", "internet", "mạng xã hội",
    "robot", "dữ liệu", "an ninh mạng", "xe điện",
]
# "AI" so sanh giu nguyen hoa/thuong: bo qua hoa/thuong se trung tu "ai" (= nguoi nao) trong tieng Viet
TECHNOLOGY_CASE_SENSITIVE_KEYWORDS = ["AI"]

ENVIRONMENT_KEYWORDS = [
    "môi trường", "ô nhiễm", "rác thải", "chất thải", "biến đổi khí hậu", "phát thải", "khí nhà kính", "nhựa",
    "rừng", "năng lượng tái tạo", "ngập", "hạn hán", "xả nguồn",
]

# Bai bao phai trung it nhat bang nay moi vao chu de theo keyword: 1 lan nhac qua khong co nghia la noi ve chu de do
MIN_KEYWORD_HITS = 3


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip().lower()


def _word_pattern(keywords: list[str], flags: int = 0) -> re.Pattern:
    # Bien theo tu de "rung" khong trung giua tu khac; sap xep dai truoc de cum dai duoc uu tien
    alternatives = "|".join(re.escape(unicodedata.normalize("NFC", kw)) for kw in sorted(keywords, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", flags)


_ENVIRONMENT_PATTERN = _word_pattern(ENVIRONMENT_KEYWORDS, re.IGNORECASE)
_TECHNOLOGY_PATTERN = _word_pattern(TECHNOLOGY_KEYWORDS, re.IGNORECASE)
_TECHNOLOGY_EXACT_PATTERN = _word_pattern(TECHNOLOGY_CASE_SENSITIVE_KEYWORDS)


def assign_topic(source_topic: str, context: str, min_keyword_hits: int) -> tuple[str | None, str]:
    """Tra ve (topic, nguon gan). Bang diem giua 2 chu de keyword thi chon environment vi it bai hon."""
    normalized_topic = _normalize(source_topic)
    if normalized_topic in EDUCATION_SOURCE_TOPICS:
        return "education", "source_topic"
    if normalized_topic in TECHNOLOGY_SOURCE_TOPICS:
        return "technology", "source_topic"

    text = unicodedata.normalize("NFC", context)
    environment_hits = len(_ENVIRONMENT_PATTERN.findall(text))
    technology_hits = len(_TECHNOLOGY_PATTERN.findall(text)) + len(_TECHNOLOGY_EXACT_PATTERN.findall(text))
    best = max(environment_hits, technology_hits)
    if best < min_keyword_hits:
        return None, "none"
    return ("environment" if environment_hits >= technology_hits else "technology"), "keyword"


def article_id_from_url(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-keyword-hits", type=int, default=MIN_KEYWORD_HITS)
    parser.add_argument("--dry-run", action="store_true", help="Chi in bao cao, khong ghi file")
    args = parser.parse_args()

    dataset = load_dataset("tranthaihoa/vifactcheck", cache_dir=str(DATA_DIR))

    assigned: dict[str, tuple[str | None, str]] = {}
    records = []
    for split, split_data in dataset.items():
        for row in split_data:
            url = row["Url"]
            if url not in assigned:
                assigned[url] = assign_topic(row["Topic"], row["Context"], args.min_keyword_hits)
            topic, _ = assigned[url]
            if topic is None:
                continue
            records.append(
                {
                    "claim_id": row["index"],
                    "split": split,
                    "topic": topic,
                    "claim": row["Statement"],
                    "label": LABEL_NAMES[row["labels"]],
                    "article_id": article_id_from_url(url),
                    "context": row["Context"],
                    "gold_evidence": row["Evidence"],
                    # Them ngoai spec: ingest can de dien knowledge_source.url va citation
                    "url": url,
                    "author": row["Author"],
                    "source_topic": row["Topic"],
                }
            )

    articles_by_topic = defaultdict(set)
    claims_by_topic: Counter = Counter()
    labels_by_topic: dict[str, Counter] = defaultdict(Counter)
    splits_by_topic: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        articles_by_topic[record["topic"]].add(record["article_id"])
        claims_by_topic[record["topic"]] += 1
        labels_by_topic[record["topic"]][record["label"]] += 1
        splits_by_topic[record["topic"]][record["split"]] += 1

    origin_counts = Counter((topic, origin) for topic, origin in assigned.values())
    print(f"Nguong keyword: {args.min_keyword_hits}. Tong: {len(assigned)} bai, {sum(claims_by_topic.values())} claim duoc giu.")
    for topic in ("education", "environment", "technology"):
        print(
            f"{topic}: {len(articles_by_topic[topic])} bai "
            f"(theo Topic goc {origin_counts[(topic, 'source_topic')]}, theo keyword {origin_counts[(topic, 'keyword')]}), "
            f"{claims_by_topic[topic]} claim, label {dict(labels_by_topic[topic])}, split {dict(splits_by_topic[topic])}"
        )

    if args.dry_run:
        return
    DATA_DIR.mkdir(exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Da ghi {len(records)} dong vao {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
