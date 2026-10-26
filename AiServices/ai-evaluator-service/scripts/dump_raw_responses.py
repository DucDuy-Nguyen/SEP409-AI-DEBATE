"""
Dump response THO cua model cho cac bai lech nhieu nhat giua 2 lan cham.

LUU Y QUAN TRONG: response tho cua 2 lan cham GOC KHONG duoc luu (jsonl cu chi co
diem). Script nay cham LAI cac bai do (moi bai --draws lan) va luu response tho cua
cac lan MOI. Day la lan boc tham moi, KHONG phai response goc, va co the khong lap
lai duoc su lech cu. Ket qua KHONG ghi vao jsonl chinh (khong lam ban du lieu do).
Tu nay ve sau, run_vi_variance_eval.py da luu raw_model_output trong moi ban ghi.

Chay: python scripts/dump_raw_responses.py [--top 3] [--draws 2] [--ids a,b,c]
Ket qua: data/_raw_dump_top.txt (doc duoc) + data/_raw_dump_top.jsonl
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from app.config import get_settings
from app.prompts.evaluator_prompt import build_user_prompt
from app.services.llm_client import GroqClient
from run_vi_variance_eval import (
    DailyQuotaExceeded, DATA_DIR, RESULTS_PATHS, append_record, build_items, build_request,
    install_usage_recorder, score_one,
)

OUT_TXT = DATA_DIR / "_raw_dump_top.txt"
OUT_JSONL = DATA_DIR / "_raw_dump_top.jsonl"
DELAY_SEC = 1.5


def top_by_overall_diff(n: int) -> list[tuple[str, float]]:
    by: dict[str, dict[int, dict]] = {}
    for line in RESULTS_PATHS["vi"].read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["status"] == "ok":
                by.setdefault(r["id"], {})[r["run"]] = r
    diffs = sorted(((i, abs(v[1]["overall_score"] - v[2]["overall_score"])) for i, v in by.items() if 1 in v and 2 in v),
                   key=lambda x: -x[1])
    if not diffs:
        raise SystemExit("Chua co bai nao du 2 luot trong jsonl VI")
    n = min(n, len(diffs))
    cutoff = diffs[n - 1][1]
    chosen = [d for d in diffs if d[1] >= cutoff]
    if len(chosen) != n:
        print(f"(!) Co hoa o hang {n} (diff = {cutoff}): lay {len(chosen)} bai thay vi {n}")
    return chosen


def original_scores(arg_id: str) -> dict:
    out = {}
    for line in RESULTS_PATHS["vi"].read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["id"] == arg_id and r["status"] == "ok":
                out[r["run"]] = {"overall": r["overall_score"], "criteria": r["criteria"]}
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--draws", type=int, default=2)
    parser.add_argument("--ids", type=str, default=None, help="Danh sach id cach nhau dau phay (bo qua --top)")
    args = parser.parse_args()

    settings = get_settings()
    client = GroqClient(settings)
    recorder = install_usage_recorder(client)
    items = {it["id"]: it for it in build_items("vi")}

    chosen = [(i, None) for i in args.ids.split(",")] if args.ids else top_by_overall_diff(args.top)
    unknown = [i for i, _ in chosen if i not in items]
    if unknown:
        raise SystemExit(f"id khong thuoc mau 50 bai: {unknown}")
    OUT_TXT.write_text("", encoding="utf-8")
    OUT_JSONL.write_text("", encoding="utf-8")

    def emit(text: str) -> None:
        with open(OUT_TXT, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    emit("DUMP RESPONSE THO — các lần chấm MỚI, KHÔNG phải response gốc của 2 lần chấm trước (response gốc không được lưu).")
    emit(f"model={settings.groq_model} temperature={settings.llm_temperature} max_tokens={settings.llm_max_tokens}")
    total_tokens = 0
    for arg_id, diff in chosen:
        item = items[arg_id]
        orig = original_scores(arg_id)
        emit("\n" + "=" * 100)
        emit(f"BÀI {arg_id} | issue={item['issue']} | side={item['side']} | stance={item['stance']}"
             + (f" | lệch gốc = {diff:.2f}" if diff is not None else ""))
        emit(f"Điểm 2 lần chấm GỐC: lần 1 = {orig.get(1)} ; lần 2 = {orig.get(2)}")
        emit("--- USER PROMPT gửi cho model (đúng như app/ dựng) ---")
        emit(build_user_prompt(build_request(item)))
        for draw in range(1, args.draws + 1):
            try:
                rec = score_one(item, draw, settings, client, recorder, "vi")
            except DailyQuotaExceeded as e:
                emit(f"\n!!! HẾT QUOTA NGÀY, dừng: {str(e)[:200]}")
                print("Het quota ngay, dung.")
                return
            except Exception as e:
                sent = len(recorder.drain())  # request lỗi của draw này không được rò sang draw sau
                emit(f"\n--- LẦN MỚI {draw}: LỖI {type(e).__name__}: {str(e)[:200]} (đã gửi {sent} request)")
                continue
            total_tokens += rec["usage"]["total_tokens"]
            append_record(OUT_JSONL, {**rec, "draw": draw, "original": orig})
            emit(f"\n--- LẦN MỚI {draw}: overall={rec['overall_score']} criteria={rec['criteria']} "
                 f"tokens={rec['usage']['total_tokens']} attempts={rec['usage']['attempts']} ---")
            emit(rec["raw_model_output"])
            print(f"{arg_id} lan moi {draw}: overall={rec['overall_score']} (goc: {orig.get(1, {}).get('overall')} / {orig.get(2, {}).get('overall')})")
            time.sleep(DELAY_SEC)
    print(f"Xong. {total_tokens} token. File: {OUT_TXT}")


if __name__ == "__main__":
    main()
