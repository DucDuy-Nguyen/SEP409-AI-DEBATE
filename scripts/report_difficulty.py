"""
Bao cao 3 cap do doi thu (Giai doan 3e, Phan 2, dev log muc 3.2 + 3.3). CHI DOC JSONL, khong goi LLM.

    python -m scripts.report_difficulty --arms <pressure.jsonl> --branch <branch.jsonl> --pairwise <pairwise.jsonl> \\
        [--labels experiments/labels/pairwise_labels.csv] [--seed 20261104] [--n-boot 10000] [--json out.json]

- H1: moi cap cap: thang / thua / hoa, ti le thang tren cac cap khong hoa, bootstrap 95% theo HOI THOAI (chinh), theo trang thai
  va sign test (phu). Tach theo tung chieu: chien thuat, loai motion, phe AI, vong. Do nhay do dai: chi cac cap
  |chenh word_count| <= 15%.
- H2: bootstrap ghep cap cua report 3d, NoF (nhanh - LM); dat khi can tren <= +0.3. Tap chinh nhu 3d: dung vi lat o vong t >= 1
  tinh la lat o vong t; dung vi loi noi dung (va lat o vong 0, ha tang, sim_invalid) ngoai tap chinh, bao rieng.
- H3 (theo sua dang ky 04/11): target dung cap o LAN THU DAU; "khong do duoc" loai khoi mau so, > 10% -> "khong du du lieu".
- Quyet dinh: quy tac muc 3.2. Giam khao pairwise dong thuan voi nhan nguoi < 75% -> H1 "chua du bang chung", khong ket luan
  co hay khong co 3 cap (dev log 3.3, sua dang ky 4).
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from scripts.eval_common import load_jsonl, read_csv
from scripts.judge_pairwise import (
    DEFAULT_N_BOOT,
    DEFAULT_SEED,
    H1_PAIRS,
    JUDGE_MISSING,
    LEVELS,
    PAIR_TYPES,
    TIE_INCONSISTENT,
    latest_pairs,
    win_stats,
)
from scripts import label_pairwise as lp
from scripts import report_pressure_eval as rep
from scripts.pressure_common import (
    CONTENT,
    DEFAULT_ROUNDS,
    INFRA,
    LEVEL_ARMS,
    SIM_INVALID,
    STANCE,
    attempt_rows,
    call_cost,
    in_main_analysis,
    latest_records,
    record_category,
)
from scripts.run_difficulty_branch import BRANCH_FAILED, BRANCH_INFRA, OK, latest_states

LENGTH_TOLERANCE = 0.15  # |a - b| / max(a, b)
H2_MAX_CI_HIGH = 0.3
H3_MIN_TARGET_FIRST = 0.90
H3_MAX_NOT_MEASURABLE = 0.10
H3_MIN_EASY_POINTS = 0.90
H3_MIN_HARD_POINTS = 0.80
TARGET_FAILURES = ("target_not_in_premises", "target_level_mismatch")
ARM_LEVEL = {"LE": "easy", "LM": "medium", "LH": "hard"}
REFERENCE = "LM"
BREAKDOWN_DIMS = ("strategy", "motion_type", "ai_side", "round")
INSUFFICIENT = "khong du du lieu"
NO_EVIDENCE = "chua du bang chung"
NOT_FINAL = "chua chot"


# ---------------- H1 ----------------


def length_ok(pair: dict, tolerance: float = LENGTH_TOLERANCE) -> bool:
    a, b = pair["word_count"][pair["high"]], pair["word_count"][pair["low"]]
    if not a or not b:
        return False
    return abs(a - b) / max(a, b) <= tolerance


def _h1_table(pairs: list[dict], n_boot: int, seed: int) -> dict:
    out = {}
    for high, low in PAIR_TYPES:
        rows = [p for p in pairs if p["pair_type"] == f"{high}-{low}"]
        out[f"{high}-{low}"] = win_stats([p["result"] for p in rows], high, low, n_boot, seed,
                                         clusters=[p["dialogue_id"] for p in rows])
    return out


def h1_summary(pairs: list[dict], n_boot: int = DEFAULT_N_BOOT, seed: int = DEFAULT_SEED) -> dict:
    pairs = latest_pairs(pairs)
    near = [p for p in pairs if length_ok(p)]
    breakdown = {}
    for dim in BREAKDOWN_DIMS:
        for value in sorted({p[dim] for p in pairs}, key=str):
            breakdown[f"{dim}={value}"] = _h1_table([p for p in pairs if p[dim] == value], n_boot, seed)
    table = _h1_table(pairs, n_boot, seed)
    return {
        "pairs": table, "breakdown": breakdown, "word_count_mean": _word_means(pairs),
        "length_sensitivity": {
            "tolerance": LENGTH_TOLERANCE, "pairs": _h1_table(near, n_boot, seed), "word_count_mean": _word_means(near),
            "remaining": {f"{h}-{l}": sum(p["pair_type"] == f"{h}-{l}" for p in near) for h, l in PAIR_TYPES},
            "total": {f"{h}-{l}": sum(p["pair_type"] == f"{h}-{l}" for p in pairs) for h, l in PAIR_TYPES},
        },
        "tie_inconsistent_rate": {
            k: (s["tie_inconsistent"] / s["n"] if s["n"] else None) for k, s in table.items()
        },
    }


def _word_means(pairs: list[dict]) -> dict:
    """Moi bai tinh 1 lan (1 bai co mat trong nhieu cap cua cung trang thai)."""
    seen: dict[tuple, int] = {}
    for p in pairs:
        for level, n in p["word_count"].items():
            seen[(p["state_id"], level)] = n
    return {lv: _mean([n for (_, level), n in seen.items() if level == lv and n]) for lv in LEVELS}


def _mean(values: list) -> float | None:
    return mean(values) if values else None


def judge_by_level(pairs: list[dict]) -> dict:
    """points_answered, attacks_foundational (mo ta) theo cap; moi cap cham 2 thu tu."""
    out = {}
    pairs = [p for p in latest_pairs(pairs) if p["result"] != JUDGE_MISSING]
    for lv in LEVELS:
        points = [p["points_answered"][lv] for p in pairs if lv in p["points_answered"]]
        found = [x for p in pairs if lv in p["attacks_foundational"] for x in p["attacks_foundational"][lv]]
        out[lv] = {"points_answered_mean": _mean(points), "attacks_foundational_rate": _mean([float(x) for x in found])}
    return out


# ---------------- H2 ----------------


def level_records(records: list[dict]) -> list[dict]:
    return [r for r in latest_records(records) if r.get("arm") in LEVEL_ARMS]


def _stopped(recs: list[dict]) -> dict:
    """Hoi thoai dung som theo quy tac 3d. stance: da tinh la lat trong NoF; con lai: ngoai tap chinh, bao rieng."""
    def rows(pred):
        return [{"dialogue_id": r["dialogue_id"], "round": r.get("failed_round"), "failure_kind": r.get("failure_kind")}
                for r in recs if pred(r)]

    return {
        "stance": rows(lambda r: record_category(r) == STANCE and (r.get("failed_round") or 0) >= 1),
        "stance_round0": rows(lambda r: record_category(r) == STANCE and not r.get("failed_round")),
        "content": rows(lambda r: record_category(r) == CONTENT),
        "infra": rows(lambda r: record_category(r) == INFRA),
        "sim_invalid": rows(lambda r: record_category(r) == SIM_INVALID),
    }


def h2_summary(records: list[dict], rounds: int = DEFAULT_ROUNDS, n_boot: int = DEFAULT_N_BOOT, seed: int = DEFAULT_SEED) -> dict:
    """Bootstrap ghep cap va cac tap phan tich cua report 3d, moc la LM thay vi B."""
    by_arm = defaultdict(list)
    for r in level_records(records):
        by_arm[r["arm"]].append(r)
    main = {a: [r for r in rs if in_main_analysis(r)] for a, rs in by_arm.items()}
    sens = {a: [r for r in rs if r["status"] == "completed"] for a, rs in by_arm.items()}
    comp, comp_sens = (rep._compare(main, rounds, n_boot, seed, REFERENCE), rep._compare(sens, rounds, n_boot, seed, REFERENCE))
    levels = {}
    for arm in ("LE", "LH"):
        paired = comp.get(f"{arm}-{REFERENCE}", {}).get("paired")
        ci_high = paired["ci_high"] if paired else None
        levels[ARM_LEVEL[arm]] = {"pass": ci_high is not None and ci_high <= H2_MAX_CI_HIGH, "ci_high": ci_high,
                                  "diff": paired["diff"] if paired else None, "n_pairs": paired["n_pairs"] if paired else 0}
    return {"compare": comp, "compare_sensitivity": comp_sens, "levels": levels, "max_ci_high": H2_MAX_CI_HIGH,
            "stopped": {a: _stopped(rs) for a, rs in sorted(by_arm.items())}}


# ---------------- H3 ----------------


def _ai_turns_by_level(records: list[dict]) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for r in level_records(records):
        for rd in r.get("rounds", []):
            if rd.get("ai"):
                out[ARM_LEVEL[r["arm"]]].append(rd["ai"])
    return out


def h3_level(level: str, turns: list[dict]) -> dict:
    """
    turns: moi luot AI cua cap do. Chi tinh luot co dong lan thu 1 (opening_reply / rebuttal; luot loi ha tang khong co dong).
    Target: tinh tren lan thu dau do duoc. Points: tren bai DUOC NHAN, la so model khai da khop premises.explicit.
    """
    n_turns = measured = correct = 0
    not_measurable: Counter = Counter()
    target_fail_turns: Counter = Counter()
    first_kinds: Counter = Counter()
    points_dist: Counter = Counter()
    unsupported_turns = accepted = 0
    for ai in turns:
        rows = attempt_rows(ai)
        first = next((r for r in rows if r["content_attempt"] == 1), None)
        if first is None:
            continue
        n_turns += 1
        first_kinds[first["failure_kind"] or "ok"] += 1
        if first["measurable"]:
            measured += 1
            correct += bool(first["target_level_ok"])
        else:
            not_measurable[first["failure_kind"] or "khac"] += 1
        if ai.get("failure_kind") in TARGET_FAILURES:
            target_fail_turns[ai["failure_kind"]] += 1
        final = next((r for r in reversed(rows) if r["success"] and r["measurable"]), None)
        if final is not None and ai.get("text"):
            accepted += 1
            points_dist[final["points_addressed_count"]] += 1
            unsupported_turns += bool(final["points_unsupported"])
    n_not = sum(not_measurable.values())
    not_rate = n_not / n_turns if n_turns else None
    target_rate = correct / measured if measured else None
    points_ok = None
    points_rate = None
    if level == "easy":
        points_rate = points_dist[1] / accepted if accepted else None
        points_ok = points_rate is not None and points_rate >= H3_MIN_EASY_POINTS
    elif level == "hard":
        points_rate = sum(v for k, v in points_dist.items() if k >= 2) / accepted if accepted else None
        points_ok = points_rate is not None and points_rate >= H3_MIN_HARD_POINTS
    insufficient = n_turns == 0 or not_rate > H3_MAX_NOT_MEASURABLE
    passed = not insufficient and target_rate is not None and target_rate >= H3_MIN_TARGET_FIRST and points_ok is not False
    return {
        "turns": n_turns, "measured": measured, "target_correct": correct, "target_first_attempt_rate": target_rate,
        "not_measurable": n_not, "not_measurable_rate": not_rate, "not_measurable_kinds": dict(not_measurable),
        "not_measurable_warning": bool(not_rate is not None and not_rate > H3_MAX_NOT_MEASURABLE),
        "first_attempt_kinds": dict(first_kinds), "target_failed_turns": dict(target_fail_turns),
        "points_addressed_dist": dict(sorted(points_dist.items())), "points_rate": points_rate,
        "points_unsupported_turns": unsupported_turns, "accepted_turns": accepted,
        "status": INSUFFICIENT if insufficient else ("dat" if passed else "khong dat"),
    }


def h3_summary(records: list[dict]) -> dict:
    by_level = _ai_turns_by_level(records)
    return {lv: h3_level(lv, by_level.get(lv, [])) for lv in LEVELS}


# ---------------- mo ta them ----------------


def branch_summary(states: list[dict]) -> dict:
    out = {}
    states = latest_states(states)
    for lv in LEVELS:
        entries = [s["levels"][lv] for s in states if lv in s["levels"]]
        out[lv] = {
            "states": len(entries), "ok": sum(e["status"] == OK for e in entries),
            "branch_failed": sum(e["status"] == BRANCH_FAILED for e in entries),
            "branch_infra": sum(e["status"] == BRANCH_INFRA for e in entries),
            "failure_kinds": dict(Counter(e["failure_kind"] for e in entries if e["status"] != OK)),
            "h3_first_attempt": h3_level(lv, [{"failure_kind": e["failure_kind"], "text": e["text"], "calls": e["calls"]}
                                              for e in entries]),
        }
    return {"states": len(states), "levels": out}


def arm_costs(records: list[dict], rounds: int = DEFAULT_ROUNDS) -> dict:
    s = rep.summarize(level_records(records), rounds, n_boot=1, seed=DEFAULT_SEED) if level_records(records) else {"arms": {}}
    out = {}
    for arm, a in s["arms"].items():
        kinds = Counter(c.get("failure_kind") for ai in _turns_of(records, arm) for c in ai.get("calls", [])
                        if c.get("role") == "ai" and c.get("failure_kind"))
        out[ARM_LEVEL[arm]] = {"n": a["n"], "word_count_mean": a["word_count_mean"], "ai_latency_ms_mean": a["ai_latency_ms_mean"],
                               "tokens": a["tokens"], "cost_usd_total": a["cost_usd_total"], "failure_kinds": dict(kinds),
                               "main": a["main"]}
    return out


def _turns_of(records: list[dict], arm: str):
    for r in level_records(records):
        if r["arm"] == arm:
            for rd in r.get("rounds", []):
                if rd.get("ai"):
                    yield rd["ai"]


def judge_cost(pairs: list[dict]) -> dict:
    tokens_in = tokens_out = calls = 0
    cost = 0.0
    for p in latest_pairs(pairs):
        for j in p.get("judgments", []):
            for c in j.get("calls", []):
                calls += 1
                tokens_in += c.get("tokens_in") or 0
                tokens_out += c.get("tokens_out") or 0
                cost += call_cost(c.get("llm_model"), c.get("tokens_in"), c.get("tokens_out")) or 0.0
    return {"calls": calls, "tokens_in": tokens_in, "tokens_out": tokens_out, "cost_usd": round(cost, 4)}


# ---------------- quyet dinh (muc 3.2) ----------------


def decide(h1: dict, h2: dict, h3: dict, label_report: dict | None) -> dict:
    """
    H1 lay giam khao. Da kiem bang nguoi ma dong thuan < 75% (3.3, sua dang ky 4): H1 "chua du bang chung", khong dung nhan nguoi
    hay giam khao de ket luan; h1_pass va accept_three_levels = None (khong tuyen bo co hay khong co 3 cap).
    Chua co hoac chua du nhan nguoi: H1 "chua chot", h1_pass chi la ket qua tam cua giam khao, accept_three_levels = None.
    """
    not_final = label_report is None or not label_report["complete"]
    no_evidence = not not_final and not label_report["judge_trusted"]
    if no_evidence:
        h1_source = "khong ket luan (giam khao chua dat dong thuan voi nhan nguoi)"
        not_separated = []
    else:
        h1_source = "giam khao (CHUA kiem bang nguoi)" if not_final else "giam khao"
        not_separated = [k for k in H1_PAIRS if not h1["pairs"][k]["h1_pass"]]
    unusable = [lv for lv, v in h2["levels"].items() if not v["pass"]]
    h3_bad = {lv: v["status"] for lv, v in h3.items() if v["status"] != "dat"}
    return {
        "h1_source": h1_source,
        "h1_status": NO_EVIDENCE if no_evidence else NOT_FINAL if not_final else ("khong dat" if not_separated else "dat"),
        "h1_pass": None if no_evidence else not not_separated, "not_separated": not_separated,
        "h2_pass": not unusable, "h2_unusable_levels": unusable, "h3_pass": not h3_bad, "h3_not_passed": h3_bad,
        "accept_three_levels": None if no_evidence or not_final else not (not_separated or unusable or h3_bad),
        "judge_checked": not not_final,
        "labels_progress": f"{label_report['labeled']}/{label_report['required']}" if label_report and not_final else None,
    }


def summarize(records: list[dict], states: list[dict], pairs: list[dict], label_rows: list[dict] | None = None,
              rounds: int = DEFAULT_ROUNDS, n_boot: int = DEFAULT_N_BOOT, seed: int = DEFAULT_SEED,
              label_required: int = lp.DEFAULT_REQUIRED) -> dict:
    h1, h2, h3 = h1_summary(pairs, n_boot, seed), h2_summary(records, rounds, n_boot, seed), h3_summary(records)
    label_report = lp.build_report(label_rows, lp.build_pool(pairs), n_boot, seed, label_required) if label_rows else None
    return {
        "seed": seed, "n_boot": n_boot, "h1": h1, "h2": h2, "h3": h3, "label_report": label_report,
        "judge_by_level": judge_by_level(pairs), "branch": branch_summary(states), "arms": arm_costs(records, rounds),
        "judge_cost": judge_cost(pairs), "decision": decide(h1, h2, h3, label_report),
    }


# ---------------- in ----------------


def _f(x, nd=2):
    return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def _pct(x):
    return "-" if x is None else f"{100 * x:.1f}%"


def _h1_lines(table: dict) -> list[str]:
    lines = []
    for k, s in table.items():
        tag = "" if k in H1_PAIRS else " (tham khao)"
        lines.append(f"  {k}{tag}: thang {s['wins']} / thua {s['losses']} / hoa {s['ties']} / khong nhat quan "
                     f"{s['tie_inconsistent']}; ti le thang {_pct(s['win_rate'])}; KTC chinh ({s['n_clusters']} hoi thoai) "
                     f"[{_pct(s['ci_low'])}; {_pct(s['ci_high'])}]; phu: theo trang thai [{_pct(s['ci_low_state'])}; "
                     f"{_pct(s['ci_high_state'])}], sign test p={_f(s['sign_test_p'], 4)}; {'DAT' if s['h1_pass'] else 'khong dat'}")
    return lines


def _stopped_lines(stopped: dict) -> list[str]:
    lines = []
    for arm, s in stopped.items():
        lines.append(f"  {arm}: lat o vong >= 1 (da tinh la lat) {len(s['stance'])}; ngoai tap chinh: loi noi dung {len(s['content'])}, "
                     f"lat o vong 0 {len(s['stance_round0'])}, ha tang {len(s['infra'])}, sim_invalid {len(s['sim_invalid'])}")
        for key in ("content", "stance_round0", "infra", "sim_invalid"):
            lines += [f"    [{key}] {r['dialogue_id']} vong {r['round']}: {r['failure_kind']}" for r in s[key]]
    return lines


def _decision_lines(d: dict) -> list[str]:
    if d["h1_status"] == NO_EVIDENCE:
        h1_line = "  H1 CHUA DU BANG CHUNG: giam khao dong thuan voi nhan nguoi < 75%; khong ha nguong."
        verdict = "CHUA DU BANG CHUNG, khong tuyen bo co hay khong co 3 cap do."
    elif d["h1_status"] == NOT_FINAL:
        provisional = "DAT" if d["h1_pass"] else "KHONG DAT, chua tach duoc: " + ", ".join(d["not_separated"])
        reason = f"chua du nhan ({d['labels_progress']})" if d["labels_progress"] else "chua co nhan nguoi"
        h1_line = f"  H1 CHUA CHOT ({reason}); giam khao tam thoi: {provisional}"
        verdict = f"CHUA CHOT, {reason}: khong tuyen bo co hay khong co 3 cap do."
    else:
        h1_line = f"  H1 {'DAT' if d['h1_pass'] else 'KHONG DAT, chua tach duoc: ' + ', '.join(d['not_separated'])}"
        verdict = "NHAN 3 cap do nhu thiet ke." if d["accept_three_levels"] else "CHUA nhan 3 cap do."
    return [h1_line, f"  H2 {'DAT' if d['h2_pass'] else 'KHONG DAT, cap khong duoc dung: ' + ', '.join(d['h2_unusable_levels'])}",
            "  H3 " + ("DAT" if d["h3_pass"] else f"KHONG DAT: {d['h3_not_passed']}"), "  => " + verdict]


def format_report(s: dict) -> str:
    h1, h2, h3, d = s["h1"], s["h2"], s["h3"], s["decision"]
    lines = [f"3 cap do doi thu — bootstrap {s['n_boot']} lan, seed {s['seed']}", "",
             "H1 — thu tu do kho (>= 70% cap khong hoa VA can duoi KTC 95% CHINH, lay mau theo hoi thoai, > 50%):"]
    lines += _h1_lines(h1["pairs"])
    lines.append("  Ti le khong nhat quan 2 thu tu: " + ", ".join(f"{k} {_pct(v)}" for k, v in h1["tie_inconsistent_rate"].items()))
    lines.append("  Word count tb moi cap: " + ", ".join(f"{k} {_f(v, 0)}" for k, v in h1["word_count_mean"].items()))
    sens = h1["length_sensitivity"]
    lines += ["", f"H1 do nhay do dai (|chenh word_count| <= {sens['tolerance']:.0%} bai dai hon):"]
    lines += _h1_lines(sens["pairs"])
    lines.append("  So cap con lai: " + ", ".join(f"{k} {sens['remaining'][k]}/{sens['total'][k]}" for k in sens["remaining"]))
    lines.append("  Word count tb: " + ", ".join(f"{k} {_f(v, 0)}" for k, v in sens["word_count_mean"].items()))
    lines += ["", "H1 tach nhom:"]
    for k, table in h1["breakdown"].items():
        lines.append(f"  {k}: " + "; ".join(
            f"{p} {t['wins']}/{t['losses']}/{t['ties'] + t['tie_inconsistent']} ({_pct(t['win_rate'])})" for p, t in table.items()))
    lines += ["", f"H2 — NoF (nhanh - LM), can tren KTC 95% ghep cap <= +{h2['max_ci_high']}:"]
    lines += rep._compare_lines(h2["compare"])
    for lv, v in h2["levels"].items():
        lines.append(f"  {lv}: chenh {_f(v['diff'])}, can tren {_f(v['ci_high'])}, {v['n_pairs']} to hop -> {'DAT' if v['pass'] else 'khong dat'}")
    lines += ["  Do nhay (chi completed):"] + rep._compare_lines(h2["compare_sensitivity"])
    lines += ["  Hoi thoai dung som (quy tac 3d):"] + _stopped_lines(h2["stopped"])
    lines += ["", "Giam khao Q1/Q2 cua NoF: 40 nhan nguoi CHUA kiem o bao cao nay (label_judge --report)."]
    lines += ["", "H3 — tuan thu cap (target o LAN THU DAU >= 90%; 'khong do duoc' ngoai mau so, > 10% -> khong du du lieu):"]
    for lv, v in h3.items():
        lines.append(f"  {lv}: {v['status'].upper()}; {v['turns']} luot; target dung {v['target_correct']}/{v['measured']} "
                     f"= {_pct(v['target_first_attempt_rate'])}; khong do duoc {v['not_measurable']} = "
                     f"{_pct(v['not_measurable_rate'])} {v['not_measurable_kinds']}; luot that bai vi target {v['target_failed_turns']}")
        if v["not_measurable_warning"]:
            lines.append(f"    CANH BAO: {lv} co > {H3_MAX_NOT_MEASURABLE:.0%} luot khong do duoc — phat hien rieng ve do on dinh cua cap nay.")
        lines.append(f"    points_addressed (model khai, da khop): {v['points_addressed_dist']}; ti le dat cap {_pct(v['points_rate'])}; "
                     f"luot co points_unsupported {v['points_unsupported_turns']}/{v['accepted_turns']}")
    lines += ["", "Theo cap: model khai vs giam khao, muc nham nen tang (mo ta):"]
    for lv, v in s["judge_by_level"].items():
        lines.append(f"  {lv}: points_answered tb (giam khao) {_f(v['points_answered_mean'])}; attacks_foundational "
                     f"{_pct(v['attacks_foundational_rate'])}")
    lines += ["", f"Re nhanh: {s['branch']['states']} trang thai."]
    for lv, v in s["branch"]["levels"].items():
        lines.append(f"  {lv}: ok {v['ok']}, branch_failed {v['branch_failed']}, branch_infra {v['branch_infra']} {v['failure_kinds']}; "
                     f"target dung o lan thu dau {_pct(v['h3_first_attempt']['target_first_attempt_rate'])}")
    lines += ["", "Nhanh theo cap (tu tb | latency AI tb | chi phi USD | failure_kind):"]
    for lv, v in s["arms"].items():
        lines.append(f"  {lv}: {_f(v['word_count_mean'], 0)} | {_f(v['ai_latency_ms_mean'], 0)} ms | {v['cost_usd_total']} | {v['failure_kinds']}")
    jc = s["judge_cost"]
    lines.append(f"Giam khao pairwise: {jc['calls']} loi goi, token {jc['tokens_in']}/{jc['tokens_out']}, {jc['cost_usd']} USD")
    if s["label_report"]:
        lines += ["", lp.format_report(s["label_report"])]
    lines += ["", f"QUYET DINH (muc 3.2), H1 theo {d['h1_source']}:"] + _decision_lines(d)
    if not d["judge_checked"] and not d["labels_progress"]:
        lines.append("  Luu y: chua co nhan nguoi pairwise (--labels), ket luan H1 chua chot.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bao cao 3 cap do doi thu (Giai doan 3e)")
    p.add_argument("--arms", nargs="+", type=Path, required=True, help="JSONL run_pressure_eval co LE / LM / LH")
    p.add_argument("--branch", nargs="+", type=Path, required=True)
    p.add_argument("--pairwise", nargs="+", type=Path, required=True)
    p.add_argument("--labels", type=Path, default=None, help="CSV cua label_pairwise")
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--n-boot", type=int, default=DEFAULT_N_BOOT)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--json", type=Path, default=None)
    args = p.parse_args(argv)
    load = lambda paths: [r for f in paths for r in load_jsonl(f)]  # noqa: E731
    labels = read_csv(args.labels) if args.labels else None
    s = summarize(load(args.arms), load(args.branch), load(args.pairwise), labels, args.rounds, args.n_boot, args.seed)
    print(format_report(s))
    if args.json:
        args.json.write_text(json.dumps(s, ensure_ascii=False, indent=2, default=list), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
