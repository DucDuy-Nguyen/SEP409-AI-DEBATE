"""
Kiem giam khao pairwise bang nguoi (Giai doan 3e, dev log muc 3.3). CHI DOC JSONL, khong goi LLM.

    python -m scripts.label_pairwise experiments/difficulty_eval/<file>_pairwise.jsonl [--per-type 8] [--seed 42]
    python -m scripts.label_pairwise experiments/difficulty_eval/<file>_pairwise.jsonl --report

- 24 cap phan tang (8 moi loai cap cap), xao tron theo seed, AN cap va thu tu that. Hien bai learner va hai bai AI.
- Nguoi chon: 1 / 2 (bai kho phan bac hon) / h (hoa). q = dung (chay lai de tiep tuc). Luu NGAY sau moi mau.
- --report: % dong thuan voi giam khao (bo cap nguoi chon hoa; giam khao hoa ma nguoi khong hoa la KHONG dong thuan), Cohen's
  kappa. Dieu kien tin giam khao: dong thuan >= 75%. Khong dat: H1 "chua du bang chung" (dev log 3.3, sua dang ky 4); nhan nguoi
  va giam khao chi de tham khao. Chi tinh khi da gan du N cap (mac dinh 24); thieu -> "chua du nhan (x/N)", khong tinh %, H1
  "chua chot".
"""
import argparse
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from scripts.eval_common import append_csv, load_jsonl, read_csv
from scripts.judge_pairwise import JUDGE_MISSING, PAIR_TYPES, TIE, TIE_INCONSISTENT, latest_pairs, win_stats
from scripts.label_judge import cohen_kappa

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LABELS = ROOT / "experiments" / "labels" / "pairwise_labels.csv"
CSV_FIELDS = ["pair_id", "shown_first", "choice", "human_winner", "labeled_at"]
CHOICE_KEYS = {"1", "2", "h"}
MIN_AGREEMENT = 0.75
DEFAULT_PER_TYPE = 8
DEFAULT_REQUIRED = DEFAULT_PER_TYPE * len(PAIR_TYPES)


def build_pool(pairs: list[dict]) -> list[dict]:
    """Cac cap giam khao da cham xong (ke ca hoa)."""
    return [p for p in latest_pairs(pairs) if p["result"] != JUDGE_MISSING]


def select_samples(pool: list[dict], per_type: int = DEFAULT_PER_TYPE, seed: int = 42) -> list[dict]:
    """Phan tang theo loai cap; thu tu hien thi cua 2 bai cung theo seed. Khong phu thuoc thu tu file."""
    rng = random.Random(seed)
    ordered = sorted(pool, key=lambda p: p["pair_id"])
    samples = []
    for high, low in PAIR_TYPES:
        group = [p for p in ordered if p["pair_type"] == f"{high}-{low}"]
        rng.shuffle(group)
        samples += [{**p, "shown_first": rng.choice((p["high"], p["low"]))} for p in group[:per_type]]
    rng.shuffle(samples)
    return samples


def _other(sample: dict, level: str) -> str:
    return sample["low"] if level == sample["high"] else sample["high"]


def render_sample(sample: dict, number: int, total: int) -> str:
    """CHI bai learner + 2 bai an nhan. KHONG pair_id, cap, phe cua AI, verdict."""
    first = sample["shown_first"]
    return (f"\n===== Mẫu {number}/{total} =====\nKiến nghị: '{sample['motion']}'\n"
            f"Pro phải chứng minh: {sample['burden_pro']}\nCon phải chứng minh: {sample['burden_con']}\n\n"
            f"Bài nói gần nhất của người học:\n«{sample['learner_text']}»\n\n"
            f"BÀI 1:\n«{sample['texts'][first]}»\n\nBÀI 2:\n«{sample['texts'][_other(sample, first)]}»\n")


def label_samples(samples: list[dict], labels_path: Path, input_fn=input, out=print) -> bool:
    """True = gan xong het. Bo qua mau da co nhan."""
    done = {r["pair_id"] for r in read_csv(labels_path)}
    todo = [s for s in samples if s["pair_id"] not in done]
    out(f"{len(samples) - len(todo)}/{len(samples)} mau da gan; con {len(todo)}.")
    for i, s in enumerate(todo, start=len(samples) - len(todo) + 1):
        out(render_sample(s, i, len(samples)))
        while True:
            answer = input_fn("Bài nào khó phản bác hơn cho người học? 1 / 2 / h=hoà (q=dừng): ").strip().lower()
            if answer == "q":
                return False
            if answer in CHOICE_KEYS:
                break
        first = s["shown_first"]
        winner = {"1": first, "2": _other(s, first), "h": TIE}[answer]
        append_csv(labels_path, CSV_FIELDS, [{
            "pair_id": s["pair_id"], "shown_first": first, "choice": answer, "human_winner": winner,
            "labeled_at": datetime.now().isoformat(timespec="seconds"),
        }])
    return True


def _judge_label(result: str) -> str:
    return TIE if result == TIE_INCONSISTENT else result


def build_report(label_rows: list[dict], pool: list[dict], n_boot: int = 10_000, seed: int = 20261104,
                 required: int = DEFAULT_REQUIRED) -> dict:
    by_id = {p["pair_id"]: p for p in pool}
    rows = [(r, by_id[r["pair_id"]]) for r in label_rows if r["pair_id"] in by_id]
    labeled = len({r["pair_id"] for r, _ in rows})
    progress = {"labeled": labeled, "required": required, "complete": labeled >= required}
    if not progress["complete"]:
        return {**progress, "n": len(rows), "missing_in_pool": len(label_rows) - len(rows), "human_ties": None, "n_compared": 0,
                "agreement": None, "kappa": None, "confusion": {}, "judge_trusted": False, "human_h1": {}}
    decided = [(r, p) for r, p in rows if r["human_winner"] != TIE]
    # Nhan theo vai tro (cap cao / cap thap / hoa) de kappa gop duoc 3 loai cap
    def role(level: str, p: dict) -> str:
        return "high" if level == p["high"] else "low" if level == p["low"] else TIE

    human = [role(r["human_winner"], p) for r, p in decided]
    judge = [role(_judge_label(p["result"]), p) for _, p in decided]
    agreement = sum(h == j for h, j in zip(human, judge)) / len(decided) if decided else None
    human_h1 = {}
    for high, low in PAIR_TYPES:
        results = [r["human_winner"] for r, p in rows if p["pair_type"] == f"{high}-{low}"]
        human_h1[f"{high}-{low}"] = win_stats(results, high, low, n_boot, seed)
    return {
        **progress, "n": len(rows), "missing_in_pool": len(label_rows) - len(rows), "human_ties": len(rows) - len(decided),
        "n_compared": len(decided), "agreement": agreement, "kappa": cohen_kappa(human, judge),
        "confusion": {f"{h}/{j}": n for (h, j), n in sorted(Counter(zip(human, judge)).items())},
        "judge_trusted": bool(agreement is not None and agreement >= MIN_AGREEMENT),
        "human_h1": human_h1,
    }


def format_report(rep: dict) -> str:
    def pct(x):
        return "-" if x is None else f"{100 * x:.1f}%"

    if not rep["complete"]:
        return (f"Doi chieu nguoi vs giam khao pairwise: chua du nhan ({rep['labeled']}/{rep['required']}), khong tinh dong thuan; "
                "H1 chua chot." + (f" ({rep['missing_in_pool']} nhan khong tim thay)" if rep["missing_in_pool"] else ""))
    lines = [
        f"Doi chieu nguoi vs giam khao pairwise: {rep['n']} cap, nguoi chon hoa {rep['human_ties']}, so sanh tren "
        f"{rep['n_compared']}" + (f" ({rep['missing_in_pool']} nhan khong tim thay)" if rep["missing_in_pool"] else ""),
        f"  dong thuan {pct(rep['agreement'])}, kappa {'-' if rep['kappa'] is None else format(rep['kappa'], '.3f')}; "
        f"(nguoi/giam khao): {rep['confusion']}",
        f"Dieu kien tin giam khao (dong thuan >= {MIN_AGREEMENT:.0%}): "
        + ("DAT — H1 dung giam khao." if rep["judge_trusted"]
           else "KHONG DAT — H1 chua du bang chung, khong ket luan; nhan nguoi va giam khao chi de tham khao."),
        "Nhan nguoi theo loai cap, tham khao (thang/thua/hoa, ti le thang, KTC 95%):",
    ]
    for k, s in rep["human_h1"].items():
        lines.append(f"  {k}: {s['wins']}/{s['losses']}/{s['ties']}, {pct(s['win_rate'])} [{pct(s['ci_low'])}; {pct(s['ci_high'])}]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Kiem giam khao pairwise bang nguoi")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--per-type", type=int, default=DEFAULT_PER_TYPE)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    p.add_argument("--report", action="store_true")
    args = p.parse_args(argv)
    pool = build_pool([r for f in args.files for r in load_jsonl(f)])
    required = args.per_type * len(PAIR_TYPES)
    if args.report:
        print(format_report(build_report(read_csv(args.labels), pool, required=required)))
        return 0
    samples = select_samples(pool, args.per_type, args.seed)
    if label_samples(samples, args.labels):
        print("\nDa gan xong.\n" + format_report(build_report(read_csv(args.labels), pool, required=required)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
