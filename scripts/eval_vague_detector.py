"""
Danh gia bo do bang chung mo ho MOI (app/opponent/vague_detector.py) bang nhan tay cua bo do CU.
Chi DOC JSONL + CSV nhan — khong goi LLM.

    python -m scripts.eval_vague_detector \\
        --design experiments/case_plan/20260927-092737_case_plan_v3.jsonl \\
        --test   experiments/case_plan/20260927-094713_case_plan_v4.jsonl

- --design: tap THIET KE (quy tac duoc viet dua tren nhan tap nay). --test: tap KIEM TRA (khong nhin khi thiet ke).
- Quet lai dung cac lan thu case_plan ma bo do cu da quet (vague_evidence != null), bang bo do moi.
- Ghep hit moi voi nhan cu: cung (file, run_index, attempt, truong) va doan khop moi CHUA cum cu (vd hit moi
  "nghiên cứu (...) cho thấy" chua cum cu "nghiên cứu"). Hit moi khong ghep duoc nhan nao -> muc "CHUA CO NHAN"
  (in rieng de gan tay). Nhan 'a' khong con hit HIGH nao phu -> muc "BO SOT".
- Precision = a / (a + n) tren hit DA CO NHAN (khong tinh 'l', 's', chua co nhan).
"""
import argparse
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from app.opponent import vague_detector as vd
from scripts.eval_common import load_jsonl, parse_case_json, read_csv, resolve_field, sentence_with

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LABELS = ROOT / "experiments" / "labels" / "vague_evidence_labels.csv"
MARK = {"a": "DUNG (a)", "n": "NHAM (n)", "l": "learner (l)", "?": "CHUA CO NHAN"}


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _file_name(path: str) -> str:
    return Path(path.replace("\\", "/")).name


def evaluate(records: list[dict], label_rows: list[dict]) -> dict:
    """Ket qua cho 1 tap (1 hoac nhieu file JSONL)."""
    files = {r["_source"] for r in records}
    labels = [row for row in label_rows if _file_name(row["source_path"]) in files and row["label"] != "s"]
    by_place: dict[tuple, list[dict]] = {}
    for row in labels:
        by_place.setdefault((_file_name(row["source_path"]), int(row["run_index"]), int(row["attempt"]), row["field"]), []).append(row)

    hits, covered = [], set()
    for r in records:
        for a in r["attempts"]:
            if a["purpose"] != "case_plan" or a.get("vague_evidence") is None:
                continue  # chi nhung lan thu bo do cu da quet
            data = parse_case_json(a.get("raw_output"))
            if data is None:
                continue
            for h in vd.detect(data):
                place = (r["_source"], r["run_index"], a["attempt"], h.field)
                matched = [row for row in by_place.get(place, []) if _norm(row["phrase"]) in _norm(h.match)]
                found = {row["label"] for row in matched}
                label = found.pop() if len(found) == 1 else ("conflict" if found else "?")
                covered.update(
                    (place, row["phrase"]) for row in matched if h.level == vd.HIGH or row["label"] != "a"
                )
                text = resolve_field(data, h.field) or ""
                hits.append({
                    "file": r["_source"], "run_index": r["run_index"], "motion_id": r.get("motion_id"),
                    "attempt": a["attempt"], "field": h.field, "rule": h.rule, "level": h.level, "match": h.match,
                    "label": label, "sentence": sentence_with(text, h.match) if text else "",
                })

    missed = []  # nhan 'a' ma bo do moi khong co hit HIGH nao phu
    for row in labels:
        place = (_file_name(row["source_path"]), int(row["run_index"]), int(row["attempt"]), row["field"])
        if row["label"] == "a" and not any(
            h["level"] == vd.HIGH and (h["file"], h["run_index"], h["attempt"], h["field"]) == place
            and _norm(row["phrase"]) in _norm(h["match"]) for h in hits
        ):
            missed.append(row)

    def stats(level_hits: list[dict]) -> dict:
        c = Counter(h["label"] for h in level_hits)
        a, n = c["a"], c["n"]
        return {"hits": len(level_hits), "a": a, "n": n, "l": c["l"], "unlabeled": c["?"], "conflict": c["conflict"],
                "precision": (a, a + n)}

    old = Counter(row["label"] for row in labels)
    return {
        "files": sorted(files),
        "old": {"hits": len(labels), "a": old["a"], "n": old["n"], "l": old["l"], "precision": (old["a"], old["a"] + old["n"])},
        "high": stats([h for h in hits if h["level"] == vd.HIGH]),
        "low": stats([h for h in hits if h["level"] == vd.LOW]),
        "hits": hits,
        "missed": missed,
    }


def _p(pair: tuple[int, int]) -> str:
    a, total = pair
    return f"{a}/{total} ({a / total:.0%})" if total else "-"


def format_report(name: str, result: dict) -> str:
    old, high, low = result["old"], result["high"], result["low"]
    lines = [
        f"\n=============== {name}: {', '.join(result['files'])} ===============",
        f"Bo do CU (theo nhan tay): {old['hits']} hit, a={old['a']} n={old['n']} l={old['l']} -> precision {_p(old['precision'])}",
        f"Bo do MOI — HIGH (reject): {high['hits']} hit | a={high['a']} n={high['n']} l={high['l']} "
        f"chua co nhan={high['unlabeled']} -> precision (tren hit da co nhan) {_p(high['precision'])}",
        f"Bo do MOI — LOW (chi log): {low['hits']} hit | a={low['a']} n={low['n']} l={low['l']} "
        f"chua co nhan={low['unlabeled']}",
    ]
    for level in (vd.HIGH, vd.LOW):
        level_hits = [h for h in result["hits"] if h["level"] == level and h["label"] != "?"]
        lines.append(f"\n--- Hit {level.upper()} da co nhan ({len(level_hits)}) ---")
        for h in level_hits:
            lines.append(
                f"  [{MARK.get(h['label'], h['label'])}] {h['motion_id']} run {h['run_index']} #{h['attempt']} "
                f"{h['field']} ({h['rule']}): \"{h['match']}\"\n      cau: {h['sentence']}"
            )
    unlabeled = [h for h in result["hits"] if h["label"] == "?"]
    lines.append(f"\n--- CHUA CO NHAN — can gan tay ({len(unlabeled)}) ---")
    for h in unlabeled:
        lines.append(
            f"  [{h['level'].upper()}] {h['motion_id']} run {h['run_index']} #{h['attempt']} {h['field']} "
            f"({h['rule']}): \"{h['match']}\"\n      cau: {h['sentence']}"
        )
    lines.append(f"\n--- BO SOT: nhan 'a' khong con hit HIGH nao ({len(result['missed'])}) ---")
    for row in result["missed"]:
        lines.append(f"  run {row['run_index']} #{row['attempt']} {row['field']} \"{row['phrase']}\": {row['sentence']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Danh gia bo do bang chung mo ho moi bang nhan tay")
    parser.add_argument("--design", nargs="+", type=Path, required=True, metavar="FILE.jsonl", help="Tap thiet ke")
    parser.add_argument("--test", nargs="+", type=Path, required=True, metavar="FILE.jsonl", help="Tap kiem tra")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = parser.parse_args()

    rows = read_csv(args.labels)
    for name, paths in (("TAP THIET KE", args.design), ("TAP KIEM TRA", args.test)):
        print(format_report(name, evaluate([r for p in paths for r in load_jsonl(p)], rows)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
