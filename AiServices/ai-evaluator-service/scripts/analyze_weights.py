"""
Phan tich OFFLINE (khong goi API) 5 phuong an trong so diem tong A-E DINH SAN (docs/AI_DEVELOPMENT_LOG.md muc 3.13).
Diem tong = 2 x Sum(w_i x diem tieu chi i), thang 0-10. Thu tu: Logic, Evidence, Relevance, Structure, Persuasiveness.
Khong hoi quy tu do: trong so co dinh.

Moi phuong an bao cao:
 (1) r voi diem nguoi (overall_quality_score_10) tren 50 bai: r thuong va r leave-one-out (bo lan luot tung bai, TB/min/max).
     Diem AI cua bai = TB 4 luot (t0.2 x2 + t0 x2); phuong an D chan 5.0 TUNG LUOT truoc khi lay TB.
 (2) SD gop mot lan cham = sqrt(TB phuong sai trong bai, ddof=1, tren 4 luot).
 (3) Khoang cach: TB diem tong 16 luot hq (8 bai x 2 lan) tru diem tong ctrl02 (1 luot).
Quy tac chon (chot truoc, muc 3.13): phuong an DON GIAN NHAT co r_LOO >= r_LOO(A) - 0.03 VA khoang cach >= 1.0; hoa thi SD thap nhat.
Thu tu don gian co dinh: A < B < C = E < D.
Chay: python scripts/analyze_weights.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from analyze_replicates import CRITERIA, SAMPLE_PATH, VI_CSV_PATH, load_matrix  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
HQ_RUN1 = DATA_DIR / "high_quality_probe_results.jsonl"
HQ_RUN2 = DATA_DIR / "high_quality_probe_results_run2.jsonl"
REPORT_PATH = Path(__file__).parent.parent / "weights_report.txt"

# w theo thu tu CRITERIA = Logic, Evidence, Relevance, Structure, Persuasiveness
OPTIONS = {
    "A": ([0.20, 0.20, 0.20, 0.20, 0.20], None),
    "B": ([0.25, 0.25, 0.25, 0.25, 0.00], None),
    "C": ([0.30, 0.30, 0.10, 0.30, 0.00], None),
    "D": ([0.25, 0.25, 0.25, 0.25, 0.00], {"gate_relevance_le": 2, "cap": 5.0}),
    "E": ([0.30, 0.30, 0.20, 0.20, 0.00], None),
}
SIMPLICITY_GROUPS = [["A"], ["B"], ["C", "E"], ["D"]]  # A < B < C = E < D
R_DROP_TOLERANCE = 0.03
MIN_GAP = 1.0


def option_score(crit: dict[str, np.ndarray | float], weights: list[float], gate) :
    """crit: {ten tieu chi: gia tri hoac mang}. Tra ve diem tong 0-10 theo trong so (va cong chan neu co)."""
    score = 2.0 * sum(w * crit[c] for w, c in zip(weights, CRITERIA))
    if gate:
        score = np.where(np.asarray(crit["Relevance"]) <= gate["gate_relevance_le"], np.minimum(score, gate["cap"]), score)
    return score


def pearson(a, b) -> float:
    return float(np.corrcoef(a, b)[0, 1])


def loo_r(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    rs = [pearson(np.delete(a, i), np.delete(b, i)) for i in range(len(a))]
    return float(np.mean(rs)), float(np.min(rs)), float(np.max(rs))


def load_ok(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["id"]: r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()) if r["status"] == "ok"}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sample_ids = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    m = load_matrix(sample_ids)
    ids = list(m["ids"])
    human = pd.read_csv(VI_CSV_PATH).assign(id=lambda d: d["id"].astype(str)).set_index("id").loc[ids, "overall_quality_score_10"].to_numpy(float)
    crit = {c: m[c] for c in CRITERIA}  # (n, 4)
    r1, r2 = load_ok(HQ_RUN1), load_ok(HQ_RUN2)
    hq_recs = [r for r in list(r1.values()) + list(r2.values()) if not r["id"].lower().startswith("ctrl")]
    ctrl02 = r1.get("ctrl02")
    out: list[str] = []
    p = out.append

    p(f"Offline, khong goi API. {len(ids)} bai x 4 luot VI cho r/SD; {len(hq_recs)} luot hq + ctrl02 ({'co' if ctrl02 else 'THIEU'}) cho khoang cach.")
    # kiem tra A trung overall da luu
    a_check = option_score(crit, OPTIONS["A"][0], None)
    p(f"Kiem tra cong thuc: max |A - overall da luu| = {np.max(np.abs(a_check - m['overall'])):.4f} (phai ~0)")
    p("")
    p(f"{'PA':<3}{'Logic':>6}{'Evid':>6}{'Relev':>6}{'Struc':>6}{'Persu':>6}{'cong':>9}{'r thuong':>10}{'r LOO TB [min, max]':>26}{'d r vs A':>10}{'SD gop':>8}{'khoang cach':>12}")
    stats = {}
    for name, (w, gate) in OPTIONS.items():
        runs = option_score(crit, w, gate)                       # (n, 4)
        mean_score = runs.mean(axis=1)
        r_plain = pearson(mean_score, human)
        r_mean, r_min, r_max = loo_r(mean_score, human)
        sd = float(np.sqrt(np.mean(runs.var(axis=1, ddof=1))))
        hq_scores = [float(option_score({c: r["criteria"][c] for c in CRITERIA}, w, gate)) for r in hq_recs]
        c_score = float(option_score({c: ctrl02["criteria"][c] for c in CRITERIA}, w, gate)) if ctrl02 else float("nan")
        gap = float(np.mean(hq_scores)) - c_score if hq_scores else float("nan")
        stats[name] = {"r_plain": r_plain, "r_loo": r_mean, "sd": sd, "gap": gap, "hq_mean": float(np.mean(hq_scores)), "ctrl02": c_score}
    for name, (w, gate) in OPTIONS.items():
        s = stats[name]
        rm = [pearson(option_score(crit, w, gate).mean(axis=1)[np.arange(len(ids)) != i], human[np.arange(len(ids)) != i]) for i in range(len(ids))]
        gate_txt = " + cong Relevance<=2 -> max 5.0" if gate else ""
        p(f"{name:<3}" + "".join(f"{x:>6.2f}" for x in w) + f"{'':>3}{s['r_plain']:>10.3f}{s['r_loo']:>10.3f} [{min(rm):.3f}, {max(rm):.3f}]"
          f"{s['r_loo'] - stats['A']['r_loo']:>+12.3f}{s['sd']:>8.3f}{s['gap']:>12.2f}{gate_txt}")
    p("(khoang cach = TB diem tong hq - diem tong ctrl02, thang 0-10; duong = hq cao hon. hq/ctrl02 tinh lai theo trong so cua tung phuong an.)")
    p("")
    p(f"{'PA':<3}{'TB hq':>8}{'ctrl02':>8}{'r dat (>= r_A - 0.03)':>24}{'cach dat (>= 1.0)':>20}")
    passes = {}
    for name, s in stats.items():
        ok_r = s["r_loo"] >= stats["A"]["r_loo"] - R_DROP_TOLERANCE
        ok_gap = s["gap"] >= MIN_GAP
        passes[name] = ok_r and ok_gap
        p(f"{name:<3}{s['hq_mean']:>8.2f}{s['ctrl02']:>8.2f}{('dat' if ok_r else 'KHONG'):>24}{('dat' if ok_gap else 'KHONG'):>20}")

    chosen, reason = None, ""
    for group in SIMPLICITY_GROUPS:
        winners = [g for g in group if passes[g]]
        if winners:
            chosen = min(winners, key=lambda g: stats[g]["sd"])
            reason = (f"nhom '{'/'.join(group)}' la nhom don gian nhat co phuong an dat ca hai dieu kien"
                      + (f"; hoa giua {winners}, chon SD thap nhat" if len(winners) > 1 else ""))
            break
    p("")
    p("QUY TAC: phuong an don gian nhat co r (LOO) giam <= 0.03 so voi A VA tach ctrl02 khoi TB hq >= 1.0 diem; hoa thi SD gop thap nhat. Thu tu don gian: A < B < C = E < D.")
    p(f"KET QUA THEO QUY TAC: {chosen if chosen else 'khong phuong an nao dat'} ({reason if chosen else ''})")
    text = chr(10).join(out)
    print(text)
    REPORT_PATH.write_text(text + chr(10), encoding="utf-8")


if __name__ == "__main__":
    main()
