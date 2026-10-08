"""
So sanh ket qua batch Case Planning giua 2 phien ban prompt (vd v3 vs v4). Chi DOC JSONL, khong goi LLM.

- Moi phien ban nhan NHIEU file (gop khi chay lap); dua DUNG 2 trong 3 nhom --v3 / --v4 / --v5:
      python -m scripts.compare_case_plan_batches --v3 a.jsonl b.jsonl --v4 c.jsonl d.jsonl
      python -m scripts.compare_case_plan_batches --v4 c.jsonl --v5 e.jsonl
- File chay lai (--only-failed, co `rerun_of`) THAY THE lan chay llm_error tuong ung (cung run_index) cua file goc
  neu file goc cung nam trong nhom.
- CHI so cac cau hinh (motion, ai_side, difficulty) co o CA 2 phien ban; in danh sach cau hinh bi thieu.
  Moi cau hinh co the co nhieu lan chay (chay lap) — chi so tinh tren moi lan chay cua cau hinh chung.
- vague_evidence tach nhom: ai_fields (khang dinh cua AI) / learner_claim (du doan loi learner) / unknown (dang cu).
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

from app.opponent.models import LLMCallPurpose, ReviewerVerdict
from app.opponent.service import FailureKind
from scripts.eval_common import AI_FIELDS, FIELD_GROUPS, LEARNER_CLAIM, UNKNOWN, Key, load_jsonl, normalize_vague, run_key
from scripts.run_case_plan_batch import content_retries, rate_limit_waits


def load_group(paths: list[Path]) -> tuple[list[dict], int]:
    """Gop nhieu file cua 1 phien ban. Tra (records, so lan chay llm_error bi thay boi file chay lai)."""
    records = [r for p in paths for r in load_jsonl(p)]
    reruns = {(r["rerun_of"], r["run_index"]) for r in records if r.get("rerun_of")}
    kept = [
        r for r in records
        if not ((r["_source"], r["run_index"]) in reruns and r["final_status"] == "llm_error" and not r.get("rerun_of"))
    ]
    return kept, len(records) - len(kept)


def pair_groups(groups: dict[str, list[dict]]) -> dict:
    """Cau hinh chung cua moi nhom + cau hinh chi co o tung nhom."""
    keys = {label: {run_key(r) for r in records} for label, records in groups.items()}
    common = set.intersection(*keys.values()) if keys else set()
    return {
        "common": common,
        "missing": {label: sorted(k - common) for label, k in keys.items()},
        "paired": {label: [r for r in records if run_key(r) in common] for label, records in groups.items()},
    }


def _plan_attempts(record: dict) -> list[dict]:
    return [a for a in record["attempts"] if a["purpose"] == LLMCallPurpose.CASE_PLAN.value]


def vague_stats(records: list[dict]) -> dict:
    """Theo nhom truong: so case file (cuoi) co hit, tong so hit, so hit theo cum."""
    stats = {g: {"case_files_with_hits": 0, "hits": 0, "by_phrase": Counter()} for g in FIELD_GROUPS}
    for r in records:
        if r["case_file"] is None:
            continue
        hits = normalize_vague(r.get("final_vague_evidence"))
        for group in FIELD_GROUPS:
            group_hits = [h for h in hits if h["group"] == group]
            if group_hits:
                stats[group]["case_files_with_hits"] += 1
                stats[group]["hits"] += len(group_hits)
                stats[group]["by_phrase"].update(h["phrase"] for h in group_hits)
    return stats


def metrics(records: list[dict]) -> dict:
    n = len(records)
    return {
        "n": n,
        "success": sum(1 for r in records if r["final_status"] == "ready"),
        "runs_with_side_flip": sum(
            1 for r in records if any(a.get("reviewer_verdict") == ReviewerVerdict.SIDE_FLIP.value for a in _plan_attempts(r))
        ),
        "side_flip_attempts": sum(
            1 for r in records for a in _plan_attempts(r) if a.get("reviewer_verdict") == ReviewerVerdict.SIDE_FLIP.value
        ),
        "schema_rejected": sum(1 for r in records for a in r["attempts"] if a.get("schema_rejected")),
        "banned_phrase_rejected": sum(
            1 for r in records for a in _plan_attempts(r) if a.get("failure_kind") == FailureKind.BANNED_PHRASE
        ),
        # retry vi NOI DUNG (khong gom cho 429) — chi so chat luong prompt
        "avg_content_retries": round(sum(content_retries(r) for r in records) / n, 2) if n else 0.0,
        # cho vi 429 — phan anh tai / rate limit luc chay, KHONG phai chat luong prompt
        "rate_limit_waits": sum(rate_limit_waits(r)[0] for r in records),
        "avg_latency_ms": round(sum(r["total_latency_ms"] for r in records) / n) if n else 0,
        "vague": vague_stats(records),
    }


def _rate(count: int, n: int) -> str:
    return f"{count}/{n} ({count / n:.0%})" if n else "0/0"


# (nhan, khoa, kieu hien thi: "rate" = count/n (%), "num" = so)
ROWS = [
    ("Thanh cong", "success", "rate"),
    ("Lan chay co side_flip", "runs_with_side_flip", "rate"),
    ("  so lan thu bi side_flip", "side_flip_attempts", "num"),
    ("Groq tu choi schema (lan thu)", "schema_rejected", "num"),
    ("Bi reject do cum cam / bang chung mo ho HIGH (lan thu)", "banned_phrase_rejected", "num"),
    ("content_retries trung binh", "avg_content_retries", "num"),
    ("rate_limit_waits (tong lan cho 429)", "rate_limit_waits", "num"),
    ("Latency trung binh (ms)", "avg_latency_ms", "num"),
]
GROUP_LABEL = {AI_FIELDS: "ai_fields", LEARNER_CLAIM: "learner_claim", UNKNOWN: "unknown (dang cu)"}


def _table(header: tuple, rows: list[tuple]) -> str:
    widths = [max(len(str(row[i])) for row in [header, *rows]) for i in range(len(header))]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def fmt(row):
        return "| " + " | ".join(str(cell).ljust(w) for cell, w in zip(row, widths)) + " |"

    return "\n".join([sep, fmt(header), sep, *map(fmt, rows), sep])


def _delta(a, b) -> str:
    diff = b - a
    return f"{diff:+.2f}" if isinstance(diff, float) else f"{diff:+d}"


def format_main_table(label_a: str, label_b: str, ma: dict, mb: dict) -> str:
    rows = []
    for label, key, kind in ROWS:
        va, vb = ma[key], mb[key]
        cell_a = _rate(va, ma["n"]) if kind == "rate" else str(va)
        cell_b = _rate(vb, mb["n"]) if kind == "rate" else str(vb)
        rows.append((label, cell_a, cell_b, _delta(va, vb)))
    return _table(("Chi so", label_a, label_b, f"Chenh ({label_b} - {label_a})"), rows)


def format_vague_tables(label_a: str, label_b: str, ma: dict, mb: dict) -> str:
    va, vb = ma["vague"], mb["vague"]
    groups = [g for g in FIELD_GROUPS if g != UNKNOWN or va[UNKNOWN]["hits"] or vb[UNKNOWN]["hits"]]
    summary_rows = []
    for g in groups:
        summary_rows.append(
            (GROUP_LABEL[g] + ": case file co hit", _rate(va[g]["case_files_with_hits"], ma["success"]),
             _rate(vb[g]["case_files_with_hits"], mb["success"]),
             _delta(va[g]["case_files_with_hits"], vb[g]["case_files_with_hits"]))
        )
        summary_rows.append(
            (GROUP_LABEL[g] + ": tong hit", va[g]["hits"], vb[g]["hits"], _delta(va[g]["hits"], vb[g]["hits"]))
        )
    phrase_rows = []
    for g in groups:
        for phrase in sorted(set(va[g]["by_phrase"]) | set(vb[g]["by_phrase"])):
            a, b = va[g]["by_phrase"][phrase], vb[g]["by_phrase"][phrase]
            phrase_rows.append((GROUP_LABEL[g], f'"{phrase}"', a, b, _delta(a, b)))
    out = [
        "vague_evidence trong case file cuoi (chi log, khong reject) — ti le tren so case file thanh cong:",
        _table(("Nhom", label_a, label_b, "Chenh"), summary_rows),
    ]
    if phrase_rows:
        out += ["", "So hit theo cum:", _table(("Nhom", "Cum", label_a, label_b, "Chenh"), phrase_rows)]
    return "\n".join(out)


def compare(groups_paths: dict[str, list[Path]]) -> str:
    if len(groups_paths) != 2:
        raise ValueError("Can dung 2 phien ban de so sanh")
    (label_a, paths_a), (label_b, paths_b) = groups_paths.items()
    lines = []
    groups = {}
    for label, paths in groups_paths.items():
        records, replaced = load_group(paths)
        groups[label] = records
        versions = sorted({r["prompt_version"] for r in records})
        lines.append(
            f"{label}: {len(paths)} file, {len(records)} lan chay, prompt_version={','.join(versions)}"
            + (f" ({replaced} lan llm_error da duoc thay bang file chay lai)" if replaced else "")
        )
        if any(label not in v for v in versions):
            lines.append(f"  CANH BAO: nhom {label} chua file prompt_version khac ({', '.join(versions)})")

    paired = pair_groups(groups)
    lines.append(f"Cau hinh (motion, ai_side, difficulty) chung: {len(paired['common'])}")
    for label, missing in paired["missing"].items():
        if missing:
            lines.append(f"  Chi co o {label} (bi bo qua, {len(missing)}):")
            lines += [f"    - {m} | {s} | {d}" for m, s, d in missing]
    if not paired["common"]:
        lines.append("Khong co cau hinh chung nao de so sanh.")
        return "\n".join(lines)

    ma, mb = metrics(paired["paired"][label_a]), metrics(paired["paired"][label_b])
    lines.append(f"So lan chay tren cau hinh chung: {label_a}={ma['n']}, {label_b}={mb['n']}")
    lines += ["", format_main_table(label_a, label_b, ma, mb), "", format_vague_tables(label_a, label_b, ma, mb)]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="So sanh batch Case Planning giua 2 phien ban prompt (JSONL)")
    for version in ("v3", "v4", "v5"):
        parser.add_argument(f"--{version}", nargs="+", type=Path, default=None, metavar="FILE.jsonl")
    args = parser.parse_args()
    groups = {v: getattr(args, v) for v in ("v3", "v4", "v5") if getattr(args, v)}
    if len(groups) != 2:
        parser.error("Can dung 2 nhom trong --v3 / --v4 / --v5")
    print(compare(groups))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
