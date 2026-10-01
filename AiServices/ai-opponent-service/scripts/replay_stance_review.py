"""
Chay LAI Stance Reviewer tren dung cac lan thu da gan nhan phe bang tay — so sanh v1 (chi claim) vs v2 (claim +
reasoning) tren cung du lieu. GOI LLM THAT (ton token), khong dung DB.

    python -m scripts.replay_stance_review --reviewer-version v2 --pause 3
    python -m scripts.replay_stance_review --reviewer-version v1 --pause 3
    python -m scripts.replay_stance_review --compare experiments/reviewer_replay/<a>_stance_review_v1.jsonl \\
                                                     experiments/reviewer_replay/<b>_stance_review_v2.jsonl
    # lay mau tu 1 file batch: cac lan thu bi bao side_flip/unclear + lan thu duoc chap nhan ngay sau
    python -m scripts.replay_stance_review --from-batch experiments/case_plan/<batch>.jsonl --only-flagged \\
                                           --reviewer-version v3 --pause 3

- --from-batch: in canh nhau verdict/position luc chay batch vs replay tung muc (kem nhan nguoi neu mau co trong
  stance_labels*.csv, restatement neu v3, phan hoi retry generator da nhan). Ghi <timestamp>_<version>_from-batch.jsonl.

- Nhan: experiments/labels/stance_labels.csv (dot 1; neu da doi ten -> tim stance_labels_round1*.csv) va
  stance_labels_round2.csv (dot 2) va stance_labels_v5.csv (dot 3, batch v5 — motion dang "A thay vi B").
  Bo qua *_old.csv (lan gan do dang).
- Weighing dot 1 KHONG tinh dong thuan (dinh nghia nhan "khong ro" luc do gop ca "trung lap").
- Reviewer: provider / model / max_tokens tu STANCE_REVIEW_*, temperature co dinh 0 (nhu cau hinh that), JSON schema
  neu CASE_PLAN_USE_JSON_SCHEMA. Loi 429 -> cho theo thoi gian provider yeu cau roi thu lai.
- Ghi experiments/reviewer_replay/<timestamp>_<reviewer_version>.jsonl (moi dong 1 mau, ghi ngay).
"""
import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.core.config import Settings, get_settings
from app.llm.client import LLMClient, get_llm_client, is_rate_limit_error, rate_limit_wait_seconds
from app.opponent import stance_reviewer as sr
from app.opponent.models import DebateSide
from scripts.eval_common import load_jsonl, parse_case_json, read_csv

ROOT = Path(__file__).resolve().parent.parent
LABELS_DIR = ROOT / "experiments" / "labels"
OUT_DIR = ROOT / "experiments" / "reviewer_replay"
POSITION_TO_LABEL = {"ung_ho_kien_nghi": "u", "phan_doi_kien_nghi": "p", "khong_ro": "k"}
LABEL_NAMES = {"u": "ung ho", "p": "phan doi", "k": "khong ro"}
VERSIONS = {"v1": sr.PROMPT_VERSION, "v2": sr.PROMPT_VERSION_V2, "v3": sr.PROMPT_VERSION_V3}
WEIGHING = sr.SUMMARY_ID

# 2 ca dac biet (lan thu reviewer v1 bao side_flip): M08 bao DUNG, M10 bao SAI (dao nghia phu dinh A3).
SPECIAL_CASES = {
    "20260926-171443_case_plan_v3.jsonl:15:3": "M08 con easy — lan thu #3 (v1 bao side_flip DUNG)",
    "20260927-094713_case_plan_v4.jsonl:19:1": "M10 con medium v4 — lan thu #1 (v1 bao side_flip SAI, A3 phu dinh)",
}


# ---------------- nhan + mau ----------------


def find_label_files(labels_dir: Path = LABELS_DIR) -> dict[int, Path]:
    """{1: file dot 1, 2: file dot 2, 3: file dot 3 (v5)}. Dot 1 uu tien stance_labels.csv, neu da doi ten thi stance_labels_round1*.csv."""
    def usable(p: Path) -> bool:
        return p.suffix == ".csv" and not p.stem.endswith("_old")

    files: dict[int, Path] = {}
    round1 = [labels_dir / "stance_labels.csv", *sorted(labels_dir.glob("stance_labels_round1*.csv"))]
    for p in round1:
        if p.exists() and usable(p):
            files[1] = p
            break
    round2 = [p for p in sorted(labels_dir.glob("stance_labels_round2*.csv")) if usable(p)]
    if round2:
        files[2] = round2[0]
    # dot 3 = nhan mu batch v5 (muc 2.4m): co motion dang "A thay vi B" (M05, M09) — ca v3 bao sai
    round3 = [p for p in sorted(labels_dir.glob("stance_labels_v5*.csv")) if usable(p)]
    if round3:
        files[3] = round3[0]
    return files


def _resolve(path: str) -> Path:
    p = Path(path.replace("\\", "/"))
    return p if p.is_absolute() else ROOT / p


def load_labeled_samples(label_files: dict[int, Path]) -> list[dict]:
    """Moi lan thu da gan nhan -> 1 mau: noi dung tu JSONL + nhan nguoi (theo dot)."""
    rows_by_sample: dict[str, dict] = {}
    for round_no, path in sorted(label_files.items()):
        for row in read_csv(path):
            entry = rows_by_sample.setdefault(
                row["sample_id"], {"round": round_no, "source_path": row["source_path"], "human": {}}
            )
            entry["human"][row["item_id"]] = row["human_label"]

    cache: dict[str, dict] = {}
    samples = []
    for sample_id, entry in rows_by_sample.items():
        source = entry["source_path"]
        if source not in cache:
            cache[source] = {f"{r['_source']}:{r['run_index']}": r for r in load_jsonl(_resolve(source))}
        file_name, run_index, attempt_no = sample_id.rsplit(":", 2)
        record = cache[source][f"{file_name}:{run_index}"]
        attempt = next(a for a in record["attempts"] if a["attempt"] == int(attempt_no))
        samples.append(_sample(record, attempt, source, entry["human"], entry["round"]))
    return samples


def _sample(record: dict, attempt: dict, source: str, human: dict, round_no: int | None, role: str | None = None) -> dict:
    case = parse_case_json(attempt["raw_output"])
    return {
        "sample_id": f"{record['_source']}:{record['run_index']}:{attempt['attempt']}", "round": round_no,
        "role": role, "source_path": source, "run_index": record["run_index"], "attempt": attempt["attempt"],
        "motion_id": record["motion_id"], "motion": record["motion"], "ai_side": record["ai_side"],
        "difficulty": record["difficulty"],
        "arguments": [{"id": a["id"], "claim": a["claim"], "reasoning": a.get("reasoning", "")} for a in case["arguments"]],
        "weighing": case["weighing"],
        "human": human,
        "original": {  # ket qua reviewer luc chay batch (phien ban luc do)
            p["id"]: p["position"] for p in (attempt.get("reviewer_detail") or {}).get("positions", [])
        },
        "original_restatements": {
            p["id"]: p["restatement"] for p in (attempt.get("reviewer_detail") or {}).get("positions", []) if p.get("restatement")
        },
        "original_verdict": attempt.get("reviewer_verdict"),
        "original_version": (attempt.get("reviewer_detail") or {}).get("prompt_version"),
    }


# ---------------- che do --from-batch ----------------

FLAGGED_VERDICTS = ("side_flip", "unclear")


def load_human_labels(labels_dir: Path = LABELS_DIR) -> dict[str, dict[str, str]]:
    """{sample_id: {item_id: nhan}} tu MOI stance_labels*.csv (tru *_old) — de hien cot 'nguoi' neu mau da duoc gan nhan."""
    labels: dict[str, dict[str, str]] = {}
    for path in sorted(labels_dir.glob("stance_labels*.csv")):
        if path.stem.endswith("_old"):
            continue
        for row in read_csv(path):
            labels.setdefault(row["sample_id"], {})[row["item_id"]] = row["human_label"]
    return labels


def load_batch_samples(path: Path, only_flagged: bool, human_labels: dict[str, dict[str, str]] | None = None) -> list[dict]:
    """
    Lay mau truc tiep tu 1 file batch. only_flagged: moi lan thu case_plan ma luc chay batch reviewer bao side_flip /
    unclear, VA lan thu duoc chap nhan ngay sau do trong cung luot chay (lan thu case_plan thanh cong dau tien phia sau).
    Khong only_flagged: moi lan thu case_plan da duoc reviewer danh gia (co position tung muc).
    """
    human_labels = human_labels or {}
    samples: dict[str, dict] = {}
    for record in load_jsonl(path):
        # lan thu case_plan co output (bo rate_limited / loi goi); purpose "stance_review" la log rieng cua reviewer
        plans = [a for a in record["attempts"] if a["purpose"] == "case_plan" and a.get("raw_output")]
        chosen: list[tuple[dict, str]] = []
        if only_flagged:
            for a in plans:
                if a.get("reviewer_verdict") in FLAGGED_VERDICTS:
                    chosen.append((a, "flagged"))
                    after = next((b for b in plans if b["attempt"] > a["attempt"] and b.get("success")), None)
                    if after is not None:
                        chosen.append((after, "accepted_after"))
        else:
            chosen = [(a, "reviewed") for a in plans if (a.get("reviewer_detail") or {}).get("positions")]
        for attempt, role in chosen:
            sample_id = f"{record['_source']}:{record['run_index']}:{attempt['attempt']}"
            if sample_id in samples:
                continue  # vd lan thu duoc chap nhan sau 2 lan side_flip — chi lay 1 lan
            sample = _sample(record, attempt, str(path), human_labels.get(sample_id, {}), None, role)
            sample["retry_feedback"] = attempt.get("retry_feedback")  # phan hoi generator nhan sau lan thu nay
            samples[sample_id] = sample
    return list(samples.values())


# ---------------- chay lai reviewer ----------------


def _call(client: LLMClient, system: str, user: str, settings: Settings, schema: dict | None, sleep, log) -> str:
    for waits in range(settings.case_plan_rate_limit_retries + 1):
        try:
            return client.generate(
                system, user, temperature=sr.TEMPERATURE, max_tokens=settings.stance_review_max_tokens, json_schema=schema
            )
        except Exception as e:  # noqa: BLE001
            if not is_rate_limit_error(e) or waits == settings.case_plan_rate_limit_retries:
                raise
            wait = (rate_limit_wait_seconds(e) or settings.case_plan_rate_limit_wait_seconds) + 1.0
            log(f"    429 -> cho {wait:.1f}s")
            sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


def replay(
    samples: list[dict], client: LLMClient, settings: Settings, version: str, out_path: Path,
    pause: float = 0, sleep=time.sleep, log=print,
) -> list[dict]:
    spec = sr.REVIEW_VERSIONS[version]  # prompt + schema + parse cua phien ban (giong service)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for i, s in enumerate(samples):
        if i and pause:
            sleep(pause)
        statements = [sr.Statement(a["id"], a["claim"], a["reasoning"]) for a in s["arguments"]]
        ids = [st.id for st in statements]
        system, user = spec.build_prompt(s["motion"], statements, s["weighing"])  # KHONG dua phe
        schema = spec.build_schema(ids, has_summary=True) if settings.case_plan_use_json_schema else None
        started = time.perf_counter()
        raw, error, positions, reasons, verdict, restatements = None, None, {}, {}, None, {}
        client.last_usage = None
        try:
            raw = _call(client, system, user, settings, schema, sleep, log)
            review, extra = spec.parse(raw, ids, has_summary=True)
            verdict, detail = sr.judge(review, DebateSide(s["ai_side"]), version, extra)
            verdict = verdict.value
            positions = {p["id"]: p["position"] for p in detail["positions"]}
            reasons = {p["id"]: p["reason"] for p in detail["positions"]}
            restatements = {k: v["restatement"] for k, v in extra.items()}  # chi v3
        except Exception as e:  # noqa: BLE001 — ghi lai, chay tiep mau khac
            error = f"{type(e).__name__}: {e}"[:2000]
        usage = client.last_usage or {}
        result = {
            "sample_id": s["sample_id"], "round": s["round"], "source_path": s["source_path"],
            "run_index": s["run_index"], "attempt": s["attempt"], "motion_id": s["motion_id"], "motion": s["motion"],
            "ai_side": s["ai_side"], "difficulty": s["difficulty"], "reviewer_version": version,
            "provider": client.provider, "model": client.model, "temperature": sr.TEMPERATURE,
            "max_tokens": settings.stance_review_max_tokens,
            "tokens_in": usage.get("tokens_in"), "tokens_out": usage.get("tokens_out"),
            "latency_ms": int((time.perf_counter() - started) * 1000), "error": error, "raw_output": raw,
            "verdict": verdict, "positions": positions, "reasons": reasons, "restatements": restatements,
            "human": s["human"], "role": s.get("role"), "retry_feedback": s.get("retry_feedback"),
            "original": s["original"], "original_verdict": s["original_verdict"],
            "original_version": s.get("original_version"), "original_restatements": s.get("original_restatements", {}),
        }
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        results.append(result)
        log(f"[{i + 1}/{len(samples)}] {s['motion_id']} {s['ai_side']} #{s['attempt']} -> {verdict or 'LOI: ' + (error or '')}")
    return results


# ---------------- bao cao ----------------


def compared_items(results: list[dict]) -> list[dict]:
    """Moi muc co nhan nguoi + ket qua reviewer. Weighing dot 1 bi loai."""
    items = []
    for r in results:
        for item_id, human in r["human"].items():
            if item_id == WEIGHING and r["round"] == 1:
                continue
            position = r["positions"].get(item_id)
            if position is None:
                continue
            items.append({"sample_id": r["sample_id"], "item_id": item_id, "kind": "weighing" if item_id == WEIGHING else "argument",
                          "human": human, "reviewer": POSITION_TO_LABEL[position], "reason": r["reasons"].get(item_id, "")})
    return items


def build_report(results: list[dict]) -> dict:
    items = compared_items(results)

    def agree(kind):
        sub = [it for it in items if it["kind"] == kind]
        return sum(1 for it in sub if it["human"] == it["reviewer"]), len(sub)

    return {
        "version": results[0]["reviewer_version"] if results else None,
        "samples": len(results),
        "errors": [r["sample_id"] for r in results if r["error"]],
        # file replay cu (truoc 2026-09-29 chieu) chua ghi token -> None
        "tokens_out_max": max((r["tokens_out"] for r in results if r.get("tokens_out") is not None), default=None),
        "max_tokens": results[0].get("max_tokens") if results else None,
        "arguments": agree("argument"),
        "weighing": agree("weighing"),
        "confusion": Counter((it["human"], it["reviewer"]) for it in items),
        "disagreements": [it for it in items if it["human"] != it["reviewer"]],
        "special": [r for r in results if r["sample_id"] in SPECIAL_CASES],
    }


def _rate(pair: tuple[int, int]) -> str:
    ok, n = pair
    return f"{ok}/{n} ({ok / n:.0%})" if n else "0/0"


def format_report(report: dict) -> str:
    lines = [
        f"\n===== REPLAY {report['version']} — {report['samples']} mau =====",
        f"Loi goi reviewer: {len(report['errors'])} {report['errors'] if report['errors'] else ''}",
        f"tokens_out lon nhat: {report['tokens_out_max']} (max_tokens={report['max_tokens']})",
        f"Dong thuan nguoi vs reviewer — luan diem: {_rate(report['arguments'])} | weighing (dot 2+): {_rate(report['weighing'])}",
        "",
        "Bang nham lan (hang = nguoi, cot = reviewer; luan diem + weighing dot 2+):",
        "          " + "".join(f"{LABEL_NAMES[c]:>10}" for c in "upk"),
    ]
    for h in "upk":
        lines.append(f"{LABEL_NAMES[h]:<10}" + "".join(f"{report['confusion'][(h, c)]:>10}" for c in "upk"))
    lines.append(f"\nBat dong ({len(report['disagreements'])}):")
    for it in report["disagreements"]:
        lines.append(f"  - {it['sample_id']} [{it['item_id']}] nguoi={LABEL_NAMES[it['human']]} "
                     f"reviewer={LABEL_NAMES[it['reviewer']]} — ly do: {it['reason']}")
    lines.append("\nHai ca dac biet:")
    for r in report["special"]:
        lines.append(f"  * {SPECIAL_CASES[r['sample_id']]} (AI phe {r['ai_side']})")
        lines.append(f"    verdict: luc chay batch={r['original_verdict']} -> replay={r['verdict'] or 'LOI'}")
        for item_id, human in r["human"].items():
            now = r["positions"].get(item_id)
            lines.append(
                f"    [{item_id}] nguoi={LABEL_NAMES.get(human, human)} | batch={POSITION_TO_LABEL.get(r['original'].get(item_id), '-')}"
                f" | replay={POSITION_TO_LABEL.get(now, '-')} — {r['reasons'].get(item_id, '')}"
            )
            restated = r.get("restatements", {}).get(item_id)
            if restated:
                lines.append(f"        dien dat lai (v3): {restated}")
    missing = [sid for sid in SPECIAL_CASES if sid not in {r["sample_id"] for r in report["special"]}]
    if missing:
        lines.append(f"  (khong co trong nhan: {missing})")
    return "\n".join(lines)


ROLE_NAMES = {"flagged": "BI BAO luc chay batch", "accepted_after": "duoc chap nhan ngay sau", "reviewed": "da review"}


def format_batch_comparison(results: list[dict]) -> str:
    """Che do --from-batch: verdict batch vs replay canh nhau, theo tung muc; kem nhan nguoi va restatement neu co."""
    if not results:
        return "Khong co lan thu nao phu hop."
    version = results[0]["reviewer_version"]
    lines = [f"\n===== BATCH vs REPLAY {version} — {len(results)} lan thu ====="]
    changed_verdicts = 0
    for r in results:
        if r["verdict"] != r["original_verdict"]:
            changed_verdicts += 1
        lines.append(
            f"\n* {r['motion_id']} {r['ai_side']} {r['difficulty']} — run {r['run_index']} lan thu #{r['attempt']} "
            f"({ROLE_NAMES.get(r.get('role'), r.get('role') or '-')}) | {r['motion']}"
        )
        lines.append(
            f"  verdict: batch ({r.get('original_version') or '?'}) = {r['original_verdict']} -> replay = {r['verdict'] or 'LOI: ' + (r['error'] or '')}"
        )
        for item_id in list(r["original"]) or list(r["positions"]):
            batch_pos = POSITION_TO_LABEL.get(r["original"].get(item_id), "-")
            replay_pos = POSITION_TO_LABEL.get(r["positions"].get(item_id), "-")
            human = r["human"].get(item_id)
            mark = "  " if batch_pos == replay_pos else "=>"
            lines.append(
                f"  {mark} [{item_id}] batch={batch_pos} replay={replay_pos}"
                + (f" nguoi={human}" if human else "")
                + (f" — {r['reasons'].get(item_id, '')}" if r["reasons"].get(item_id) else "")
            )
            for label, text in (("batch", r.get("original_restatements", {}).get(item_id)),
                                ("replay", r.get("restatements", {}).get(item_id))):
                if text:
                    lines.append(f"        dien dat lai ({label}): {text}")
        if r.get("retry_feedback"):
            lines.append("  phan hoi retry generator da nhan: " + r["retry_feedback"].replace("\n", " | "))
    labeled = [(h, POSITION_TO_LABEL.get(r["positions"].get(i))) for r in results for i, h in r["human"].items()
               if r["positions"].get(i)]
    labeled_batch = [(h, POSITION_TO_LABEL.get(r["original"].get(i))) for r in results for i, h in r["human"].items()
                     if r["original"].get(i)]
    lines.append(f"\nVerdict doi so voi batch: {changed_verdicts}/{len(results)}")
    if labeled:
        lines.append(
            f"Dong thuan voi nhan nguoi (moi muc co nhan): batch {sum(h == p for h, p in labeled_batch)}/{len(labeled_batch)}"
            f" | replay {sum(h == p for h, p in labeled)}/{len(labeled)}"
        )
    return "\n".join(lines)


def compare_replays(a: list[dict], b: list[dict]) -> str:
    """Dat 2 lan replay (vd v1, v2) canh nhau; liet ke muc doi ket luan."""
    ra, rb = build_report(a), build_report(b)
    va, vb = ra["version"], rb["version"]
    by_id_b = {r["sample_id"]: r for r in b}
    lines = [
        f"\n===== SO SANH {va} vs {vb} =====",
        f"{'':<28}{va:>22}{vb:>22}",
        f"{'Dong thuan luan diem':<28}{_rate(ra['arguments']):>22}{_rate(rb['arguments']):>22}",
        f"{'Dong thuan weighing (dot 2+)':<28}{_rate(ra['weighing']):>22}{_rate(rb['weighing']):>22}",
        f"{'Loi goi reviewer':<28}{len(ra['errors']):>22}{len(rb['errors']):>22}",
        "\nMuc DOI ket luan:",
    ]
    changed = 0
    for r in a:
        other = by_id_b.get(r["sample_id"])
        if other is None:
            continue
        if r["verdict"] != other["verdict"]:
            lines.append(f"  * {r['sample_id']} verdict: {r['verdict']} -> {other['verdict']}")
        for item_id, pos in r["positions"].items():
            new = other["positions"].get(item_id)
            if new is not None and new != pos:
                changed += 1
                human = r["human"].get(item_id)
                excluded = " (weighing dot 1 — khong tinh)" if item_id == WEIGHING and r["round"] == 1 else ""
                lines.append(
                    f"  - {r['sample_id']} [{item_id}] {POSITION_TO_LABEL[pos]} -> {POSITION_TO_LABEL[new]}"
                    f" | nguoi={human or '-'}{excluded}"
                    f"{' | ' + SPECIAL_CASES[r['sample_id']] if r['sample_id'] in SPECIAL_CASES else ''}"
                )
    if not changed:
        lines.append("  (khong muc nao doi)")
    only = sorted(set(by_id_b) ^ {r["sample_id"] for r in a})
    if only:
        lines.append(f"Mau chi co o 1 ben (bo qua): {only}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, client: LLMClient | None = None, settings: Settings | None = None,
         sleep=time.sleep) -> int:
    """client / settings / sleep: chi de test truyen LLM gia."""
    parser = argparse.ArgumentParser(description="Chay lai Stance Reviewer tren cac lan thu da gan nhan (LLM THAT)")
    parser.add_argument("--reviewer-version", choices=sorted(VERSIONS), default="v2")
    parser.add_argument("--pause", type=float, default=3.0, help="Giay nghi giua cac loi goi")
    parser.add_argument("--labels-dir", type=Path, default=LABELS_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A.jsonl", "B.jsonl"),
                        help="Khong goi LLM: so sanh 2 file replay da co")
    parser.add_argument("--from-batch", type=Path, metavar="BATCH.jsonl",
                        help="Lay mau tu 1 file batch (experiments/case_plan/...) thay vi tu file nhan")
    parser.add_argument("--only-flagged", action="store_true",
                        help="Cung --from-batch: chi cac lan thu bi bao side_flip/unclear + lan thu duoc chap nhan ngay sau")
    args = parser.parse_args(argv)

    if args.only_flagged and not args.from_batch:
        parser.error("--only-flagged chi dung cung --from-batch")

    if args.compare:
        a, b = ([json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] for p in args.compare)
        print(format_report(build_report(a)))
        print(format_report(build_report(b)))
        print(compare_replays(a, b))
        return 0

    version = VERSIONS[args.reviewer_version]
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    if args.from_batch:
        samples = load_batch_samples(args.from_batch, args.only_flagged, load_human_labels(args.labels_dir))
        if not samples:
            print(f"Khong co lan thu phu hop trong {args.from_batch}")
            return 0
        source = f"{args.from_batch.name}{' (only-flagged)' if args.only_flagged else ''}"
        out_path = args.out_dir / f"{stamp}_{version}_from-batch.jsonl"
    else:
        label_files = find_label_files(args.labels_dir)
        if not label_files:
            parser.error(f"Khong tim thay file nhan trong {args.labels_dir}")
        samples = load_labeled_samples(label_files)
        source = ", ".join(f"dot {k}: {v.name}" for k, v in sorted(label_files.items()))
        out_path = args.out_dir / f"{stamp}_{version}.jsonl"
    settings = settings or get_settings()
    client = client or get_llm_client(settings, provider=settings.stance_review_provider, model=settings.stance_review_model)
    print(f"{len(samples)} mau tu {source} | {version} | {client.provider}/{client.model} temperature={sr.TEMPERATURE} "
          f"max_tokens={settings.stance_review_max_tokens} | pause {args.pause}s -> {out_path}")
    results = replay(samples, client, settings, version, out_path, pause=args.pause, sleep=sleep)
    if args.from_batch:
        print(format_batch_comparison(results))
    else:
        print(format_report(build_report(results)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
