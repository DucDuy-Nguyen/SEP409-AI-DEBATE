"""
Danh gia tach claim tren data/eval/extract_set.jsonl (docs/RAG_STEP2_SPEC.md muc 3.2). GOI LLM THAT de tach claim,
nhung KHONG dung LLM de cham: claim tach ra khop expected khi cosine bge-m3 >= 0.8 (ghep 1-1, cap cao nhat truoc).

Do: so lap luan quan diem bi tach ra claim (ky vong 0); so claim tach ra so voi expected; claim co chuan hoa so
khong: moi so trong expected phai xuat hien trong claim tach ra voi CUNG gia tri khi doc theo dinh dang tieng Viet
(dau cham hang nghin, dau phay thap phan), va dem rieng so viet dau phay hang nghin kieu tieng Anh ("29,383").
In tung lap luan de doc tay.

Cach dung:
    python scripts/rag/eval_extract.py
"""
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVICE_DIR))

from app.rag.claim_extractor import extract_claims
from app.rag.embedder import Embedder
from app.rag.llm_usage import LLMCallStats
from app.services.json_utils import EvaluationParseError

sys.stdout.reconfigure(encoding="utf-8")

INPUT_PATH = SERVICE_DIR / "data" / "eval" / "extract_set.jsonl"
RESULTS_DIR = SERVICE_DIR / "data" / "results"
DOCS_RESULTS_DIR = SERVICE_DIR / "docs" / "rag_results"
MATCH_THRESHOLD = 0.8

_NUMBER = re.compile(r"\d+(?:[.,/]\d+)*")
# Dau phay phan cach hang nghin kieu tieng Anh ("29,383", "12,000"): tieng Viet doc la so thap phan -> sai dinh dang
_EN_THOUSANDS = re.compile(r"^\d{1,3}(?:,\d{3})+$")


def vn_number_values(text: str) -> set[str]:
    """
    Gia tri cac so, doc theo dinh dang TIENG VIET: dau cham hang nghin, dau phay thap phan. "8.000" va "8000" -> "8000";
    "3,5" -> "3.5"; "29,383" -> "29.383" (thap phan) nen KHONG khop "29.383" kieu tieng Viet (= 29383). Ngay "22/3" giu nguyen.
    """
    values = set()
    for token in _NUMBER.findall(text):
        values.add(token if "/" in token else token.replace(".", "").replace(",", "."))
    return values


def english_thousands(text: str) -> list[str]:
    return [token for token in _NUMBER.findall(text) if _EN_THOUSANDS.match(token)]


def match_claims(expected: list[str], extracted: list[str], vectors: dict[str, list[float]]) -> list[tuple[int, int, float]]:
    """Ghep 1-1 theo cosine giam dan (vector da normalize nen cosine = tich vo huong), chi giu cap >= nguong."""
    pairs = []
    for i, exp in enumerate(expected):
        for j, ext in enumerate(extracted):
            score = sum(a * b for a, b in zip(vectors[exp], vectors[ext]))
            pairs.append((score, i, j))
    used_expected, used_extracted, matches = set(), set(), []
    for score, i, j in sorted(pairs, reverse=True):
        if score < MATCH_THRESHOLD:
            break
        if i not in used_expected and j not in used_extracted:
            used_expected.add(i)
            used_extracted.add(j)
            matches.append((i, j, score))
    return matches


def main() -> None:
    rows = [json.loads(line) for line in INPUT_PATH.open(encoding="utf-8")]
    stats = LLMCallStats()
    started = time.perf_counter()
    for row in rows:
        try:
            claims = extract_claims(row["argument_text"], row["motion"], stats=stats)
            row["extracted"] = [{"text": c.text, "claim_type": c.claim_type.value} for c in claims]
            row["error"] = None
        except (EvaluationParseError, RuntimeError) as exc:
            row["extracted"], row["error"] = [], str(exc)
        print(f"{row['id']}: {len(row['extracted'])} claim", flush=True)
    llm_seconds = time.perf_counter() - started

    texts = list(dict.fromkeys(t for row in rows for t in row["expected_claims"] + [c["text"] for c in row["extracted"]]))
    vectors = dict(zip(texts, Embedder().encode(texts))) if texts else {}

    total_expected = total_extracted = total_matched = 0
    numbers_expected = numbers_found = 0
    wrong_format: list[str] = []
    print("\n| id | loai | expected | tach ra | khop | so dung dinh dang VN | so dau phay hang nghin |")
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        extracted = [c["text"] for c in row["extracted"]]
        matches = match_claims(row["expected_claims"], extracted, vectors)
        row["matches"] = [{"expected": row["expected_claims"][i], "extracted": extracted[j], "cosine": round(s, 3)}
                          for i, j, s in matches]
        # expected_claims viet dung dinh dang VN; so cua claim tach ra phai cho CUNG gia tri khi doc theo dinh dang VN
        wanted = set().union(*(vn_number_values(c) for c in row["expected_claims"])) if row["expected_claims"] else set()
        found = wanted & set().union(*(vn_number_values(c) for c in extracted)) if extracted else set()
        bad = [token for claim in extracted for token in english_thousands(claim)]
        wrong_format.extend(bad)
        row["numbers"] = {"expected": sorted(wanted), "found": sorted(found), "english_thousands": bad}
        total_expected += len(row["expected_claims"])
        total_extracted += len(extracted)
        total_matched += len(matches)
        numbers_expected += len(wanted)
        numbers_found += len(found)
        number_cell = f"{len(found)}/{len(wanted)}" if wanted else "-"
        print(f"| {row['id']} | {row['kind']} | {len(row['expected_claims'])} | {len(extracted)} | {len(matches)} "
              f"| {number_cell} | {', '.join(bad) or '-'} |")

    opinion_rows = [row for row in rows if row["kind"] == "opinion"]
    summary = {
        "arguments": len(rows),
        "opinion_arguments": len(opinion_rows),
        "opinion_with_claims": sum(bool(row["extracted"]) for row in opinion_rows),
        "expected_claims": total_expected,
        "extracted_claims": total_extracted,
        "matched_claims": total_matched,
        "recall": total_matched / total_expected if total_expected else 0.0,
        "precision": total_matched / total_extracted if total_extracted else 0.0,
        "numbers_expected": numbers_expected,
        "numbers_found_vn_format": numbers_found,
        "english_thousands_separator": wrong_format,
        "errors": sum(row["error"] is not None for row in rows),
        "match_threshold": MATCH_THRESHOLD,
        "llm": {"requests": stats.requests, "llm_calls": stats.llm_calls, "retries": stats.retries,
                "prompt_tokens": stats.prompt_tokens, "completion_tokens": stats.completion_tokens,
                "total_tokens": stats.total_tokens, "seconds": round(llm_seconds, 1)},
    }
    print(f"\nTong: {json.dumps(summary, ensure_ascii=False)}")

    print("\n=== Chi tiet tung lap luan ===")
    for row in rows:
        print(f"\n## {row['id']} ({row['kind']})")
        for claim in row["expected_claims"]:
            print(f"  expected: {claim}")
        for claim in row["extracted"]:
            print(f"  tach ra [{claim['claim_type']}]: {claim['text']}")
        for match in row["matches"]:
            print(f"  khop {match['cosine']}: {match['expected'][:60]} <-> {match['extracted'][:60]}")
        if row["error"]:
            print(f"  LOI: {row['error']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / f"extract_{datetime.now():%Y%m%d_%H%M%S}.json"
    output_path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(output_path, DOCS_RESULTS_DIR / output_path.name)
    print(f"\nDa ghi {output_path} va chep sang {DOCS_RESULTS_DIR / output_path.name}")


if __name__ == "__main__":
    main()
