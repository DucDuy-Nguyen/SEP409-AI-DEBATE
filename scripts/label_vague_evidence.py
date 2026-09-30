"""
Gan nhan tung hit cua detect_vague_evidence — do precision cua detector (chi log, khong reject).

Duyet MOI hit vague_evidence trong 1 file JSONL (moi lan thu case_plan co vague_evidence). Moi hit hien: cum tu,
ten truong, CAU chua cum do. Nhap:
    a = AI tu vien dan bang chung mo ho (van de that)
    l = du doan loi learner (hop le)
    n = bat nham (cum tu khong dung de vien dan bang chung, vd "phe X thang khi chung minh rang...")
    s = bo qua (khong tinh vao thong ke)          q = dung (chay lai de tiep tuc)
Luu NGAY sau moi hit vao experiments/labels/vague_evidence_labels.csv; chay lai bo qua hit da gan.

    python -m scripts.label_vague_evidence experiments/case_plan/<file>.jsonl
    python -m scripts.label_vague_evidence --report
Precision detector = a / (a + n)  (khong tinh l: learner viện dẫn la hop le nhung cung khong phai "bat nham").
"""
import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from scripts.eval_common import (
    UNKNOWN,
    append_csv,
    find_phrase_field,
    load_jsonl,
    normalize_vague,
    parse_case_json,
    read_csv,
    resolve_field,
    sentence_with,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LABELS = ROOT / "experiments" / "labels" / "vague_evidence_labels.csv"
CSV_FIELDS = [
    "hit_id", "source_path", "run_index", "attempt", "field", "group", "phrase", "label", "sentence", "labeled_at",
]
LABELS = {"a": "AI tu vien dan (van de that)", "l": "du doan loi learner (hop le)", "n": "bat nham", "s": "bo qua"}


def build_hits(records: list[dict]) -> list[dict]:
    hits = []
    for r in records:
        for a in r["attempts"]:
            entries = normalize_vague(a.get("vague_evidence"))
            if not entries:
                continue
            data = parse_case_json(a.get("raw_output")) or {}
            for e in entries:
                field, text = e["field"], None
                shown_field = field
                if field is not None:
                    text = resolve_field(data, field)
                else:  # dang cu: khong co ten truong -> tim truong dau tien chua cum (chi de hien thi)
                    located, text = find_phrase_field(data, e["phrase"])
                    shown_field = f"{located} (suy ra, du lieu cu)" if located else "? (du lieu cu)"
                hits.append(
                    {
                        "hit_id": f"{r['_source']}:{r['run_index']}:{a['attempt']}:{field or '?'}:{e['phrase']}",
                        "source_path": r["_source_path"],
                        "run_index": r["run_index"],
                        "attempt": a["attempt"],
                        "field": field or "",
                        "shown_field": shown_field,
                        "group": e["group"],
                        "phrase": e["phrase"],
                        "sentence": sentence_with(text, e["phrase"]) if text else "(khong tim thay cau trong output)",
                    }
                )
    return hits


def label_hits(hits: list[dict], labels_path: Path, input_fn=input, out=print) -> bool:
    """Tra True neu gan xong het, False neu nguoi dung dung (q)."""
    done = {row["hit_id"] for row in read_csv(labels_path)}
    todo = [h for h in hits if h["hit_id"] not in done]
    out(f"{len(hits)} hit | da gan {len(hits) - len(todo)} | chua gan {len(todo)}")
    out("  " + " | ".join(f"{k} = {v}" for k, v in LABELS.items()) + " | q = dung")
    for i, hit in enumerate(todo, start=1):
        out(f"\n----- Hit {len(hits) - len(todo) + i}/{len(hits)} -----")
        out(f"Cum tu : \"{hit['phrase']}\"")
        out(f"Truong : {hit['shown_field']}")
        out(f"Cau    : {hit['sentence']}")
        while True:
            answer = input_fn("  Nhan [a/l/n/s]: ").strip().lower()
            if answer == "q":
                out("Da dung. Chay lai lenh de tiep tuc (hit da gan duoc giu).")
                return False
            if answer in LABELS:
                break
            out("  Chi nhan a / l / n / s (hoac q de dung).")
        append_csv(
            labels_path,
            CSV_FIELDS,
            [{**{k: hit[k] for k in CSV_FIELDS if k in hit}, "label": answer,
              "labeled_at": datetime.now().isoformat(timespec="seconds")}],
        )
    return True


def _stats(rows: list[dict]) -> dict:
    counts = Counter(row["label"] for row in rows if row["label"] != "s")
    total = sum(counts.values())
    a, n = counts["a"], counts["n"]
    return {
        "total": total,
        "a": a,
        "l": counts["l"],
        "n": n,
        "precision": round(a / (a + n), 3) if (a + n) else None,
    }


def build_report(rows: list[dict]) -> dict:
    by_group = {g: _stats([r for r in rows if r["group"] == g]) for g in sorted({r["group"] for r in rows})}
    by_phrase = {p: _stats([r for r in rows if r["phrase"] == p]) for p in sorted({r["phrase"] for r in rows})}
    return {
        "labeled": len(rows),
        "skipped": sum(1 for r in rows if r["label"] == "s"),
        "overall": _stats(rows),
        "by_group": by_group,
        "by_phrase": by_phrase,
    }


def _fmt(s: dict) -> str:
    total = s["total"]

    def pct(k):
        return f"{s[k]} ({s[k] / total:.0%})" if total else "0"

    precision = f"{s['precision']:.0%}" if s["precision"] is not None else "-"
    return f"n={total:<4} a={pct('a'):<10} l={pct('l'):<10} n={pct('n'):<10} precision={precision}"


def format_report(report: dict) -> str:
    lines = [
        "\n===== BAO CAO NHAN vague_evidence =====",
        f"{report['labeled']} hit da gan ({report['skipped']} bo qua, khong tinh). Precision = a / (a + n).",
        "",
        f"Tong the : {_fmt(report['overall'])}",
        "",
        "Theo nhom truong:",
    ]
    lines += [f"  {g:<14} {_fmt(s)}" for g, s in report["by_group"].items()]
    if UNKNOWN in report["by_group"]:
        lines.append("  (unknown = du lieu cu khong co ten truong)")
    lines += ["", "Theo cum tu:"]
    lines += [f"  \"{p}\"".ljust(18) + f" {_fmt(s)}" for p, s in report["by_phrase"].items()]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gan nhan tung hit vague_evidence")
    parser.add_argument("file", nargs="?", type=Path, help="1 file JSONL batch")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--report", action="store_true", help="Chi in bao cao tu file nhan da co")
    args = parser.parse_args()

    if not args.report:
        if args.file is None:
            parser.error("Can 1 file JSONL (hoac --report)")
        if not label_hits(build_hits(load_jsonl(args.file)), args.labels):
            return 0
    rows = read_csv(args.labels)
    print(format_report(build_report(rows)) if rows else f"Chua co nhan nao trong {args.labels}.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
