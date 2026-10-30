"""
Gan nhan cau truc case file — thi nghiem motion_type, case_plan_v5 vs v6 (dev log muc 2.13). Chi DOC JSONL, khong goi
LLM. HAI LUOT, luu 2 file CSV rieng (moi luot chay tiep duoc):

LUOT 1 (mac dinh) — Q2, MU, MOI mau (ca v5 lan v6), xao tron theo --seed:
  hien kien nghi, motion_type, cach hieu CHUAN (motions_v2.json, lam ngu canh), claim + reasoning tung luan diem,
  weighing. KHONG hien motion_reading cua case file (ke ca ban model tu viet — v6 chep nguyen van cach hieu chuan nen
  se lo nhanh), prompt_version, ten file, phe, do kho, reviewer.
    policy      "Có ít nhất một luận điểm về thực thi/khả thi?"
    comparative "Vừa bảo vệ lựa chọn của mình VỪA đánh lựa chọn kia?"
    value       "Phần cân nhắc có tiêu chí rõ ràng?"                                   -> y / n
  Mau khong co motion_type -> bo qua (khong co cau hoi Q2).

LUOT 2 (--q1) — Q1, KHONG MU, CHI mau v5, chi de MO TA (khong tham gia quy tac quyet dinh):
  hien motion_reading MODEL viet canh cach hieu chuan: g = giong, h = hep hon, r = rong hon, k = khac han.

q = dung; luu NGAY sau moi mau, chay lai se bo qua mau da gan. --report: Q2 theo nhanh x loai + tong (nhanh doc lai
tu file nguon); Q1 chi cho v5.

    python -m scripts.label_case_structure experiments/case_plan/<v5>.jsonl experiments/case_plan/<v6>.jsonl --seed 7
    python -m scripts.label_case_structure experiments/case_plan/<v5>.jsonl experiments/case_plan/<v6>.jsonl --q1
    python -m scripts.label_case_structure --report
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from scripts.eval_common import append_csv, load_jsonl, read_csv

ROOT = Path(__file__).resolve().parent.parent
LABELS_DIR = ROOT / "experiments" / "labels"
DEFAULT_Q2_LABELS = LABELS_DIR / "case_structure_q2.csv"
DEFAULT_Q1_LABELS = LABELS_DIR / "case_structure_q1.csv"
DEFAULT_MOTIONS = ROOT / "experiments" / "motions_v2.json"
BASE_FIELDS = ["sample_id", "source_path", "run_index", "motion_id", "motion_type"]
Q2_FIELDS = [*BASE_FIELDS, "q2_structure", "labeled_at"]
Q1_FIELDS = [*BASE_FIELDS, "q1_reading", "labeled_at"]
Q1_LABELS = {"g": "giong", "h": "hep hon", "r": "rong hon", "k": "khac han"}
Q2_QUESTION = {
    "policy": "Có ít nhất một luận điểm về thực thi/khả thi?",
    "comparative": "Vừa bảo vệ lựa chọn của mình VỪA đánh lựa chọn kia?",
    "value": "Phần cân nhắc có tiêu chí rõ ràng?",
}
MOTION_TYPES = ("policy", "comparative", "value")
V5 = "case_plan_v5"
OVERRIDDEN = "motion_reading_overridden"


# ---------------- lay mau ----------------


def load_canonical_readings(path: Path = DEFAULT_MOTIONS) -> dict[str, str]:
    """
    Ngu canh chuan moi motion: motions_v2 -> motion_reading; motions_v3 (muc 2.15, khong co motion_reading) -> ganh
    nang chung minh cua CA HAI phe (hien giong nhau cho moi nhanh nen khong lo nhanh).
    """
    if not Path(path).exists():
        return {}
    out = {}
    for m in json.loads(Path(path).read_text(encoding="utf-8"))["motions"]:
        if m.get("motion_reading"):
            out[m["id"]] = m["motion_reading"]
        elif m.get("burden_pro") and m.get("burden_con"):
            out[m["id"]] = f"De xuat phai chung minh: {m['burden_pro']} | Phan doi phai chung minh: {m['burden_con']}"
    return out


def model_reading(record: dict) -> str:
    """Cach hieu MODEL viet (truoc khi v6 ghi de): key_repairs.motion_reading_overridden.model, khong thi case file."""
    for a in reversed(record.get("attempts", [])):
        if a.get("purpose") == "case_plan" and a.get("success"):
            overridden = (a.get("key_repairs") or {}).get(OVERRIDDEN)
            if overridden:
                return overridden["model"]
            break
    return record["case_file"].get("motion_reading", "")


def build_samples(records: list[dict], canonical: dict[str, str]) -> list[dict]:
    samples = []
    for r in records:
        case = r.get("case_file")
        if r.get("final_status") != "ready" or not case:
            continue
        samples.append({
            "sample_id": f"{r['_source']}:{r['run_index']}",
            "source_path": r["_source_path"],
            "run_index": r["run_index"],
            "motion_id": r["motion_id"],
            "motion": r["motion"],
            "motion_type": r.get("motion_type"),
            "canonical_reading": canonical.get(r["motion_id"]) or r.get("motion_reading") or "(khong co)",
            "arguments": [{"claim": a.get("claim", ""), "reasoning": a.get("reasoning", "")} for a in case.get("arguments", [])],
            "weighing": case.get("weighing", ""),
            # --- KHONG hien o luot Q2 (mu) ---
            "model_reading": model_reading(r),
            "prompt_version": r.get("prompt_version"),
        })
    return samples


def shuffle(samples: list[dict], seed: int) -> list[dict]:
    ordered = sorted(samples, key=lambda s: s["sample_id"])  # on dinh truoc khi xao (khong phu thuoc thu tu file)
    random.Random(seed).shuffle(ordered)
    return ordered


def _base_lines(sample: dict, number: int, total: int) -> list[str]:
    return [
        f"\n===== Mau {number}/{total} =====",
        f"Kien nghi: {sample['motion']}",
        f"Loai: {sample['motion_type'] or '(khong ro)'}",
        f"Cach hieu CHUAN: {sample['canonical_reading']}",
    ]


def render_q2(sample: dict, number: int, total: int) -> str:
    """Luot MU: KHONG motion_reading cua case file (ca ban model), prompt_version, ten file, phe, do kho, reviewer."""
    lines = _base_lines(sample, number, total) + [""]
    for i, a in enumerate(sample["arguments"], start=1):
        lines.append(f"[Luan diem {i}] {a['claim']}")
        if a["reasoning"]:
            lines.append(f"      ly do: {' '.join(a['reasoning'].split())}")
    lines += ["", f"[Can nhac] {sample['weighing']}", ""]
    return "\n".join(lines)


def render_q1(sample: dict, number: int, total: int) -> str:
    """Luot KHONG MU (chi v5): cach hieu model viet canh cach hieu chuan."""
    return "\n".join(_base_lines(sample, number, total) + [f"Cach hieu MODEL viet: {sample['model_reading']}", ""])


# ---------------- gan nhan ----------------


def _ask(prompt: str, allowed: set[str], input_fn, out) -> str | None:
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer == "q":
            return None
        if answer in allowed:
            return answer
        out(f"  Chi nhan {' / '.join(sorted(allowed))} (hoac q de dung).")


def _row(sample: dict, **answer) -> dict:
    return {"sample_id": sample["sample_id"], "source_path": sample["source_path"], "run_index": sample["run_index"],
            "motion_id": sample["motion_id"], "motion_type": sample["motion_type"] or "", **answer,
            "labeled_at": datetime.now().isoformat(timespec="seconds")}


def _label_loop(samples, labels_path, fields, render, ask, header, input_fn, out) -> bool:
    done = {row["sample_id"] for row in read_csv(labels_path)}
    todo = [s for s in samples if s["sample_id"] not in done]
    out(f"{len(samples)} mau | da gan {len(samples) - len(todo)} | chua gan {len(todo)}")
    out(header)
    for i, sample in enumerate(todo, start=1):
        out(render(sample, len(samples) - len(todo) + i, len(samples)))
        answer = ask(sample)
        if answer is None:
            out("Da dung. Chay lai lenh de tiep tuc (mau da gan duoc giu).")
            return False
        append_csv(labels_path, fields, [_row(sample, **answer)])
    out("Da gan xong. Xem ket qua: --report")
    return True


def label_q2(samples: list[dict], labels_path: Path, input_fn=input, out=print) -> bool:
    """Luot 1 (MU): Q2 cho moi mau co motion_type. True = gan xong het, False = dung (q)."""
    eligible = [s for s in samples if s["motion_type"] in Q2_QUESTION]
    if len(eligible) < len(samples):
        out(f"Bo qua {len(samples) - len(eligible)} mau khong co motion_type (khong co cau hoi Q2).")

    def ask(sample):
        q2 = _ask(f"  Q2 {Q2_QUESTION[sample['motion_type']]} [y/n]: ", {"y", "n"}, input_fn, out)
        return None if q2 is None else {"q2_structure": q2}

    return _label_loop(eligible, labels_path, Q2_FIELDS, render_q2, ask,
                       "Q2 (MU): cau truc dung loai kien nghi? y / n.   q = dung", input_fn, out)


def label_q1(samples: list[dict], labels_path: Path, input_fn=input, out=print) -> bool:
    """Luot 2 (KHONG MU, chi mo ta): Q1 cho mau v5."""
    v5 = [s for s in samples if s["prompt_version"] == V5]

    def ask(sample):
        q1 = _ask("  Q1 [g/h/r/k]: ", set(Q1_LABELS), input_fn, out)
        return None if q1 is None else {"q1_reading": q1}

    return _label_loop(
        v5, labels_path, Q1_FIELDS, render_q1, ask,
        "Q1 (KHONG MU, chi mau v5, chi mo ta): cach hieu model viet so voi chuan — g = giong | h = hep hon | "
        "r = rong hon | k = khac han.   q = dung",
        input_fn, out,
    )


# ---------------- bao cao (chi --report) ----------------


def _versions(rows: list[dict]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for path in sorted({row["source_path"] for row in rows}):
        for r in load_jsonl(Path(path)):
            versions[f"{r['_source']}:{r['run_index']}"] = r.get("prompt_version") or "(khong ro)"
    return versions


def build_report(q2_rows: list[dict], q1_rows: list[dict], versions: dict[str, str]) -> dict:
    """
    {"q2": {(nhanh, loai): {"n", "yes"}} (loai gom "tat ca"),
     "q1": {loai: Counter(g/h/r/k)} — CHI mau v5 (loai gom "tat ca")}.
    """
    q2: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "yes": 0})
    for row in q2_rows:
        branch = versions.get(row["sample_id"], "(khong ro)")
        for key in ((branch, row["motion_type"] or "(khong ro)"), (branch, "tat ca")):
            q2[key]["n"] += 1
            q2[key]["yes"] += row["q2_structure"] == "y"
    q1: dict[str, Counter] = defaultdict(Counter)
    for row in q1_rows:
        if versions.get(row["sample_id"]) != V5:
            continue  # Q1 chi mo ta nhanh v5
        for key in (row["motion_type"] or "(khong ro)", "tat ca"):
            q1[key][row["q1_reading"]] += 1
    return {"q2": dict(q2), "q1": dict(q1)}


def _rate(k: int, n: int) -> str:
    return f"{k}/{n} ({k / n:.0%})" if n else "-"


def format_report(report: dict) -> str:
    order = {t: i for i, t in enumerate([*MOTION_TYPES, "(khong ro)", "tat ca"])}
    lines = ["Q2 (MU) — dung cau truc loai: nhanh x loai | n | Q2 = y"]
    if not report["q2"]:
        lines.append("  (chua co nhan Q2)")
    for branch, mtype in sorted(report["q2"], key=lambda k: (k[0], order.get(k[1], 99))):
        c = report["q2"][(branch, mtype)]
        lines.append(f"{branch} x {mtype} | {c['n']} | {_rate(c['yes'], c['n'])}")
    lines += ["", "Q1 (KHONG MU, chi v5, chi mo ta) — cach hieu model viet so voi chuan: loai | n | g / h / r / k"]
    if not report["q1"]:
        lines.append("  (chua co nhan Q1)")
    for mtype in sorted(report["q1"], key=lambda t: order.get(t, 99)):
        c = report["q1"][mtype]
        n = sum(c.values())
        lines.append(f"{V5} x {mtype} | {n} | {c['g']} / {c['h']} / {c['r']} / {c['k']} (giong {_rate(c['g'], n)})")
    return "\n".join(lines)


def report_from_csv(q2_path: Path, q1_path: Path) -> str:
    q2_rows, q1_rows = read_csv(q2_path), read_csv(q1_path)
    if not q2_rows and not q1_rows:
        return f"Chua co nhan nao trong {q2_path} / {q1_path}."
    return format_report(build_report(q2_rows, q1_rows, _versions(q2_rows + q1_rows)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Gan nhan cau truc case file (v5 vs v6): luot Q2 mu / luot Q1 v5")
    parser.add_argument("files", nargs="*", type=Path, help="JSONL batch (vd 1 file v5 + 1 file v6)")
    parser.add_argument("--q1", action="store_true", help="Luot 2: CHI Q1, CHI mau v5 (khong mu, chi mo ta)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--motions", type=Path, default=DEFAULT_MOTIONS, help="File motion co cach hieu chuan")
    parser.add_argument("--labels", type=Path, default=DEFAULT_Q2_LABELS, help="CSV nhan Q2 (luot 1)")
    parser.add_argument("--q1-labels", type=Path, default=DEFAULT_Q1_LABELS, help="CSV nhan Q1 (luot 2)")
    parser.add_argument("--report", action="store_true", help="Chi in ket qua tu cac file nhan da co")
    args = parser.parse_args()

    if args.report:
        print(report_from_csv(args.labels, args.q1_labels))
        return 0
    if not args.files:
        parser.error("Can it nhat 1 file JSONL (hoac --report)")
    records = [r for p in args.files for r in load_jsonl(p)]
    samples = shuffle(build_samples(records, load_canonical_readings(args.motions)), args.seed)
    if args.q1:
        label_q1(samples, args.q1_labels)
    else:
        label_q2(samples, args.labels)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
