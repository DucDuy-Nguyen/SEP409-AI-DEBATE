"""
Phan tich dao dong diem AI giua 2 lan cham (doc data/{vi,en}_variance_results.jsonl
do scripts/run_vi_variance_eval.py ghi). KHONG goi API.

Chay:
    python scripts/analyze_vi_variance.py --lang vi      # chi tieng Viet (mac dinh)
    python scripts/analyze_vi_variance.py --lang en
    python scripts/analyze_vi_variance.py --lang both    # vi + en + so sanh cap
In ra man hinh va luu variance_report_<lang>.txt (thu muc goc project).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_PATHS = {
    "vi": DATA_DIR / "vi_variance_results.jsonl",
    "en": DATA_DIR / "en_variance_results.jsonl",
    "vi_t0": DATA_DIR / "vi_t0_variance_results.jsonl",  # tieng Viet, temperature 0
}
SAMPLE_PATH = DATA_DIR / "_dagstuhl_vi_sample50.json"
VI_CSV_PATH = DATA_DIR / "dagstuhl_processed_vi.csv"
REPORT_DIR = Path(__file__).parent.parent

CRITERIA = ["Logic", "Evidence", "Relevance", "Structure", "Persuasiveness"]
METRICS = ["overall"] + CRITERIA
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 42
HUMAN_SPLIT = 5.0  # nhom diem nguoi: <= 5.0 / > 5.0
OVERALL_SD_THRESHOLD = 0.4
FLAG_LABEL = "ban_plastic_side_uncertain"
# Quy tac THAM CHIEU lay tu ke hoach truoc (mau 30 bai), KHONG phai nguong da chot
# cho lan so sanh nay — in ra de doi chieu, nguoi dung quyet dinh co dung hay khong.
OLD_PLAN_MAX_EXTRA_RANGE = 0.3

THRESHOLD_TEXT = (
    "Điểm tổng: độ lệch chuẩn gộp <= 0.4 trên thang 0-10, tương đương hai lần chấm lệch "
    "nhau trung bình (căn quân phương) khoảng 1.4 điểm tiêu chí cộng dồn. r giữa hai lần "
    "chỉ báo cáo, không dùng làm tiêu chí đạt/không đạt vì mẫu lệch về điểm thấp. "
    "Từng tiêu chí: chỉ báo cáo, không đặt ngưỡng."
)
LANG_NAME = {"vi": "TIẾNG VIỆT", "en": "TIẾNG ANH", "vi_t0": "TIẾNG VIỆT, TEMPERATURE 0"}


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Chua co {path}, hay chay run_vi_variance_eval.py truoc")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_pairs(records: list[dict], sample_ids: list[str]):
    """Tra ve (DataFrame cac bai du 2 luot hop le, danh sach bai bi loai kem ly do)."""
    ok: dict[tuple[str, int], dict] = {}
    last_error: dict[tuple[str, int], str] = {}
    for r in records:
        key = (r["id"], r["run"])
        if r["status"] == "ok":
            ok[key] = r  # neu trung thi lay ban ghi ok sau cung
        else:
            last_error[key] = f"{r.get('error_type')}: {(r.get('error') or '')[:80]}"

    rows, excluded = [], []
    for arg_id in sample_ids:
        runs = {run: ok.get((arg_id, run)) for run in (1, 2)}
        if runs[1] is None or runs[2] is None:
            reasons = []
            for run in (1, 2):
                if runs[run] is None:
                    reasons.append(f"lan {run}: " + last_error.get((arg_id, run), "chua cham"))
            excluded.append((arg_id, "; ".join(reasons)))
            continue
        row = {"id": arg_id, "flag": runs[1].get("flag"), "side": runs[1].get("side")}
        for run in (1, 2):
            row[f"overall_{run}"] = runs[run]["overall_score"]
            for c in CRITERIA:
                row[f"{c}_{run}"] = runs[run]["criteria"][c]
        rows.append(row)
    return pd.DataFrame(rows), excluded


# ---------------------------------------------------------------- thong ke
def pooled_sd(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2 / 2)))


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def icc_2_1(a: np.ndarray, b: np.ndarray) -> float:
    """ICC(2,1) cua Shrout & Fleiss (1979): hai chieu ngau nhien, DO DONG THUAN TUYET DOI
    (absolute agreement), 1 luot cham don. Doi tuong = bai, 'nguoi cham' = lan 1 / lan 2."""
    x = np.column_stack([a, b])
    n, k = x.shape
    if n < 3:
        return float("nan")
    grand = x.mean()
    row_means, col_means = x.mean(axis=1), x.mean(axis=0)
    ms_r = k * np.sum((row_means - grand) ** 2) / (n - 1)
    ms_c = n * np.sum((col_means - grand) ** 2) / (k - 1)
    sse = np.sum((x - row_means[:, None] - col_means[None, :] + grand) ** 2)
    ms_e = sse / ((n - 1) * (k - 1))
    denom = ms_r + (k - 1) * ms_e + k * (ms_c - ms_e) / n
    return float((ms_r - ms_e) / denom) if denom > 0 else float("nan")


def bootstrap_ci(stat, *arrays: np.ndarray) -> tuple[float, float]:
    """CI 95% percentile bootstrap, resample theo bai (cac mang cung do dai, cung chi so)."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n = len(arrays[0])
    vals = []
    for _ in range(N_BOOTSTRAP):
        idx = rng.integers(0, n, n)
        v = stat(*[a[idx] for a in arrays])
        if not np.isnan(v):
            vals.append(v)
    if len(vals) < N_BOOTSTRAP * 0.5:
        return float("nan"), float("nan")
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def fmt(x, nd=2, sign=False) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def ci_text(lo, hi, nd=2, sign=False) -> str:
    return f"[{fmt(lo, nd, sign)}, {fmt(hi, nd, sign)}]"


def metric_values(df: pd.DataFrame, m: str):
    return df[f"{m}_1"].to_numpy(float), df[f"{m}_2"].to_numpy(float)


def top_by_diff(a: np.ndarray, b: np.ndarray, n: int = 5):
    """n bai lech nhieu nhat (hoa thi lay theo thu tu trong mau, on dinh). Tra ve them so bai
    KHAC cung muc lech voi bai cuoi danh sach nhung khong duoc liet ke, de bao cao noi ro."""
    d = np.abs(a - b)
    order = np.argsort(-d, kind="stable")[:n]
    cutoff = d[order[-1]]
    unlisted = int(np.sum(d == cutoff)) - int(np.sum(d[order] == cutoff))
    return list(order), d, unlisted


# ---------------------------------------------------------------- bao cao 1 ngon ngu
def analyze_language(lang: str, sample_ids: list[str], human: pd.Series):
    records = load_records(RESULTS_PATHS[lang])
    pairs, excluded = build_pairs(records, sample_ids)
    out: list[str] = []
    p = out.append

    p("=" * 100)
    p(f"BÁO CÁO {LANG_NAME[lang]}")
    p("=" * 100)
    p("NGƯỠNG (chốt trước khi chạy, đề xuất, chưa có căn cứ nguồn):")
    p(THRESHOLD_TEXT)
    p("")
    p(f"Mẫu {len(sample_ids)} bài x 2 lần, {LANG_NAME[lang].lower()}, side theo ánh xạ stance"
      + ("; temperature 0, các thiết lập khác như đợt temperature 0.2." if lang == "vi_t0" else "."))
    p(f"Bài đủ 2 lượt hợp lệ: {len(pairs)}/{len(sample_ids)} | bị loại: {len(excluded)}")
    for arg_id, reason in excluded:
        p(f"  - loại {arg_id}: {reason}")

    calls = [c for r in records for c in (r.get("usage") or {}).get("calls", [])]
    if calls:
        ok_calls = [c for c in calls if not c.get("failed")]
        failed = len(calls) - len(ok_calls)
        tot = sum(c["total_tokens"] for c in ok_calls)
        p(f"Request: {len(calls)} đã gửi = {len(ok_calls)} thành công + {failed} lỗi (không có usage nên token của chúng không biết). "
          f"Token thật của request thành công: {tot}, TB {tot / max(len(ok_calls), 1):.0f}/request.")
        if any("failed" not in c for c in calls):
            p("  (lưu ý: một số bản ghi cũ chưa đếm request lỗi; 'đã gửi' có thể thiếu ở các bản ghi đó)")

    if len(pairs) < 3:
        p("\nChưa đủ bài để tính chỉ số (cần >= 3).")
        return out, pairs

    pairs["human"] = pairs["id"].map(human)

    p("")
    p(f"=== CHỈ SỐ (n={len(pairs)}; khoảng tin cậy 95% bootstrap theo bài, {N_BOOTSTRAP} lần resample, seed {BOOTSTRAP_SEED}) ===")
    p(f"{'chiều':<15}{'SD gộp':>8}{'SD giữa bài':>13}{'r(l1,l2)':>10}{'CI 95% r':>16}"
      f"{'ICC(2,1)':>10}{'CI 95% ICC':>16}{'chênh TB (l2-l1)':>18}{'CI 95%':>18}{'% lệch>=ngưỡng':>16}")
    for m in METRICS:
        a, b = metric_values(pairs, m)
        r_lo, r_hi = bootstrap_ci(pearson, a, b)
        i_lo, i_hi = bootstrap_ci(icc_2_1, a, b)
        d_lo, d_hi = bootstrap_ci(lambda x, y: float(np.mean(y - x)), a, b)
        between = float(np.std((a + b) / 2, ddof=1))
        big = float(np.mean(np.abs(a - b) >= 1.0)) * 100
        p(f"{m:<15}{fmt(pooled_sd(a, b)):>8}{fmt(between):>13}{fmt(pearson(a, b)):>10}{ci_text(r_lo, r_hi):>16}"
          f"{fmt(icc_2_1(a, b)):>10}{ci_text(i_lo, i_hi):>16}{fmt(float(np.mean(b - a)), 3, True):>18}"
          f"{ci_text(d_lo, d_hi, 3, True):>18}{big:>15.0f}%")
    p("(% lệch>=ngưỡng: |lần1 - lần2| >= 1 điểm tiêu chí; riêng 'overall' là >= 1.0 trên thang 0-10)")
    p("(chênh TB có dấu = trung bình (lần 2 - lần 1); khác 0 một cách có hệ thống nghĩa là lần chấm sau cao/thấp hơn lần trước)")
    p("(ICC(2,1): đồng thuận tuyệt đối giữa 2 lần, 1 lượt chấm đơn; 1 = hai lần luôn giống hệt nhau)")

    p("")
    p(f"=== SD GỘP THEO NHÓM ĐIỂM NGƯỜI (điểm tổng người: <= {HUMAN_SPLIT} / > {HUMAN_SPLIT}) ===")
    no_human = int(pairs["human"].isna().sum())
    if no_human:
        p(f"(!) {no_human} bài không có điểm người trong CSV, không thuộc nhóm nào dưới đây")
    groups = {
        f"<= {HUMAN_SPLIT}": pairs[pairs["human"] <= HUMAN_SPLIT],
        f"> {HUMAN_SPLIT}": pairs[pairs["human"] > HUMAN_SPLIT],
        "= 0.0": pairs[pairs["human"] == 0.0],
    }
    p(f"{'nhóm':<10}{'n':>4}" + "".join(f"{m:>16}" for m in METRICS))
    for name, g in groups.items():
        cells = "".join(f"{(fmt(pooled_sd(*metric_values(g, m))) if len(g) else 'n/a'):>16}" for m in METRICS)
        p(f"{name:<10}{len(g):>4}{cells}")
    p("(nhóm '= 0.0' là tập con của '<= 5.0', in thêm để tham khảo)")

    p("")
    flagged = pairs[pairs["flag"] == FLAG_LABEL]
    rest = pairs[pairs["flag"] != FLAG_LABEL]
    p(f"=== NHÓM ĐÁNH DẤU ban-plastic (side không chắc), báo cáo riêng: n={len(flagged)} ===")
    p("(n rất nhỏ, chỉ để tham khảo, không kết luận từ nhóm này)")
    p(f"{'nhóm':<22}{'n':>4}" + "".join(f"{m:>16}" for m in METRICS))
    for name, g in (("ban-plastic (đánh dấu)", flagged), ("các bài còn lại", rest)):
        cells = "".join(f"{(fmt(pooled_sd(*metric_values(g, m))) if len(g) else 'n/a'):>16}" for m in METRICS)
        p(f"{name:<22}{len(g):>4}{cells}")
    for r in flagged.itertuples():
        p(f"  {r.id} (phe {r.side}): overall {r.overall_1} / {r.overall_2}")

    p("")
    p("=== 5 BÀI LỆCH NHIỀU NHẤT (hòa thì lấy theo thứ tự trong mẫu; số bài hòa không liệt kê được ghi rõ) ===")
    a, b = metric_values(pairs, "overall")
    chosen, d, unlisted = top_by_diff(a, b)
    p("Điểm tổng (thang 0-10)" + (f" — còn {unlisted} bài khác cũng lệch {d[chosen[-1]]:.2f}, không liệt kê" if unlisted else "") + ":")
    for i in chosen:
        r = pairs.iloc[i]
        p(f"  {r['id']}: lần 1 = {a[i]}, lần 2 = {b[i]}, lệch {d[i]:.2f} (điểm người {r['human']})")
    for c in CRITERIA:
        ca, cb = metric_values(pairs, c)
        chosen, d, unlisted = top_by_diff(ca, cb)
        note = f" — còn {unlisted} bài khác cũng lệch {d[chosen[-1]]:.0f}, không liệt kê" if unlisted else ""
        p(f"{c} (thang 1-5){note}: " + "; ".join(f"{pairs.iloc[i]['id']} ({ca[i]:.0f} vs {cb[i]:.0f})" for i in chosen))

    a, b = metric_values(pairs, "overall")
    sd = pooled_sd(a, b)
    p("")
    verdict = "ĐẠT" if sd <= OVERALL_SD_THRESHOLD else "KHÔNG ĐẠT"
    p(f"Điểm tổng: {verdict} ngưỡng (SD gộp = {sd:.3f} so với {OVERALL_SD_THRESHOLD}, n={len(pairs)}).")
    return out, pairs


# ---------------------------------------------------------------- so sanh VI - EN
def compare_languages(pv: pd.DataFrame, pe: pd.DataFrame) -> list[str]:
    ids = sorted(set(pv["id"]) & set(pe["id"]))
    out: list[str] = []
    p = out.append
    p("=" * 100)
    p("SO SÁNH TIẾNG VIỆT vs TIẾNG ANH (cặp theo bài, chỉ bài đủ 2 lượt ở CẢ HAI ngôn ngữ)")
    p("=" * 100)
    p(f"Bài dùng được ở cả hai: {len(ids)} | VI có {len(pv)} bài hợp lệ, EN có {len(pe)}")
    if len(ids) < 3:
        p("Chưa đủ bài để so sánh.")
        return out
    v = pv.set_index("id").loc[ids].reset_index()
    e = pe.set_index("id").loc[ids].reset_index()
    p("Cùng bộ bài, cùng side, cùng cấu hình; chỉ khác ngôn ngữ của text và motion. Hiệu = VI - EN.")
    p("")
    p(f"{'chiều':<15}{'SD gộp VI':>10}{'SD gộp EN':>10}{'VI-EN':>8}{'CI 95%':>16}"
      f"{'ICC VI':>8}{'ICC EN':>8}{'range TB VI':>12}{'range TB EN':>12}{'r(TB VI,TB EN)':>16}{'lệch TB (VI-EN)':>17}")
    for m in METRICS:
        va, vb = metric_values(v, m)
        ea, eb = metric_values(e, m)
        diff = lambda x1, x2, y1, y2: pooled_sd(x1, x2) - pooled_sd(y1, y2)
        lo, hi = bootstrap_ci(diff, va, vb, ea, eb)
        vm, em = (va + vb) / 2, (ea + eb) / 2
        p(f"{m:<15}{fmt(pooled_sd(va, vb)):>10}{fmt(pooled_sd(ea, eb)):>10}{fmt(pooled_sd(va, vb) - pooled_sd(ea, eb), 2, True):>8}"
          f"{ci_text(lo, hi, 2, True):>16}{fmt(icc_2_1(va, vb)):>8}{fmt(icc_2_1(ea, eb)):>8}"
          f"{fmt(float(np.mean(np.abs(va - vb)))):>12}{fmt(float(np.mean(np.abs(ea - eb)))):>12}"
          f"{fmt(pearson(vm, em)):>16}{fmt(float(np.mean(vm - em)), 2, True):>17}")
    p("(range TB = trung bình |lần1 - lần2| = trung bình max-min giữa 2 lần; r(TB VI,TB EN) = tương quan giữa điểm trung bình 2 lần của hai ngôn ngữ;")
    p(" lệch TB (VI-EN) = hiệu điểm trung bình, có dấu. CI 95% là của hiệu SD gộp, bootstrap theo bài.)")

    va, vb = metric_values(v, "overall")
    ea, eb = metric_values(e, "overall")
    rv, re_ = float(np.mean(np.abs(va - vb))), float(np.mean(np.abs(ea - eb)))
    p("")
    p("Tham chiếu (từ kế hoạch trước, mẫu 30 bài; KHÔNG phải ngưỡng đã chốt cho lần chạy này): "
      f"'Tiếng Việt coi là KHÔNG ồn hơn tiếng Anh nếu range trung bình của điểm tổng của VI không vượt EN quá {OLD_PLAN_MAX_EXTRA_RANGE} điểm.'")
    verdict = "KHÔNG ồn hơn" if rv - re_ <= OLD_PLAN_MAX_EXTRA_RANGE else "ồn hơn"
    p(f"Range TB điểm tổng: VI = {rv:.2f}, EN = {re_:.2f}, VI - EN = {rv - re_:+.2f} -> theo quy tắc tham chiếu: VI {verdict} EN.")
    return out


# ---------------------------------------------------------------- so sanh temperature
def compare_temperatures(p02: pd.DataFrame, p0: pd.DataFrame, human: pd.Series) -> list[str]:
    ids = sorted(set(p02["id"]) & set(p0["id"]))
    out: list[str] = []
    p = out.append
    p("=" * 100)
    p("SO SÁNH TEMPERATURE 0 vs 0.2 (tiếng Việt, cặp theo bài, chỉ bài đủ 2 lượt ở CẢ HAI đợt)")
    p("=" * 100)
    p(f"Bài dùng được ở cả hai: {len(ids)} | t0.2 có {len(p02)} bài hợp lệ, t0 có {len(p0)}")
    if len(ids) < 3:
        p("Chưa đủ bài để so sánh.")
        return out
    a = p02.set_index("id").loc[ids].reset_index()   # temperature 0.2
    b = p0.set_index("id").loc[ids].reset_index()    # temperature 0
    p("Cùng bài, cùng side, cùng text/motion VI, cùng prompt; chỉ khác temperature. Hiệu = t0 - t0.2.")
    p("MAE(t0 vs t0.2) = trung bình |điểm TB 2 lần của t0 - điểm TB 2 lần của t0.2| theo bài (mức khác nhau giữa hai thiết lập).")
    p("")
    p(f"{'chiều':<15}{'SD gộp t0.2':>12}{'SD gộp t0':>10}{'t0-t0.2':>9}{'CI 95%':>16}{'ICC t0.2':>9}{'ICC t0':>8}"
      f"{'range TB t0.2':>14}{'range TB t0':>12}{'% giống hệt t0':>15}{'MAE(t0 vs t0.2)':>16}{'lệch TB (t0-t0.2)':>18}")
    for m in METRICS:
        a1, a2 = metric_values(a, m)
        b1, b2 = metric_values(b, m)
        diff = lambda x1, x2, y1, y2: pooled_sd(y1, y2) - pooled_sd(x1, x2)
        lo, hi = bootstrap_ci(diff, a1, a2, b1, b2)
        am, bm = (a1 + a2) / 2, (b1 + b2) / 2
        same = float(np.mean(b1 == b2)) * 100
        p(f"{m:<15}{fmt(pooled_sd(a1, a2)):>12}{fmt(pooled_sd(b1, b2)):>10}{fmt(pooled_sd(b1, b2) - pooled_sd(a1, a2), 2, True):>9}"
          f"{ci_text(lo, hi, 2, True):>16}{fmt(icc_2_1(a1, a2)):>9}{fmt(icc_2_1(b1, b2)):>8}"
          f"{fmt(float(np.mean(np.abs(a1 - a2)))):>14}{fmt(float(np.mean(np.abs(b1 - b2)))):>12}{same:>14.0f}%"
          f"{fmt(float(np.mean(np.abs(bm - am)))):>16}{fmt(float(np.mean(bm - am)), 2, True):>18}")
    p("(% giống hệt t0: tỷ lệ bài mà 2 lần chấm ở temperature 0 cho đúng cùng điểm)")

    p("")
    p("MAE so với điểm người (chỉ điểm tổng, thang 0-10; điểm tổng AI có sàn 2.0 còn người tới 0, nên đây chỉ là mức lệch, không phải độ chính xác):")
    h = a["id"].map(human).to_numpy(float)
    for name, d in (("temperature 0.2", a), ("temperature 0", b)):
        ai = (d["overall_1"].to_numpy(float) + d["overall_2"].to_numpy(float)) / 2
        p(f"  {name:<16}: MAE = {np.mean(np.abs(ai - h)):.2f} | lệch TB có dấu (AI - người) = {np.mean(ai - h):+.2f} | r = {fmt(pearson(ai, h))}")
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=["vi", "en", "both", "vi_t0", "temp"], default="vi",
                        help="both = vi + en + so sanh; temp = vi_t0 + so sanh temperature 0 vs 0.2")
    args = parser.parse_args()

    sample_ids = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    human = pd.read_csv(VI_CSV_PATH).assign(id=lambda d: d["id"].astype(str)).set_index("id")["overall_quality_score_10"]

    langs = {"both": ["vi", "en"], "temp": ["vi", "vi_t0"]}.get(args.lang, [args.lang])
    pairs_by_lang, all_lines = {}, []
    for lang in langs:
        lines, pairs = analyze_language(lang, sample_ids, human)
        pairs_by_lang[lang] = pairs
        all_lines += lines + [""]
    if args.lang == "both":
        all_lines += compare_languages(pairs_by_lang["vi"], pairs_by_lang["en"])
    if args.lang == "temp":
        all_lines += compare_temperatures(pairs_by_lang["vi"], pairs_by_lang["vi_t0"], human)

    text = "\n".join(all_lines)
    print(text)
    (REPORT_DIR / f"variance_report_{args.lang}.txt").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
