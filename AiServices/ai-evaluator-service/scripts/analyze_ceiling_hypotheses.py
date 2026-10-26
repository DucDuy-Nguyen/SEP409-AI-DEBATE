"""
Kiem tra OFFLINE (khong goi API) cac gia thuyet H1-H4 ve "tran diem" Evidence/Persuasiveness
(xem docs/AI_DEVELOPMENT_LOG.md muc 3.11.1). Dung du lieu da co:
- 300 luot cham AI: data/vi_variance_results.jsonl (t0.2), vi_t0_variance_results.jsonl, en_variance_results.jsonl
- diem tung nguoi cham cua Dagstuhl (CSV goc, 3 nguoi cham chung 320 bai) va diem TB (dagstuhl_processed_vi.csv)

Noi dung:
 (a) Do dong thuan giua nguoi theo tung chieu -> TRAN THAM CHIEU cho tuong quan AI-nguoi
 H1  Persuasiveness co phai la ham cua cac tieu chi khac khong
 H2  Evidence thap vi van ban khong co dau hieu bang chung? (bao so bai co dau hieu TRUOC khi so)
 H3  Lech khai niem Evidence (AI) vs local sufficiency (nguoi)
 H4  Duong hieu chuan: diem nguoi TB theo tung muc diem AI
Chay: python scripts/analyze_ceiling_hypotheses.py   (ghi ceiling_hypotheses_report.txt, data/_h3_audit.txt)
"""
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_dagstuhl_agreement_eval import RAW_CSV_ENCODING, RAW_CSV_PATH, _parse_score_label  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
SAMPLE_PATH = DATA_DIR / "_dagstuhl_vi_sample50.json"
VI_CSV_PATH = DATA_DIR / "dagstuhl_processed_vi.csv"
REPORT_PATH = Path(__file__).parent.parent / "ceiling_hypotheses_report.txt"
AUDIT_PATH = DATA_DIR / "_h3_audit.txt"
SOURCES = {"vi_t02": DATA_DIR / "vi_variance_results.jsonl", "vi_t0": DATA_DIR / "vi_t0_variance_results.jsonl",
           "en_t02": DATA_DIR / "en_variance_results.jsonl"}

CRITERIA = ["Logic", "Evidence", "Relevance", "Structure", "Persuasiveness"]
PAIRS = [  # (ten AI, cot human processed, cot trong CSV goc)
    ("overall", "overall_quality", "overall quality"), ("Logic", "cogency", "cogency"),
    ("Evidence", "sufficiency", "sufficiency"), ("Relevance", "global_relevance", "global relevance"),
    ("Structure", "arrangement", "arrangement"), ("Persuasiveness", "effectiveness", "effectiveness"),
]
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 42
MIN_MARKER_ARTICLES = 8  # duoi muc nay: khong ket luan duoc (yeu cau cua nguoi dung)

URL_RE = re.compile(r"https?://|www\.", re.I)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\b\d{2,}\b")
# Hep co chu y (bo 'data', 'report', 'expert' vi de duong tinh gia): chi tu nguon ro rang.
SOURCE_RE = re.compile(r"\b(?:study|studies|research|survey|poll|statistics?|according to|scientists?)\b", re.I)


# ---------------------------------------------------------------- tai du lieu
def load_ai_runs() -> pd.DataFrame:
    rows = []
    for src, path in SOURCES.items():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r["status"] == "ok":
                    rows.append({"src": src, "lang": src.split("_")[0], "id": r["id"], "run": r["run"],
                                 "overall": r["overall_score"], **r["criteria"], "raw": r.get("raw_model_output")})
    return pd.DataFrame(rows)


def load_annotator_matrix() -> dict[str, dict[str, np.ndarray]]:
    """dim -> {id: [score_annotator1, 2, 3]} (nan neu khong co diem hop le)."""
    with open(RAW_CSV_PATH, "r", newline="", encoding=RAW_CSV_ENCODING) as f:
        reader = csv.reader(f, delimiter="\t")
        header = [h.strip().lower() for h in next(reader)]
        idx = {h: i for i, h in enumerate(header)}
        out = {raw: {} for _, _, raw in PAIRS}
        for row in reader:
            if len(row) <= max(idx.values()):
                continue
            aid, ann = row[idx["#id"]].strip(), int(row[idx["annotator"]].strip())
            for _, _, raw in PAIRS:
                try:
                    v = _parse_score_label(row[idx[raw]])
                except ValueError:
                    v = None
                out[raw].setdefault(aid, np.full(3, np.nan))[ann - 1] = np.nan if v is None else v
    return out


# ---------------------------------------------------------------- thong ke
def icc_anova(x: np.ndarray) -> tuple[float, float, float]:
    """x: (n, k) day du. Tra ve (ICC(2,1), ICC(2,k), ICC(3,k)) theo Shrout & Fleiss."""
    n, k = x.shape
    grand, rm, cm = x.mean(), x.mean(axis=1), x.mean(axis=0)
    msr = k * np.sum((rm - grand) ** 2) / (n - 1)
    msc = n * np.sum((cm - grand) ** 2) / (k - 1)
    mse = np.sum((x - rm[:, None] - cm[None, :] + grand) ** 2) / ((n - 1) * (k - 1))
    return (float((msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n)),
            float((msr - mse) / (msr + (msc - mse) / n)), float((msr - mse) / msr) if msr > 0 else float("nan"))


def boot(stat, x: np.ndarray) -> tuple[float, float]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n = len(x)
    vals = [stat(x[rng.integers(0, n, n)]) for _ in range(N_BOOTSTRAP)]
    vals = [v for v in vals if not np.isnan(v)]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def pav_increasing(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Hoi quy don dieu tang (pool-adjacent-violators), co trong so."""
    blocks = [[y[i], w[i], 1] for i in range(len(y))]
    out: list[list[float]] = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][0] > out[-1][0]:
            b2, b1 = out.pop(), out.pop()
            wsum = b1[1] + b2[1]
            out.append([(b1[0] * b1[1] + b2[0] * b2[1]) / wsum, wsum, b1[2] + b2[2]])
    fitted = []
    for val, _, cnt in out:
        fitted += [val] * int(cnt)
    return np.array(fitted)


def r2_of(y: np.ndarray, X: np.ndarray) -> float:
    A = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    ss_res = float(np.sum((y - A @ beta) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def fmt(x, nd=2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sample_ids = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    ai = load_ai_runs()
    vi = pd.read_csv(VI_CSV_PATH).assign(id=lambda d: d["id"].astype(str)).set_index("id")
    ann = load_annotator_matrix()
    out: list[str] = []
    p = out.append
    sample = vi.loc[sample_ids]

    # bai-mean cua AI: VI 4 lan (t0.2 x2 + t0 x2), EN 2 lan
    ai_cols = ["overall"] + CRITERIA
    vi_mean = ai[ai.lang == "vi"].groupby("id")[ai_cols].mean().loc[sample_ids]
    en_mean = ai[ai.lang == "en"].groupby("id")[ai_cols].mean().loc[sample_ids]
    all_mean = ai.groupby("id")[ai_cols].mean().loc[sample_ids]
    p(f"Offline, khong goi API. {len(ai)} luot cham AI ({', '.join(f'{k}: {int((ai.src == k).sum())}' for k in SOURCES)}), {len(sample_ids)} bai.")

    # ============================================================ (a)
    p("")
    p("=" * 100)
    p("(a) DONG THUAN GIUA NGUOI CHAM THEO CHIEU -> TRAN THAM CHIEU CHO TUONG QUAN AI-NGUOI")
    p("=" * 100)
    p("3 nguoi cham (id 1,2,3) chung cho ca 320 bai (thiet ke cheo day du). Chi dung bai ca 3 nguoi deu co diem hop le cho chieu do.")
    p("ICC(2,1): dong thuan tuyet doi cua MOT nguoi cham. Do tin cay cua TB 3 nguoi = ICC(3,3) (nhat quan, hop voi tuong quan);")
    p("TRAN tuong quan AI-nguoi = sqrt(ICC(3,3)) (neu AI do hoan hao cung dai luong that thi r(AI, TB nguoi) khong the vuot muc nay).")
    p("")
    p(f"{'chieu (nguoi)':<18}{'n':>4}{'ICC(2,1) [CI 95%]':>24}{'ICC(3,3)':>10}{'TRAN r':>8}{'r Pearson vi':>14}{'r Pearson en':>14}{'r Spearman vi':>15}{'r Spearman en':>15}{'vi/tran':>9}{'en/tran':>9}")
    ceilings, humdist = {}, {}
    for ai_name, proc, raw in PAIRS:
        ids_ok = [i for i in sample_ids if i in ann[raw] and not np.isnan(ann[raw][i]).any()]
        mat = np.array([ann[raw][i] for i in ids_ok])
        icc21, _, icc33 = icc_anova(mat)
        lo, hi = boot(lambda z: icc_anova(z)[0], mat)
        ceil = float(np.sqrt(max(icc33, 0)))
        ceilings[ai_name] = ceil
        # r AI-nguoi tinh tren CUNG tap bai da dung de tinh tran (du 3 nguoi cham hop le), de ty le r/tran so sanh duoc
        h = sample.loc[ids_ok, f"{proc}_score_10"]
        rv, re_ = vi_mean.loc[ids_ok, ai_name].corr(h), en_mean.loc[ids_ok, ai_name].corr(h)
        sv, se = vi_mean.loc[ids_ok, ai_name].corr(h, method="spearman"), en_mean.loc[ids_ok, ai_name].corr(h, method="spearman")
        p(f"{ai_name + ' ~ ' + proc:<18}{len(ids_ok):>4}{(fmt(icc21) + ' [' + fmt(lo) + ', ' + fmt(hi) + ']'):>24}{fmt(icc33):>10}{fmt(ceil):>8}"
          f"{fmt(rv):>14}{fmt(re_):>14}{fmt(sv):>15}{fmt(se):>15}{fmt(rv / ceil):>9}{fmt(re_ / ceil):>9}")
        # phan bo diem tung nguoi: ty le 'High' (3)
        allr = np.concatenate([v[~np.isnan(v)] for v in ann[raw].values()])
        sr = np.concatenate([ann[raw][i][~np.isnan(ann[raw][i])] for i in sample_ids if i in ann[raw]])
        humdist[ai_name] = (np.mean(allr == 3) * 100, np.mean(sr == 3) * 100, len(allr), len(sr))
    p("(r dung diem AI trung binh theo bai: vi = 4 lan, en = 2 lan, so voi diem TB nguoi, tren cung n bai voi cot n; vi/tran = r / tran.)")
    p("")
    p("Ty le diem 'High' (3) trong TUNG LAN cham cua nguoi (y nghia cho H8: nguoi co cho nhieu diem cao o chieu nay khong?):")
    for k, (all_p, smp_p, n_all, n_smp) in humdist.items():
        p(f"  {k:<15}: 320 bai {all_p:4.1f}% ({n_all} luot cham) | mau 50 bai {smp_p:4.1f}% ({n_smp} luot cham)")

    # ============================================================ H1
    p("")
    p("=" * 100)
    p("H1. Persuasiveness co phai la ham cua cac tieu chi khac (rubric: 'xet tren tong hoa cac tieu chi tren')?")
    p("=" * 100)
    runs = ai.copy()
    others = runs[["Logic", "Evidence", "Relevance", "Structure"]]
    diff = runs["Persuasiveness"] - others.mean(axis=1)
    p(f"{len(runs)} luot cham. Persuasiveness - TB(Logic, Evidence, Relevance, Structure): TB {diff.mean():+.2f}, SD {diff.std():.2f}")
    p(f"  Pers < TB cac tieu chi khac: {np.mean(diff < -1e-9) * 100:.0f}% | bang: {np.mean(np.abs(diff) <= 1e-9) * 100:.0f}% | > : {np.mean(diff > 1e-9) * 100:.0f}% ; "
      f"|diff| <= 0.5: {np.mean(np.abs(diff) <= 0.5) * 100:.0f}%")
    p("  R^2 khi hoi quy MOI tieu chi tren 4 tieu chi con lai (kiem soat: Persuasiveness co dac biet hon cac tieu chi khac khong?):")
    for c in CRITERIA:
        rest = [x for x in CRITERIA if x != c]
        p(f"    {c:<15}: R^2 = {r2_of(runs[c].to_numpy(float), runs[rest].to_numpy(float)):.2f}"
          f" (tren {len(runs)} luot) | {r2_of(all_mean[c].to_numpy(float), all_mean[rest].to_numpy(float)):.2f} (tren 50 bai, TB cac luot)")
    p("  Bang cheo Evidence (hang) x Persuasiveness (cot), so luot:")
    ct = pd.crosstab(runs["Evidence"], runs["Persuasiveness"])
    p("    " + ct.to_string().replace("\n", "\n    "))
    p(f"  Evidence lon nhat = {int(runs['Evidence'].max())}, Persuasiveness lon nhat = {int(runs['Persuasiveness'].max())}; "
      f"Pers > Evidence o {np.mean(runs['Persuasiveness'] > runs['Evidence']) * 100:.0f}% luot, Pers = Evidence o {np.mean(runs['Persuasiveness'] == runs['Evidence']) * 100:.0f}%")
    # text mining 100 raw EN
    raws = runs[runs["raw"].notna()]
    kw = {"bang chung": r"bằng chứng|dẫn chứng|chứng cứ", "logic": r"logic|suy luận|lập luận", "cau truc": r"cấu trúc", "lien quan": r"liên quan"}
    cnt = {k: 0 for k in kw}
    ctrl = {k: 0 for k in kw}
    nparse = 0
    for raw in raws["raw"]:
        try:
            cr = {c["name"]: c["reasoning"] for c in json.loads(raw)["criteria"]}
        except Exception:
            continue
        nparse += 1
        for k, pat in kw.items():
            cnt[k] += bool(re.search(pat, cr["Persuasiveness"], re.I))
            ctrl[k] += bool(re.search(pat, cr["Relevance"], re.I))
    p(f"  Phan tich van ban ly do ({nparse} response tho = 100 ban EN t0.2 + 100 ban VI t0; dot VI t0.2 cu khong luu response): ty le ly do co nhac tu khoa")
    p(f"    {'':<12}" + "".join(f"{k:>12}" for k in kw))
    p(f"    {'Persuasive.':<12}" + "".join(f"{cnt[k] / nparse * 100:>11.0f}%" for k in kw))
    p(f"    {'Relevance':<12}" + "".join(f"{ctrl[k] / nparse * 100:>11.0f}%" for k in kw) + "   (doi chung)")

    # ============================================================ H2
    p("")
    p("=" * 100)
    p("H2. Evidence thap vi van ban Dagstuhl khong co dau hieu bang chung?")
    p("=" * 100)
    text = sample["text"]
    has_url = text.map(lambda t: bool(URL_RE.search(t)))
    has_num = text.map(lambda t: bool(NUMBER_RE.search(t)))
    has_src = text.map(lambda t: bool(SOURCE_RE.search(t)))
    marker = has_url | has_num | has_src
    n_marker = int(marker.sum())
    p("Dau hieu bang chung (tren van ban tieng Anh goc): URL | so lieu (so >= 2 chu so hoac %) | tu nguon (study, research, survey, poll, statistics, according to, scientist).")
    p(f"SO BAI CO DAU HIEU (bao truoc khi so sanh): {n_marker}/{len(sample)}  [URL {int(has_url.sum())}, so lieu {int(has_num.sum())}, tu nguon {int(has_src.sum())}]")
    p("Tu khoa nguon da thu hep (study, research, survey, poll, statistics, according to, scientist) de han che duong tinh gia; so khop cua tung bai co dau hieu:")
    for i in marker.index[marker]:
        hits = []
        if URL_RE.search(text[i]):
            hits.append("URL")
        hits += [f"so:{m}" for m in NUMBER_RE.findall(text[i])[:3]]
        hits += [f"nguon:{m}" for m in SOURCE_RE.findall(text[i])[:3]]
        p(f"    {i}: " + ", ".join(hits))
    evi_vi, evi_en = vi_mean["Evidence"], en_mean["Evidence"]
    any3 = ai[ai["Evidence"] >= 3].groupby("id").size()
    if n_marker < MIN_MARKER_ARTICLES:
        p(f"=> {n_marker} < {MIN_MARKER_ARTICLES}: KHONG DU DE KET LUAN o mau 50 bai (so lieu duoi day chi de mo ta):")
    else:
        p("=> du bai de so sanh so bo (van la mau nho):")
    for name, m in (("co dau hieu", marker), ("khong co", ~marker)):
        ids_g = marker.index[m]
        p(f"  {name:<12}: n={len(ids_g):>2} | AI Evidence TB vi={fmt(float(evi_vi[ids_g].mean()))} en={fmt(float(evi_en[ids_g].mean()))}"
          f" | so bai co it nhat 1 luot Evidence>=3: {int(sum(i in any3.index for i in ids_g))}"
          f" | diem nguoi (sufficiency) TB={fmt(float(sample.loc[ids_g, 'sufficiency_score_10'].mean()))}")
    if n_marker:
        p("  Bai co dau hieu: " + ", ".join(f"{i}(vi {evi_vi[i]:.2f}/en {evi_en[i]:.2f}, nguoi {sample.loc[i, 'sufficiency_score_10']:.1f})" for i in marker.index[marker]))
    # bo sung: 316 bai, chi phia nguoi
    t_all = vi["text"]
    m_all = t_all.map(lambda t: bool(URL_RE.search(t) or NUMBER_RE.search(t) or SOURCE_RE.search(t)))
    p(f"Bo sung (chi phia NGUOI, khong can AI): tren 316 bai co {int(m_all.sum())} bai co dau hieu; sufficiency (nguoi) TB "
      f"co={fmt(float(vi.loc[m_all, 'sufficiency_score_10'].mean()))} vs khong={fmt(float(vi.loc[~m_all, 'sufficiency_score_10'].mean()))}")

    # ============================================================ H3
    p("")
    p("=" * 100)
    p("H3. Lech khai niem: Evidence (AI) vs local sufficiency (nguoi)")
    p("=" * 100)
    p("Dinh nghia goc trong annotation guidelines (data/_dagstuhl_raw/.../guidelines.pdf, trich tu PDF, ky tu ghep 'fi' bi loi hien thi):")
    p("  Local sufficiency: 'premises ... should be seen as sufficient if, together, they provide enough support to make it rational to draw the")
    p("    argument's conclusion ... sufficiency does not presuppose acceptability.'  (khong yeu cau vi du cu the hay so lieu)")
    p("  Effectiveness: 'effective if it achieves to persuade YOU of the author's stance ... or corroborates your agreement. Besides the actual")
    p("    arguments, also take into consideration the credibility and the emotional force ...; decide in dubio pro reo.'")
    p("  Prompt AI: Evidence = 'Lap luan co bang chung / vi du cu the ho tro, khong chi la khang dinh suong'; Persuasiveness = 'Kha nang thuyet phuc tong the, xet tren tong hoa cac tieu chi tren'.")
    h_suf = sample["sufficiency_score_10"]
    bins_h = pd.cut(h_suf, [-0.01, 3.34, 6.67, 10.01], labels=["nguoi <= 3.33", "nguoi (3.33, 6.67]", "nguoi > 6.67"])
    bins_a = pd.cut(vi_mean["Evidence"], [0, 1.5, 2.5, 5], labels=["AI Evidence <=1.5", "AI 1.5-2.5", "AI >2.5"])
    p("Bang cheo so bai (50 bai): diem nguoi 'sufficiency' (hang) x AI Evidence TB 4 lan VI (cot):")
    p("  " + pd.crosstab(bins_h, bins_a).to_string().replace("\n", "\n  "))
    p(f"Tuong quan Evidence (AI, VI 4 lan) ~ sufficiency (nguoi): Pearson {fmt(vi_mean['Evidence'].corr(h_suf))}, Spearman {fmt(vi_mean['Evidence'].corr(h_suf, method='spearman'))}"
      f" ; tran tham chieu {fmt(ceilings['Evidence'])} (muc (a))")
    cand = [i for i in sample_ids if sample.loc[i, "sufficiency_score_10"] >= 5.0 and all_mean.loc[i, "Evidence"] <= 1.5]
    p(f"Bai nguoi danh gia sufficiency >= 5.0 nhung AI Evidence TB (6 luot) <= 1.5: {len(cand)} bai -> ghi vao {AUDIT_PATH.name} de doc tay")
    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        f.write("H3 AUDIT: nguoi cho sufficiency cao (>=5.0) nhung AI Evidence thap (TB 6 luot <= 1.5)\n")
        for i in cand:
            f.write("=" * 90 + f"\nid={i} | nguoi sufficiency={sample.loc[i, 'sufficiency_score_10']:.2f} | AI Evidence TB={all_mean.loc[i, 'Evidence']:.2f}"
                    f" | dau hieu bang chung: {'co' if marker[i] else 'khong'}\n{sample.loc[i, 'text'][:600]}\n")

    # ============================================================ H4
    p("")
    p("=" * 100)
    p("H4. Duong hieu chuan: diem nguoi TB (thang 0-10) theo tung muc diem AI")
    p("=" * 100)
    p("Moi luot cham AI la 1 diem; diem nguoi la TB 3 nguoi cua bai do. Nguoi cham 3 muc (1-3) quy ve 0/5/10 (low/medium/high).")
    p("Hoi quy don dieu (PAV) co trong so la gia tri hieu chuan da lam tron. Muc it luot (n < 10) khong dang tin.")
    for ai_name, proc, _ in PAIRS:
        merged = ai.merge(vi[[f"{proc}_score_10"]].rename(columns={f"{proc}_score_10": "human"}), left_on="id", right_index=True)
        if ai_name == "overall":
            merged["lvl"] = pd.cut(merged["overall"], [0, 3, 4, 5, 6, 10], labels=["<3", "3-4", "4-5", "5-6", ">=6"])
        else:
            merged["lvl"] = merged[ai_name].astype(int)
        g = merged.groupby("lvl", observed=True)["human"].agg(["mean", "count"])
        fit = pav_increasing(g["mean"].to_numpy(), g["count"].to_numpy(float))
        hi_share = merged.groupby("lvl", observed=True)["human"].apply(lambda s: float(np.mean(s >= 6.67)) * 100)
        p(f"  {ai_name:<15}: " + " | ".join(f"AI {lvl}: nguoi {row['mean']:.1f} (n={int(row['count'])}, PAV {f:.1f}, {hi_share[lvl]:.0f}% bai nguoi>=6.67)"
                                            for (lvl, row), f in zip(g.iterrows(), fit)))
    p("(Neu 'nguoi' da cao (>= 6.67) o muc AI = 3 cua Evidence/Persuasiveness thi tran la lech thang -> xu ly bang anh xa; neu van thap thi khong.)")

    text_out = "\n".join(out)
    print(text_out)
    REPORT_PATH.write_text(text_out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
