"""
Doc ket qua dot XAC NHAN cau hinh cuoi (docs/AI_DEVELOPMENT_LOG.md muc 3.15) theo QUY TAC DA CHOT TRUOC KHI CHAY. Khong goi API.

Du lieu: data/vi_confirm_variance_results.jsonl (50 bai Dagstuhl VI x 2 lan)  +  data/high_quality_probe_confirm_results.jsonl (10 bai probe x 1 lan)
Quy tac:
  (1) r diem tong voi overall_quality_score_10 >= 0.55   (50 bai, trung binh 2 lan)
  (2) SD gop mot lan cham (diem tong) <= 0.70
  (3) TB diem tong 8 hq - TB ctrl02 >= 1.0
  Dat ca ba -> nhanh san sang. Truot bat ky dieu kien nao -> DUNG, khong commit app/, bao lai. KHONG tu chay lai de tim lan "dat".

Chay: python scripts/analyze_confirm.py [--expect-hash HASH]    (ghi confirm_report.txt)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze_replicates import CRITERIA, SAMPLE_PATH, VI_CSV_PATH  # noqa: E402
from analyze_weights import OPTIONS, option_score  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
DAGSTUHL_PATH = DATA_DIR / "vi_confirm_variance_results.jsonl"
PROBE_PATH = DATA_DIR / "high_quality_probe_confirm_results.jsonl"
REPORT_PATH = Path(__file__).parent.parent / "confirm_report.txt"
EXPECTED_VERSION = "v2_4x25"
HQ_IDS = [f"hq0{i}" for i in range(1, 9)]
R_MIN, SD_MAX, GAP_MIN = 0.55, 0.70, 1.0
N_BOOTSTRAP, SEED = 2000, 42
B_WEIGHTS = OPTIONS["B"][0]
# Hash tong hop da ghi trong nhat ky muc 3.15 TRUOC khi chay (scripts/config_fingerprint.py); --expect-hash de ghi de.
EXPECTED_CONFIG_HASH = "8eaaf59ca8d40695a8e626bed7622e877afa1d92588ddb3a3de22349e582ef8d"


def read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def pearson(a, b) -> float:
    return float(np.corrcoef(a, b)[0, 1])


def boot_ci(stat, n: int) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    vals = [stat(rng.integers(0, n, n)) for _ in range(N_BOOTSTRAP)]
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-hash", type=str, default=EXPECTED_CONFIG_HASH)
    args = parser.parse_args()

    sample_ids = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    human = pd.read_csv(VI_CSV_PATH).assign(id=lambda d: d["id"].astype(str)).set_index("id")["overall_quality_score_10"]
    all_d, all_p = read_all(DAGSTUHL_PATH), read_all(PROBE_PATH)
    ok_d = [r for r in all_d if r.get("status") == "ok"]
    ok_p = [r for r in all_p if r.get("status") == "ok"]
    out: list[str] = []
    p = out.append

    p("DOT XAC NHAN CAU HINH CUOI — doc theo quy tac da chot truoc khi chay (docs/AI_DEVELOPMENT_LOG.md muc 3.15). Khong goi API.")
    p("")
    p(f"Ban ghi: Dagstuhl {len(ok_d)} ok / {len(all_d) - len(ok_d)} loi (can 100 ok = 50 bai x 2); probe {len(ok_p)} ok / {len(all_p) - len(ok_p)} loi (can 10 ok).")

    # ---------------------------------------------------------------- kiem tra tinh toan ven
    anomalies: list[str] = []   # chi bao cao (retry, luot loi)
    integrity: list[str] = []   # vi pham toan ven: lam VO HIEU dot chay
    versions = {r.get("scoring_version") for r in ok_d + ok_p}
    hashes = {r.get("config_hash") for r in ok_d + ok_p}
    p(f"scoring_version: {sorted(map(str, versions))} (phai la ['{EXPECTED_VERSION}']) | config_hash: {sorted(map(str, hashes))}")
    if versions - {EXPECTED_VERSION}:
        integrity.append(f"scoring_version khac {EXPECTED_VERSION}: {sorted(map(str, versions))}")
    if len(hashes) > 1:
        integrity.append(f"co {len(hashes)} config_hash khac nhau trong du lieu -> cau hinh da bi doi giua luc chay")
    temps = {r.get("temperature") for r in ok_d + ok_p}
    models = {r.get("model") for r in ok_d + ok_p}
    from app.config import get_settings
    app_default = get_settings()
    p(f"temperature: {sorted(map(str, temps))} (app: {app_default.llm_temperature}) | model: {sorted(map(str, models))} (app: {app_default.groq_model})")
    if len(temps) > 1 or (temps and temps != {app_default.llm_temperature}):
        integrity.append(f"temperature {sorted(map(str, temps))} khong dong nhat hoac khac app ({app_default.llm_temperature})")
    if len(models) > 1 or (models and models != {app_default.groq_model}):
        integrity.append(f"model {sorted(map(str, models))} khong dong nhat hoac khac app ({app_default.groq_model})")
    if args.expect_hash and hashes != {args.expect_hash}:
        integrity.append(f"config_hash khong khop hash da ghi trong nhat ky ({args.expect_hash})")
    for r in ok_d + ok_p:
        tag = f"{r['id']} run{r.get('run', 1)}"
        if not r.get("raw_model_output"):
            integrity.append(f"{tag}: thieu raw_model_output")
        names = list(r.get("criteria", {}))
        if sorted(names) != sorted(CRITERIA):
            integrity.append(f"{tag}: tieu chi {names} khong dung 5 tieu chi")
            continue
        recomputed = float(option_score({c: r["criteria"][c] for c in CRITERIA}, B_WEIGHTS, None))
        if abs(recomputed - r["overall_score"]) > 1e-6:
            integrity.append(f"{tag}: overall {r['overall_score']} khac cong thuc B {recomputed}")
        u = r.get("usage", {})
        if u.get("attempts", 1) > 1 or u.get("failed_attempts", 0) > 0:
            anomalies.append(f"{tag}: attempts={u.get('attempts')} failed={u.get('failed_attempts')} (retry/parse/429)")
    for r in all_d + all_p:
        if r.get("status") != "ok":
            anomalies.append(f"{r['id']} run{r.get('run', 1)}: LUOT LOI {r.get('error_type')}: {r.get('error', '')[:100]}")
    n429 = sum(1 for r in all_d + all_p for c in r.get("usage", {}).get("calls", []) if c.get("failed") and "RateLimit" in str(c.get("error_type")))
    n_failed_req = sum(r.get("usage", {}).get("failed_attempts", 0) for r in all_d + all_p)
    tokens = sum(r.get("usage", {}).get("total_tokens", 0) for r in ok_d + ok_p)
    p(f"Request loi (khong co usage): {n_failed_req} | trong do 429: {n429} | tong token (request thanh cong): {tokens}")
    p("Vi pham toan ven (lam vo hieu dot chay): " + ("khong co" if not integrity else ""))
    for a in integrity:
        p("  - " + a)
    p("Luot can luu y (retry / parse / 429 / luot loi; chi bao cao): " + ("khong co" if not anomalies else ""))
    for a in anomalies:
        p("  - " + a)

    # ---------------------------------------------------------------- ma tran 50 x 2
    by = {(r["id"], r["run"]): r for r in ok_d}
    ids_ok = [i for i in sample_ids if (i, 1) in by and (i, 2) in by]
    probe = {r["id"]: r for r in ok_p}
    complete = len(ids_ok) == len(sample_ids) and all(i in probe for i in HQ_IDS + ["ctrl01", "ctrl02"])
    r_ok = sd_ok = gap_ok = None

    p("")
    if len(ids_ok) < 3:
        p("CHUA DU DU LIEU de tinh r / SD.")
    else:
        ov = np.array([[by[(i, 1)]["overall_score"], by[(i, 2)]["overall_score"]] for i in ids_ok], float)
        h = human[ids_ok].to_numpy(float)
        mean2 = ov.mean(axis=1)
        sigma = lambda x: float(np.sqrt(np.mean((x[:, 0] - x[:, 1]) ** 2 / 2)))
        r = pearson(mean2, h)
        r_lo, r_hi = boot_ci(lambda ix: pearson(mean2[ix], h[ix]), len(ids_ok))
        s = sigma(ov)
        s_lo, s_hi = boot_ci(lambda ix: sigma(ov[ix]), len(ids_ok))
        r_ok, sd_ok = r >= R_MIN, s <= SD_MAX
        p(f"(1) r diem tong (TB 2 lan) voi overall_quality_score_10, {len(ids_ok)} bai: {r:.3f}  [CI 95% bootstrap {r_lo:.3f}, {r_hi:.3f}]  (can >= {R_MIN}) -> {'DAT' if r_ok else 'TRUOT'}")
        p(f"(2) SD gop mot lan cham (diem tong): {s:.3f}  [CI 95% bootstrap {s_lo:.3f}, {s_hi:.3f}]  (can <= {SD_MAX}) -> {'DAT' if sd_ok else 'TRUOT'}")
        p(f"    k = 1: {s:.3f} (do duoc) | k = 2: {s / np.sqrt(2):.3f} (LY THUYET sigma-hat / sqrt(2): chi 2 lan cham nen khong co lan de doi chieu)")

    hq = [probe[i] for i in HQ_IDS if i in probe]
    if len(hq) == 8 and "ctrl02" in probe:
        hq_scores = np.array([r["overall_score"] for r in hq], float)
        c2 = float(probe["ctrl02"]["overall_score"])
        gap = float(hq_scores.mean() - c2)
        gap_ok = gap >= GAP_MIN
        rng = np.random.default_rng(SEED)
        bs = [float(hq_scores[rng.integers(0, 8, 8)].mean() - c2) for _ in range(N_BOOTSTRAP)]
        p(f"(3) TB diem tong 8 hq - TB ctrl02: {hq_scores.mean():.2f} - {c2:.2f} = {gap:.2f}  (can >= {GAP_MIN}) -> {'DAT' if gap_ok else 'TRUOT'}")
        p(f"    CI: KHONG tinh duoc dung nghia (ctrl02 chi 1 luot); bootstrap CHI tren 8 hq (ctrl02 co dinh) cho [{np.percentile(bs, 2.5):.2f}, {np.percentile(bs, 97.5):.2f}] — chi phan anh nhieu giua cac bai hq")
    else:
        p("(3) CHUA DU DU LIEU probe (can du 8 hq + ctrl02).")

    # ---------------------------------------------------------------- histogram + probe
    p("")
    p("Histogram 5 tieu chi (Dagstuhl, so luot o moi muc 1..5):")
    for c in CRITERIA:
        counts = np.bincount([r["criteria"][c] for r in ok_d if c in r.get("criteria", {})], minlength=6)[1:]
        p(f"  {c:<15}: " + " | ".join(f"{k + 1}: {int(v)}" for k, v in enumerate(counts)) + f"   [n={int(counts.sum())}]")
    p("Probe (1 lan): " + "; ".join(f"{i} overall {probe[i]['overall_score']} " + str([probe[i]['criteria'][c] for c in CRITERIA])
                                    for i in HQ_IDS + ["ctrl01", "ctrl02"] if i in probe))
    p("(thu tu tieu chi: Logic, Evidence, Relevance, Structure, Persuasiveness)")

    # ---------------------------------------------------------------- ket luan
    p("")
    if integrity:
        p("KET QUA THEO QUY TAC: DU LIEU KHONG HOP LE (vi pham toan ven o tren) -> DUNG, khong commit app/, bao lai")
    elif complete and None not in (r_ok, sd_ok, gap_ok):
        verdict = "NHANH SAN SANG (dat ca ba) -> sang buoc 4" if (r_ok and sd_ok and gap_ok) else "DUNG: khong commit app/, bao lai"
        p(f"KET QUA THEO QUY TAC: {verdict}   [r: {'DAT' if r_ok else 'TRUOT'} | SD gop: {'DAT' if sd_ok else 'TRUOT'} | khoang cach: {'DAT' if gap_ok else 'TRUOT'}]")
    else:
        p("KET QUA THEO QUY TAC: CHUA DU DU LIEU (can du 50 bai x 2 + 10 bai probe)")

    text = chr(10).join(out)
    print(text)
    REPORT_PATH.write_text(text + chr(10), encoding="utf-8")


if __name__ == "__main__":
    main()
