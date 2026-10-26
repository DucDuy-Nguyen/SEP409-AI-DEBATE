"""
Phan tich OFFLINE (khong goi API): coi 4 lan cham VI (temperature 0.2 x2, temperature 0 x2)
la 4 lan lap cua cung 1 phep do, tinh
  (1) SD gop cua trung binh k lan cham (k = 1, 2, 3, 4) + CI 95% bootstrap theo bai, so voi nguong 0.4
  (2) ma tran tuong quan 5x5 giua cac tieu chi tren trung binh 4 lan.

SD gop cua trung binh k lan = do lech chuan TRONG BAI cua gia tri trung binh do (sigma / sqrt(k)).
Cach tinh (khong gia dinh gi ngoai "cac lan lap doc lap, cung phuong sai"):
- k = 2: chia 4 lan thanh 2 cap roi rac, mien la 3 cach: {12|34}, {13|24}, {14|23}. Hai trung binh
  cap la 2 uoc luong DOC LAP cua cung 1 gia tri -> SD2 = sqrt(mean(d^2) / 2), d = hieu 2 trung binh.
- k = 3: 4 lan khong du de lap 2 nhom roi nhau moi nhom 3 lan, nen dung "giu lai 1 lan": d = trung
  binh cua 3 lan - lan con lai (4 cach). E[d^2] = sigma^2 (1/3 + 1) -> SD3 = sqrt(mean(d^2) / 4).
- Doi chieu: sigma-hat (SD trong bai cua 1 lan, ddof = 1, 4 lan lap) chia sqrt(k).
Chay: python scripts/analyze_replicates.py
"""
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"
SOURCES = [("vi", DATA_DIR / "vi_variance_results.jsonl"), ("vi_t0", DATA_DIR / "vi_t0_variance_results.jsonl")]
SAMPLE_PATH = DATA_DIR / "_dagstuhl_vi_sample50.json"
VI_CSV_PATH = DATA_DIR / "dagstuhl_processed_vi.csv"
REPORT_PATH = Path(__file__).parent.parent / "variance_report_replicates.txt"

CRITERIA = ["Logic", "Evidence", "Relevance", "Structure", "Persuasiveness"]
METRICS = ["overall"] + CRITERIA
HUMAN_COLS = {"Logic": "cogency_score_10", "Evidence": "sufficiency_score_10", "Relevance": "global_relevance_score_10",
              "Structure": "arrangement_score_10", "Persuasiveness": "effectiveness_score_10"}
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 42
THRESHOLD = 0.4
PAIRINGS = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]
REPLICATE_LABELS = ["t0.2 lan 1", "t0.2 lan 2", "t0 lan 1", "t0 lan 2"]


def load_matrix(sample_ids: list[str]) -> dict[str, np.ndarray]:
    """Moi chieu -> mang (n_bai, 4): cot 0,1 = t0.2 lan 1,2; cot 2,3 = t0 lan 1,2. Chi giu bai du ca 4 luot."""
    per_id: dict[str, dict[int, dict]] = {i: {} for i in sample_ids}
    for k, (_, path) in enumerate(SOURCES):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r["status"] == "ok":
                    per_id[r["id"]][k * 2 + r["run"] - 1] = r
    ids = [i for i in sample_ids if len(per_id[i]) == 4]
    out = {"ids": np.array(ids)}
    out["overall"] = np.array([[per_id[i][c]["overall_score"] for c in range(4)] for i in ids], float)
    for crit in CRITERIA:
        out[crit] = np.array([[per_id[i][c]["criteria"][crit] for c in range(4)] for i in ids], float)
    return out


def sigma_hat(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.var(axis=1, ddof=1))))


def sd_k2_pairings(x: np.ndarray) -> list[float]:
    return [float(np.sqrt(np.mean((x[:, list(a)].mean(1) - x[:, list(b)].mean(1)) ** 2) / 2)) for a, b in PAIRINGS]


def sd_k3_holdouts(x: np.ndarray) -> list[float]:
    vals = []
    for h in range(4):
        rest = [c for c in range(4) if c != h]
        vals.append(float(np.sqrt(np.mean((x[:, rest].mean(1) - x[:, h]) ** 2) / 4)))
    return vals


def boot(stat, x: np.ndarray) -> tuple[float, float]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n = len(x)
    vals = [stat(x[rng.integers(0, n, n)]) for _ in range(N_BOOTSTRAP)]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def f(x: float, nd: int = 3) -> str:
    return f"{x:.{nd}f}"


def verdict(point: float) -> str:
    return "ĐẠT" if point <= THRESHOLD else "KHÔNG ĐẠT"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sample_ids = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    m = load_matrix(sample_ids)
    n = len(m["ids"])
    out: list[str] = []
    p = out.append

    p("4 lần chấm VI (t0.2 x2, t0 x2) coi là 4 lần lặp của cùng một phép đo. Không gọi API.")
    p(f"Bài có đủ 4 lượt hợp lệ: {n}/{len(sample_ids)}. Bootstrap theo bài: {N_BOOTSTRAP} lần resample, seed {BOOTSTRAP_SEED}, CI 95% percentile.")
    p("Giả định: các lần lặp độc lập, cùng phương sai (đợt t0.2 và t0 trước đó không khác nhau rõ về SD/mức điểm); nếu có hiệu ứng temperature theo từng bài thì sigma-hat bị thổi nhẹ.")
    p("")
    p("Điểm tổng, thang 0-10: trung bình mỗi lần chấm và sigma-hat theo từng đợt (kiểm tra 4 lần lặp có cùng mặt bằng):")
    for j, lab in enumerate(REPLICATE_LABELS):
        p(f"  {lab:<12}: TB = {m['overall'][:, j].mean():.3f}")
    p(f"  SD trong bài (1 lần): chỉ 2 lần t0.2 = {sigma_hat(m['overall'][:, :2]):.3f} ; chỉ 2 lần t0 = {sigma_hat(m['overall'][:, 2:]):.3f} ; cả 4 lần = {sigma_hat(m['overall']):.3f}")

    p("")
    p("=== 1. SD GỘP CỦA TRUNG BÌNH k LẦN (điểm tổng, thang 0-10), so với ngưỡng 0.4 ===")
    p(f"Ngưỡng {THRESHOLD} được chốt cho SD gộp của MỘT lần chấm; áp vào trung bình k lần là so sánh theo yêu cầu, không phải ngưỡng chốt riêng cho trung bình.")
    x = m["overall"]
    sig = sigma_hat(x)
    rows = []
    s1 = float(sigma_hat(x))
    lo, hi = boot(sigma_hat, x)
    rows.append(("k=1 (1 lần, sigma-hat từ 4 lần)", s1, lo, hi, ""))
    pair_vals = sd_k2_pairings(x)
    lo, hi = boot(lambda z: float(np.mean(sd_k2_pairings(z))), x)
    rows.append(("k=2 (TB 3 cách ghép cặp)", float(np.mean(pair_vals)), lo, hi,
                 "từng cách {12|34},{13|24},{14|23}: " + ", ".join(f(v) for v in pair_vals)))
    lo, hi = boot(lambda z: sigma_hat(z) / np.sqrt(2), x)
    rows.append(("k=2 (sigma-hat / sqrt2)", sig / np.sqrt(2), lo, hi, "đối chiếu lý thuyết"))
    hold = sd_k3_holdouts(x)
    lo, hi = boot(lambda z: float(np.mean(sd_k3_holdouts(z))), x)
    rows.append(("k=3 (TB 4 cách giữ-1-lần)", float(np.mean(hold)), lo, hi,
                 "từng cách giữ lại lần 1..4: " + ", ".join(f(v) for v in hold)))
    lo, hi = boot(lambda z: sigma_hat(z) / np.sqrt(3), x)
    rows.append(("k=3 (sigma-hat / sqrt3)", sig / np.sqrt(3), lo, hi, "đối chiếu lý thuyết"))
    lo, hi = boot(lambda z: sigma_hat(z) / 2, x)
    rows.append(("k=4 (sigma-hat / 2)", sig / 2, lo, hi, "chỉ lý thuyết, không có ước lượng độc lập"))
    p(f"{'cách tính':<34}{'SD gộp':>8}{'CI 95%':>20}{'vs 0.4':>12}   ghi chú")
    for name, v, lo, hi, note in rows:
        p(f"{name:<34}{f(v):>8}{('[' + f(lo) + ', ' + f(hi) + ']'):>20}{verdict(v):>12}   {note}")
    p("(vs 0.4: so điểm ước lượng với ngưỡng; ĐẠT khi SD gộp <= 0.4. Cận trên CI cho biết có chắc dưới 0.4 hay không.)")

    p("")
    p("SD gộp của trung bình k lần theo từng tiêu chí (thang 1-5; chỉ báo cáo, không đặt ngưỡng): k=1 | k=2 (TB 3 cách) | k=3 (TB 4 cách)")
    for crit in CRITERIA:
        xc = m[crit]
        p(f"  {crit:<15}: {f(sigma_hat(xc)):>6} | {f(float(np.mean(sd_k2_pairings(xc)))):>6} | {f(float(np.mean(sd_k3_holdouts(xc)))):>6}")

    p("")
    p("=== 2. MA TRẬN TƯƠNG QUAN 5x5 GIỮA CÁC TIÊU CHÍ (Pearson, trung bình 4 lần, n=%d bài) ===" % n)
    mean4 = pd.DataFrame({c: m[c].mean(axis=1) for c in CRITERIA})
    corr = mean4.corr()
    p(f"{'':<16}" + "".join(f"{c:>16}" for c in CRITERIA))
    for a in CRITERIA:
        p(f"{a:<16}" + "".join(f"{corr.loc[a, b]:>16.2f}" for b in CRITERIA))
    off = [corr.loc[a, b] for a, b in combinations(CRITERIA, 2)]
    p(f"Tương quan ngoài đường chéo: TB = {np.mean(off):.2f}, nhỏ nhất = {np.min(off):.2f}, lớn nhất = {np.max(off):.2f}")
    p("SD giữa bài của trung bình 4 lần (cho thấy tiêu chí nào bị co hẹp thang): " +
      "; ".join(f"{c} {mean4[c].std(ddof=1):.2f}" for c in CRITERIA))

    human = pd.read_csv(VI_CSV_PATH).assign(id=lambda d: d["id"].astype(str)).set_index("id")
    hm = pd.DataFrame({c: human.loc[list(m["ids"]), HUMAN_COLS[c]].to_numpy(float) for c in CRITERIA})
    hcorr = hm.corr()
    p("")
    p("Tham chiếu (ngoài yêu cầu): cùng ma trận cho điểm NGƯỜI chấm, 5 chiều Dagstuhl tương ứng, cùng %d bài:" % n)
    p(f"{'':<16}" + "".join(f"{c:>16}" for c in CRITERIA))
    for a in CRITERIA:
        p(f"{a:<16}" + "".join(f"{hcorr.loc[a, b]:>16.2f}" for b in CRITERIA))
    hoff = [hcorr.loc[a, b] for a, b in combinations(CRITERIA, 2)]
    p(f"Tương quan ngoài đường chéo (người): TB = {np.mean(hoff):.2f}, nhỏ nhất = {np.min(hoff):.2f}, lớn nhất = {np.max(hoff):.2f}")

    text = "\n".join(out)
    print(text)
    REPORT_PATH.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
