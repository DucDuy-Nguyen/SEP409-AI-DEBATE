"""
Doc ket qua dot kiem tra v2 (docs/AI_DEVELOPMENT_LOG.md muc 3.14.1) theo QUY TAC DA CHOT TRUOC KHI CHAY. Khong goi API.

Du lieu moi:  data/vi_v2_variance_results.jsonl (50 bai Dagstuhl VI x 3 lan)  +  data/high_quality_probe_v2_results.jsonl (10 bai x 3 lan)
Moc cu:       tinh lai tu 4 lan lap VI cu (t0.2 x2 + t0 x2) duoi cong thuc B (dung cach tinh o muc 3.12.2 / 3.11.2 / 3.13)

D1 Evidence khong bi don cuc: SD giua bai cua Evidence >= 0.60 (moc cu 0.46) VA r Evidence-sufficiency >= 0.43
D2 Probe: hq01, hq02, hq05 moi bai Evidence >= 4 o it nhat 2/3 luot; ctrl01 Evidence <= 2 o ca 3 luot; TB diem tong 8 hq - TB ctrl02 >= 1.5 (moc cu 1.16)
D3 Khong lam hong: r diem tong voi overall_quality_score_10 >= 0.55 (moc cu 0.565) VA SD gop mot lan cham <= 0.70 (moc cu 0.637)
Quyet dinh: dat ca D1,D2,D3 -> GIU Evidence moi; truot D1 hoac D2 -> BO Evidence moi (giu B voi mo ta Evidence cu); truot D3 (du dat D1,D2) -> DUNG, bao lai.

Chay: python scripts/analyze_v2_check.py   (ghi v2_check_report.txt)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from analyze_ceiling_hypotheses import load_annotator_matrix  # noqa: E402
from analyze_replicates import CRITERIA, SAMPLE_PATH, VI_CSV_PATH, load_matrix  # noqa: E402
from analyze_weights import HQ_RUN1, HQ_RUN2, OPTIONS, option_score  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
NEW_DAGSTUHL = DATA_DIR / "vi_v2_variance_results.jsonl"
NEW_PROBE = DATA_DIR / "high_quality_probe_v2_results.jsonl"
REPORT_PATH = Path(__file__).parent.parent / "v2_check_report.txt"
EXPECTED_VERSION = "v2_4x25"

D1_SD_MIN, D1_R_MIN = 0.60, 0.43
D2_MIN_RUNS_OF_3, D2_GAP_MIN = 2, 1.5
D3_R_MIN, D3_SD_MAX = 0.55, 0.70
B_WEIGHTS = OPTIONS["B"][0]


def pearson(a, b) -> float:
    return float(np.corrcoef(a, b)[0, 1])


def read_ok(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()) if r.get("status") == "ok"]


def sigma_hat(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.var(axis=1, ddof=1))))


def sd_k2_holdout3(x: np.ndarray) -> float:
    """3 lan lap: k = 2 do duoc bang 'giu lai 1 lan': d = TB 2 lan - lan con lai, E[d^2] = 1.5 sigma^2 -> SD2 = sqrt(mean(d^2) / 3)."""
    ds = [x[:, [j for j in range(3) if j != h]].mean(axis=1) - x[:, h] for h in range(3)]
    return float(np.sqrt(np.mean(np.concatenate(ds) ** 2) / 3))


def sd_k2_pairings4(x: np.ndarray) -> float:
    """4 lan lap (du lieu cu): TB 3 cach chia cap roi nhau, SD2 = sqrt(mean(d^2) / 2)."""
    pairs = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]
    return float(np.mean([np.sqrt(np.mean((x[:, list(a)].mean(1) - x[:, list(b)].mean(1)) ** 2) / 2) for a, b in pairs]))


def matrix_from_records(recs: list[dict], ids: list[str], n_runs: int):
    by = {(r["id"], r["run"]): r for r in recs}
    keep = [i for i in ids if all((i, k) in by for k in range(1, n_runs + 1))]
    overall = np.array([[by[(i, k)]["overall_score"] for k in range(1, n_runs + 1)] for i in keep], float)
    crit = {c: np.array([[by[(i, k)]["criteria"][c] for k in range(1, n_runs + 1)] for i in keep], float) for c in CRITERIA}
    return keep, overall, crit


def hist_line(values: np.ndarray) -> str:
    flat = values.ravel().astype(int)
    total = len(flat)
    return " | ".join(f"{lvl}: {int((flat == lvl).sum())} ({(flat == lvl).mean() * 100:.0f}%)" for lvl in range(1, 6)) + f"  [n={total}]"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sample_ids = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    human_df = pd.read_csv(VI_CSV_PATH).assign(id=lambda d: d["id"].astype(str)).set_index("id")
    human_overall = human_df.loc[sample_ids, "overall_quality_score_10"].to_numpy(float)
    ann = load_annotator_matrix()
    ids_ok = [i for i in sample_ids if i in ann["sufficiency"] and not np.isnan(ann["sufficiency"][i]).any()]
    suff = human_df["sufficiency_score_10"]
    pos = {i: k for k, i in enumerate(sample_ids)}
    out: list[str] = []
    p = out.append

    # ------------------------------------------------------------------ moc cu duoi cong thuc B
    old = load_matrix(sample_ids)
    old_crit = {c: old[c] for c in CRITERIA}
    old_overall_b = option_score(old_crit, B_WEIGHTS, None)                  # (50, 4)
    old_ev = old["Evidence"]
    old_sd_between = float(np.std(old_ev.mean(axis=1), ddof=1))
    old_r_ev = pearson(pd.Series(old_ev.mean(axis=1), index=sample_ids)[ids_ok].to_numpy(), suff[ids_ok].to_numpy())
    old_r_overall = pearson(old_overall_b.mean(axis=1), human_overall)
    old_sigma = sigma_hat(old_overall_b)
    hq_old = [r for r in read_ok(HQ_RUN1) + read_ok(HQ_RUN2) if not r["id"].lower().startswith("ctrl")]
    c2_old = [r for r in read_ok(HQ_RUN1) if r["id"] == "ctrl02"]
    old_gap = (float(np.mean([option_score({c: r["criteria"][c] for c in CRITERIA}, B_WEIGHTS, None) for r in hq_old]))
               - float(np.mean([option_score({c: r["criteria"][c] for c in CRITERIA}, B_WEIGHTS, None) for r in c2_old])))

    p("DOT KIEM TRA v2 — doc theo quy tac da chot truoc khi chay (docs/AI_DEVELOPMENT_LOG.md muc 3.14.1). Khong goi API.")
    p("")
    p("MOC CU (prompt cu, 4 lan lap VI, tinh lai duoi cong thuc B): "
      f"SD giua bai Evidence = {old_sd_between:.3f} (ky vong ~0.46) | r Evidence-sufficiency = {old_r_ev:.3f} (n={len(ids_ok)}; ky vong ~0.43) | "
      f"r diem tong = {old_r_overall:.3f} (ky vong ~0.565) | SD gop 1 lan = {old_sigma:.3f} (ky vong ~0.637) | khoang cach hq - ctrl02 = {old_gap:.2f} (ky vong ~1.16)")

    # ------------------------------------------------------------------ du lieu moi
    new_recs = read_ok(NEW_DAGSTUHL)
    probe_recs = read_ok(NEW_PROBE)
    versions = {r.get("scoring_version") for r in new_recs + probe_recs}
    p(f"scoring_version trong ban ghi moi: {sorted(map(str, versions))} (phai la ['{EXPECTED_VERSION}'])")
    if (new_recs or probe_recs) and versions != {EXPECTED_VERSION}:
        print(chr(10).join(out))
        raise SystemExit(f"LOI: ban ghi moi co scoring_version khac {EXPECTED_VERSION} (hoac thieu) -> tron hai thang diem, KHONG ra quyet dinh")
    keep, overall_new, crit_new = matrix_from_records(new_recs, sample_ids, 3)
    p(f"Dagstuhl moi: {len(keep)}/{len(sample_ids)} bai du 3 luot ({len(new_recs)} luot hop le).")
    d1 = d2 = d3 = None
    out_sections: list[str] = []

    if len(keep) == len(sample_ids):
        # kiem tra diem tong da luu khop cong thuc B tinh lai tu cac diem tieu chi
        recomputed = option_score(crit_new, B_WEIGHTS, None)
        p(f"Kiem tra: max |overall luu - cong thuc B tinh lai| = {np.max(np.abs(recomputed - overall_new)):.4f} (phai ~0)")
        ev = crit_new["Evidence"]
        sd_between = float(np.std(ev.mean(axis=1), ddof=1))
        r_ev = pearson(pd.Series(ev.mean(axis=1), index=keep)[ids_ok].to_numpy(), suff[ids_ok].to_numpy())
        r_ev50 = pearson(ev.mean(axis=1), suff[keep].to_numpy())
        d1 = sd_between >= D1_SD_MIN and r_ev >= D1_R_MIN
        r_overall = pearson(overall_new.mean(axis=1), human_overall[[pos[i] for i in keep]])
        sigma = sigma_hat(overall_new)
        d3 = r_overall >= D3_R_MIN and sigma <= D3_SD_MAX
        sd2 = sd_k2_holdout3(overall_new)
        out_sections.append("")
        out_sections.append("=== D1 — Evidence khong bi don cuc (50 bai Dagstuhl) ===")
        out_sections.append(f"SD giua bai cua Evidence (TB 3 luot) = {sd_between:.3f}  (nguong >= {D1_SD_MIN}; moc cu {old_sd_between:.3f}, TB 4 luot) -> {'DAT' if sd_between >= D1_SD_MIN else 'TRUOT'}")
        out_sections.append(f"r Evidence-sufficiency = {r_ev:.3f} tren {len(ids_ok)} bai du 3 nguoi cham (nguong >= {D1_R_MIN}; moc cu {old_r_ev:.3f}) -> {'DAT' if r_ev >= D1_R_MIN else 'TRUOT'}"
                             f"   [tham khao: tren ca {len(keep)} bai r = {r_ev50:.3f}]")
        out_sections.append(f"D1: {'DAT' if d1 else 'TRUOT'}")
        out_sections.append("")
        out_sections.append("=== D3 — Khong lam hong phan dang tot (50 bai Dagstuhl) ===")
        out_sections.append(f"r diem tong voi overall_quality_score_10 = {r_overall:.3f}  (nguong >= {D3_R_MIN}; moc cu {old_r_overall:.3f}) -> {'DAT' if r_overall >= D3_R_MIN else 'TRUOT'}")
        out_sections.append(f"SD gop mot lan cham (sigma-hat, 3 luot) = {sigma:.3f}  (nguong <= {D3_SD_MAX}; moc cu {old_sigma:.3f}) -> {'DAT' if sigma <= D3_SD_MAX else 'TRUOT'}")
        out_sections.append(f"D3: {'DAT' if d3 else 'TRUOT'}")
        out_sections.append("")
        out_sections.append("=== SD gop theo so lan cham (diem tong, thang 0-10) ===")
        out_sections.append(f"k = 1: {sigma:.3f}  (do duoc: sigma-hat tu 3 luot)   | cu (B, 4 luot): {old_sigma:.3f}")
        out_sections.append(f"k = 2: {sd2:.3f}  (do duoc, 'giu lai 1 lan')          | cu (B, 4 luot, 3 cach ghep cap): {sd_k2_pairings4(old_overall_b):.3f}")
        out_sections.append(f"k = 3: {sigma / np.sqrt(3):.3f}  (LY THUYET sigma-hat / sqrt(3), khong co lan nao de doi chieu)  | cu: {old_sigma / np.sqrt(3):.3f} (ly thuyet)")
        out_sections.append("")
        out_sections.append("=== Histogram Evidence 1-5 ===")
        out_sections.append("cu  (4 lan lap VI x 50 bai): " + hist_line(old_ev))
        out_sections.append("moi (3 lan x 50 bai):        " + hist_line(ev))
        out_sections.append("Histogram cac tieu chi khac (moi): " + "; ".join(f"{c}: {np.bincount(crit_new[c].ravel().astype(int), minlength=6)[1:].tolist()}" for c in CRITERIA if c != "Evidence"))
    else:
        out_sections.append("")
        out_sections.append("D1 va D3: CHUA DU DU LIEU (can du 50 bai x 3 luot).")

    # ------------------------------------------------------------------ D2 probe
    p_ids = sorted({r["id"] for r in probe_recs})
    pk, p_overall, p_crit = matrix_from_records(probe_recs, p_ids, 3)
    out_sections.append("")
    out_sections.append("=== D2 — Probe (10 bai x 3 luot) ===")
    if {"hq01", "hq02", "hq05", "ctrl01", "ctrl02"} <= set(pk) and len([i for i in pk if not i.startswith("ctrl")]) == 8:
        row = {i: k for k, i in enumerate(pk)}
        ev_p = p_crit["Evidence"]
        counts = {i: int((ev_p[row[i]] >= 4).sum()) for i in ("hq01", "hq02", "hq05")}
        ok_hq = all(c >= D2_MIN_RUNS_OF_3 for c in counts.values())
        ctrl01_runs = ev_p[row["ctrl01"]].astype(int).tolist()
        ok_ctrl = all(v <= 2 for v in ctrl01_runs)
        hq_idx = [row[i] for i in pk if not i.startswith("ctrl")]
        gap = float(p_overall[hq_idx].mean() - p_overall[row["ctrl02"]].mean())
        ok_gap = gap >= D2_GAP_MIN
        d2 = ok_hq and ok_ctrl and ok_gap
        out_sections.append("Evidence >= 4 o bao nhieu trong 3 luot: " + ", ".join(f"{i}: {c}/3" for i, c in counts.items())
                            + f"  (can >= {D2_MIN_RUNS_OF_3}/3 moi bai) -> {'DAT' if ok_hq else 'TRUOT'}")
        out_sections.append(f"ctrl01 Evidence ca 3 luot = {ctrl01_runs} (can ca 3 <= 2) -> {'DAT' if ok_ctrl else 'TRUOT'}")
        out_sections.append(f"TB diem tong 8 hq (24 luot) = {p_overall[hq_idx].mean():.2f}, TB ctrl02 (3 luot) = {p_overall[row['ctrl02']].mean():.2f}, khoang cach = {gap:.2f}"
                            f"  (nguong >= {D2_GAP_MIN}; moc cu {old_gap:.2f}) -> {'DAT' if ok_gap else 'TRUOT'}")
        out_sections.append(f"D2: {'DAT' if d2 else 'TRUOT'}")
        out_sections.append("Evidence 3 luot tung bai: " + "; ".join(f"{i} {ev_p[row[i]].astype(int).tolist()}" for i in pk))
        out_sections.append("Diem tong 3 luot tung bai: " + "; ".join(f"{i} {p_overall[row[i]].round(1).tolist()}" for i in pk))
    else:
        out_sections.append(f"CHUA DU DU LIEU (bai du 3 luot: {pk}).")

    # ------------------------------------------------------------------ quyet dinh
    if d1 is False or d2 is False:
        decision = "BO Evidence moi, giu cong thuc B voi mo ta Evidence cu (truot D1 hoac D2)"
    elif None in (d1, d2, d3):
        decision = "CHUA QUYET DINH DUOC: thieu du lieu"
    elif d3 is False:
        decision = "DUNG, bao lai, chua quyet dinh (D1 va D2 dat nhung truot D3)"
    else:
        decision = "GIU Evidence moi (dat ca D1, D2, D3)"
    p("")
    p("TOM TAT: D1 = " + {True: "DAT", False: "TRUOT", None: "?"}[d1] + " | D2 = " + {True: "DAT", False: "TRUOT", None: "?"}[d2]
      + " | D3 = " + {True: "DAT", False: "TRUOT", None: "?"}[d3])
    out.extend(out_sections)
    p("")
    p(f"QUYET DINH THEO QUY TAC: {decision}")

    text = chr(10).join(out)
    print(text)
    REPORT_PATH.write_text(text + chr(10), encoding="utf-8")


if __name__ == "__main__":
    main()
