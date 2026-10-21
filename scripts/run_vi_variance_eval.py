"""
Do do dao dong DIEM AI giua 2 lan cham tren 50 bai Dagstuhl (mau phan tang
data/_dagstuhl_vi_sample50.json) x 2 lan, prompt hien tai cua app/ (khong sua
gi trong app/).

Hai ngon ngu, CUNG bo bai, CUNG side, CUNG cau hinh, chi khac text + motion:
- --lang vi (mac dinh): text = cot text_vi cua data/dagstuhl_processed_vi.csv,
  motion = ban dich tieng Viet trong data/_dagstuhl_issue_vi.json.
  Ket qua: data/vi_variance_results.jsonl
- --lang en: text = cot text goc (tieng Anh), motion = ban tieng Anh DICH SAT tu
  motion tieng Viet (data/_dagstuhl_issue_motion_en.json), KHONG phai slug goc.
  Ket qua: data/en_variance_results.jsonl
- side = PRO neu stance cua bai (doc tu CSV goc Dagstuhl) == pro_stance cua issue,
  nguoc lai CON. KHONG dat PRO co dinh.
- Moi lan cham ghi NGAY 1 dong vao file jsonl (diem tong, 5 diem tieu chi, usage
  THAT tu response.usage, response tho cua model). Lan chay sau bo qua (id, run)
  da co ket qua "ok", nen chay don qua nhieu ngay duoc.
- --temperature T (vd 0): ghi de llm_temperature CHI trong script nay (khong dong vao
  .env hay app/); ket qua ghi file rieng data/<lang>_t<T>_variance_results.jsonl,
  vd data/vi_t0_variance_results.jsonl.
- "attempts" dem TAT CA request da gui (ke ca request loi nhu json_validate_failed
  hay 429 theo phut — loi khong co usage nen token cua chung khong biet);
  "failed_attempts" la phan loi trong do. Token chi cong tu request thanh cong.
- Gap 429 loai tokens-per-day / requests-per-day: dung sach, bao da xong/con bao
  nhieu. 429 theo phut (TPM/RPM): cho roi thu lai vai lan, khong retry vo han.

Chay (tu thu muc goc project):
    python scripts/run_vi_variance_eval.py --lang vi --max-new 2
    python scripts/run_vi_variance_eval.py --lang en
Phan tich: python scripts/analyze_vi_variance.py --lang both
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from openai import RateLimitError

from app.config import get_settings
from app.schemas import ArgumentEvaluationRequest, DebateSide, DebateStage
from app.services.evaluator import evaluate_argument
from app.services.llm_client import GroqClient
from config_fingerprint import combined_hash
from run_dagstuhl_agreement_eval import RAW_CSV_ENCODING, RAW_CSV_PATH

DATA_DIR = Path(__file__).parent.parent / "data"
VI_CSV_PATH = DATA_DIR / "dagstuhl_processed_vi.csv"
SAMPLE_PATH = DATA_DIR / "_dagstuhl_vi_sample50.json"
ISSUE_MAP_PATH = DATA_DIR / "_dagstuhl_issue_vi.json"
EN_MOTION_PATH = DATA_DIR / "_dagstuhl_issue_motion_en.json"
RESULTS_PATHS = {
    "vi": DATA_DIR / "vi_variance_results.jsonl",
    "en": DATA_DIR / "en_variance_results.jsonl",
}

N_RUNS = 2
DELAY_BETWEEN_CALLS_SEC = 1.5
MINUTE_LIMIT_WAIT_SEC = 65
MINUTE_LIMIT_MAX_WAITS = 3
MAX_CONSECUTIVE_ERRORS = 5

# Cac bai co gan side khong chac chan (chi so cua nhom nay duoc bao cao rieng).
# Chot sau khi nguoi dung doc tay _stance_check.txt: ban-plastic, stance 'yes' co
# nhieu bai khong the hien ro lap truong ung ho lenh cam.
FLAGGED_ISSUES = {"ban-plastic-water-bottles"}
FLAG_LABEL = "ban_plastic_side_uncertain"


class DailyQuotaExceeded(Exception):
    """429 theo NGAY (tokens/requests per day) — khong thu lai duoc trong ngay."""


def is_daily_limit(error: Exception) -> bool:
    text = str(error).lower()
    return "per day" in text or "(tpd)" in text or "(rpd)" in text


class UsageRecorder:
    """Boc ham create() cua SDK de (1) ghi usage THAT cua tung request thanh cong,
    (2) ghi nhan MOI request that bai (JSON hong, 429...) de dem dung so lan gui,
    va (3) bien 429 theo ngay thanh DailyQuotaExceeded ngay lap tuc — GroqClient
    chi bat RateLimitError nen exception nay di xuyen len tren, khong bi
    GroqClient thu lai 5 lan."""

    def __init__(self, real_create):
        self._real_create = real_create
        self.calls: list[dict] = []

    def create(self, **kwargs):
        try:
            response = self._real_create(**kwargs)
        except Exception as e:
            # Request loi khong co usage -> token = 0 chi la "khong biet", khong phai "khong ton".
            self.calls.append({"failed": True, "error_type": type(e).__name__, "error": str(e)[:200],
                               "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                               "reasoning_tokens": None})
            if isinstance(e, RateLimitError) and is_daily_limit(e):
                raise DailyQuotaExceeded(str(e)) from e
            raise
        usage = response.usage
        if usage is None:
            # Khong de loi ghi usage lam hong 1 luot cham da thanh cong; ghi nhan thieu usage.
            self.calls.append({"failed": False, "prompt_tokens": 0, "completion_tokens": 0,
                               "total_tokens": 0, "reasoning_tokens": None, "usage_missing": True})
            return response
        details = getattr(usage, "completion_tokens_details", None)
        self.calls.append({
            "failed": False,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "reasoning_tokens": getattr(details, "reasoning_tokens", None),
        })
        return response

    def drain(self) -> list[dict]:
        calls, self.calls = self.calls, []
        return calls


def install_usage_recorder(client: GroqClient) -> UsageRecorder:
    completions = client._client.chat.completions
    recorder = UsageRecorder(completions.create)
    completions.create = recorder.create
    return recorder


def summarize_usage(calls: list[dict]) -> dict:
    return {
        "attempts": len(calls),
        "failed_attempts": sum(1 for c in calls if c.get("failed")),
        "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
        "completion_tokens": sum(c["completion_tokens"] for c in calls),
        "total_tokens": sum(c["total_tokens"] for c in calls),
        "reasoning_tokens": sum(c["reasoning_tokens"] or 0 for c in calls),
        "calls": calls,
    }


def load_stances() -> dict[str, str]:
    """id -> stance, doc tu CSV goc (file processed khong giu cot nay)."""
    with open(RAW_CSV_PATH, "r", newline="", encoding=RAW_CSV_ENCODING) as f:
        reader = csv.reader(f, delimiter="\t")
        header = [h.strip().lower() for h in next(reader)]
        id_col, stance_col = header.index("#id"), header.index("stance")
        stances = {}
        for row in reader:
            if len(row) > max(id_col, stance_col) and row[id_col].strip():
                stances[row[id_col].strip()] = row[stance_col].strip()
    return stances


def build_items(lang: str = "vi") -> list[dict]:
    sample_ids = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    issue_map = json.loads(ISSUE_MAP_PATH.read_text(encoding="utf-8"))
    en_motions = json.loads(EN_MOTION_PATH.read_text(encoding="utf-8")) if lang == "en" else {}
    stances = load_stances()

    df = pd.read_csv(VI_CSV_PATH)
    df["id"] = df["id"].astype(str)
    by_id = df.set_index("id")

    items = []
    for arg_id in sample_ids:
        row = by_id.loc[arg_id]
        info = issue_map[row["issue"]]
        if info["status"] != "included":
            raise SystemExit(f"Bai {arg_id} thuoc issue bi loai ({row['issue']}), mau khong hop le")
        stance = stances[arg_id]
        items.append({
            "id": arg_id,
            "issue": row["issue"],
            "stance": stance,
            "side": "pro" if stance == info["pro_stance"] else "con",
            "motion": info["motion_vi"] if lang == "vi" else en_motions[row["issue"]],
            "text": row["text_vi"] if lang == "vi" else row["text"],
            "flag": FLAG_LABEL if row["issue"] in FLAGGED_ISSUES else None,
        })
    return items


def load_done(path: Path) -> set[tuple[str, int]]:
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add((rec["id"], rec["run"]))
    return done


def append_record(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def build_request(item: dict) -> ArgumentEvaluationRequest:
    return ArgumentEvaluationRequest(
        motion=item["motion"],
        side=DebateSide(item["side"]),
        stage=DebateStage.OPENING,
        argument_text=item["text"],
        opponent_argument_text=None,
    )


def score_one(item: dict, run: int, settings, client, recorder: UsageRecorder, lang: str = "vi") -> dict:
    # KHONG drain o day: request loi (vd 429 theo phut) cua cac lan thu truoc cho CUNG
    # item phai di vao ban ghi cua lan thanh cong ke tiep. Nguoi goi drain() sau khi
    # da dung ban ghi (ok hoac error) hoac khi bo item.
    result = evaluate_argument(build_request(item), settings=settings, llm_client=client)
    return {
        "id": item["id"], "run": run, "lang": lang, "status": "ok",
        "temperature": settings.llm_temperature,
        "scoring_version": result.scoring_version,
        "config_hash": combined_hash(),
        "model": settings.groq_model,
        "side": item["side"], "flag": item["flag"],
        "overall_score": result.overall_score,
        "criteria": {c.name: c.score for c in result.criteria},
        "raw_model_output": result.raw_model_output,
        "usage": summarize_usage(recorder.drain()),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Cham 50 bai x 2 lan, ghi jsonl (chay lai duoc)")
    parser.add_argument("--lang", choices=["vi", "en"], default="vi", help="Ngon ngu text + motion")
    parser.add_argument("--temperature", type=float, default=None,
                        help="Ghi de llm_temperature (vd 0); ket qua ghi file rieng, khong lan voi dot mac dinh")
    parser.add_argument("--n-runs", type=int, default=N_RUNS, help="So lan cham moi bai (mac dinh 2)")
    parser.add_argument("--tag", type=str, default=None,
                        help="Ghi vao data/<lang>_<tag>_variance_results.jsonl (vd v2) de khong tron voi du lieu cu")
    parser.add_argument("--max-new", type=int, default=None, help="Chi gui toi da N request moi lan chay (de thu/gioi han ngan sach)")
    args = parser.parse_args()
    if args.tag and args.temperature is not None:
        raise SystemExit("Khong truyen dong thoi --tag va --temperature (ten file ket qua se mo ho); chon mot trong hai")
    lang, results_path, n_runs = args.lang, RESULTS_PATHS[args.lang], args.n_runs
    if args.tag:
        results_path = DATA_DIR / f"{lang}_{args.tag}_variance_results.jsonl"

    settings = get_settings()
    if args.temperature is not None:
        settings = settings.model_copy(update={"llm_temperature": args.temperature})
        results_path = DATA_DIR / f"{lang}_t{args.temperature:g}_variance_results.jsonl"
    if settings.llm_provider.lower() != "groq":
        raise SystemExit(f"Script nay do usage qua GroqClient, LLM_PROVIDER hien la '{settings.llm_provider}'")
    client = GroqClient(settings)
    recorder = install_usage_recorder(client)

    items = build_items(lang)
    done = load_done(results_path)
    todo = [(it, run) for it in items for run in range(1, n_runs + 1) if (it["id"], run) not in done]
    total = len(items) * n_runs
    print(f"lang={lang} provider={settings.llm_provider} model={settings.groq_model} temperature={settings.llm_temperature} | "
          f"{len(items)} bai x {n_runs} lan = {total} luot | da xong {total - len(todo)} | con {len(todo)}")
    if args.max_new is not None:
        todo = todo[:args.max_new]
        print(f"--max-new {args.max_new}: lan chay nay toi da {len(todo)} request moi")

    sent = tokens = failed_attempts = errors_in_row = 0
    stop_reason = None
    try:
        for item, run in todo:
            record, minute_waits = None, 0
            while record is None:
                try:
                    record = score_one(item, run, settings, client, recorder, lang)
                except DailyQuotaExceeded as e:
                    stop_reason = f"HET QUOTA THEO NGAY: {str(e)[:300]}"
                    break
                except RateLimitError as e:
                    minute_waits += 1
                    if minute_waits > MINUTE_LIMIT_MAX_WAITS:
                        stop_reason = f"429 theo phut van con sau {MINUTE_LIMIT_MAX_WAITS} lan cho: {str(e)[:200]}"
                        break
                    print(f"  429 theo phut, cho {MINUTE_LIMIT_WAIT_SEC}s ({minute_waits}/{MINUTE_LIMIT_MAX_WAITS}) ...")
                    time.sleep(MINUTE_LIMIT_WAIT_SEC)
                except Exception as e:  # gom ca EvaluationParseError/ValidationError sau khi het lan thu lai
                    record = {
                        "id": item["id"], "run": run, "lang": lang, "status": "error",
                        "error_type": type(e).__name__, "error": str(e)[:300],
                        "usage": summarize_usage(recorder.drain()),
                        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
            if stop_reason:
                break

            append_record(results_path, record)
            sent += 1
            failed_attempts += record["usage"]["failed_attempts"]
            if record["status"] == "ok":
                errors_in_row = 0
                tokens += record["usage"]["total_tokens"]
                print(f"[{item['id']} run{run}] overall={record['overall_score']} criteria={record['criteria']} "
                      f"tokens={record['usage']['total_tokens']} (attempts={record['usage']['attempts']}, "
                      f"failed={record['usage']['failed_attempts']})")
            else:
                errors_in_row += 1
                print(f"[{item['id']} run{run}] LOI {record['error_type']}: {record['error'][:120]}")
                if errors_in_row >= MAX_CONSECUTIVE_ERRORS:
                    stop_reason = f"{MAX_CONSECUTIVE_ERRORS} loi lien tiep, dung de khong ton token vo ich"
                    break
            time.sleep(DELAY_BETWEEN_CALLS_SEC)
    except KeyboardInterrupt:
        stop_reason = "Bi ngat boi nguoi dung (Ctrl+C); ket qua da cham da duoc ghi"

    remaining = total - len(load_done(results_path))
    print(f"\nLan chay nay: {sent} luot ghi vao {results_path.name}, {tokens} token (chi tinh request thanh cong), "
          f"{failed_attempts} request loi khong co usage.")
    print(f"Tong: da xong {total - remaining}/{total} luot hop le, con {remaining}.")
    if stop_reason:
        print(f"DUNG VI: {stop_reason}")


if __name__ == "__main__":
    main()
