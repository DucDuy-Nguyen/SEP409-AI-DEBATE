"""
Gan nhan phe MU cho luan diem trong case file — de do do chinh xac cua Stance Reviewer.

- Lay mau tu cac LAN THU case_plan da duoc reviewer danh gia (khong chi case file cuoi: ca lat phe nam o lan thu
  bi reject). Chi DOC JSONL, khong goi LLM.
- Khi gan nhan KHONG hien ai_side, reviewer_verdict, reviewer_detail (tranh bi dan dat). Chi hien: kien nghi,
  tung luan diem (id + claim + reasoning rut gon), weighing.
- Nhap cho tung muc: u = ung ho kien nghi, p = phan doi kien nghi, k = khong ro (q = dung, chay lai de tiep tuc).
- Luu NGAY sau moi mau vao experiments/labels/stance_labels.csv; chay lai se bo qua mau da gan.
- Doi chieu (nguoi vs reviewer, nguoi vs phe mong doi) CHI hien khi gan xong het hoac voi --report.

    python -m scripts.label_stance experiments/case_plan/<v3>.jsonl experiments/case_plan/<v4>.jsonl --n 5 --seed 42 \\
        --include "experiments/case_plan/invalid/20260926-171443_case_plan_v3.jsonl:M08:con:easy"
    python -m scripts.label_stance --report
"""
import argparse
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from scripts.eval_common import append_csv, load_jsonl, parse_case_json, parse_source_spec, read_csv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LABELS = ROOT / "experiments" / "labels" / "stance_labels.csv"
CSV_FIELDS = ["sample_id", "source_path", "run_index", "attempt", "motion_id", "item_id", "human_label", "labeled_at"]

POSITION_TO_LABEL = {"ung_ho_kien_nghi": "u", "phan_doi_kien_nghi": "p", "khong_ro": "k"}
LABEL_NAMES = {"u": "ung ho", "p": "phan doi", "k": "khong ro"}
EXPECTED_LABEL = {"pro": "u", "con": "p"}
OPPOSITE = {"u": "p", "p": "u"}
REASONING_PREVIEW = 220
SUMMARY_ID = "weighing"


# ---------------- lay mau ----------------


def _sample_from_attempt(record: dict, attempt: dict) -> dict | None:
    detail = attempt.get("reviewer_detail") or {}
    positions = detail.get("positions")
    case = parse_case_json(attempt.get("raw_output"))
    if not positions or case is None or not isinstance(case.get("arguments"), list):
        return None  # reviewer loi (khong co position) hoac output khong doc duoc
    return {
        "sample_id": f"{record['_source']}:{record['run_index']}:{attempt['attempt']}",
        "source_path": record["_source_path"],
        "source": record["_source"],
        "run_index": record["run_index"],
        "attempt": attempt["attempt"],
        "motion_id": record["motion_id"],
        "motion": record["motion"],
        # --- chi dung khi REPORT, khong bao gio hien khi gan nhan ---
        "ai_side": record["ai_side"],
        "difficulty": record["difficulty"],
        "reviewer_verdict": attempt.get("reviewer_verdict"),
        "reviewer": {p["id"]: (POSITION_TO_LABEL.get(p["position"], "k"), p.get("reason", "")) for p in positions},
        # --- hien khi gan nhan ---
        "arguments": [
            {"id": a.get("id", f"A{i + 1}"), "claim": a.get("claim", ""), "reasoning": a.get("reasoning", "")}
            for i, a in enumerate(case["arguments"])
        ],
        "weighing": case.get("weighing", ""),
    }


def build_pool(records: list[dict]) -> dict[str, dict]:
    """Moi lan thu case_plan da duoc reviewer danh gia (co position tung muc) -> 1 mau."""
    pool = {}
    for r in records:
        for a in r["attempts"]:
            if a["purpose"] == "case_plan" and a.get("reviewer_verdict"):
                sample = _sample_from_attempt(r, a)
                if sample is not None:
                    pool[sample["sample_id"]] = sample
    return pool


def resolve_include(spec: str) -> list[dict]:
    """--include '<file>:<motion_id>:<ai_side>:<difficulty>' -> (cac) lan thu reviewer bao side_flip cua lan chay do."""
    path, motion_id, ai_side, difficulty = parse_source_spec(spec)
    records = load_jsonl(Path(path))
    matched = [r for r in records if (r["motion_id"], r["ai_side"], r["difficulty"]) == (motion_id, ai_side, difficulty)]
    if not matched:
        raise ValueError(f"Khong thay lan chay {motion_id}/{ai_side}/{difficulty} trong {path}")
    samples = [
        s for r in matched for a in r["attempts"]
        if a["purpose"] == "case_plan" and a.get("reviewer_verdict") == "side_flip"
        and (s := _sample_from_attempt(r, a)) is not None
    ]
    if not samples:
        raise ValueError(f"Lan chay {motion_id}/{ai_side}/{difficulty} trong {path} khong co lan thu nao reviewer bao side_flip")
    return samples


def select_samples(pool: dict[str, dict], n: int, seed: int, includes: list[dict]) -> list[dict]:
    """includes (luon co) + n mau ngau nhien tu phan con lai; tron thu tu theo seed de nguoi gan khong biet mau nao la 'dac biet'."""
    rng = random.Random(seed)
    include_ids = {s["sample_id"] for s in includes}
    rest = sorted(sid for sid in pool if sid not in include_ids)
    chosen = [pool[sid] for sid in rng.sample(rest, min(n, len(rest)))]
    merged = list({s["sample_id"]: s for s in [*includes, *chosen]}.values())
    rng.shuffle(merged)
    return merged


# ---------------- gan nhan (MU) ----------------


def _short(text: str, limit: int = REASONING_PREVIEW) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_sample(sample: dict, number: int, total: int) -> str:
    """CHI motion + luan diem + weighing. KHONG ai_side / do kho / reviewer."""
    lines = [f"\n===== Mau {number}/{total} =====", f"Kien nghi: {sample['motion']}", ""]
    for a in sample["arguments"]:
        lines.append(f"[{a['id']}] {a['claim']}")
        if a["reasoning"]:
            lines.append(f"      ly do: {_short(a['reasoning'])}")
    lines += ["", f"[{SUMMARY_ID}] {sample['weighing']}", ""]
    return "\n".join(lines)


def labeled_ids(labels_path: Path) -> set[str]:
    return {row["sample_id"] for row in read_csv(labels_path)}


def label_samples(samples: list[dict], labels_path: Path, input_fn=input, out=print) -> bool:
    """Gan nhan cac mau chua gan. Tra True neu gan xong het, False neu nguoi dung dung (q)."""
    done = labeled_ids(labels_path)
    todo = [s for s in samples if s["sample_id"] not in done]
    out(f"{len(samples)} mau | da gan {len(samples) - len(todo)} | chua gan {len(todo)}")
    out("Voi moi muc, noi dung do BAO VE phia nao cua kien nghi?  u = ung ho | p = phan doi | k = khong ro | q = dung")
    for i, sample in enumerate(todo, start=1):
        out(render_sample(sample, len(samples) - len(todo) + i, len(samples)))
        labels: dict[str, str] = {}
        for item_id in [a["id"] for a in sample["arguments"]] + [SUMMARY_ID]:
            while True:
                answer = input_fn(f"  {item_id} [u/p/k]: ").strip().lower()
                if answer == "q":
                    out("Da dung. Chay lai lenh de tiep tuc (mau da gan duoc giu).")
                    return False
                if answer in LABEL_NAMES:
                    labels[item_id] = answer
                    break
                out("  Chi nhan u / p / k (hoac q de dung).")
        now = datetime.now().isoformat(timespec="seconds")
        append_csv(
            labels_path,
            CSV_FIELDS,
            [
                {"sample_id": sample["sample_id"], "source_path": sample["source_path"], "run_index": sample["run_index"],
                 "attempt": sample["attempt"], "motion_id": sample["motion_id"], "item_id": item_id,
                 "human_label": label, "labeled_at": now}
                for item_id, label in labels.items()
            ],
        )
    return True


# ---------------- doi chieu (chi sau khi gan xong / --report) ----------------


def _verdict(labels: dict[str, str], ai_side: str) -> str:
    """Cung logic stance_reviewer.judge, ap cho nhan cua NGUOI."""
    if any(v == OPPOSITE[EXPECTED_LABEL[ai_side]] for v in labels.values()):
        return "side_flip"
    if any(v == "k" for v in labels.values()):
        return "unclear"
    return "pass"


def build_report(label_rows: list[dict], samples: dict[str, dict]) -> dict:
    items, missing = [], set()
    for row in label_rows:
        sample = samples.get(row["sample_id"])
        if sample is None:
            missing.add(row["sample_id"])
            continue
        reviewer_label, reason = sample["reviewer"].get(row["item_id"], (None, ""))
        text = next((a["claim"] for a in sample["arguments"] if a["id"] == row["item_id"]), sample["weighing"])
        items.append(
            {"sample_id": row["sample_id"], "item_id": row["item_id"], "human": row["human_label"],
             "reviewer": reviewer_label, "reason": reason, "expected": EXPECTED_LABEL[sample["ai_side"]],
             "ai_side": sample["ai_side"], "motion": sample["motion"], "text": text}
        )
    compared = [it for it in items if it["reviewer"] is not None]
    by_sample: dict[str, dict[str, str]] = {}
    for it in items:
        by_sample.setdefault(it["sample_id"], {})[it["item_id"]] = it["human"]
    verdict_pairs = Counter(
        (_verdict(labels, samples[sid]["ai_side"]), samples[sid]["reviewer_verdict"]) for sid, labels in by_sample.items()
    )
    return {
        "items": len(items),
        "samples": len(by_sample),
        "compared": len(compared),
        "agree": sum(1 for it in compared if it["human"] == it["reviewer"]),
        "confusion": Counter((it["human"], it["reviewer"]) for it in compared),
        "human_flips": [it for it in items if it["human"] == OPPOSITE.get(it["expected"])],
        "disagreements": [it for it in compared if it["human"] != it["reviewer"]],
        "verdict_pairs": verdict_pairs,
        "missing_samples": sorted(missing),
    }


def format_report(report: dict) -> str:
    lines = ["\n===== DOI CHIEU =====", f"{report['samples']} mau, {report['items']} muc da gan nhan."]
    if report["missing_samples"]:
        lines.append(f"CANH BAO: {len(report['missing_samples'])} mau khong tim thay trong file nguon: {report['missing_samples']}")
    compared = report["compared"]
    rate = f"{report['agree']}/{compared} ({report['agree'] / compared:.0%})" if compared else "0/0"
    lines += ["", f"Nguoi vs reviewer — dong thuan theo tung muc: {rate}", "", "Bang nham lan (hang = nguoi, cot = reviewer):"]
    header = "          " + "".join(f"{LABEL_NAMES[c]:>10}" for c in "upk")
    lines.append(header)
    for h in "upk":
        lines.append(f"{LABEL_NAMES[h]:<10}" + "".join(f"{report['confusion'][(h, r)]:>10}" for r in "upk"))

    lines += ["", "Ket luan theo mau (nguoi -> reviewer):"]
    for (human_v, reviewer_v), count in sorted(report["verdict_pairs"].items()):
        lines.append(f"  nguoi={human_v:<9} reviewer={reviewer_v:<9} : {count}")

    lines += ["", f"Nguoi vs phe mong doi — muc NGUOI danh la LAT PHE: {len(report['human_flips'])}"]
    for it in report["human_flips"]:
        lines.append(f"  - {it['sample_id']} [{it['item_id']}] (AI phe {it['ai_side']}): {it['text']}")

    lines += ["", f"Nguoi va reviewer BAT DONG: {len(report['disagreements'])}"]
    for it in report["disagreements"]:
        lines.append(
            f"  - {it['sample_id']} [{it['item_id']}] nguoi={LABEL_NAMES[it['human']]} reviewer={LABEL_NAMES[it['reviewer']]}"
            f"\n      noi dung: {it['text']}\n      ly do reviewer: {it['reason']}"
        )
    return "\n".join(lines)


def report_from_csv(labels_path: Path) -> str:
    rows = read_csv(labels_path)
    if not rows:
        return f"Chua co nhan nao trong {labels_path}."
    samples: dict[str, dict] = {}
    for path in sorted({row["source_path"] for row in rows}):
        samples.update(build_pool(load_jsonl(Path(path))))
    return format_report(build_report(rows, samples))


def main() -> int:
    parser = argparse.ArgumentParser(description="Gan nhan phe MU cho luan diem case file")
    parser.add_argument("files", nargs="*", type=Path, help="JSONL batch de lay mau")
    parser.add_argument("--n", type=int, default=5, help="So mau ngau nhien (ngoai --include)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--include", action="append", default=[], metavar="FILE:MOTION_ID:AI_SIDE:DIFFICULTY",
                        help="Them lan thu reviewer bao side_flip cua lan chay nay (lap lai duoc)")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--report", action="store_true", help="Chi in doi chieu tu file nhan da co")
    args = parser.parse_args()

    if args.report:
        print(report_from_csv(args.labels))
        return 0
    if not args.files and not args.include:
        parser.error("Can it nhat 1 file JSONL hoac --include")

    pool = build_pool([r for p in args.files for r in load_jsonl(p)])
    includes = [s for spec in args.include for s in resolve_include(spec)]
    samples = select_samples(pool, args.n, args.seed, includes)
    if label_samples(samples, args.labels):
        print(report_from_csv(args.labels))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
