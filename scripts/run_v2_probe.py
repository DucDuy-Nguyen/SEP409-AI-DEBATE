"""
Dot kiem tra v2 (docs/AI_DEVELOPMENT_LOG.md muc 3.14.1): cham 10 bai probe (8 hq + 2 ctrl) x N lan (mac dinh 3) bang
pipeline HIEN TAI cua app/ (cong thuc B + mo ta Evidence moi), temperature giu nhu app. KHONG sua app/.

- Dau vao: data/high_quality_args.json (nhu probe_high_quality.py).
- Ket qua: data/high_quality_probe_v2_results.jsonl (rieng, khong tron voi probe cu). Moi dong: id, run, diem tong,
  5 diem tieu chi, scoring_version, raw_model_output, usage that. Chay lai se bo qua (id, run) da co.
- Gap 429 theo ngay: dung sach. 429 theo phut: cho 65s toi da 3 lan roi dung (khong ghi loi).

Chay: python scripts/run_v2_probe.py [--n-runs 3] [--max-new N]
Phan tich: python scripts/analyze_v2_check.py
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from openai import RateLimitError

from app.config import get_settings
from app.services.evaluator import evaluate_argument
from app.services.llm_client import GroqClient
from config_fingerprint import combined_hash
from probe_high_quality import INPUT_PATH, build_request, load_items, validate_items
from run_vi_variance_eval import (
    DailyQuotaExceeded, append_record, install_usage_recorder, summarize_usage,
)

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_PATH = DATA_DIR / "high_quality_probe_v2_results.jsonl"
DELAY_SEC = 1.5
MINUTE_LIMIT_WAIT_SEC = 65
MINUTE_LIMIT_MAX_WAITS = 3


def load_done(path: Path) -> set[tuple[str, int]]:
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("status") == "ok":
                    done.add((r["id"], r["run"]))
    return done


def run_items(items: list[dict], n_runs: int, settings, client, recorder, results_path: Path = RESULTS_PATH,
              max_new: int | None = None, delay: float = DELAY_SEC, sleep=time.sleep) -> str | None:
    """Cham tung (bai, lan) chua co ket qua, ghi ngay vao results_path. Tra ve ly do dung (None neu xong)."""
    done = load_done(results_path)
    sent = 0
    for it in items:
        for run in range(1, n_runs + 1):
            if (str(it["id"]), run) in done:
                continue
            if max_new is not None and sent >= max_new:
                return f"da dat --max-new {max_new}"
            recorder.drain()
            result, minute_waits = None, 0
            while result is None:
                try:
                    result = evaluate_argument(build_request(it), settings=settings, llm_client=client)
                except DailyQuotaExceeded as e:
                    return f"HET QUOTA THEO NGAY: {str(e)[:200]}"
                except RateLimitError as e:
                    minute_waits += 1
                    if minute_waits > MINUTE_LIMIT_MAX_WAITS:
                        return f"429 theo phut van con sau {MINUTE_LIMIT_MAX_WAITS} lan cho: {str(e)[:200]}"
                    print(f"  429 theo phut, cho {MINUTE_LIMIT_WAIT_SEC}s ({minute_waits}/{MINUTE_LIMIT_MAX_WAITS}) ...")
                    sleep(MINUTE_LIMIT_WAIT_SEC)
                except Exception as e:
                    append_record(results_path, {"id": str(it["id"]), "run": run, "status": "error", "error_type": type(e).__name__,
                                                 "error": str(e)[:300], "usage": summarize_usage(recorder.drain())})
                    print(f"[{it['id']} run{run}] LOI {type(e).__name__}: {str(e)[:120]}")
                    break
            if result is None:
                continue
            rec = {"id": str(it["id"]), "run": run, "status": "ok", "side": it["side"].lower(), "text_chars": len(it["text"]),
                   "temperature": settings.llm_temperature, "scoring_version": result.scoring_version, "config_hash": combined_hash(), "model": settings.groq_model,
                   "overall_score": result.overall_score, "criteria": {c.name: c.score for c in result.criteria},
                   "raw_model_output": result.raw_model_output, "usage": summarize_usage(recorder.drain()),
                   "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            append_record(results_path, rec)
            sent += 1
            print(f"[{it['id']} run{run}] overall={rec['overall_score']} criteria={rec['criteria']} tokens={rec['usage']['total_tokens']}")
            sleep(delay)
    return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Probe v2: 10 bai x N lan voi cong thuc B + Evidence moi")
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--n-runs", type=int, default=3)
    parser.add_argument("--results", type=Path, default=RESULTS_PATH, help="File ket qua (mac dinh: probe v2 cu); dat file rieng cho dot khac")
    parser.add_argument("--max-new", type=int, default=None, help="Chi gui toi da N request moi lan chay")
    args = parser.parse_args()

    items = load_items(args.input)
    problems = [p for p in validate_items(items) if not p.startswith("Canh bao")]
    if problems:
        raise SystemExit("; ".join(problems))
    settings = get_settings()
    if settings.llm_provider.lower() != "groq":
        raise SystemExit(f"Script do usage qua GroqClient, LLM_PROVIDER hien la '{settings.llm_provider}'")
    client = GroqClient(settings)
    recorder = install_usage_recorder(client)
    total = len(items) * args.n_runs
    done = load_done(args.results)
    print(f"model={settings.groq_model} temperature={settings.llm_temperature} | {len(items)} bai x {args.n_runs} lan = {total} luot | da xong {len(done)}")
    stop = run_items(items, args.n_runs, settings, client, recorder, results_path=args.results, max_new=args.max_new)
    print(f"Tong: da xong {len(load_done(args.results))}/{total} luot hop le.")
    if stop:
        print(f"DUNG VI: {stop}")


if __name__ == "__main__":
    main()
