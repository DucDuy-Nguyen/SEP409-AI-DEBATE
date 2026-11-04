"""
Giai doan 3e, Phan 2 (dev log muc 3.3) — giam khao PAIRWISE mu cap. GOI LLM THAT — ton tien.

    python -m scripts.judge_pairwise experiments/difficulty_eval/<file>_branch.jsonl --concurrency 2
    python -m scripts.judge_pairwise <file>_branch.jsonl --resume --out experiments/difficulty_eval/<file>_pairwise.jsonl

- Giam khao thay: motion, 2 burden, bai learner gan nhat, hai bai AI an nhan "Bài 1" / "Bài 2". KHONG co phe cua AI, KHONG
  co cap do.
- 3 cap moi trang thai (hard-medium, medium-easy, hard-easy), moi cap cham 2 lan dao thu tu = 6 loi goi / trang thai.
- Ket qua cap = bai thang neu nhat quan ca 2 thu tu; ca 2 "tie" = "tie"; con lai "tie_inconsistent" (dem rieng, gom ca khi 1
  thu tu thang + 1 thu tu hoa). Loi giam khao -> "judge_missing": --resume cham lai cap do.
- Trang thai co bai branch_failed / branch_infra: bo cac cap dinh toi cap do, liet ke.
"""
import argparse
import asyncio
import json
import logging
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from math import comb
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.llm.client import get_llm_client
from app.llm.json_utils import LLMOutputParseError, extract_json
from app.opponent.turn_generators import LLMCaller, TurnLLMError
from scripts.eval_common import load_jsonl
from scripts.pressure_common import ROOT, _settings_with_effort, call_record
from scripts.run_difficulty_branch import OK, latest_states

logger = logging.getLogger(__name__)
OUT_DIR = ROOT / "experiments" / "difficulty_eval"
LEVELS = ("easy", "medium", "hard")
PAIR_TYPES = (("hard", "medium"), ("medium", "easy"), ("hard", "easy"))
H1_PAIRS = ("hard-medium", "medium-easy")  # H1 (muc 3.2) quyet dinh tren 2 cap ke nhau; hard-easy chi de tham khao
TIE, TIE_INCONSISTENT, JUDGE_MISSING = "tie", "tie_inconsistent", "judge_missing"
JUDGE_VERSION = "pairwise_judge_v1"
H1_MIN_WIN_RATE = 0.70
H1_MIN_CI_LOW = 0.50
DEFAULT_SEED = 20261104
DEFAULT_N_BOOT = 10_000


@dataclass
class PairwiseJudgeConfig:
    provider: str = "groq"
    model: str = "openai/gpt-oss-120b"
    temperature: float = 0.0
    max_tokens: int = 3000  # gom token suy luan cua gpt-oss
    reasoning_effort: str | None = "medium"


JUDGE_SYSTEM = (
    "Bạn là giám khảo độc lập trong một cuộc tranh luận tiếng Việt. Bạn so sánh hai câu trả lời của cùng một đối thủ. Chỉ "
    "đánh giá nội dung. Chỉ trả về một JSON object hợp lệ, không thêm chữ nào khác."
)


def judge_prompt(motion: str, burden_pro: str, burden_con: str, learner_text: str, speech_1: str, speech_2: str) -> str:
    """MU: chi motion, 2 burden, bai learner, 2 bai AI. KHONG phe cua AI, KHONG cap do."""
    return f"""Kiến nghị: '{motion}'
Phe ỦNG HỘ (pro) phải chứng minh: {burden_pro}
Phe PHẢN ĐỐI (con) phải chứng minh: {burden_con}

Bài nói gần nhất của người học:
«{learner_text}»

Dưới đây là hai câu trả lời của CÙNG MỘT đối thủ ở CÙNG MỘT thời điểm, ngay sau bài nói trên của người học.

Bài 1:
«{speech_1}»

Bài 2:
«{speech_2}»

Trả lời:
harder_for_learner: bài nào khó phản bác hơn cho người học — "1", "2", hoặc "tie" nếu ngang nhau.
reason: lý do, tối đa 30 từ.
speech_1 và speech_2, với mỗi bài:
  - points_answered: số ý chính của bài người học được đáp lại bằng lập luận cụ thể (số nguyên, 0 nếu không có);
  - attacks_foundational: bài có nhắm vào tiền đề nền tảng của người học không (true / false).

Định dạng JSON:
{{"harder_for_learner": "1" | "2" | "tie", "reason": "...", \
"speech_1": {{"points_answered": 0, "attacks_foundational": true/false}}, \
"speech_2": {{"points_answered": 0, "attacks_foundational": true/false}}}}"""


_SPEECH_SCHEMA = {
    "type": "object",
    "properties": {"points_answered": {"type": "integer"}, "attacks_foundational": {"type": "boolean"}},
    "required": ["points_answered", "attacks_foundational"],
    "additionalProperties": False,
}
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "harder_for_learner": {"type": "string", "enum": ["1", "2", "tie"]},
        "reason": {"type": "string"},
        "speech_1": _SPEECH_SCHEMA,
        "speech_2": _SPEECH_SCHEMA,
    },
    "required": ["harder_for_learner", "reason", "speech_1", "speech_2"],
    "additionalProperties": False,
}


class _Speech(BaseModel):
    points_answered: int = Field(ge=0)
    attacks_foundational: bool


class PairwiseVerdict(BaseModel):
    harder_for_learner: Literal["1", "2", "tie"]
    reason: str = ""
    speech_1: _Speech
    speech_2: _Speech


def parse_verdict(raw: str | None) -> dict:
    """Nem ValueError neu khong doc duoc."""
    try:
        return PairwiseVerdict.model_validate(extract_json(raw or "")).model_dump()
    except (LLMOutputParseError, ValidationError) as e:
        raise ValueError(str(e)[:1000]) from e


def unmask(verdict: dict, first: str, second: str) -> dict:
    """Doi "Bài 1" / "Bài 2" ve cap do."""
    winner = {"1": first, "2": second, "tie": TIE}[verdict["harder_for_learner"]]
    return {
        "winner": winner, "reason": verdict["reason"],
        "points_answered": {first: verdict["speech_1"]["points_answered"], second: verdict["speech_2"]["points_answered"]},
        "attacks_foundational": {first: verdict["speech_1"]["attacks_foundational"],
                                 second: verdict["speech_2"]["attacks_foundational"]},
    }


def pair_result(winner_a: str | None, winner_b: str | None) -> str:
    """Ket qua cap tu 2 thu tu. None = thu tu do giam khao loi."""
    if winner_a is None or winner_b is None:
        return JUDGE_MISSING
    return winner_a if winner_a == winner_b else TIE_INCONSISTENT


async def _judge_order(state: dict, first: str, second: str, client_factory, settings, cfg: PairwiseJudgeConfig) -> dict:
    """Toi da 2 lan goi (output loi -> goi lai 1 lan), nhu giam khao 3d."""
    caller = LLMCaller(client_factory(), _settings_with_effort(settings, cfg.reasoning_effort))
    levels = state["levels"]
    user = judge_prompt(state["motion"], state["burden_pro"], state["burden_con"], state["learner_text"],
                        levels[first]["text"], levels[second]["text"])
    error, judged = None, None
    for _ in range(2):
        try:
            call = await caller.complete(
                JUDGE_SYSTEM, user, temperature=cfg.temperature, max_tokens=cfg.max_tokens,
                prompt_version=JUDGE_VERSION, json_schema=JUDGE_SCHEMA,
            )
        except TurnLLMError as e:
            error = str(e)
            break
        if not call.success:
            error = call.error
            continue
        try:
            judged = unmask(parse_verdict(call.raw_output), first, second)
            error = None
            break
        except ValueError as e:
            call.success, call.error, call.failure_kind = False, str(e), "judge_parse_error"
            error = call.error
    return {"order": [first, second], "error": error, **(judged or {"winner": None}),
            "calls": [call_record(c, "pairwise_judge") for c in caller.calls]}


async def judge_pair(state: dict, high: str, low: str, client_factory, settings, cfg: PairwiseJudgeConfig) -> dict:
    orders = [await _judge_order(state, high, low, client_factory, settings, cfg),
              await _judge_order(state, low, high, client_factory, settings, cfg)]
    judged = [o for o in orders if o["winner"] is not None]
    words = {lv: state["levels"][lv]["word_count"] for lv in (high, low)}
    return {
        "pair_id": f"{state['state_id']}|{high}-{low}", "state_id": state["state_id"], "dialogue_id": state["dialogue_id"],
        "pair_type": f"{high}-{low}", "high": high, "low": low, "round": state["snapshot_round"],
        "motion_id": state["motion_id"], "motion": state["motion"], "motion_type": state["motion_type"],
        "ai_side": state["ai_side"], "strategy": state["strategy"], "burden_pro": state["burden_pro"],
        "burden_con": state["burden_con"], "learner_text": state["learner_text"], "word_count": words,
        "texts": {lv: state["levels"][lv]["text"] for lv in (high, low)},
        "result": pair_result(orders[0]["winner"], orders[1]["winner"]),
        "points_answered": {lv: sum(o["points_answered"][lv] for o in judged) / len(judged) for lv in (high, low)}
        if len(judged) == 2 else None,
        "attacks_foundational": {lv: [o["attacks_foundational"][lv] for o in judged] for lv in (high, low)}
        if len(judged) == 2 else None,
        "judgments": orders, "judge_config": {**asdict(cfg), "version": JUDGE_VERSION},
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def plan_pairs(states: list[dict]) -> tuple[list[tuple[dict, str, str]], list[dict]]:
    """([(trang thai, cap cao, cap thap)], cac cap bi bo). Bo cap co bai khong dung duoc."""
    todo, skipped = [], []
    for state in latest_states(states):
        for high, low in PAIR_TYPES:
            bad = {lv: state["levels"][lv]["status"] for lv in (high, low) if state["levels"][lv]["status"] != OK}
            if bad:
                skipped.append({"pair_id": f"{state['state_id']}|{high}-{low}", "reason": bad})
            else:
                todo.append((state, high, low))
    return todo, skipped


def latest_pairs(pairs: list[dict]) -> list[dict]:
    last: dict[str, dict] = {}
    for p in pairs:
        last.pop(p["pair_id"], None)
        last[p["pair_id"]] = p
    return list(last.values())


def done_ids(path: Path) -> set[str]:
    pairs = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                pair = json.loads(line)
                pair["pair_id"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            pairs.append(pair)
    return {p["pair_id"] for p in latest_pairs(pairs) if p["result"] != JUDGE_MISSING}


async def run_all(states: list[dict], client_factory, settings, cfg: PairwiseJudgeConfig, out_path: Path, *,
                  concurrency: int = 2, resume: bool = False, out=print) -> dict:
    plan, skipped = plan_pairs(states)
    done = done_ids(out_path) if resume else set()
    todo = [(s, h, l) for s, h, l in plan if f"{s['state_id']}|{h}-{l}" not in done]
    out(f"{len(plan)} cap; bo {len(skipped)}; da xong {len(plan) - len(todo)}; cham {len(todo)} -> {out_path}")
    for s in skipped:
        out(f"  [BO] {s['pair_id']}: {s['reason']}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sem, lock = asyncio.Semaphore(max(1, concurrency)), asyncio.Lock()
    counts: dict[str, int] = {"error": 0}

    async def one(state, high, low):
        async with sem:
            try:
                pair = await judge_pair(state, high, low, client_factory, settings, cfg)
            except Exception as e:  # noqa: BLE001 — loi harness: khong ghi dong (resume cham lai)
                logger.exception("Cap %s|%s-%s loi harness", state["state_id"], high, low)
                counts["error"] += 1
                out(f"  [LOI HARNESS] {state['state_id']}|{high}-{low}: {type(e).__name__}: {e}")
                return
            async with lock:
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(pair, ensure_ascii=False) + "\n")
            counts[pair["result"]] = counts.get(pair["result"], 0) + 1
            out(f"  {pair['pair_id']}: {pair['result']}")

    await asyncio.gather(*(asyncio.create_task(one(s, h, l)) for s, h, l in todo))
    out(f"Xong: {counts}")
    return counts


# ---------------- thong ke (dung chung report_difficulty, label_pairwise) ----------------


def sign_test(wins: int, losses: int) -> float | None:
    """p hai phia, nhi thuc chinh xac, p = 0.5. Bo hoa."""
    n = wins + losses
    if n == 0:
        return None
    tail = sum(comb(n, k) for k in range(max(wins, losses), n + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _bootstrap_rate(groups: list[tuple[int, int]], n_boot: int, seed: int) -> tuple[float | None, float | None]:
    """groups: (thang, thua) moi don vi lay mau. Lay mau lai co hoan lai cac don vi; mau khong co cap phan thang thua -> bo qua."""
    rng = random.Random(seed)
    rates = []
    for _ in range(n_boot):
        sample = rng.choices(groups, k=len(groups))
        w, l = sum(g[0] for g in sample), sum(g[1] for g in sample)
        if w + l:
            rates.append(w / (w + l))
    if not rates:
        return None, None
    rates.sort()
    return rates[int(0.025 * len(rates))], rates[min(len(rates) - 1, int(0.975 * len(rates)))]


def win_stats(results: list[str], high: str, low: str, n_boot: int = DEFAULT_N_BOOT, seed: int = DEFAULT_SEED,
              clusters: list[str] | None = None) -> dict:
    """
    results: moi trang thai 1 ket qua. Ti le thang cua `high` tren cac cap KHONG hoa (bo tie, tie_inconsistent).
    clusters: hoi thoai cua tung ket qua (dev log 3.3, sua dang ky 1). Co clusters -> KTC CHINH (ci_low, ci_high, h1_pass) lay
    mau lai theo HOI THOAI; KTC theo trang thai (ci_*_state) la chi so phu. Khong co (nhan nguoi) -> KTC theo trang thai.
    """
    if clusters is not None and len(clusters) != len(results):
        raise ValueError("clusters phai cung do dai voi results")
    keep = [i for i, r in enumerate(results) if r != JUDGE_MISSING]
    judged = [results[i] for i in keep]
    wins, losses = judged.count(high), judged.count(low)
    decided = wins + losses
    out = {
        "n": len(judged), "wins": wins, "losses": losses, "ties": judged.count(TIE),
        "tie_inconsistent": judged.count(TIE_INCONSISTENT), "judge_missing": len(results) - len(judged),
        "win_rate": wins / decided if decided else None, "ci_low": None, "ci_high": None,
        "ci_unit": "hoi thoai" if clusters is not None else "trang thai", "n_clusters": None,
        "ci_low_state": None, "ci_high_state": None, "sign_test_p": sign_test(wins, losses),
    }
    if clusters is not None:
        out["n_clusters"] = len({clusters[i] for i in keep})
    if decided:
        out["ci_low_state"], out["ci_high_state"] = _bootstrap_rate(
            [(r == high, r == low) for r in judged], n_boot, seed)
        out["ci_low"], out["ci_high"] = out["ci_low_state"], out["ci_high_state"]
        if clusters is not None:
            groups: dict[str, list[int]] = {}
            for i in keep:
                group = groups.setdefault(clusters[i], [0, 0])
                group[0] += results[i] == high
                group[1] += results[i] == low
            out["ci_low"], out["ci_high"] = _bootstrap_rate([tuple(g) for g in groups.values()], n_boot, seed)
    out["h1_pass"] = bool(decided and out["ci_low"] is not None and out["win_rate"] >= H1_MIN_WIN_RATE
                          and out["ci_low"] > H1_MIN_CI_LOW)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Giam khao pairwise mu cap (Giai doan 3e) — LLM THAT")
    p.add_argument("files", nargs="+", type=Path, help="JSONL cua run_difficulty_branch")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--judge-provider", default=PairwiseJudgeConfig.provider)
    p.add_argument("--judge-model", default=PairwiseJudgeConfig.model)
    p.add_argument("--judge-temperature", type=float, default=PairwiseJudgeConfig.temperature)
    p.add_argument("--judge-max-tokens", type=int, default=PairwiseJudgeConfig.max_tokens)
    p.add_argument("--judge-effort", default=PairwiseJudgeConfig.reasoning_effort)
    args = p.parse_args(argv)
    if args.resume and args.out is None:
        p.error("--resume can --out <file JSONL dang chay>")
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    states = [s for f in args.files for s in load_jsonl(f)]
    settings = get_settings()
    cfg = PairwiseJudgeConfig(args.judge_provider, args.judge_model, args.judge_temperature, args.judge_max_tokens,
                              args.judge_effort)
    out_path = args.out or OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}_pairwise.jsonl"
    counts = asyncio.run(run_all(states, lambda: get_llm_client(settings, provider=cfg.provider, model=cfg.model), settings,
                                 cfg, out_path, concurrency=args.concurrency, resume=args.resume))
    return 0 if counts["error"] == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
