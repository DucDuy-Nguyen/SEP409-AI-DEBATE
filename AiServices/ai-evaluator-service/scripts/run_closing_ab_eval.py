"""
Do truoc/sau fix A + C (docs/AI_DEVELOPMENT_LOG.md muc 3.16) tren transcript phien 13: closing va rebuttal x N lan
moi dieu kien, qua dung evaluate_round cua app/ HIEN TAI. Dot "before" phai chay TRUOC khi sua app/.

- Dau vao: tests/fixtures/session13_ai_regulation.json.
- Ket qua: data/closing_ab_results.jsonl (gitignore). Moi dong: tag, stage, run, diem, nhan xet, so nhan xet bi loai,
  raw_model_output, usage that, config_hash. Chay lai se bo qua (tag, stage, run) da co.
- Ngan sach: dem MOI request gui di (ca request loi va retry), tinh ca cac lan chay truoc trong file ket qua; cham
  NGAN SACH thi dung sach. Retry ngam cua SDK openai bi tat de khong co request nao lot khoi bo dem.

Chay: python scripts/run_closing_ab_eval.py --tag before [--n-runs 10] [--budget 60]
Bao cao (khong goi API): python scripts/run_closing_ab_eval.py --report
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.config import get_settings
from app.schemas import ArgumentTurn, DebateSide, DebateStage, RoundEvaluationRequest, TurnSpeaker
from app.services.json_utils import EvaluationParseError
from app.services.llm_client import GroqClient
from app.services.round_evaluator import evaluate_round
from config_fingerprint import combined_hash
from run_vi_variance_eval import DailyQuotaExceeded, append_record, install_usage_recorder, summarize_usage

ROOT = Path(__file__).parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "session13_ai_regulation.json"
RESULTS_PATH = ROOT / "data" / "closing_ab_results.jsonl"
STAGES = ("closing", "rebuttal")
DELAY_SEC = 1.5
NO_RESPONSE_RE = re.compile(r"(chưa|không)\s+(được\s+)?(phản hồi|trả lời)", re.IGNORECASE)


class BudgetExhausted(Exception):
    """Da gui du so request cho phep cua dot do."""


def load_records() -> list[dict]:
    if not RESULTS_PATH.exists():
        return []
    return [json.loads(line) for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_request(stage: str) -> RoundEvaluationRequest:
    session = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    turns = [ArgumentTurn(speaker=TurnSpeaker(t["speaker"]), text=t["text"]) for t in session["turns"] if t["stage"] == stage]
    return RoundEvaluationRequest(motion=session["motion"], side=DebateSide.PRO, stage=DebateStage(stage), turns=turns)


def run(tag: str, n_runs: int, budget: int) -> None:
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    previous = load_records()
    used = sum(r["usage"]["attempts"] for r in previous)
    done = {(r["tag"], r["stage"], r["run"]) for r in previous if "round_score" in r}
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

    for stage in STAGES:
        request = build_request(stage)
        for run_index in range(n_runs):
            if (tag, stage, run_index) in done:
                continue
            recorder.calls.clear()
            record = {"tag": tag, "stage": stage, "run": run_index, "model": settings.groq_model,
                      "temperature": settings.llm_temperature, "config_hash": combined_hash()}
            stop_reason = None
            try:
                result = evaluate_round(request, settings, client)
                record.update(
                    round_score=result.round_score,
                    scores={c.name: c.score for c in result.criteria},
                    reasoning={c.name: c.reasoning for c in result.criteria},
                    consistency_note=result.consistency_note,
                    weaknesses=result.weaknesses,
                    dropped_weakness_count=getattr(result, "dropped_weakness_count", 0),
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
            print(tag, stage, run_index, record.get("round_score", record.get("error")), record.get("scores"), f"[{used}/{budget}]", flush=True)
            if stop_reason:
                print("DUNG:", stop_reason)
                return
            time.sleep(DELAY_SEC)


def report() -> None:
    records = load_records()
    usage = [r["usage"] for r in records]
    print(f"Tong request: {sum(u['attempts'] for u in usage)} (that bai {sum(u['failed_attempts'] for u in usage)}) | "
          f"token: {sum(u['total_tokens'] for u in usage)} (prompt {sum(u['prompt_tokens'] for u in usage)}, "
          f"completion {sum(u['completion_tokens'] for u in usage)}, reasoning {sum(u['reasoning_tokens'] for u in usage)})")
    print(f"config_hash: {sorted({(r['tag'], r['config_hash'][:12]) for r in records})}")
    for tag in sorted({r["tag"] for r in records}, reverse=True):
        for stage in STAGES:
            group = [r for r in records if r["tag"] == tag and r["stage"] == stage]
            ok = [r for r in group if "round_score" in r]
            if not ok:
                print(tag, stage, "khong co ket qua")
                continue
            scores = [r["round_score"] for r in ok]
            sd = statistics.stdev(scores) if len(scores) > 1 else 0.0
            kept = sum(len(r["weaknesses"]) for r in ok)
            dropped = sum(r["dropped_weakness_count"] for r in ok)
            no_response = sum(1 for r in ok for w in r["weaknesses"] if NO_RESPONSE_RE.search(w))
            criteria = {name: round(statistics.mean(r["scores"][name] for r in ok), 2) for name in ok[0]["scores"]}
            print(f"{tag:6} {stage:8} n={len(ok)} loi={len(group) - len(ok)} TB={statistics.mean(scores):.2f} SD={sd:.2f} "
                  f"min={min(scores)} max={max(scores)} | diem={scores}\n"
                  f"       nhan xet giu={kept} bi_loai={dropped} 'khong phan hoi'={no_response} | tieu chi TB={criteria}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", choices=["before", "after"])
    parser.add_argument("--n-runs", type=int, default=10)
    parser.add_argument("--budget", type=int, default=60)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.report:
        report()
    elif args.tag:
        run(args.tag, args.n_runs, args.budget)
    else:
        parser.error("can --tag hoac --report")


if __name__ == "__main__":
    main()
