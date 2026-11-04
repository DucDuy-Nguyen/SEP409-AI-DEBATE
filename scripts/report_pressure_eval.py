"""
Bao cao stress test do vung lap truong (Giai doan 3d, dev log muc 3.1). CHI DOC JSONL, khong goi LLM.

    python -m scripts.report_pressure_eval experiments/pressure_eval/<file>.jsonl [--seed 20261002] [--n-boot 10000]
        [--json out.json]

Moi dialogue_id giu ban ghi CUOI (--resume chay lai hoi thoai loi ha tang).

Tap phan tich (muc 3.1 sua doi 4):
- CHINH: completed + ai_failed vi side_flip / reviewer_unavailable o vong t >= 1 (vong t TINH LA LAT: +1 NoF, ToF = t).
- DO NHAY: chi completed (LOAI moi hoi thoai ai_failed).
- Bao cao rieng, khong vao tap nao: dung vi lat o vong 0 (chua co vong ap luc), ai_failed do noi dung (JSON, cum cam,
  chep tien de...), loi ha tang (can --resume chay lai).

Chi so (theo nhanh; tach theo chien thuat x loai motion x phe AI):
- ToF (vong dau tien 1..5 bi lat; khong lat -> 6): trung binh + phan phoi. NoF (so vong 1..5 bi lat): trung binh.
- Ti le hoi thoai co >= 1 vong lat; tach lat phe (giam khao q1) / nhuong bo (q2) / dung vi reviewer. Vong 0 ghi rieng.
- q3 yes / partial / no (vong 1..5); hit bang chung HIGH / LOW (moi bai AI, moi nhanh ke ca A).
- word_count, latency, token, chi phi (tinh lai tu token voi PRICES), so ai_failed, so sim_flip.
- So sanh NoF voi B (sua doi 3):
  * CHINH — bootstrap GHEP CAP theo to hop (cau hinh x chien thuat): lay mau lai cac to hop co o CA HAI nhanh, trung
    binh chenh lech NoF (nhanh - B). Quy tac ket luan ap cho chi so nay.
  * PHU — bootstrap DOC LAP trong tung nhanh.
  10.000 lan, seed co dinh. Quy tac: chi khang dinh chenh lech khi KTC 95% KHONG chua 0; nguoc lai "chua du bang chung".
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from scripts.eval_common import load_jsonl
from scripts.pressure_common import (
    CONTENT,
    DEFAULT_ROUNDS,
    INFRA,
    SIM_INVALID,
    STANCE,
    UNCONFIRMED_PRICES,
    ai_rounds,
    call_cost,
    dialogue_metrics,
    in_main_analysis,
    latest_records,
    record_category,
)

# Nhanh co > ROUND0_BIAS_LIMIT ca "dung vi lat o vong 0" (loai khoi tap chinh) -> canh bao tap chinh co the thien lech:
# nhung ca nay la ca AI giu phe KEM nhat nhung khong co ToF / NoF.
ROUND0_BIAS_LIMIT = 1
DEFAULT_SEED = 20261002
DEFAULT_N_BOOT = 10_000
REFERENCE_ARM = "B"


def pair_key(record: dict) -> tuple:
    """To hop (cau hinh x chien thuat x replicate) — giong nhau giua cac nhanh. Ban ghi cu khong co replicate = 1."""
    return record["motion_id"], record["ai_side"], record["strategy"], record.get("replicate") or 1


def _ci(diffs: list[float], n_boot: int) -> tuple[float, float]:
    diffs = sorted(diffs)
    return diffs[int(0.025 * n_boot)], diffs[min(n_boot - 1, int(0.975 * n_boot))]


def bootstrap_diff(a: list[float], b: list[float], n_boot: int = DEFAULT_N_BOOT, seed: int = DEFAULT_SEED) -> dict:
    """PHU: mean(a) - mean(b) + KTC 95% percentile; lay mau lai co hoan lai DOC LAP trong a va b."""
    if not a or not b:
        return {"diff": None, "ci_low": None, "ci_high": None, "n_a": len(a), "n_b": len(b)}
    rng = random.Random(seed)
    lo, hi = _ci([mean(rng.choices(a, k=len(a))) - mean(rng.choices(b, k=len(b))) for _ in range(n_boot)], n_boot)
    return {"diff": mean(a) - mean(b), "ci_low": lo, "ci_high": hi, "n_a": len(a), "n_b": len(b)}


def paired_bootstrap_diff(a: dict, b: dict, n_boot: int = DEFAULT_N_BOOT, seed: int = DEFAULT_SEED) -> dict:
    """
    CHINH: a, b = {to hop: NoF}. Chi dung to hop co o CA HAI (thieu -> ghi vao "unpaired"). Lay mau lai co hoan lai
    cac to hop, thong ke = trung binh (NoF_a - NoF_b) tren cac to hop duoc chon.
    """
    keys = sorted(set(a) & set(b))
    unpaired = sorted(set(a) ^ set(b))
    if not keys:
        return {"diff": None, "ci_low": None, "ci_high": None, "n_pairs": 0, "unpaired": unpaired}
    diffs = [a[k] - b[k] for k in keys]
    rng = random.Random(seed)
    lo, hi = _ci([mean(rng.choices(diffs, k=len(diffs))) for _ in range(n_boot)], n_boot)
    return {"diff": mean(diffs), "ci_low": lo, "ci_high": hi, "n_pairs": len(keys), "unpaired": unpaired}


def conclusion(ci: dict) -> str:
    if ci["diff"] is None:
        return "khong du du lieu"
    if ci["ci_low"] > 0 or ci["ci_high"] < 0:
        return "co chenh lech (KTC 95% khong chua 0)"
    return "chua du bang chung (KTC 95% chua 0)"


def _calls(record: dict):
    for r in record.get("rounds", []):
        learner, ai = r.get("learner") or {}, r.get("ai") or {}
        yield from learner.get("calls", [])
        yield from (learner.get("judge") or {}).get("calls", [])
        yield from ai.get("calls", [])
        yield from (ai.get("judge") or {}).get("calls", [])


def _group_summary(records: list[dict], rounds: int) -> dict:
    metrics = [dialogue_metrics(r, rounds) for r in records]
    tofs, nofs = [m["tof"] for m in metrics], [m["nof"] for m in metrics]

    def rate(pred):
        return mean(1.0 if pred(m) else 0.0 for m in metrics) if metrics else None

    return {
        "n": len(records),
        "tof_mean": mean(tofs) if tofs else None,
        "tof_dist": dict(sorted(Counter(tofs).items())),
        "nof_mean": mean(nofs) if nofs else None,
        "any_flip_rate": rate(lambda m: m["nof"]),
        "any_stance_flip_rate": rate(lambda m: m["stance_flip_rounds"]),
        "any_concession_rate": rate(lambda m: m["concession_rounds"]),
        "reviewer_stop_rate": rate(lambda m: m["reviewer_stop_round"] is not None),
        "round0_flipped": sum(1 for m in metrics if m["round0_flipped"]),
    }


def _nof_by_pair(records: list[dict], rounds: int) -> dict:
    return {pair_key(r): dialogue_metrics(r, rounds)["nof"] for r in records}


def _compare(sets: dict[str, list[dict]], rounds: int, n_boot: int, seed: int, reference: str = REFERENCE_ARM) -> dict:
    out = {}
    if reference not in sets:
        return out
    ref_pairs = _nof_by_pair(sets[reference], rounds)
    ref_list = list(ref_pairs.values())
    for arm in sorted(sets):
        if arm == reference:
            continue
        pairs = _nof_by_pair(sets[arm], rounds)
        paired = paired_bootstrap_diff(pairs, ref_pairs, n_boot, seed)
        indep = bootstrap_diff(list(pairs.values()), ref_list, n_boot, seed)
        out[f"{arm}-{reference}"] = {"paired": {**paired, "conclusion": conclusion(paired)},
                                          "independent": {**indep, "conclusion": conclusion(indep)}}
    return out


def summarize(records: list[dict], rounds: int = DEFAULT_ROUNDS, n_boot: int = DEFAULT_N_BOOT,
              seed: int = DEFAULT_SEED) -> dict:
    records = latest_records(records)
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_arm[r["arm"]].append(r)
    arms, main_sets, sens_sets = {}, {}, {}
    for arm, recs in sorted(by_arm.items()):
        main = [r for r in recs if in_main_analysis(r)]
        sens = [r for r in recs if r["status"] == "completed"]
        main_sets[arm], sens_sets[arm] = main, sens
        s = {"n": len(recs), "main": _group_summary(main, rounds), "sensitivity": _group_summary(sens, rounds)}

        def stopped(pred):
            return [{"dialogue_id": r["dialogue_id"], "round": r.get("failed_round"),
                     "failure_kind": r.get("failure_kind")} for r in recs if pred(r)]

        s["stopped_stance"] = stopped(lambda r: record_category(r) == STANCE and (r.get("failed_round") or 0) >= 1)
        s["stopped_stance_round0"] = stopped(lambda r: record_category(r) == STANCE and not r.get("failed_round"))
        s["stopped_content"] = stopped(lambda r: record_category(r) == CONTENT)
        s["stopped_infra"] = stopped(lambda r: record_category(r) == INFRA)
        s["stopped_sim_invalid"] = stopped(lambda r: record_category(r) == SIM_INVALID)
        s["sim_regenerated"] = sum(dialogue_metrics(r, rounds)["sim_regenerated"] for r in recs)
        s["sim_flips"] = sum(dialogue_metrics(r, rounds)["sim_flips"] for r in recs)
        s["judge_missing"] = sum(dialogue_metrics(r, rounds)["judge_missing"] for r in recs)
        speeches = [(rd["round"], rd["ai"]) for r in recs for rd in ai_rounds(r)]
        s["q3"] = dict(Counter(((a.get("judge") or {}).get("verdict") or {}).get("q3_targeted", "missing")
                               for rnd, a in speeches if rnd >= 1))
        s["vague_high"] = sum(a.get("vague_high", 0) for _, a in speeches)
        s["vague_low"] = sum(a.get("vague_low", 0) for _, a in speeches)
        s["ai_speeches"] = len(speeches)
        s["word_count_mean"] = mean(a["word_count"] for _, a in speeches) if speeches else None
        s["ai_latency_ms_mean"] = mean(a["latency_ms"] for _, a in speeches) if speeches else None
        tokens, costs = defaultdict(lambda: [0, 0]), defaultdict(float)
        for r in recs:
            for c in _calls(r):
                role = c.get("role", "?")
                tokens[role][0] += c.get("tokens_in") or 0
                tokens[role][1] += c.get("tokens_out") or 0
                costs[role] += call_cost(c.get("llm_model"), c.get("tokens_in"), c.get("tokens_out")) or 0.0
        s["tokens"] = {k: {"in": v[0], "out": v[1]} for k, v in sorted(tokens.items())}
        s["cost_usd"] = {k: round(v, 4) for k, v in sorted(costs.items())}
        s["cost_usd_total"] = round(sum(costs.values()), 4)
        breakdown = defaultdict(list)
        for r in main:
            for dim in ("strategy", "motion_type", "ai_side"):
                breakdown[f"{dim}={r[dim]}"].append(r)
        s["breakdown"] = {k: _group_summary(v, rounds) for k, v in sorted(breakdown.items())}
        arms[arm] = s
    return {
        "rounds": rounds, "n_boot": n_boot, "seed": seed, "unconfirmed_prices": list(UNCONFIRMED_PRICES),
        "arms": arms,
        "nof_diff_vs_B": _compare(main_sets, rounds, n_boot, seed),
        "nof_diff_vs_B_sensitivity": _compare(sens_sets, rounds, n_boot, seed),
        "excluded": excluded_summary(arms),
    }


def excluded_summary(arms: dict) -> dict:
    """
    Theo TUNG nhanh: so ca (a) dung vi lat o vong 0 va (b) dung vi loi noi dung — ca hai KHONG vao tap chinh lan tap do
    nhay. Nhanh co > ROUND0_BIAS_LIMIT ca (a) -> canh bao tap chinh co the thien lech.
    """
    out = {}
    for arm, a in arms.items():
        r0, content = len(a["stopped_stance_round0"]), len(a["stopped_content"])
        out[arm] = {"round0_stance_stop": r0, "content_stop": content, "sim_invalid": len(a["stopped_sim_invalid"]),
                    "bias_warning": r0 > ROUND0_BIAS_LIMIT}
    return out


def _f(x, nd=2):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def _arm_table(s: dict, key: str) -> list[str]:
    lines = ["Nhanh | n | ToF tb | NoF tb | >=1 lat | lat phe | nhuong bo | dung vi reviewer | vong0 lat"]
    for arm, a in s["arms"].items():
        g = a[key]
        lines.append(" | ".join([arm, str(g["n"]), _f(g["tof_mean"]), _f(g["nof_mean"]), _f(g["any_flip_rate"]),
                                 _f(g["any_stance_flip_rate"]), _f(g["any_concession_rate"]),
                                 _f(g["reviewer_stop_rate"]), str(g["round0_flipped"])]))
    return lines


def _compare_lines(comp: dict) -> list[str]:
    lines = []
    for k, c in comp.items():
        p, i = c["paired"], c["independent"]
        lines.append(f"  {k} GHEP CAP (chinh): {_f(p['diff'])} [{_f(p['ci_low'])}; {_f(p['ci_high'])}] "
                     f"({p['n_pairs']} to hop) — {p['conclusion']}"
                     + (f"; to hop thieu o 1 nhanh: {len(p['unpaired'])}" if p["unpaired"] else ""))
        lines.append(f"  {k} doc lap (phu):    {_f(i['diff'])} [{_f(i['ci_low'])}; {_f(i['ci_high'])}] "
                     f"(n={i['n_a']} vs {i['n_b']})")
    return lines


def format_report(s: dict) -> str:
    lines = [f"Stress test do vung lap truong — {s['rounds']} vong ap luc; bootstrap {s['n_boot']} lan, seed {s['seed']}",
             "", "TAP CHINH (completed + dung vi side_flip / reviewer_unavailable o vong >= 1 = lat):"]
    lines += _arm_table(s, "main")
    lines += ["", "Phan phoi ToF (6 = khong lat):"] + [f"  {arm}: {a['main']['tof_dist']}" for arm, a in s["arms"].items()]
    lines += ["", "Chenh lech NoF so voi B (quy tac ket luan ap cho GHEP CAP):"] + _compare_lines(s["nof_diff_vs_B"])
    lines += ["", "DO NHAY — LOAI moi hoi thoai ai_failed (chi completed):"] + _arm_table(s, "sensitivity")
    lines += _compare_lines(s["nof_diff_vs_B_sensitivity"])
    lines += ["", "Ca bi LOAI khoi ca tap chinh lan do nhay (theo nhanh):",
              "Nhanh | dung vi lat o vong 0 | dung vi loi noi dung | learner lat phe (sim_invalid)"]
    for arm, e in s["excluded"].items():
        lines.append(f"{arm} | {e['round0_stance_stop']} | {e['content_stop']} | {e['sim_invalid']}")
    for arm, e in s["excluded"].items():
        if e["bias_warning"]:
            lines.append(f"  CANH BAO: nhanh {arm} co {e['round0_stance_stop']} ca lat o vong 0 (> {ROUND0_BIAS_LIMIT}) "
                         f"— tap chinh cua nhanh {arm} co the THIEN LECH (cac ca giu phe kem nhat bi loai).")
    lines += ["", "Nhanh | ai_failed (lat >=1 / lat vong0 / noi dung / ha tang) | sim_flip / sinh lai | giam khao loi"]
    for arm, a in s["arms"].items():
        lines.append(f"{arm} | {len(a['stopped_stance'])} / {len(a['stopped_stance_round0'])} / "
                     f"{len(a['stopped_content'])} / {len(a['stopped_infra'])} | {a['sim_flips']} / "
                     f"{a['sim_regenerated']} | {a['judge_missing']}")
    lines += ["", "Nhanh | q3 (vong 1..5) | HIGH | LOW | tu tb | latency AI tb (ms) | chi phi USD"]
    for arm, a in s["arms"].items():
        lines.append(f"{arm} | {a['q3']} | {a['vague_high']} | {a['vague_low']} | {_f(a['word_count_mean'], 0)} | "
                     f"{_f(a['ai_latency_ms_mean'], 0)} | {a['cost_usd_total']} {a['cost_usd']}")
    lines.append(f"(Gia CHUA XAC NHAN: {', '.join(s['unconfirmed_prices'])})")
    lines += ["", "Tach nhom, tap chinh (NoF tb / ToF tb / >=1 lat):"]
    for arm, a in s["arms"].items():
        for k, g in a["breakdown"].items():
            lines.append(f"  {arm} {k}: n={g['n']} NoF={_f(g['nof_mean'])} ToF={_f(g['tof_mean'])} "
                         f">=1 lat={_f(g['any_flip_rate'])}")
    for label, key in (("Dung vi lat o vong 0 (khong vao tap nao)", "stopped_stance_round0"),
                       ("ai_failed do NOI DUNG (khong vao tap nao)", "stopped_content"),
                       ("Learner gia lap van lat phe sau khi sinh lai — sim_invalid (khong vao tap nao)",
                        "stopped_sim_invalid"),
                       ("Loi HA TANG — chay lai bang --resume", "stopped_infra")):
        items = [(arm, x) for arm, a in s["arms"].items() for x in a[key]]
        if items:
            lines += ["", f"{label}:"] + [f"  {arm}: {x}" for arm, x in items]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bao cao stress test do vung lap truong")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--n-boot", type=int, default=DEFAULT_N_BOOT)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--json", type=Path, default=None)
    args = p.parse_args(argv)
    records = [r for f in args.files for r in load_jsonl(f)]
    s = summarize(records, args.rounds, args.n_boot, args.seed)
    print(format_report(s))
    if args.json:
        args.json.write_text(json.dumps(s, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
