"""
H8 (docs/AI_DEVELOPMENT_LOG.md muc 3.11.1): "tran diem Evidence/Persuasiveness <= 3/5 co the do dataset toan bai yeu".
Script THU (probe): cham 8-10 lap luan CHAT LUONG CAO do nguoi dung cung cap, 1 lan moi bai, bang DUNG pipeline
cua app/ (evaluate_argument, cung prompt, cung settings mac dinh, temperature 0.2). KHONG sua app/.

Dinh dang file dau vao (JSON, mac dinh data/high_quality_args.json):
[
  {"id": "hq01", "motion": "...", "side": "pro" | "con", "text": "...",
   "source": "nguon / ly do ban cho la chat luong cao (tuy chon, chi de ghi chu)",
   "opponent_text": "luot cua doi phuong (tuy chon; neu co thi chay o che do INTERACTIVE)"}
]
- Cung ngon ngu voi san pham (tieng Viet) neu muon so voi ket qua VI; tieng Anh cung chay duoc (prompt van tieng Viet).
- Nen ghi ro nguon va tieu chi "chat luong cao"; nen co do dai/the loai gan Dagstuhl neu muon tranh gay nhieu (do dai la bien gay nhieu).

Che do:
  python scripts/probe_high_quality.py --validate   # kiem tra file, KHONG goi API
  python scripts/probe_high_quality.py              # cham (chi bai chua co ket qua; ghi data/high_quality_probe_results.jsonl)
  python scripts/probe_high_quality.py --report     # in tong hop tu file ket qua, KHONG goi API
Gap 429 theo ngay: dung sach. Ket qua ghi ngay sau tung bai (kem raw_model_output va usage that).

Tham chieu Dagstuhl (300 luot cham, 50 bai): Evidence lon nhat 3, Persuasiveness lon nhat 3, diem tong lon nhat 7.2;
Evidence >= 4: 0/300, Persuasiveness >= 4: 0/300. Hay CHOT TRUOC cach doc ket qua (vd: bao nhieu bai phai dat Evidence/Persuasiveness >= 4
de coi H8 duoc ung ho) TRUOC KHI chay; script chi in so, khong ket luan.
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
from app.schemas import ArgumentEvaluationRequest, DebateSide, DebateStage
from app.services.evaluator import evaluate_argument
from app.services.llm_client import GroqClient
from run_vi_variance_eval import DailyQuotaExceeded, append_record, install_usage_recorder, summarize_usage

DATA_DIR = Path(__file__).parent.parent / "data"
INPUT_PATH = DATA_DIR / "high_quality_args.json"
RESULTS_PATH = DATA_DIR / "high_quality_probe_results.jsonl"
RESULTS_PATH_RUN2 = DATA_DIR / "high_quality_probe_results_run2.jsonl"  # chay lai 8 bai hq (quy tac muc 3.11.3)
CRITERIA = ["Logic", "Evidence", "Relevance", "Structure", "Persuasiveness"]
EXPECTED_MIN, EXPECTED_MAX = 8, 10
DELAY_SEC = 1.5
MINUTE_LIMIT_WAIT_SEC = 65
MINUTE_LIMIT_MAX_WAITS = 3
DAGSTUHL_REFERENCE = {"Evidence>=4": "0/300 luot", "Persuasiveness>=4": "0/300 luot", "overall_max": 7.2}


def load_items(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Chua co file dau vao: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_items(items: list[dict]) -> list[str]:
    """Tra ve danh sach loi/canh bao (rong = hop le)."""
    problems = []
    if not isinstance(items, list):
        return ["File phai la mot danh sach JSON"]
    if not (EXPECTED_MIN <= len(items) <= EXPECTED_MAX):
        problems.append(f"Canh bao: co {len(items)} bai, ke hoach la {EXPECTED_MIN}-{EXPECTED_MAX}")
    seen = set()
    for i, it in enumerate(items, start=1):
        tag = f"muc {i}"
        if not isinstance(it, dict):
            problems.append(f"{tag}: phai la object")
            continue
        for key in ("id", "motion", "side", "text"):
            if not str(it.get(key, "")).strip():
                problems.append(f"{tag}: thieu '{key}'")
        if str(it.get("side", "")).lower() not in ("pro", "con"):
            problems.append(f"{tag}: side phai la 'pro' hoac 'con'")
        if str(it.get("id", "")) in seen:
            problems.append(f"{tag}: id trung '{it.get('id')}'")
        seen.add(str(it.get("id", "")))
        if str(it.get("id", "")).lower().startswith("example"):
            problems.append(f"{tag}: id bat dau bang 'example' (co ve la du lieu mau, chua thay bang bai that)")
    return problems


def build_request(it: dict) -> ArgumentEvaluationRequest:
    return ArgumentEvaluationRequest(
        motion=it["motion"],
        side=DebateSide(it["side"].lower()),
        stage=DebateStage.OPENING,
        argument_text=it["text"],
        opponent_argument_text=(it.get("opponent_text") or None),
    )


def load_done() -> set[str]:
    done = set()
    if RESULTS_PATH.exists():
        for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(rec["id"])
    return done


def score_items(items: list[dict], settings, client, recorder, results_path: Path = RESULTS_PATH, delay: float = DELAY_SEC) -> str | None:
    """Cham tung bai chua co ket qua, ghi ngay vao results_path. Tra ve ly do dung (None neu xong)."""
    done = set()
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(rec["id"])
    for it in items:
        if str(it["id"]) in done:
            continue
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
                time.sleep(MINUTE_LIMIT_WAIT_SEC)
            except Exception as e:
                append_record(results_path, {"id": str(it["id"]), "status": "error", "error_type": type(e).__name__,
                                             "error": str(e)[:300], "usage": summarize_usage(recorder.drain())})
                print(f"[{it['id']}] LOI {type(e).__name__}: {str(e)[:120]}")
                break
        if result is None:
            continue
        rec = {"id": str(it["id"]), "status": "ok", "side": it["side"].lower(), "text_chars": len(it["text"]),
               "temperature": settings.llm_temperature, "source": it.get("source"),
               "overall_score": result.overall_score, "criteria": {c.name: c.score for c in result.criteria},
               "raw_model_output": result.raw_model_output, "usage": summarize_usage(recorder.drain()),
               "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        append_record(results_path, rec)
        print(f"[{it['id']}] overall={rec['overall_score']} criteria={rec['criteria']} tokens={rec['usage']['total_tokens']}")
        time.sleep(delay)
    return None


RULE_TEXT = (
    "QUY TẮC ĐỌC KẾT QUẢ H8 (chốt TRƯỚC khi chạy): "
    "ỦNG HỘ H8 nếu >= 6/8 bài hq có Evidence >= 4 VÀ >= 6/8 bài hq có Persuasiveness >= 4 VÀ cả 2 bài ctrl có Evidence <= 2. "
    "BÁC BỎ nếu <= 2/8 bài hq đạt Evidence >= 4 HOẶC <= 2/8 đạt Persuasiveness >= 4. "
    "Còn lại: KHÔNG KẾT LUẬN, chạy lại 8 bài hq thêm 1 lần. "
    "CỜ ĐỘ DÀI nếu một bài ctrl có Evidence >= 3."
)


def is_ctrl(rec_id: str) -> bool:
    return rec_id.lower().startswith("ctrl")


def decide(hq: list[dict], ctrl: list[dict]) -> tuple[str, dict]:
    """Ap dung DUNG quy tac RULE_TEXT tren cac ban ghi 'ok' (hq: 8 bai, ctrl: 2 bai)."""
    ev_hq = sum(r["criteria"]["Evidence"] >= 4 for r in hq)
    pe_hq = sum(r["criteria"]["Persuasiveness"] >= 4 for r in hq)
    ctrl_ok = len(ctrl) == 2 and all(r["criteria"]["Evidence"] <= 2 for r in ctrl)
    support = ev_hq >= 6 and pe_hq >= 6 and ctrl_ok
    refute = ev_hq <= 2 or pe_hq <= 2
    length_flag = any(r["criteria"]["Evidence"] >= 3 for r in ctrl)
    if len(hq) != 8 or len(ctrl) != 2:
        outcome = f"CHUA DU DU LIEU (hq {len(hq)}/8, ctrl {len(ctrl)}/2)"
    elif support:
        outcome = "ỦNG HỘ H8"
    elif refute:
        outcome = "BÁC BỎ H8"
    else:
        outcome = "KHÔNG KẾT LUẬN -> chạy lại 8 bài hq thêm 1 lần"
    return outcome, {"ev_hq": ev_hq, "pe_hq": pe_hq, "ctrl_ok": ctrl_ok, "length_flag": length_flag}


def report(results_path: Path = RESULTS_PATH) -> str:
    if not results_path.exists():
        return "Chua co ket qua."
    recs = [json.loads(l) for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = {r["id"]: r for r in recs if r["status"] == "ok"}
    lines = [RULE_TEXT, "",
             f"Bai da cham: {len(ok)} (loi: {sum(1 for r in recs if r['status'] != 'ok')}). Moi bai 1 lan, temperature "
             f"{next(iter(ok.values()))['temperature'] if ok else 'n/a'}; 1 lan cham co nhieu giua cac lan (xem docs/AI_DEVELOPMENT_LOG.md muc 3.12), "
             f"nen diem 1 bai khong phai gia tri on dinh."]
    lines.append(f"{'id':<12}{'chars':>7}{'overall':>9}" + "".join(f"{c[:5]:>7}" for c in CRITERIA))
    for r in ok.values():
        lines.append(f"{r['id']:<12}{r['text_chars']:>7}{r['overall_score']:>9.2f}" + "".join(f"{r['criteria'][c]:>7}" for c in CRITERIA))
    if ok:
        hq = [r for r in ok.values() if not is_ctrl(r["id"])]
        ctrl = [r for r in ok.values() if is_ctrl(r["id"])]
        outcome, d = decide(hq, ctrl)
        over = lambda rs: sum(r["overall_score"] > 7.2 + 1e-9 for r in rs)
        lines += ["",
                  f"hq: Evidence >= 4: {d['ev_hq']}/{len(hq)} | Persuasiveness >= 4: {d['pe_hq']}/{len(hq)} | ctrl Evidence <= 2 (ca hai): {d['ctrl_ok']}",
                  f"Diem tong hq: " + ", ".join(f"{r['id']}={r['overall_score']:.1f}" for r in hq)
                  + (f" | TB {sum(r['overall_score'] for r in hq) / len(hq):.2f}, lon nhat {max(r['overall_score'] for r in hq):.1f}" if hq else ""),
                  f"So bai co diem tong > 7.2: hq {over(hq)}/{len(hq)}, ctrl {over(ctrl)}/{len(ctrl)} (tran Dagstuhl: max 7.2 tren 300 luot)",
                  f"Tham chieu Dagstuhl (300 luot): Evidence >= 4: {DAGSTUHL_REFERENCE['Evidence>=4']}, Persuasiveness >= 4: {DAGSTUHL_REFERENCE['Persuasiveness>=4']}",
                  f"CO DO DO DAI: {'CO (ctrl co Evidence >= 3: do dai co the keo diem len)' if d['length_flag'] else 'khong (ctrl Evidence <= 2)'}",
                  "Luu y: bai do nguoi dung chon/viet rieng nen 'chat luong cao' khong doc lap voi nguoi chon; do dai (~1000 ky tu) gap ~3 lan Dagstuhl.",
                  "", f"KET QUA THEO QUY TAC: {outcome}"]
    return "\n".join(lines)


def show(rec_id: str, results_path: Path = RESULTS_PATH) -> str:
    """In diem + ly do tung tieu chi cua 1 bai tu raw_model_output (khong goi API)."""
    if not results_path.exists():
        return "Chua co ket qua."
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("id") == rec_id and r.get("status") == "ok":
                out = [f"{rec_id}: overall {r['overall_score']}, criteria {r['criteria']}"]
                try:
                    parsed = json.loads(r.get("raw_model_output") or "")
                except (TypeError, ValueError):
                    return chr(10).join(out + ["  (khong doc duoc raw_model_output)"])
                out += [f"  {c.get('name')} = {c.get('score')}: {c.get('reasoning')}" for c in parsed.get("criteria", [])]
                out.append(f"  overall_reasoning: {parsed.get('overall_reasoning')}")
                out.append(f"  weaknesses: {parsed.get('weaknesses')}")
                return chr(10).join(out)
    return f"Khong co ket qua ok cho {rec_id}"


def report_runs() -> str:
    """Doc lan 1 va lan chay lai: ap quy tac cho TUNG lan rieng (bai ctrl lay tu lan 1, vi chi chay lai 8 bai hq)."""
    def load(path):
        if not path.exists():
            return {}
        return {r["id"]: r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()) if r["status"] == "ok"}
    r1, r2 = load(RESULTS_PATH), load(RESULTS_PATH_RUN2)
    ctrl = [r for r in r1.values() if is_ctrl(r["id"])]
    lines = [RULE_TEXT, "", "Doc sau khi chay lai (DE XUAT, chua chot): ap quy tac cho tung lan rieng; bai ctrl lay tu lan 1."]
    hq1 = [r for r in r1.values() if not is_ctrl(r["id"])]
    hq2 = [r for r in r2.values() if not is_ctrl(r["id"])]
    for name, hq in (("Lan 1", hq1), ("Lan chay lai", hq2)):
        outcome, d = decide(hq, ctrl)
        lines.append(f"{name}: Evidence >= 4: {d['ev_hq']}/{len(hq)} | Persuasiveness >= 4: {d['pe_hq']}/{len(hq)} | ctrl Evidence <= 2: {d['ctrl_ok']} -> {outcome}")
    lines.append("")
    lines.append(f"{'id':<8}" + "".join(f"{c[:5] + ' l1/l2':>13}" for c in CRITERIA) + f"{'overall l1/l2':>16}")
    for i in sorted(set(r1) | set(r2)):
        if is_ctrl(i):
            continue
        a, b = r1.get(i), r2.get(i)
        cells = "".join(f"{(str(a['criteria'][c]) if a else '-') + '/' + (str(b['criteria'][c]) if b else '-'):>13}" for c in CRITERIA)
        ov1 = f"{a['overall_score']:.1f}" if a else "-"
        ov2 = f"{b['overall_score']:.1f}" if b else "-"
        lines.append(f"{i:<8}{cells}{ov1 + '/' + ov2:>16}")
    for name, hq in (("lan 1", hq1), ("lan chay lai", hq2)):
        if hq:
            lines.append(f"Diem tong hq {name}: TB {sum(r['overall_score'] for r in hq) / len(hq):.2f}, so bai > 7.2: {sum(r['overall_score'] > 7.2 + 1e-9 for r in hq)}/{len(hq)}")
    return chr(10).join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="H8 probe: cham 8-10 lap luan chat luong cao, 1 lan/bai")
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--validate", action="store_true", help="Chi kiem tra file dau vao, khong goi API")
    parser.add_argument("--report", action="store_true", help="Chi in tong hop tu file ket qua, khong goi API")
    parser.add_argument("--rerun-hq", action="store_true", help="Chay lai CHI cac bai hq (khong phai ctrl), ghi data/high_quality_probe_results_run2.jsonl")
    parser.add_argument("--report-runs", action="store_true", help="Doc lan 1 + lan chay lai theo quy tac, khong goi API")
    parser.add_argument("--run", type=int, choices=[1, 2], default=1, help="Dung voi --show: doc lan 1 hay lan chay lai")
    parser.add_argument("--show", type=str, default=None, help="In diem + ly do tung tieu chi cua 1 bai (vd hq04) tu file ket qua, khong goi API")
    args = parser.parse_args()

    if args.report:
        print(report())
        return
    if args.show:
        print(show(args.show, RESULTS_PATH if args.run == 1 else RESULTS_PATH_RUN2))
        return
    if args.report_runs:
        print(report_runs())
        return
    items = load_items(args.input)
    problems = validate_items(items)
    if args.validate:
        print(f"{len(items)} bai trong {args.input}")
        for it in items:
            if isinstance(it, dict):
                print(f"  {it.get('id')}: {len(str(it.get('text', '')))} ky tu, side={it.get('side')}, motion={str(it.get('motion', ''))[:60]!r}")
        print("\n".join(problems) if problems else "Hop le.")
        return
    errors = [p for p in problems if not p.startswith("Canh bao")]
    for p in problems:
        print(p)
    if errors:
        raise SystemExit("Sua loi o tren truoc khi cham.")

    settings = get_settings()
    if settings.llm_provider.lower() != "groq":
        raise SystemExit(f"Script do usage qua GroqClient, LLM_PROVIDER hien la '{settings.llm_provider}'")
    client = GroqClient(settings)
    recorder = install_usage_recorder(client)
    print(f"model={settings.groq_model} temperature={settings.llm_temperature} | {len(items)} bai, 1 lan/bai, da xong {len(load_done())}")
    results_path = RESULTS_PATH
    if args.rerun_hq:
        items = [it for it in items if not is_ctrl(str(it["id"]))]
        results_path = RESULTS_PATH_RUN2
        print(f"CHAY LAI {len(items)} bai hq -> {results_path.name}")
    stop = score_items(items, settings, client, recorder, results_path=results_path)
    if stop:
        print(f"DUNG VI: {stop}")
    print(chr(10) + (report_runs() if args.rerun_hq else report()))


if __name__ == "__main__":
    main()
