"""
So sanh 2 cach tinh overall_score — Holistic (AI tu cham doc lap, dang dung
trong production) vs Formula (cong thuc cu: tong 5 tieu chi con / 25 * 10) —
TREN CUNG 1 bo du lieu DA CHAM SAN trong dagstuhl_agreement_results.xlsx
(tu scripts/run_dagstuhl_agreement_eval.py). KHONG goi API them lan nao —
chi tinh lai tu du lieu co san.

BOI CANH: r=0.585 (Overall, n=22) giua AI holistic va nguoi that co the la
do (A) ban than cach tinh holistic tot hon cong thuc cong trung binh, HOAC
(B) chi vi Dagstuhl khop dung khai niem voi rubric ADPP (khong lien quan gi
den cach tong hop 5 diem thanh 1 diem). Script nay tach 2 gia thuyet do:
neu Formula (tinh lai tu CHINH 5 tieu chi con AI da cham — khong doi gi ca
o buoc cham chi tiet) cho r TUONG DUONG hoac TOT HON Holistic, gia thuyet B
dung (van de khong nam o cach tong hop). Neu Formula cho r KEM HON RO RET,
gia thuyet A co co so hon.

QUAN TRONG VE DU LIEU: file Excel nguon CHI luu san cot "... - AI avg" cho
tung tieu chi da o thang 0-10 (da quy doi + trung binh qua cac lan chay boi
run_dagstuhl_agreement_eval.py), KHONG con luu diem 1-5 goc cua tung lan
chay. De ap dung dung cong thuc cu (von dinh nghia tren thang 1-5), script
nay suy nguoc ve thang 1-5 bang chinh phep bien doi NGHICH DAO cua cong thuc
da dùng khi tao file nay (score_10 = (score_5 - 1) / 4 * 10, xem
_ai_criterion_1_5_to_10 trong run_dagstuhl_agreement_eval.py):
    score_5 = score_10 * 0.4 + 1
Vi ca phep quy doi 1-5->0-10 lan phep trung binh nhieu lan chay DEU TUYEN
TINH (giao hoan voi nhau), ket qua nay TUONG DUONG TOAN HOC voi viec tinh
cong thuc cu truc tiep tren diem 1-5 tho cua tung lan chay roi moi trung
binh — khong phai xap xi.

Cach dung (khong can tham so dong lenh, doc thang file Excel co san):
    python scripts/compare_overall_score_methods.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from scipy import stats

INPUT_PATH = Path(__file__).parent.parent / "dagstuhl_agreement_results.xlsx"
SHEET_NAME = "Agreement Results"

# Ten cot THAT trong file (da xac nhan bang cach doc header truoc, khong doan).
COL_HOLISTIC_AI = "Overall (overall_score vs ArgumentationQuality) - AI avg"
COL_HUMAN = "Overall (overall_score vs ArgumentationQuality) - Human"
COL_ERROR = "Error"

CRITERION_AI_COLUMNS = {
    "Logic": "Logic vs Cogency - AI avg",
    "Evidence": "Evidence vs LocalSufficiency - AI avg",
    "Relevance": "Relevance vs GlobalRelevance - AI avg",
    "Structure": "Structure vs Arrangement - AI avg",
    "Persuasiveness": "Persuasiveness vs Effectiveness - AI avg",
}

REQUIRED_COLUMNS = [COL_HOLISTIC_AI, COL_HUMAN] + list(CRITERION_AI_COLUMNS.values())

SIGNIFICANT_DIFF_THRESHOLD = 1.0


def _score_10_to_5(score_10: float) -> float:
    """Nghich dao chinh xac cua _ai_criterion_1_5_to_10 trong
    run_dagstuhl_agreement_eval.py: score_10 = (score_5 - 1) / 4 * 10."""
    return score_10 * 0.4 + 1


def load_and_validate(path: Path, sheet_name: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Khong tim thay {path}. Chay scripts/run_dagstuhl_agreement_eval.py truoc de tao file nay."
        )
    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")

    print(f"Da doc sheet '{sheet_name}' tu {path.name} — {len(df)} dong.")
    print(f"Danh sach cot THAT tim thay ({len(df.columns)} cot):")
    for col in df.columns:
        print(f"  - {col!r}")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"Sheet '{sheet_name}' thieu cac cot bat buoc: {missing}.\n"
            f"Danh sach cot THAT: {list(df.columns)}"
        )
    return df


def compute_metrics(human_scores: list[float], ai_scores: list[float]) -> dict:
    n = len(human_scores)
    if n < 2:
        return {"n": n, "pearson_r": None, "p_value": None, "mae": None}
    r_val, p_val = stats.pearsonr(human_scores, ai_scores)
    mae = sum(abs(h - a) for h, a in zip(human_scores, ai_scores)) / n
    return {"n": n, "pearson_r": round(r_val, 3), "p_value": round(p_val, 4), "mae": round(mae, 2)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    df = load_and_validate(INPUT_PATH, SHEET_NAME)

    # Chi giu dong hop le: khong co Error, va co du CA 6 gia tri can dung
    # (1 holistic + 5 tieu chi con) + diem nguoi.
    has_error = df[COL_ERROR].notna() & (df[COL_ERROR].astype(str).str.strip() != "")
    valid = df[~has_error].dropna(subset=REQUIRED_COLUMNS).reset_index(drop=True)

    n_total = len(df)
    n_valid = len(valid)
    print(f"\nSo dong hop le de phan tich: {n_valid}/{n_total} (loai dong co Error hoac thieu du lieu).")

    human_scores = valid[COL_HUMAN].astype(float).tolist()
    holistic_scores = valid[COL_HOLISTIC_AI].astype(float).tolist()

    formula_scores = []
    for _, row in valid.iterrows():
        scores_5 = [_score_10_to_5(float(row[col])) for col in CRITERION_AI_COLUMNS.values()]
        formula_10 = sum(scores_5) / 25 * 10
        formula_scores.append(round(formula_10, 2))

    holistic_metrics = compute_metrics(human_scores, holistic_scores)
    formula_metrics = compute_metrics(human_scores, formula_scores)

    print("\n=== BANG SO SANH 2 CACH TINH overall_score (vs nguoi that, cung du lieu) ===")
    header = f"{'Cach tinh':<45} {'N':>4} {'Pearson r':>10} {'p-value':>10} {'MAE':>8}"
    print(header)
    print("-" * len(header))
    print(
        f"{'Holistic (AI tu cham doc lap)':<45} "
        f"{holistic_metrics['n']:>4} {holistic_metrics['pearson_r']!s:>10} "
        f"{holistic_metrics['p_value']!s:>10} {holistic_metrics['mae']!s:>8}"
    )
    print(
        f"{'Formula (tong 5 tieu chi con / 25 * 10)':<45} "
        f"{formula_metrics['n']:>4} {formula_metrics['pearson_r']!s:>10} "
        f"{formula_metrics['p_value']!s:>10} {formula_metrics['mae']!s:>8}"
    )

    # Phan tich bo sung: lech giua 2 cach tinh O TUNG BAI (khong chi o muc thong ke tong).
    diffs = [abs(f - h) for f, h in zip(formula_scores, holistic_scores)]
    n_significant = sum(1 for d in diffs if d > SIGNIFICANT_DIFF_THRESHOLD)
    pct_significant = round(100 * n_significant / len(diffs), 1) if diffs else None

    print(
        f"\n=== LECH GIUA 2 CACH TINH O TUNG BAI (|Formula - Holistic| > {SIGNIFICANT_DIFF_THRESHOLD}) ==="
    )
    print(f"So bai lech > {SIGNIFICANT_DIFF_THRESHOLD} diem: {n_significant}/{len(diffs)} ({pct_significant}%)")
    if diffs:
        print(f"Lech trung binh (MAE giua 2 cach tinh): {round(sum(diffs) / len(diffs), 2)}")
        print(f"Lech lon nhat quan sat duoc: {round(max(diffs), 2)}")

    r_holistic = holistic_metrics["pearson_r"]
    r_formula = formula_metrics["pearson_r"]
    if r_holistic is not None and r_formula is not None:
        r_diff = round(r_formula - r_holistic, 3)
        direction = "TOT HON" if r_diff > 0 else ("KEM HON" if r_diff < 0 else "NGANG")
        print(
            f"\nKET LUAN SO BO: Formula co r {direction} Holistic {abs(r_diff)} diem "
            f"(r_formula={r_formula} vs r_holistic={r_holistic})."
        )
        if r_diff >= -0.05:
            print(
                "-> Ung ho GIA THUYET B: van de khong nam o cach tong hop (holistic vs formula), "
                "ma o viec Dagstuhl khop khai niem voi rubric ADPP."
            )
        else:
            print(
                "-> Ung ho GIA THUYET A: cach tong hop holistic thuc su tot hon formula, "
                "khong chi la trung hop tu Dagstuhl."
            )


if __name__ == "__main__":
    main()
