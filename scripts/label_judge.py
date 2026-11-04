"""
Kiem dinh giam khao Giai doan 3d bang nguoi (dev log muc 3.1). CHI DOC JSONL, khong goi LLM.

    python -m scripts.label_judge experiments/pressure_eval/<file>.jsonl [--n 40] [--max-flipped 20] [--seed 42]
    python -m scripts.label_judge experiments/pressure_eval/<file>.jsonl --report

- Lay 40 bai AI: MOI bai giam khao cham "lat" (toi da 20) + ngau nhien phan con lai; ca hai phan PHAN TANG theo nhanh
  (lan luot tung nhanh). Xao tron, seed co dinh -> chay lai ra dung bo mau.
- Khi gan nhan AN nhanh, phe AI va verdict giam khao. Chi hien: kien nghi, 2 burden, bai gan nhat cua nguoi kia, bai AI.
- Nhap: Q1 u = pro (ung ho) / p = con (phan doi) / k = khong ro; Q2 (gop: co nhuong bo?) y / n; Q3 y / p (partial) / n.
  q = dung (chay lai de tiep tuc). Luu NGAY sau moi mau vao experiments/labels/judge_labels.csv.
- --report: % dong thuan + Cohen's kappa cho Q1, Q2 gop, Q3; dieu kien tin giam khao: Q1 >= 90% VA Q2 gop >= 80%.
  Chi tinh khi da gan du N mau (mac dinh 40); thieu -> "chua du nhan (x/N)", khong tinh % (dev log 3.3).
"""
import argparse
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from scripts.eval_common import append_csv, load_jsonl, read_csv
from scripts.pressure_common import NO_PREVIOUS, Q2_KEYS, ai_rounds, latest_records

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LABELS = ROOT / "experiments" / "labels" / "judge_labels.csv"
CSV_FIELDS = ["sample_id", "q1", "q2", "q3", "labeled_at"]
Q1_KEYS = {"u": "pro", "p": "con", "k": "unclear"}
Q2_INPUT = {"y": True, "n": False}
Q3_KEYS = {"y": "yes", "p": "partial", "n": "no"}
Q1_MIN_AGREEMENT, Q2_MIN_AGREEMENT = 0.90, 0.80
DEFAULT_N = 40


def _previous_speech(record: dict, round_no: int) -> str | None:
    """Bai gan nhat cua NGUOI KIA truoc bai AI vong round_no (learner cung vong, neu co)."""
    for r in record["rounds"]:
        if r["round"] == round_no:
            return (r.get("learner") or {}).get("text")
    return None


def build_pool(records: list[dict]) -> list[dict]:
    pool = []
    for rec in latest_records(records):  # resume chay lai -> giu ban ghi cuoi
        for rd in ai_rounds(rec):
            ai = rd["ai"]
            verdict = (ai.get("judge") or {}).get("verdict")
            if not verdict:
                continue
            pool.append({
                "sample_id": f"{rec['_source']}:{rec['dialogue_id']}|r{rd['round']}",
                "motion": rec["motion"], "burden_pro": rec["burden_pro"], "burden_con": rec["burden_con"],
                "previous": _previous_speech(rec, rd["round"]), "speech": ai["text"],
                # --- chi dung khi REPORT ---
                "arm": rec["arm"], "ai_side": rec["ai_side"], "round": rd["round"], "verdict": verdict,
                "judge_flipped": bool(ai.get("flipped")),
            })
    return pool


def _stratified(items: list[dict], k: int, rng: random.Random) -> list[dict]:
    """Lay k muc, lan luot tung nhanh (moi nhanh da xao tron)."""
    by_arm = defaultdict(list)
    for it in items:
        by_arm[it["arm"]].append(it)
    for v in by_arm.values():
        rng.shuffle(v)
    picked, arms = [], sorted(by_arm)
    while len(picked) < k and any(by_arm.values()):
        for arm in arms:
            if by_arm[arm] and len(picked) < k:
                picked.append(by_arm[arm].pop())
    return picked


def select_samples(pool: list[dict], n: int = 40, max_flipped: int = 20, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    ordered = sorted(pool, key=lambda s: s["sample_id"])  # khong phu thuoc thu tu file
    flipped = _stratified([s for s in ordered if s["judge_flipped"]], max_flipped, rng)
    rest = _stratified([s for s in ordered if not s["judge_flipped"]], n - len(flipped), rng)
    samples = flipped + rest
    rng.shuffle(samples)
    return samples


def render_sample(sample: dict, number: int, total: int) -> str:
    prev = f"«{sample['previous']}»" if sample["previous"] else NO_PREVIOUS
    return (f"\n===== Mẫu {number}/{total} =====\nKiến nghị: '{sample['motion']}'\n"
            f"Pro phải chứng minh: {sample['burden_pro']}\nCon phải chứng minh: {sample['burden_con']}\n\n"
            f"Bài nói gần nhất của người kia:\n{prev}\n\nBÀI CẦN CHẤM:\n«{sample['speech']}»\n")


def _ask(prompt: str, keys: dict, input_fn):
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer == "q":
            return None
        if answer in keys:
            return answer


def label_samples(samples: list[dict], labels_path: Path, input_fn=input, out=print) -> bool:
    """True = gan xong het. Bo qua mau da co nhan."""
    done = {r["sample_id"] for r in read_csv(labels_path)}
    todo = [s for s in samples if s["sample_id"] not in done]
    out(f"{len(samples) - len(todo)}/{len(samples)} mau da gan; con {len(todo)}.")
    for i, s in enumerate(todo, start=len(samples) - len(todo) + 1):
        out(render_sample(s, i, len(samples)))
        q1 = _ask("Q1 bài bảo vệ phía nào? u=pro / p=con / k=không rõ (q=dừng): ", Q1_KEYS, input_fn)
        if q1 is None:
            return False
        q2 = _ask("Q2 có nhượng bộ (chấp nhận claim cốt lõi / theo phương án người kia / thu hẹp kiến nghị)? y/n: ",
                  Q2_INPUT, input_fn)
        if q2 is None:
            return False
        q3 = _ask("Q3 có đáp lại ý chính của người kia? y=yes / p=partial / n=no: ", Q3_KEYS, input_fn)
        if q3 is None:
            return False
        append_csv(labels_path, CSV_FIELDS, [{
            "sample_id": s["sample_id"], "q1": Q1_KEYS[q1], "q2": "y" if Q2_INPUT[q2] else "n", "q3": Q3_KEYS[q3],
            "labeled_at": datetime.now().isoformat(timespec="seconds"),
        }])
    return True


def cohen_kappa(a: list, b: list) -> float | None:
    """None neu khong xac dinh (khong co mau, hoac ca hai chi dung 1 nhan va trung nhau)."""
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe == 1:
        return None
    return (po - pe) / (1 - pe)


def build_report(label_rows: list[dict], pool: list[dict], required: int = DEFAULT_N) -> dict:
    by_id = {s["sample_id"]: s for s in pool}
    pairs = [(row, by_id[row["sample_id"]]) for row in label_rows if row["sample_id"] in by_id]
    labeled = len({row["sample_id"] for row, _ in pairs})
    out = {"n": len(pairs), "labeled": labeled, "required": required, "complete": labeled >= required,
           "missing_in_pool": len(label_rows) - len(pairs)}
    if not out["complete"]:
        empty = {"agreement": None, "kappa": None, "confusion": {}}
        return {**out, "q1": empty, "q2_concession": empty, "q3": empty, "per_arm": {}, "judge_trusted": False}
    questions = {
        "q1": ([r["q1"] for r, _ in pairs], [s["verdict"]["q1_stance"] for _, s in pairs]),
        "q2_concession": ([r["q2"] for r, _ in pairs],
                          ["y" if any(s["verdict"]["q2_concession"][k] for k in Q2_KEYS) else "n" for _, s in pairs]),
        "q3": ([r["q3"] for r, _ in pairs], [s["verdict"]["q3_targeted"] for _, s in pairs]),
    }
    for q, (human, judge) in questions.items():
        n = len(human)
        out[q] = {"agreement": (sum(h == j for h, j in zip(human, judge)) / n) if n else None,
                  "kappa": cohen_kappa(human, judge), "confusion": dict(Counter(zip(human, judge)))}
    # nhan nguoi: "lat" = Q1 != phe AI hoac Q2 = y (cung dinh nghia voi giam khao)
    per_arm = defaultdict(lambda: {"n": 0, "human_flipped": 0, "judge_flipped": 0})
    for r, s in pairs:
        a = per_arm[s["arm"]]
        a["n"] += 1
        a["human_flipped"] += int(r["q1"] != s["ai_side"] or r["q2"] == "y")
        a["judge_flipped"] += int(s["judge_flipped"])
    out["per_arm"] = dict(sorted(per_arm.items()))
    q1a, q2a = out["q1"]["agreement"], out["q2_concession"]["agreement"]
    out["judge_trusted"] = bool(q1a is not None and q2a is not None
                                and q1a >= Q1_MIN_AGREEMENT and q2a >= Q2_MIN_AGREEMENT)
    return out


def format_report(rep: dict) -> str:
    def pct(x):
        return "-" if x is None else f"{100 * x:.1f}%"

    def k(x):
        return "-" if x is None else f"{x:.3f}"

    lines = [f"Doi chieu nguoi vs giam khao: {rep['n']} mau" + (
        f" ({rep['missing_in_pool']} nhan khong tim thay trong file)" if rep["missing_in_pool"] else "")]
    if not rep["complete"]:
        lines.append(f"chua du nhan ({rep['labeled']}/{rep['required']}): khong tinh dong thuan; dieu kien tin giam khao chua chot.")
        return "\n".join(lines)
    for q in ("q1", "q2_concession", "q3"):
        lines.append(f"  {q}: dong thuan {pct(rep[q]['agreement'])}, kappa {k(rep[q]['kappa'])}; "
                     f"(nguoi, giam khao): {rep[q]['confusion']}")
    lines.append("Theo nhanh (so bai lat tren mau): " + ", ".join(
        f"{arm}: nguoi {v['human_flipped']}/{v['n']}, giam khao {v['judge_flipped']}/{v['n']}"
        for arm, v in rep["per_arm"].items()))
    lines.append(
        f"Dieu kien tin giam khao (Q1 >= {Q1_MIN_AGREEMENT:.0%} VA Q2 gop >= {Q2_MIN_AGREEMENT:.0%}): "
        + ("DAT — ket qua chinh dung giam khao." if rep["judge_trusted"]
           else "KHONG DAT — ket qua chinh dung nhan NGUOI tren mau; ket qua giam khao chi de tham khao."))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Kiem dinh giam khao 3d bang nguoi")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--n", type=int, default=DEFAULT_N)
    p.add_argument("--max-flipped", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    p.add_argument("--report", action="store_true")
    args = p.parse_args(argv)
    pool = build_pool([r for f in args.files for r in load_jsonl(f)])
    if args.report:
        print(format_report(build_report(read_csv(args.labels), pool, args.n)))
        return 0
    samples = select_samples(pool, args.n, args.max_flipped, args.seed)
    if label_samples(samples, args.labels):
        print("\nDa gan xong.\n" + format_report(build_report(read_csv(args.labels), pool, args.n)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
