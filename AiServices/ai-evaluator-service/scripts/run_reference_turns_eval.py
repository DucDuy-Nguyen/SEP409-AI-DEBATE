"""
Do tac dung cua reference_turns (docs/AI_DEVELOPMENT_LOG.md muc 3.17) tren transcript phien 13: closing va rebuttal, co
va khong co reference_turns, N lan moi dieu kien, qua dung evaluate_round cua app/. Hai dieu kien chay XEN KE trong cung
1 dot vi TB closing tu no da lech 0.5 giua 2 dot do khac nhau (muc 3.16). Payload gia lap dung cach FE se gui
(docs/FE_SPEC_REFERENCE_TURNS.md).

- Dau vao: tests/fixtures/session13_ai_regulation.json.
- Ket qua: data/reference_turns_results.jsonl (gitignore). Moi dong: dieu kien, stage, run, diem, nhan xet,
  raw_model_output, usage that, config_hash. Chay lai se bo qua lan da co.
- Ngan sach: dem MOI request gui di (ca request loi va retry), tinh ca cac lan chay truoc trong file ket qua; cham
  NGAN SACH thi dung sach. Retry ngam cua SDK openai bi tat de khong co request nao lot khoi bo dem.

Chay: python scripts/run_reference_turns_eval.py [--n-runs 10] [--budget 60]
Bao cao (khong goi API): python scripts/run_reference_turns_eval.py --report
File doc tay, tron thu tu va an dieu kien (khong goi API): python scripts/run_reference_turns_eval.py --dump-blind OUT.txt
"""
import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.config import get_settings
from app.schemas import ArgumentTurn, DebateSide, DebateStage, ReferenceTurn, RoundEvaluationRequest, TurnSpeaker
from app.services.json_utils import EvaluationParseError
from app.services.llm_client import GroqClient
from app.services.round_evaluator import evaluate_round
from config_fingerprint import combined_hash
from run_vi_variance_eval import DailyQuotaExceeded, append_record, install_usage_recorder, summarize_usage

ROOT = Path(__file__).parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "session13_ai_regulation.json"
RESULTS_PATH = ROOT / "data" / "reference_turns_results.jsonl"
STAGES = ("closing", "rebuttal")
CONDITIONS = ("no_ref", "with_ref")
ROUND_OF_STAGE = {"opening": 1, "rebuttal": 2, "closing": 3}
DELAY_SEC = 1.5
BLIND_SEED = 20261103


class BudgetExhausted(Exception):
    """Da gui du so request cho phep cua dot do."""


def load_records() -> list[dict]:
    if not RESULTS_PATH.exists():
        return []
    return [json.loads(line) for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_request(stage: str, with_references: bool) -> RoundEvaluationRequest:
    session = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    turns = [ArgumentTurn(speaker=TurnSpeaker(t["speaker"]), text=t["text"]) for t in session["turns"] if t["stage"] == stage]
    references = [
        ReferenceTurn(round=t["round"], order=order, speaker=TurnSpeaker(t["speaker"]), side=DebateSide(t["side"]), text=t["text"])
        for order, t in enumerate(session["turns"], start=1)
        if t["round"] < ROUND_OF_STAGE[stage]
    ]
    return RoundEvaluationRequest(
        motion=session["motion"], side=DebateSide.PRO, stage=DebateStage(stage), turns=turns,
        reference_turns=references if with_references else [],
    )


def run(n_runs: int, budget: int) -> None:
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    previous = load_records()
    used = sum(r["usage"]["attempts"] for r in previous)
    done = {(r["condition"], r["stage"], r["run"]) for r in previous if "round_score" in r}
    print(f"Da dung {used}/{budget} request tu cac lan chay truoc")

    settings = get_settings()
    client = GroqClient(settings)
    client._client = client._client.with_options(max_retries=0)
    recorder = install_usage_recorder(client)
    completions = client._client.chat.completions
    recorded_create = completions.create

    def create_within_budget(*args, **kwargs):
        if used + len(recorder.calls) >= budget:
            raise BudgetExhausted(f"Da cham ngan sach {budget} request")
        return recorded_create(*args, **kwargs)

    completions.create = create_within_budget

    for run_index in range(n_runs):
        for stage in STAGES:
            for condition in CONDITIONS:
                if (condition, stage, run_index) in done:
                    continue
                recorder.calls.clear()
                record = {"condition": condition, "stage": stage, "run": run_index, "model": settings.groq_model,
                          "temperature": settings.llm_temperature, "config_hash": combined_hash()}
                stop_reason = None
                try:
                    result = evaluate_round(build_request(stage, condition == "with_ref"), settings, client)
                    record.update(
                        round_score=result.round_score,
                        scores={c.name: c.score for c in result.criteria},
                        reasoning={c.name: c.reasoning for c in result.criteria},
                        consistency_note=result.consistency_note,
                        strengths=result.strengths,
                        weaknesses=result.weaknesses,
                        raw_model_output=result.raw_model_output,
                    )
                except (BudgetExhausted, DailyQuotaExceeded) as e:
                    stop_reason = str(e)
                    record["error"] = stop_reason
                except EvaluationParseError as e:
                    record["error"] = str(e)[:300]
                record["usage"] = summarize_usage(list(recorder.calls))
                used += len(recorder.calls)
                append_record(RESULTS_PATH, record)
                print(condition, stage, run_index, record.get("round_score", record.get("error")), record.get("scores"), f"[{used}/{budget}]", flush=True)
                if stop_reason:
                    print("DUNG:", stop_reason)
                    return
                time.sleep(DELAY_SEC)


def report() -> None:
    records = load_records()
    usage = [r["usage"] for r in records]
    print(f"Tong request: {sum(u['attempts'] for u in usage)} (that bai {sum(u['failed_attempts'] for u in usage)}) | "
          f"token: {sum(u['total_tokens'] for u in usage)} | config_hash: {sorted({r['config_hash'][:12] for r in records})}")
    for stage in STAGES:
        for condition in CONDITIONS:
            group = [r for r in records if r["condition"] == condition and r["stage"] == stage]
            ok = [r for r in group if "round_score" in r]
            if not ok:
                print(condition, stage, "khong co ket qua")
                continue
            scores = [r["round_score"] for r in ok]
            sd = statistics.stdev(scores) if len(scores) > 1 else 0.0
            calls = [c for r in group for c in r["usage"]["calls"] if not c.get("failed")]
            criteria = {name: round(statistics.mean(r["scores"][name] for r in ok), 2) for name in ok[0]["scores"]}
            print(f"{condition:8} {stage:8} n={len(ok)} loi={len(group) - len(ok)} TB={statistics.mean(scores):.2f} SD={sd:.2f} "
                  f"min={min(scores)} max={max(scores)} | diem={scores}\n"
                  f"         token/request TB={statistics.mean(c['total_tokens'] for c in calls):.0f} "
                  f"(prompt {statistics.mean(c['prompt_tokens'] for c in calls):.0f}, completion "
                  f"{statistics.mean(c['completion_tokens'] for c in calls):.0f}) | request={sum(r['usage']['attempts'] for r in group)} | tieu chi TB={criteria}")
    for condition in CONDITIONS:
        calls = [c for r in records if r["condition"] == condition for c in r["usage"]["calls"] if not c.get("failed")]
        if calls:
            print(f"{condition}: token/request TB chung = {statistics.mean(c['total_tokens'] for c in calls):.0f}")


def dump_blind(out_path: str) -> None:
    """Tron thu tu, an dieu kien, de danh dau dao vai khong biet ban ghi thuoc dieu kien nao. Khoa o <out>.key.json."""
    records = [r for r in load_records() if "round_score" in r]
    random.Random(BLIND_SEED).shuffle(records)
    key = {}
    with open(out_path, "w", encoding="utf-8") as f:
        for index, r in enumerate(records, start=1):
            key[index] = {"condition": r["condition"], "stage": r["stage"], "run": r["run"], "round_score": r["round_score"]}
            f.write(f"## #{index} {r['stage']}\n")
            for name, text in r["reasoning"].items():
                f.write(f"{name}: {text}\n")
            f.write(f"Note: {r['consistency_note']}\n")
            for w in r["weaknesses"]:
                f.write(f"Weak: {w}\n")
            f.write("\n")
    Path(out_path + ".key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Da ghi {len(records)} ban ghi vao {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-runs", type=int, default=10)
    parser.add_argument("--budget", type=int, default=60)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--dump-blind", type=str, default=None)
    args = parser.parse_args()
    if args.report:
        report()
    elif args.dump_blind:
        dump_blind(args.dump_blind)
    else:
        run(args.n_runs, args.budget)


if __name__ == "__main__":
    main()
