"""
Phan tich OFFLINE (khong goi API) tren 4 lan cham VI lap (t0.2 x2, t0 x2), doc qua analyze_replicates.load_matrix:

(1) Ma tran tuong quan 5x5 cua NHIEU giua cac tieu chi. Nhieu = do lech cua tung lan cham so voi
    trung binh 4 lan cua CHINH bai do (theo tung tieu chi); tuong quan Pearson gop tren n_bai x 4 do lech.
    (Tuong duong tuong quan tu ma tran hiep phuong sai TRONG BAI.) Bootstrap theo bai.
(2) Mo phong cham THICH UNG: cham 2 lan, neu |lech diem tong| >= T thi them lan 3, T = 0.4 / 0.8 / 1.2.
    Liet ke ca 24 thu tu (a, b, c, d) cua 4 lan lap cho moi bai: uoc luong = TB(a,b) neu |a-b| < T, nguoc lai
    TB(a,b,c); lan d (chua dung, chon theo thu tu co dinh, DOC LAP voi viec chon) lam tham chieu.
    Var(uoc luong) = E[(uoc luong - d)^2] - sigma^2, sigma^2 = phuong sai trong bai gop (4 lan, ddof = 1).

Chay: python scripts/analyze_noise_structure.py
"""
import sys
from itertools import combinations, permutations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from analyze_replicates import CRITERIA, SAMPLE_PATH, load_matrix, sigma_hat  # noqa: E402

import json  # noqa: E402

REPORT_PATH = Path(__file__).parent.parent / "variance_report_adaptive.txt"
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 42
THRESHOLD = 0.4
THRESHOLDS_T = [0.4, 0.8, 1.2]
EPS = 1e-9  # diem tong la boi cua 0.4, so sanh so thuc can dung sai
PERMS = np.array(list(permutations(range(4))))  # 24 x 4


def noise_corr(mats: list[np.ndarray]) -> np.ndarray:
    """mats: 5 mang (n, 4), moi mang 1 tieu chi. Tra ve ma tran tuong quan 5x5 cua do lech trong bai."""
    dev = np.stack([(x - x.mean(axis=1, keepdims=True)).ravel() for x in mats])
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.corrcoef(dev)


def adaptive_stats(x: np.ndarray, t: float | None, sigma2: float):
    """x: (n, 4) diem tong. t=None -> co dinh (xem fixed_k). Tra ve (ty le them lan 3, so lan TB, SD gop uoc luong)."""
    a, b, c, d = (x[:, PERMS[:, j]] for j in range(4))  # moi mang (n, 24)
    first = (a + b) / 2
    extra = np.abs(a - b) >= t - EPS
    est = np.where(extra, (a + b + c) / 3, first)
    mse = float(np.mean((est - d) ** 2))
    bias = float(np.mean(est - d))  # d la 1 lan khong chech -> TB(est - d) la do chech TB cua uoc luong
    return float(extra.mean()), 2.0 + float(extra.mean()), float(np.sqrt(max(mse - sigma2, 0.0))), bias


def fixed_k(x: np.ndarray, k: int, sigma2: float) -> tuple[float, float]:
    a, b, c, d = (x[:, PERMS[:, j]] for j in range(4))
    est = (a + b) / 2 if k == 2 else (a + b + c) / 3
    return float(np.sqrt(max(float(np.mean((est - d) ** 2)) - sigma2, 0.0))), float(np.mean(est - d))


def boot_ci(stat, x, seed=BOOTSTRAP_SEED):
    rng = np.random.default_rng(seed)
    n = len(x)
    vals = [stat(x[rng.integers(0, n, n)]) for _ in range(N_BOOTSTRAP)]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def verdict(v: float) -> str:
    return "ĐẠT" if v <= THRESHOLD else "KHÔNG ĐẠT"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    m = load_matrix(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))
    n = len(m["ids"])
    out: list[str] = []
    p = out.append
    p(f"4 lần chấm VI (t0.2 x2, t0 x2) coi là 4 lần lặp; {n} bài đủ 4 lượt. Không gọi API. Bootstrap theo bài: {N_BOOTSTRAP} lần, seed {BOOTSTRAP_SEED}, CI 95%.")

    # ------------------------------------------------------------------ (1)
    p("")
    p("=== 1. MA TRẬN TƯƠNG QUAN 5x5 CỦA NHIỄU GIỮA CÁC TIÊU CHÍ ===")
    p("Nhiễu = độ lệch của mỗi lần chấm so với trung bình 4 lần của chính bài đó; Pearson gộp trên %d x 4 = %d độ lệch." % (n, n * 4))
    mats = [m[c] for c in CRITERIA]
    corr = noise_corr(mats)
    p(f"{'':<16}" + "".join(f"{c:>16}" for c in CRITERIA))
    for i, a in enumerate(CRITERIA):
        p(f"{a:<16}" + "".join(f"{corr[i, j]:>16.2f}" for j in range(5)))
    pairs = list(combinations(range(5), 2))
    off = np.array([corr[i, j] for i, j in pairs])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    boots = []
    for _ in range(N_BOOTSTRAP):
        idx = rng.integers(0, n, n)
        boots.append(noise_corr([x[idx] for x in mats]))
    boots = np.array(boots)
    p("")
    p("Từng cặp (điểm ước lượng [CI 95%]):")
    for (i, j), v in zip(pairs, off):
        lo, hi = np.nanpercentile(boots[:, i, j], [2.5, 97.5])
        p(f"  {CRITERIA[i]:<15}- {CRITERIA[j]:<15}: {v:+.2f}  [{lo:+.2f}, {hi:+.2f}]")
    mean_off = np.array([np.mean([b[i, j] for i, j in pairs]) for b in boots])
    p(f"Trung bình ngoài đường chéo: {off.mean():.2f}  [{np.nanpercentile(mean_off, 2.5):.2f}, {np.nanpercentile(mean_off, 97.5):.2f}]"
      f" | nhỏ nhất {off.min():.2f}, lớn nhất {off.max():.2f}")
    eig = np.linalg.eigvalsh(np.nan_to_num(corr))[::-1]
    p(f"Giá trị riêng lớn nhất của ma trận nhiễu = {eig[0]:.2f}/5 -> {eig[0] / 5 * 100:.0f}% phương sai nhiễu nằm trên 1 trục chung")
    sig_c = np.array([sigma_hat(x) for x in mats])
    indep = 0.4 * float(np.sqrt(np.sum(sig_c ** 2)))
    obs = sigma_hat(m["overall"])
    p(f"Hệ quả cho điểm tổng: SD trong bài quan sát = {obs:.3f}; nếu nhiễu 5 tiêu chí độc lập thì chỉ khoảng {indep:.3f} "
      f"(0.4 x sqrt(tổng phương sai từng tiêu chí)) -> nhiễu tương quan làm SD điểm tổng gấp {obs / indep:.2f} lần.")
    p("(Điểm là số nguyên 1-5 và Evidence gần như hằng số: cặp có Evidence dựa trên ít độ lệch khác 0, CI rộng.)")
    sig_corr = np.corrcoef(np.stack([x.mean(axis=1) for x in mats]))
    sig_off = np.array([sig_corr[i, j] for i, j in pairs])
    p(f"Tham chiếu: tương quan TÍN HIỆU giữa các tiêu chí (trung bình 4 lần, giữa các bài) có trung bình ngoài đường chéo {sig_off.mean():.2f} "
      f"(nhỏ nhất {sig_off.min():.2f}, lớn nhất {sig_off.max():.2f}).")

    # ------------------------------------------------------------------ (2)
    x = m["overall"]
    sigma2 = float(np.mean(x.var(axis=1, ddof=1)))
    p("")
    p("=== 2. MÔ PHỎNG CHẤM THÍCH ỨNG (điểm tổng, thang 0-10) ===")
    p(f"Chấm 2 lần; nếu |lệch điểm tổng| >= T thì chấm thêm lần 3, rồi lấy trung bình các lần đã chấm. 24 thứ tự x {n} bài.")
    p("Điểm tổng là bội của 0.4 (1 điểm tiêu chí = 0.4): T=0.4 nghĩa là hễ hai lần khác nhau là chấm thêm; T=0.8 là lệch >= 2 điểm tiêu chí; T=1.2 là >= 3 điểm.")
    p(f"sigma-hat (1 lần) = {np.sqrt(sigma2):.3f}. SD gộp của ước lượng = sqrt(E[(ước lượng - lần tham chiếu)^2] - sigma^2); lần tham chiếu là lần thứ 4, độc lập với việc chọn.")
    p("Ngưỡng 0.4 được chốt cho SD gộp của MỘT lần chấm; áp vào ước lượng thích ứng là so sánh theo yêu cầu.")
    p("")
    p(f"{'phương án':<26}{'% thêm lần 3':>13}{'số lần TB':>10}{'SD gộp**':>9}{'CI 95%':>18}{'vs 0.4':>11}{'chệch TB (ước lượng - tham chiếu)':>36}{'SD nếu thêm lần 3 ngẫu nhiên*':>32}")
    rows = []
    for k in (2, 3):
        v, bias = fixed_k(x, k, sigma2)
        lo, hi = boot_ci(lambda z, k=k: fixed_k(z, k, float(np.mean(z.var(axis=1, ddof=1))))[0], x)
        blo, bhi = boot_ci(lambda z, k=k: fixed_k(z, k, float(np.mean(z.var(axis=1, ddof=1))))[1], x)
        rows.append((f"cố định {k} lần", "-", f"{float(k):.2f}", v, lo, hi, f"{bias:+.3f} [{blo:+.3f}, {bhi:+.3f}]", "-"))
    for t in THRESHOLDS_T:
        rate, runs, v, bias = adaptive_stats(x, t, sigma2)
        lo, hi = boot_ci(lambda z, t=t: adaptive_stats(z, t, float(np.mean(z.var(axis=1, ddof=1))))[2], x)
        blo, bhi = boot_ci(lambda z, t=t: adaptive_stats(z, t, float(np.mean(z.var(axis=1, ddof=1))))[3], x)
        rand = float(np.sqrt(sigma2 * (rate / 3 + (1 - rate) / 2)))
        rows.append((f"thích ứng T={t}", f"{rate * 100:.0f}%", f"{runs:.2f}", v, lo, hi, f"{bias:+.3f} [{blo:+.3f}, {bhi:+.3f}]", f"{rand:.3f}"))
    for name, rate, runs, v, lo, hi, bias_txt, rand in rows:
        p(f"{name:<26}{rate:>13}{runs:>10}{v:>9.3f}{('[' + f'{lo:.3f}, {hi:.3f}' + ']'):>18}{verdict(v):>11}{bias_txt:>36}{rand:>32}")
    p("** SD gộp = sqrt(E[(ước lượng - lần tham chiếu)^2] - sigma^2). Bằng SD thật nếu ước lượng không chệch; nếu quy tắc chọn theo |lệch| tạo chệch")
    p("   (điểm bị chặn ở sàn 2.0 nên nhiễu không đối xứng) thì con số đã gồm bình phương độ chệch, tức là cận trên. Cột 'chệch TB' chỉ là chệch trung bình trên mọi bài, chệch ngược dấu giữa các bài vẫn có thể triệt tiêu nhau.")
    p("* cùng ngân sách số lần chấm nhưng chọn bài nào được chấm thêm lần 3 NGẪU NHIÊN (không nhìn độ lệch): sigma*sqrt(p/3 + (1-p)/2).")
    p("  Chênh giữa cột SD gộp và cột này là lợi ích riêng của việc chọn bài theo độ lệch.")
    p("Giả định: các lần lặp hoán đổi được (t0.2 và t0 coi như một), nhiễu không phụ thuộc nhiều vào bài; điểm là số nguyên; chưa kiểm chứng bằng chấm thật theo quy tắc này.")

    text = "\n".join(out)
    print(text)
    REPORT_PATH.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
