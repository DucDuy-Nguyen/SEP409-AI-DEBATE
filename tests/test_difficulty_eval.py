"""
Giai doan 3e, Phan 2 (dev log muc 3.3): nhanh LE / LM / LH, re nhanh, giam khao pairwise, bao cao, nhan nguoi. LLM GIA.
"""
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.llm.client import LLMClient
from app.opponent import turn_full as tf
from app.opponent.models import DebateSide, OpponentDifficulty
from app.opponent.turn_full import FullTurnGeneratorV6, FullTurnGeneratorV7
from app.opponent.turn_generators import BaselineTurnGenerator
from scripts import judge_pairwise as jp
from scripts import label_pairwise as lp
from scripts import pressure_common as pc
from scripts import report_difficulty as rd
from scripts import run_case_plan_batch as batch
from scripts import run_difficulty_branch as br
from tests.conftest import VALID_CASE_FILE, FakeStanceReviewer
from tests.test_pressure_eval import BC, BP, CASE, JudgeFake, SimFake, _rec, _spec, honest_judge

SETTINGS = Settings(_env_file=None)
LABEL = {"easy": "DỄ", "medium": "TRUNG BÌNH", "hard": "KHÓ"}


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    from app.opponent import turn_generators

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(turn_generators, "_sleep", _no_sleep)


_TAG = itertools.count(1)  # dem CHUNG moi fake: premises khong trung ledger cua hoi thoai goc (bo chu so khi chuan hoa)


def _level_of(user: str) -> str:
    return next(k for k, v in LABEL.items() if f"Độ khó của trận: {v}." in user)


class AIFakeV7(LLMClient):
    """Bo sinh v7: JSON hop le, premises MOI moi lan. fail: output sai / nem loi provider."""

    provider, model = "fake", "fake-ai"

    def __init__(self, log: list, error: Exception | None = None):
        self.log, self.error = log, error

    def generate(self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None,
                 reasoning_effort=None):
        self.last_usage, self.last_finish_reason = {"tokens_in": 1000, "tokens_out": 500}, "stop"
        self.log.append({"system": system_prompt, "user": user_prompt, "schema": json_schema})
        if self.error:
            raise self.error
        tag = "x" * next(_TAG)
        level = _level_of(user_prompt) if "Độ khó của trận:" in user_prompt else "v6"
        words = {"easy": 300, "medium": 320, "hard": 340, "v6": 320}[level]
        data = {
            "premises": {"explicit": [f"Tiền đề mới {tag}.", f"Một ý khác hẳn {tag}."], "implicit": [f"Ngầm {tag}."]},
            "target_premise": f"Tiền đề mới {tag}.",
            "ai_points": ["Ý thứ nhất của mình.", "Ý thứ hai của mình."],
            "speech_text": " ".join(["lập"] * words) + f" {level} {len(self.log)}.",
        }
        if "points_addressed" in (json_schema or {}).get("properties", {}):
            data["points_addressed"] = [f"Tiền đề mới {tag}."]
        return json.dumps(data, ensure_ascii=False)


class Harness:
    def __init__(self, ai_side="con", ai_error=None, reviewer_position=None):
        self.ai_log, self.sim_log, self.judge_log, self.reviewers = [], [], [], []
        pos = reviewer_position or ("ung_ho_kien_nghi" if ai_side == "pro" else "phan_doi_kien_nghi")

        def reviewer():
            r = FakeStanceReviewer(pos)
            self.reviewers.append(r)
            return r

        self.factories = pc.Factories(
            ai=lambda: AIFakeV7(self.ai_log, ai_error), reviewer=reviewer, sim=lambda: SimFake(self.sim_log),
            judge=lambda: JudgeFake(self.judge_log, honest_judge(ai_side)),
        )


async def _run_arm(arm, ai_side="con", case_difficulty=OpponentDifficulty.MEDIUM, settings=SETTINGS, strategy="moi_nhuong_bo"):
    h = Harness(ai_side)
    spec = _spec(arm, ai_side, strategy)
    spec.difficulty = case_difficulty
    spec.case_file = CASE
    return await pc.run_dialogue(spec, settings, h.factories), h


# ---------------- 1. case file co dinh ----------------


MOTIONS = [{"id": f"M{i}", "motion": f"Kiến nghị {i}"} for i in range(3)]


def test_build_runs_default_still_cycles():
    assert [r["difficulty"].value for r in batch.build_runs(MOTIONS)[:4]] == ["easy", "medium", "hard", "easy"]


def test_build_runs_fixed_difficulty_all_rounds():
    runs = batch.build_runs(MOTIONS, repeat=2, difficulty=OpponentDifficulty.MEDIUM)
    assert len(runs) == 12 and {r["difficulty"] for r in runs} == {OpponentDifficulty.MEDIUM}
    assert [r["repeat_round"] for r in runs] == [1] * 6 + [2] * 6


def test_case_selector_works_on_medium_batch(tmp_path):
    motions = json.loads((pc.MOTIONS_FILE).read_text(encoding="utf-8"))["motions"]
    rows = []
    for m in motions:
        for side in ("pro", "con"):
            for rr in (1, 2):
                bad = m["id"] == "P1" and side == "con" and rr == 1  # vong 1 hong -> lay vong 2
                rows.append({"motion_id": m["id"], "ai_side": side, "repeat_round": rr, "difficulty": "medium",
                             "run_index": len(rows), "prompt_version": "case_plan_v7",
                             "final_status": "invalid_output" if bad else "ready", "final_reviewer_verdict": "pass",
                             "case_file": VALID_CASE_FILE})
    path = tmp_path / "b.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    configs, notes = pc.load_case_configs(path, repeat_rounds=(1, 2))
    assert len(configs) == 12 and {c.difficulty for c in configs} == {OpponentDifficulty.MEDIUM}
    assert next(c for c in configs if c.motion_id == "P1" and c.ai_side == DebateSide.CON).case_source["repeat_round"] == 2
    specs = pc.build_specs(configs, list(pc.LEVEL_ARMS), list(pc.STRATEGIES))
    assert len(specs) == 72 and sum(s.arm == "LE" for s in specs) == 24


# ---------------- 2. nhanh ----------------


def test_a_to_f_flags_unchanged():
    expected = {
        "A": ("turn_baseline_v1", False, False, False, False, False),
        "B": ("turn_full_v6", True, True, True, False, True),
        "C": ("turn_full_v6", True, True, True, True, True),
        "D": ("turn_full_v6", True, False, True, False, True),
        "E": ("turn_full_v6", True, True, True, False, False),
        "F": ("turn_full_v6", True, True, False, False, True),
    }
    keys = ("generator", "case_file", "reviewer", "burden", "second_person", "final_constraints")
    for name, values in expected.items():
        assert pc.ARMS[name].flags() == dict(zip(keys, values))  # dung cac khoa cu, khong them turn_difficulty


def test_default_arms_stay_a_to_f():
    assert pc.DEFAULT_ARMS == ("A", "B", "C", "D", "E", "F") and pc.LEVEL_ARMS == ("LE", "LM", "LH")


@pytest.mark.parametrize("arm,cls", [("A", BaselineTurnGenerator), ("B", FullTurnGeneratorV6), ("F", FullTurnGeneratorV6),
                                     ("LE", FullTurnGeneratorV7), ("LM", FullTurnGeneratorV7), ("LH", FullTurnGeneratorV7)])
def test_make_generator_pins_version(arm, cls):
    assert type(pc.make_generator(pc.ARMS[arm], SETTINGS, Harness().factories)) is cls


def test_level_arms_equal_b_except_generator_and_difficulty():
    b = pc.ARMS["B"]
    for name, level in (("LE", "easy"), ("LM", "medium"), ("LH", "hard")):
        a = pc.ARMS[name]
        assert (a.case_file, a.reviewer, a.burden, a.second_person, a.final_constraints) == (
            b.case_file, b.reviewer, b.burden, b.second_person, b.final_constraints)
        assert a.generator == "turn_full_v7" and a.turn_difficulty == level


@pytest.mark.parametrize("arm,level", [("LE", "easy"), ("LM", "medium"), ("LH", "hard")])
@pytest.mark.parametrize("case_difficulty", list(OpponentDifficulty))
async def test_level_arm_difficulty_ignores_case_file(arm, level, case_difficulty):
    record, h = await _run_arm(arm, case_difficulty=case_difficulty)
    assert {_level_of(c["user"]) for c in h.ai_log} == {level}
    assert record["case_difficulty"] == case_difficulty.value and record["turn_difficulty"] == level
    assert record["status"] == "completed" and record["case_file"] == CASE
    assert {r["ai"]["generator_version"] for r in record["rounds"]} == {"turn_full_v7"}


async def test_level_arm_ignores_turn_difficulty_flag_off():
    record, h = await _run_arm("LH", settings=Settings(_env_file=None, turn_difficulty_enabled=False))
    assert {_level_of(c["user"]) for c in h.ai_log} == {"hard"}
    assert {r["ai"]["generator_version"] for r in record["rounds"]} == {"turn_full_v7"}


async def test_level_arm_hard_gets_anticipated_block_and_keeps_reviewer():
    record, h = await _run_arm("LH")
    assert all("Những phản biện bạn đã dự đoán từ phía" in c["user"] for c in h.ai_log)
    assert len(h.reviewers) == 6 and all(r.calls for r in h.reviewers)
    assert all(c["user"].endswith("- Chỉ trả về JSON hợp lệ.") for c in h.ai_log)  # khoi rang buoc cuoi


async def test_level_arm_logs_attempts_and_points():
    record, _ = await _run_arm("LE")
    ai = record["rounds"][1]["ai"]
    assert ai["points_addressed"] and pc.attempt_rows(ai)[0]["content_attempt"] == 1
    assert pc.attempt_rows(ai)[0]["measurable"] is True


async def test_arm_b_record_unchanged():
    h = Harness()
    record = await pc.run_dialogue(_spec("B"), SETTINGS, h.factories)
    assert not {"case_difficulty", "turn_difficulty", "case_file"} & set(record)
    assert "turn_difficulty" not in record["flags"]
    assert {r["ai"]["generator_version"] for r in record["rounds"]} == {"turn_full_v6"}
    assert all("Độ khó của trận:" not in c["user"] for c in h.ai_log)
    assert all(tf.TARGET_RULE[OpponentDifficulty.MEDIUM] in c["user"] for c in h.ai_log)
    assert "points_addressed" not in record["rounds"][1]["ai"]


# ---------------- 3. re nhanh ----------------


@pytest.mark.parametrize("ai_side", ["pro", "con"])
@pytest.mark.parametrize("snap", [1, 3])
async def test_build_state_rebuilds_exact_transcript(ai_side, snap):
    record, _ = await _run_arm("LM", ai_side)
    state = br.build_state(record, snap)
    expected = []
    for rd_ in record["rounds"]:
        if rd_["round"] > snap:
            break
        if rd_.get("learner"):
            expected.append(("learner", rd_["learner"]["text"]))
        if rd_["round"] < snap:
            expected.append(("ai", rd_["ai"]["text"]))
    assert [(s.speaker.value, s.text) for s in state.transcript] == expected
    assert state.transcript[-1].speaker.value == "learner"
    assert [s.turn_index for s in state.transcript] == list(range(1, len(expected) + 1))


@pytest.mark.parametrize("ai_side", ["pro", "con"])
@pytest.mark.parametrize("snap", [1, 3])
async def test_branch_state_reproduces_medium_prompt_exactly(ai_side, snap):
    """Bang chung manh nhat: dung lai trang thai roi dung prompt medium -> TRUNG TUNG BYTE voi prompt hoi thoai goc da gui."""
    record, _ = await _run_arm("LM", ai_side)
    ai = next(r["ai"] for r in record["rounds"] if r["round"] == snap)
    sent = next(c for c in ai["calls"] if c["role"] == "ai")
    spec = br.spec_from_record(record, "LM")
    mode, ctx = pc.ai_turn_context(spec, pc.ARMS["LM"], br.build_state(record, snap), SETTINGS, snap)
    system, user = tf.build_full_prompt(mode, ctx, version=ai["generator_version"])
    assert (system, user) == (sent["system_prompt"], sent["user_prompt"])


async def test_ledger_has_only_rounds_before_snapshot():
    record, _ = await _run_arm("LM")
    state = br.build_state(record, 1)
    r0 = record["rounds"][0]["ai"]
    assert state.ledger.learner_premises == r0["premises"]["explicit"]
    assert state.ledger.attacked_premises == [r0["target_premise"]]
    assert state.ledger.ai_points == r0["ai_points"]


async def test_branch_generates_exactly_one_easy_one_hard_medium_from_source():
    record, _ = await _run_arm("LM")
    h = Harness()
    state = await br.branch_state(record, 1, SETTINGS, h.factories)
    assert sorted(_level_of(c["user"]) for c in h.ai_log) == ["easy", "hard"]
    assert h.sim_log == [] and h.judge_log == [] and len(h.reviewers) == 2
    medium = record["rounds"][1]["ai"]
    assert state["levels"]["medium"]["text"] == medium["text"] and state["levels"]["medium"]["status"] == br.OK
    assert state["state_id"] == "LM|P1|con|moi_nhuong_bo|r1"
    assert state["learner_text"] == record["rounds"][1]["learner"]["text"]
    for level in ("easy", "hard"):
        e = state["levels"][level]
        assert e["status"] == br.OK and f" {level} " in e["text"] and e["target_premise"] and e["points_addressed"]
        assert e["attempts"][0]["content_attempt"] == 1 and e["attempts"][0]["failure_kind"] is None


async def test_branch_side_flip_recorded_as_branch_failed():
    record, _ = await _run_arm("LM")
    h = Harness(reviewer_position="ung_ho_kien_nghi")  # AI con -> moi bai bi bao lat
    state = await br.branch_state(record, 1, SETTINGS, h.factories)
    for level in ("easy", "hard"):
        e = state["levels"][level]
        assert e["status"] == br.BRANCH_FAILED and e["text"] is None and e["failure_kind"] == "side_flip"
        assert [a["failure_kind"] for a in e["attempts"]] == ["side_flip"] * SETTINGS.turn_max_attempts


async def test_branch_provider_error_is_infra_and_resume_reruns(tmp_path):
    record, _ = await _run_arm("LM")
    path = tmp_path / "b.jsonl"
    await br.run_all([record], SETTINGS, Harness(ai_error=RuntimeError("503 down")).factories, path,
                     snapshot_rounds=(1,), out=lambda _: None)
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert first["levels"]["easy"]["status"] == br.BRANCH_INFRA and br.done_ids(path) == set()
    h = Harness()
    await br.run_all([record], SETTINGS, h.factories, path, resume=True, snapshot_rounds=(1,), out=lambda _: None)
    assert len(h.ai_log) == 2 and br.done_ids(path) == {"LM|P1|con|moi_nhuong_bo|r1"}
    h2 = Harness()
    await br.run_all([record], SETTINGS, h2.factories, path, resume=True, snapshot_rounds=(1,), out=lambda _: None)
    assert h2.ai_log == []  # da xong


async def test_plan_skips_not_completed_and_missing_medium_and_other_arms():
    good, _ = await _run_arm("LM")
    failed = {**good, "dialogue_id": "LM|P1|con|x", "status": "ai_failed", "failed_round": 2}
    missing = json.loads(json.dumps({**good, "dialogue_id": "LM|P1|con|y"}))
    missing["rounds"][3]["ai"] = {"text": None, "calls": []}
    other = {**good, "dialogue_id": "LH|P1|con|z", "arm": "LH"}
    todo, skipped = br.plan_states([good, failed, missing, other])
    assert sorted((r["dialogue_id"], s) for r, s in todo) == [
        ("LM|P1|con|moi_nhuong_bo", 1), ("LM|P1|con|moi_nhuong_bo", 3), ("LM|P1|con|y", 1)]
    reasons = {s["state_id"]: s["reason"] for s in skipped}
    assert set(reasons) == {"LM|P1|con|x|r1", "LM|P1|con|x|r3", "LM|P1|con|y|r3"}
    assert "ai_failed" in reasons["LM|P1|con|x|r1"] and "khong co bai medium" in reasons["LM|P1|con|y|r3"]


async def test_plan_keeps_latest_record_after_resume():
    good, _ = await _run_arm("LM")
    old = {**good, "status": "ai_failed", "failed_round": 1}
    todo, skipped = br.plan_states([old, good])
    assert len(todo) == 2 and not skipped


def test_max_48_states_from_24_dialogues():
    assert len(br.SNAPSHOT_ROUNDS) * 24 == 48


# ---------------- 4. pairwise ----------------


TEXTS = {"easy": "BÀI CẤP MỘT", "medium": "BÀI CẤP HAI", "hard": "BÀI CẤP BA"}


def _state(sid="s1", statuses=None, words=None, **over):
    statuses = statuses or {}
    words = words or {"easy": 300, "medium": 320, "hard": 340}
    return {
        "state_id": sid, "dialogue_id": "LM|P1|con|moi_nhuong_bo", "snapshot_round": 1, "motion_id": "P1",
        "motion": "Nên cấm điện thoại", "motion_type": "policy", "ai_side": "con", "strategy": "moi_nhuong_bo",
        "burden_pro": BP, "burden_con": BC, "learner_text": "BÀI NGƯỜI HỌC", "case_difficulty": "medium",
        "levels": {lv: {"status": statuses.get(lv, br.OK), "text": TEXTS[lv], "word_count": words[lv],
                        "failure_kind": None, "calls": []} for lv in TEXTS},
        **over,
    }


class PairFake(LLMClient):
    provider, model = "fake", "openai/gpt-oss-120b"

    def __init__(self, log, verdict):
        self.log, self.verdict = log, verdict

    def generate(self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None,
                 reasoning_effort=None):
        self.last_usage, self.last_finish_reason = {"tokens_in": 100, "tokens_out": 50}, "stop"
        self.log.append({"system": system_prompt, "user": user_prompt, "temperature": temperature, "schema": json_schema,
                         "effort": reasoning_effort})
        v = self.verdict(user_prompt)
        if isinstance(v, Exception):
            raise v
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _first_level(user: str) -> str:
    first = user.split("Bài 1:\n«")[1].split("»")[0]
    return next(k for k, v in TEXTS.items() if v == first)


def _second_level(user: str) -> str:
    second = user.split("Bài 2:\n«")[1].split("»")[0]
    return next(k for k, v in TEXTS.items() if v == second)


def V_(harder, p1=2, p2=1, f1=True, f2=False):
    return {"harder_for_learner": harder, "reason": "Vì lập luận chặt hơn.",
            "speech_1": {"points_answered": p1, "attacks_foundational": f1},
            "speech_2": {"points_answered": p2, "attacks_foundational": f2}}


def prefer(level_rank=("hard", "medium", "easy")):
    """Giam khao nhat quan: luon chon cap cao hon, ke ca khi dao thu tu."""
    def verdict(user):
        a, b = _first_level(user), _second_level(user)
        return V_("1" if level_rank.index(a) < level_rank.index(b) else "2")

    return verdict


CFG = jp.PairwiseJudgeConfig()


async def _pair(verdict, high="hard", low="medium"):
    log = []
    pair = await jp.judge_pair(_state(), high, low, lambda: PairFake(log, verdict), SETTINGS, CFG)
    return pair, log


def test_judge_defaults():
    assert (CFG.provider, CFG.model, CFG.temperature, CFG.reasoning_effort) == ("groq", "openai/gpt-oss-120b", 0.0, "medium")


async def test_pair_judged_twice_in_swapped_order():
    pair, log = await _pair(prefer())
    assert [(_first_level(c["user"]), _second_level(c["user"])) for c in log] == [("hard", "medium"), ("medium", "hard")]
    assert [j["order"] for j in pair["judgments"]] == [["hard", "medium"], ["medium", "hard"]]
    assert all(c["temperature"] == 0.0 and c["effort"] == "medium" for c in log)


async def test_consistent_winner():
    pair, _ = await _pair(prefer())
    assert pair["result"] == "hard" and pair["pair_type"] == "hard-medium"


async def test_position_bias_is_tie_inconsistent():
    pair, _ = await _pair(lambda user: V_("1"))  # luon chon Bai 1 -> 2 thu tu ra 2 bai khac nhau
    assert pair["result"] == jp.TIE_INCONSISTENT


async def test_both_tie_is_tie():
    pair, _ = await _pair(lambda user: V_("tie"))
    assert pair["result"] == jp.TIE


@pytest.mark.parametrize("a,b,expected", [
    ("hard", "hard", "hard"), ("tie", "tie", "tie"), ("hard", "medium", jp.TIE_INCONSISTENT),
    ("hard", "tie", jp.TIE_INCONSISTENT), ("tie", "medium", jp.TIE_INCONSISTENT),
    (None, "hard", jp.JUDGE_MISSING), ("hard", None, jp.JUDGE_MISSING), (None, None, jp.JUDGE_MISSING),
])
def test_pair_result_rule(a, b, expected):
    assert jp.pair_result(a, b) == expected


async def test_points_answered_averaged_and_mapped_to_levels():
    def verdict(user):
        # hard duoc 3 o thu tu dau, 2 o thu tu sau; medium 1 va 2
        return V_("1", 3, 1, True, False) if _first_level(user) == "hard" else V_("2", 2, 2, False, True)

    pair, _ = await _pair(verdict)
    assert pair["points_answered"] == {"hard": 2.5, "medium": 1.5}
    assert pair["attacks_foundational"] == {"hard": [True, True], "medium": [False, False]}


def test_prompt_is_blind_to_level_and_side():
    s = _state()
    user = jp.judge_prompt(s["motion"], BP, BC, s["learner_text"], "X", "Y").replace("harder_for_learner", "")
    for word in ("easy", "medium", "hard", "DỄ", "TRUNG BÌNH", "KHÓ", "Độ khó", "phe của AI", "ai_side", "BẠN là phe"):
        assert word not in user + jp.JUDGE_SYSTEM
    assert "CÙNG MỘT đối thủ ở CÙNG MỘT thời điểm" in user and BP in user and BC in user


async def test_prompt_same_for_pro_and_con_ai():
    log_a, log_b = [], []
    await jp.judge_pair(_state(ai_side="pro"), "hard", "easy", lambda: PairFake(log_a, prefer()), SETTINGS, CFG)
    await jp.judge_pair(_state(ai_side="con"), "hard", "easy", lambda: PairFake(log_b, prefer()), SETTINGS, CFG)
    assert [c["user"] for c in log_a] == [c["user"] for c in log_b]
    assert [c["system"] for c in log_a] == [c["system"] for c in log_b]


def test_judge_schema_fields():
    assert set(jp.JUDGE_SCHEMA["required"]) == {"harder_for_learner", "reason", "speech_1", "speech_2"}
    assert set(jp._SPEECH_SCHEMA["required"]) == {"points_answered", "attacks_foundational"}


@pytest.mark.parametrize("raw", ["khong phai json", json.dumps({"harder_for_learner": "3"}),
                                 json.dumps(V_("1", p1=-1))])
def test_parse_verdict_rejects(raw):
    with pytest.raises(ValueError):
        jp.parse_verdict(raw)


async def test_six_calls_per_state(tmp_path):
    log = []
    path = tmp_path / "p.jsonl"
    await jp.run_all([_state()], lambda: PairFake(log, prefer()), SETTINGS, CFG, path, out=lambda _: None)
    assert len(log) == 6 and len(path.read_text(encoding="utf-8").splitlines()) == 3


async def test_parse_error_retried_then_missing_and_resume_rejudges(tmp_path):
    log = []
    path = tmp_path / "p.jsonl"
    await jp.run_all([_state()], lambda: PairFake(log, lambda u: "khong phai json"), SETTINGS, CFG, path, out=lambda _: None)
    assert len(log) == 12 and jp.done_ids(path) == set()  # moi thu tu goi 2 lan
    log2 = []
    await jp.run_all([_state()], lambda: PairFake(log2, prefer()), SETTINGS, CFG, path, resume=True, out=lambda _: None)
    assert len(log2) == 6 and len(jp.done_ids(path)) == 3
    log3 = []
    await jp.run_all([_state()], lambda: PairFake(log3, prefer()), SETTINGS, CFG, path, resume=True, out=lambda _: None)
    assert log3 == []


async def test_provider_error_gives_missing():
    pair, log = await _pair(lambda u: RuntimeError("503 down"))
    assert pair["result"] == jp.JUDGE_MISSING and pair["points_answered"] is None
    assert pair["judgments"][0]["error"]


def test_plan_pairs_drops_failed_level_keeps_others():
    todo, skipped = jp.plan_pairs([_state(statuses={"easy": br.BRANCH_FAILED})])
    assert [(h, l) for _, h, l in todo] == [("hard", "medium")]
    assert sorted(s["pair_id"] for s in skipped) == ["s1|hard-easy", "s1|medium-easy"]


# ---------------- 5. bao cao ----------------


def _pairs(results, pair_type="hard-medium", words=(340, 320), **over):
    high, low = pair_type.split("-")
    return [{
        "pair_id": f"s{i}|{pair_type}", "state_id": f"s{i}", "dialogue_id": f"d{i}", "pair_type": pair_type, "high": high,
        "low": low, "round": 1,
        "strategy": "moi_nhuong_bo", "motion_type": "policy", "ai_side": "con", "result": r,
        "word_count": {high: words[0], low: words[1]}, "texts": {high: "A", low: "B"}, "learner_text": "L", "motion": "M",
        "burden_pro": BP, "burden_con": BC, "points_answered": {high: 2.0, low: 1.0},
        "attacks_foundational": {high: [True, True], low: [False, True]}, "judgments": [], **over,
    } for i, r in enumerate(results)]


def test_win_stats_counts_exclude_ties_from_rate():
    s = jp.win_stats(["hard"] * 7 + ["medium"] * 3 + ["tie"] * 2 + [jp.TIE_INCONSISTENT] * 3 + [jp.JUDGE_MISSING], "hard", "medium", 200)
    assert (s["wins"], s["losses"], s["ties"], s["tie_inconsistent"], s["judge_missing"]) == (7, 3, 2, 3, 1)
    assert s["win_rate"] == 0.7 and s["n"] == 15


def test_bootstrap_reproducible_with_seed_and_changes_with_other_seed():
    results = ["hard"] * 14 + ["medium"] * 6 + ["tie"] * 4
    a, b = jp.win_stats(results, "hard", "medium", 2000, 7), jp.win_stats(results, "hard", "medium", 2000, 7)
    c = jp.win_stats(results, "hard", "medium", 2000, 8)
    assert a == b and (a["ci_low"], a["ci_high"]) != (c["ci_low"], c["ci_high"])
    assert a["ci_low"] < a["win_rate"] < a["ci_high"]


@pytest.mark.parametrize("results,passed", [
    (["hard"] * 40 + ["medium"] * 10, True),  # 80%, CI cao hon 50%
    (["hard"] * 7 + ["medium"] * 3, False),  # 70% nhung mau nho: can duoi <= 50%
    (["hard"] * 30 + ["medium"] * 20, False),  # 60%
    (["tie"] * 10, False),
    ([], False),
])
def test_h1_pass_rule(results, passed):
    assert jp.win_stats(results, "hard", "medium", 1000)["h1_pass"] is passed


def test_sign_test():
    assert jp.sign_test(0, 0) is None
    assert jp.sign_test(5, 5) == 1.0
    assert jp.sign_test(10, 0) == pytest.approx(2 / 1024)


@pytest.mark.parametrize("a,b,ok", [(340, 300, True), (100, 85, True), (100, 84, False), (0, 100, False), (None, 100, False)])
def test_length_ok_relative_to_longer(a, b, ok):
    assert rd.length_ok({"high": "hard", "low": "easy", "word_count": {"hard": a, "easy": b}}) is ok


def test_h1_length_sensitivity_filters_pairs():
    near = _pairs(["hard"] * 3)
    far = _pairs(["medium"] * 2, words=(600, 300))
    for i, p in enumerate(far):
        p["pair_id"], p["state_id"] = f"f{i}|hard-medium", f"f{i}"
    s = rd.h1_summary(near + far, 200)
    assert s["pairs"]["hard-medium"]["wins"] == 3 and s["pairs"]["hard-medium"]["losses"] == 2
    sens = s["length_sensitivity"]
    assert sens["pairs"]["hard-medium"]["wins"] == 3 and sens["pairs"]["hard-medium"]["losses"] == 0
    assert sens["remaining"]["hard-medium"] == 3 and sens["total"]["hard-medium"] == 5
    assert s["word_count_mean"]["hard"] == pytest.approx((340 * 3 + 600 * 2) / 5)


def test_h1_breakdown_by_each_dimension():
    pairs = _pairs(["hard"] * 2)
    pairs[1].update(strategy="ap_luc_xa_hoi", round=3, ai_side="pro", motion_type="value")
    s = rd.h1_summary(pairs, 100)["breakdown"]
    assert {"strategy=moi_nhuong_bo", "strategy=ap_luc_xa_hoi", "round=1", "round=3", "ai_side=pro", "ai_side=con",
            "motion_type=value", "motion_type=policy"} <= set(s)
    assert s["round=3"]["hard-medium"]["wins"] == 1


def _ai_turn(checks_list, failure_kind=None, text="bai"):
    """1 luot AI: moi phan tu = speech_checks 1 lan thu (+ failure_kind)."""
    calls = []
    for c in checks_list:
        kind = c.pop("_kind", None)
        calls.append({"role": "ai", "speech_checks": c, "failure_kind": kind, "success": kind is None})
    return {"text": text, "failure_kind": failure_kind, "calls": calls, "word_count": 300, "latency_ms": 1}


def _first(ok=True, kind=None, count=1, unsupported=()):
    d = {"content_attempt": 1, "target_premise": "t", "points_addressed": ["p"], "target_kind": "explicit" if ok else "implicit",
         "target_level_ok": ok, "points_addressed_count": count, "points_below_expected": False,
         "points_unsupported": list(unsupported)}
    if kind:
        d["_kind"] = kind
    return d


def _second(count=1):
    return {**_first(count=count), "content_attempt": 2}


UNPARSEABLE = {"content_attempt": 1, "_kind": "invalid_json"}


def _turns(n_ok, n_wrong=0, n_unparse=0, count=1):
    turns = [_ai_turn([_first(count=count)]) for _ in range(n_ok)]
    turns += [_ai_turn([_first(False, "target_level_mismatch"), _second(count)]) for _ in range(n_wrong)]
    turns += [_ai_turn([dict(UNPARSEABLE), _second(count)]) for _ in range(n_unparse)]
    return turns


def test_h3_not_measurable_excluded_from_denominator():
    v = rd.h3_level("medium", _turns(9, 1, 2))
    assert (v["turns"], v["measured"], v["target_correct"], v["not_measurable"]) == (12, 10, 9, 2)
    assert v["target_first_attempt_rate"] == 0.9  # 9/10, KHONG phai 9/12
    assert v["not_measurable_kinds"] == {"invalid_json": 2}


@pytest.mark.parametrize("n_ok,n_unparse,warn,status", [(10, 0, False, "dat"), (18, 1, False, "dat"),
                                                        (10, 2, True, rd.INSUFFICIENT)])
def test_h3_warns_above_10_percent_and_marks_insufficient(n_ok, n_unparse, warn, status):
    v = rd.h3_level("medium", _turns(n_ok, 0, n_unparse))
    assert v["not_measurable_warning"] is warn and v["status"] == status


def test_h3_exactly_10_percent_is_not_warning():
    v = rd.h3_level("medium", _turns(9, 0, 1))
    assert v["not_measurable_rate"] == 0.1 and v["not_measurable_warning"] is False and v["status"] == "dat"


def test_h3_turns_without_first_attempt_row_are_ignored():
    """opening_first va luot loi ha tang khong co dong lan thu."""
    v = rd.h3_level("medium", _turns(5) + [{"text": "bai", "failure_kind": None, "calls": []}])
    assert v["turns"] == 5


def test_h3_target_threshold_on_first_attempt():
    assert rd.h3_level("medium", _turns(9, 1))["status"] == "dat"
    # bai duoc nhan deu dung cap (retry), nhung lan thu dau chi 8/10 -> khong dat
    assert rd.h3_level("medium", _turns(8, 2))["status"] == "khong dat"


def test_h3_points_thresholds():
    assert rd.h3_level("easy", _turns(10, count=1))["status"] == "dat"
    assert rd.h3_level("easy", _turns(8, count=1) + _turns(2, count=2))["status"] == "khong dat"  # 80% < 90%
    assert rd.h3_level("hard", _turns(10, count=2))["status"] == "dat"
    assert rd.h3_level("hard", _turns(7, count=2) + _turns(3, count=1))["status"] == "khong dat"  # 70% < 80%
    assert rd.h3_level("medium", _turns(10, count=5))["status"] == "dat"  # medium khong co nguong points


def test_h3_counts_failed_turns_by_kind_and_unsupported():
    failed = _ai_turn([_first(False, "target_level_mismatch")], failure_kind="target_level_mismatch", text=None)
    v = rd.h3_level("easy", _turns(9) + [failed] + [_ai_turn([_first(unsupported=["p"])])])
    assert v["target_failed_turns"] == {"target_level_mismatch": 1}
    assert v["points_unsupported_turns"] == 1 and v["accepted_turns"] == 10


def test_h3_empty_is_insufficient():
    assert rd.h3_level("easy", [])["status"] == rd.INSUFFICIENT


def _level_recs(values: dict[str, list[list[int]]]):
    out = []
    for arm, nofs in values.items():
        for k, rounds in enumerate(nofs):
            out.append(_rec(arm, rounds, k=k))
    return out


def test_h2_compares_with_lm_and_applies_upper_bound():
    recs = _level_recs({"LM": [[]] * 8, "LE": [[]] * 8, "LH": [[1, 2, 3]] * 8})
    s = rd.h2_summary(recs, n_boot=300)
    assert set(s["compare"]) == {"LE-LM", "LH-LM"}
    assert s["levels"]["easy"]["pass"] is True and s["levels"]["easy"]["ci_high"] == 0
    assert s["levels"]["hard"]["pass"] is False and s["levels"]["hard"]["diff"] == 3
    assert s["levels"]["easy"]["n_pairs"] == 8


def test_h2_missing_arm_not_passed():
    s = rd.h2_summary(_level_recs({"LM": [[]] * 3}), n_boot=50)
    assert s["levels"]["easy"]["pass"] is False and s["levels"]["easy"]["ci_high"] is None


def test_h2_ignores_a_to_f():
    s = rd.h2_summary(_level_recs({"B": [[1]] * 3, "LM": [[]] * 3, "LE": [[]] * 3}), n_boot=50)
    assert set(s["compare"]) == {"LE-LM"}


def test_report_pressure_default_reference_still_b():
    from scripts import report_pressure_eval as rep

    s = rep.summarize(_level_recs({"B": [[]] * 3, "F": [[1]] * 3}), n_boot=50)
    assert set(s["nof_diff_vs_B"]) == {"F-B"}


def _table(hm=True, me=True):
    def row(ok):
        return {"h1_pass": ok}

    return {"hard-medium": row(hm), "medium-easy": row(me), "hard-easy": row(False)}


H2_OK = {"levels": {"easy": {"pass": True}, "hard": {"pass": True}}}
H3_OK = {lv: {"status": "dat"} for lv in jp.LEVELS}


def test_decide_accepts_when_all_pass_ignoring_hard_easy():
    d = rd.decide({"pairs": _table()}, H2_OK, H3_OK, {"complete": True, "judge_trusted": True, "human_h1": {}})
    assert d["accept_three_levels"] and d["h1_source"] == "giam khao"


def test_decide_reports_not_separated_pair():
    d = rd.decide({"pairs": _table(me=False)}, H2_OK, H3_OK, {"complete": True, "judge_trusted": True, "human_h1": {}})
    assert not d["accept_three_levels"] and d["not_separated"] == ["medium-easy"]


def test_decide_h2_blocks_level():
    h2 = {"levels": {"easy": {"pass": False}, "hard": {"pass": True}}}
    d = rd.decide({"pairs": _table()}, h2, H3_OK, None)
    assert d["h2_unusable_levels"] == ["easy"] and not d["accept_three_levels"]


@pytest.mark.parametrize("judge_all_pass", [True, False])
def test_decide_judge_not_trusted_makes_no_claim(judge_all_pass):
    """3.3 sua dang ky 4: dong thuan < 75% -> khong dung ca nhan nguoi lan giam khao de ket luan."""
    label = {"complete": True, "judge_trusted": False, "human_h1": _table(hm=False)}
    d = rd.decide({"pairs": _table(hm=judge_all_pass)}, H2_OK, H3_OK, label)
    assert d["h1_status"] == rd.NO_EVIDENCE and d["h1_pass"] is None and d["accept_three_levels"] is None
    assert d["not_separated"] == []
    text = "\n".join(rd._decision_lines(d))
    assert "CHUA DU BANG CHUNG" in text and "NHAN 3 cap do" not in text and "CHUA nhan" not in text


@pytest.mark.parametrize("h1_ok,h2,h3", [
    (True, H2_OK, H3_OK),  # moi thu dat van chua duoc tuyen bo
    (False, H2_OK, H3_OK),
    (True, {"levels": {"easy": {"pass": False}, "hard": {"pass": True}}}, H3_OK),
])
def test_decide_without_labels_is_not_final(h1_ok, h2, h3):
    d = rd.decide({"pairs": _table(hm=h1_ok)}, h2, h3, None)
    assert d["h1_status"] == rd.NOT_FINAL and d["accept_three_levels"] is None and d["h1_pass"] is h1_ok
    text = "\n".join(rd._decision_lines(d))
    assert "CHUA CHOT" in text and "NHAN 3 cap do" not in text and "CHUA nhan" not in text


def test_decide_trusted_at_threshold_still_decides():
    d = rd.decide({"pairs": _table()}, H2_OK, H3_OK, {"complete": True, "judge_trusted": True, "human_h1": {}})
    assert d["h1_status"] == "dat" and d["accept_three_levels"] is True


def test_report_flow_agreement_below_75_gives_no_evidence():
    pool = _pairs(["hard"] * 4)
    report = lp.build_report(_labels(pool, ["hard", "hard", "medium", "medium"]), pool, n_boot=50, required=4)  # 50%
    d = rd.decide({"pairs": _table()}, H2_OK, H3_OK, report)
    assert d["h1_status"] == rd.NO_EVIDENCE and "chua du bang chung" in lp.format_report(report)


# ---------------- 3.3 sua dang ky: du nhan moi tinh dong thuan ----------------


def test_pairwise_partial_labels_not_computed():
    pool = _pairs(["hard"] * 30)
    report = lp.build_report(_labels(pool[:23], ["hard"] * 23), pool, n_boot=20)  # khop 100% nhung moi 23/24
    assert report["complete"] is False and report["agreement"] is None and report["kappa"] is None
    assert report["judge_trusted"] is False and report["human_h1"] == {}
    text = lp.format_report(report)
    assert "chua du nhan (23/24)" in text and "H1 chua chot" in text and "%" not in text


def test_pairwise_full_labels_computed_at_exactly_required():
    pool = _pairs(["hard"] * 30)
    report = lp.build_report(_labels(pool[:24], ["hard"] * 24), pool, n_boot=20)
    assert report["complete"] is True and report["agreement"] == 1.0 and report["judge_trusted"] is True


def test_pairwise_labels_not_in_pool_or_duplicated_do_not_count():
    pool = _pairs(["hard"] * 30)
    outside = [{"pair_id": f"khac{i}", "human_winner": "hard"} for i in range(10)]
    duplicates = _labels(pool[:1], ["hard"]) * 5
    report = lp.build_report(_labels(pool[:20], ["hard"] * 20) + outside + duplicates, pool, n_boot=20)
    assert report["labeled"] == 20 and report["complete"] is False and report["missing_in_pool"] == 10


def test_pairwise_human_ties_count_as_labeled():
    pool = _pairs(["hard"] * 24)
    report = lp.build_report(_labels(pool, ["tie"] * 23 + ["hard"]), pool, n_boot=20)
    assert report["complete"] is True and report["n_compared"] == 1 and report["human_ties"] == 23


def test_decide_partial_labels_is_not_final_not_no_evidence():
    pool = _pairs(["hard"] * 3)
    report = lp.build_report(_labels(pool, ["medium"] * 3), pool, n_boot=20)  # lech het, nhung chua du nhan
    d = rd.decide({"pairs": _table()}, H2_OK, H3_OK, report)
    assert d["h1_status"] == rd.NOT_FINAL and d["accept_three_levels"] is None and d["judge_checked"] is False
    text = "\n".join(rd._decision_lines(d))
    assert "chua du nhan (3/24)" in text and "CHUA DU BANG CHUNG" not in text and "NHAN 3 cap do" not in text


# ---------------- 3.3 sua dang ky: --replicates ----------------


def test_replicates_ids_are_independent_clusters_in_h1():
    configs, _ = pc.load_case_configs()
    specs = pc.build_specs(configs, ["LM"], ["moi_nhuong_bo"], limit=1, replicates=2)
    assert [s.dialogue_id for s in specs] == ["LM|P1|pro|moi_nhuong_bo|r1", "LM|P1|pro|moi_nhuong_bo|r2"]
    # 2 replicate, 2 trang thai moi replicate -> 2 cum (khong gop thanh 1 cum)
    results, clusters = ["hard"] * 4, [specs[0].dialogue_id] * 2 + [specs[1].dialogue_id] * 2
    pairs = _pairs(results)
    for p, c in zip(pairs, clusters):
        p["dialogue_id"] = c
    assert rd.h1_summary(pairs, 50)["pairs"]["hard-medium"]["n_clusters"] == 2


def test_replicate_states_do_not_collide_in_branch():
    base = {"arm": "LM", "status": "completed", "rounds": [
        {"round": i, "learner": {"text": f"L{i}"}, "ai": {"text": f"A{i}", "premises": None, "ai_points": None, "target_premise": None}}
        for i in range(5)]}
    records = [{**base, "dialogue_id": f"LM|P1|con|s|r{k}"} for k in (1, 2)]
    todo, skipped = br.plan_states(records)
    assert not skipped
    assert sorted(br.state_id(r["dialogue_id"], s) for r, s in todo) == [
        "LM|P1|con|s|r1|r1", "LM|P1|con|s|r1|r3", "LM|P1|con|s|r2|r1", "LM|P1|con|s|r2|r3"]


def test_48_dialogues_each_arm_and_96_states_with_two_replicates():
    configs = [SimpleNamespace(motion_id=f"M{i}", motion="m", motion_type="policy", ai_side=DebateSide.PRO, difficulty=None,
                               case_file={}, case_source={}, burden_pro="", burden_con="") for i in range(12)]
    specs = pc.build_specs(configs, list(pc.LEVEL_ARMS), list(pc.STRATEGIES), replicates=2)
    assert len(specs) == 3 * 48 and len({s.dialogue_id for s in specs}) == 3 * 48
    rounds = [{"round": i, "learner": {"text": f"L{i}"}, "ai": {"text": f"A{i}"}} for i in range(5)]
    records = [{"dialogue_id": s.dialogue_id, "arm": "LM", "status": "completed", "rounds": rounds} for s in specs if s.arm == "LM"]
    todo, skipped = br.plan_states(records)
    assert len(records) == 48 and len(todo) == 96 and not skipped


def test_h2_pairs_by_combination_and_replicate():
    def rec(arm, k, replicate, flips):
        return _rec(arm, flips, k=k, replicate=replicate, dialogue_id=f"{arm}|M{k}|pro|moi_nhuong_bo|r{replicate}")

    recs = [rec(arm, k, rep, [1] if (arm, rep) == ("LH", 2) else []) for arm in ("LM", "LH") for k in range(3) for rep in (1, 2)]
    paired = rd.h2_summary(recs + [rec("LM", 3, 1, [])], n_boot=50)["compare"]["LH-LM"]["paired"]
    # r2 cua LH lat, r1 khong: neu ghep theo to hop khong co replicate thi 1 ban ghi de len ban kia va diff sai
    assert paired["n_pairs"] == 6 and paired["diff"] == pytest.approx(0.5)
    assert paired["unpaired"] == [("M3", "pro", "moi_nhuong_bo", 1)]


# ---------------- 3.3 sua dang ky 1: bootstrap H1 theo hoi thoai ----------------


def _doubled(wins, losses):
    """Moi hoi thoai 2 trang thai (vong 1, 3) cung ket qua: tuong quan hoan toan trong cum."""
    per_dialogue = ["hard"] * wins + ["medium"] * losses
    return [r for r in per_dialogue for _ in range(2)], [f"d{i}" for i in range(wins + losses) for _ in range(2)], per_dialogue


def test_cluster_bootstrap_resamples_dialogues_not_states():
    results, clusters, per_dialogue = _doubled(9, 3)
    s = jp.win_stats(results, "hard", "medium", 2000, 7, clusters=clusters)
    single = jp.win_stats(per_dialogue, "hard", "medium", 2000, 7)
    # 2 trang thai giong het nhau khong cho them thong tin: KTC CHINH bang dung ban 12 hoi thoai
    assert (s["ci_low"], s["ci_high"]) == (single["ci_low"], single["ci_high"])
    assert s["ci_unit"] == "hoi thoai" and s["n_clusters"] == 12 and s["n"] == 24
    # KTC phu theo trang thai hep hon: chinh la do lac quan ma cum sua
    assert s["ci_high_state"] - s["ci_low_state"] < s["ci_high"] - s["ci_low"]


def test_h1_pass_uses_cluster_ci_not_state_ci():
    results, clusters, _ = _doubled(11, 4)  # 73,3%
    s = jp.win_stats(results, "hard", "medium", 10_000, jp.DEFAULT_SEED, clusters=clusters)
    assert s["ci_low_state"] > jp.H1_MIN_CI_LOW >= s["ci_low"]
    assert s["h1_pass"] is False
    assert jp.win_stats(results, "hard", "medium", 10_000, jp.DEFAULT_SEED)["h1_pass"] is True


def test_cluster_counts_and_rate_same_as_state_level():
    results = ["hard", "medium", "tie", jp.JUDGE_MISSING, "hard", jp.TIE_INCONSISTENT]
    clusters = ["a", "a", "b", "b", "c", "c"]
    s = jp.win_stats(results, "hard", "medium", 200, clusters=clusters)
    assert (s["wins"], s["losses"], s["ties"], s["tie_inconsistent"], s["judge_missing"]) == (2, 1, 1, 1, 1)
    assert s["win_rate"] == pytest.approx(2 / 3) and s["n_clusters"] == 3


def test_cluster_with_only_missing_is_not_counted():
    s = jp.win_stats(["hard", jp.JUDGE_MISSING], "hard", "medium", 50, clusters=["a", "b"])
    assert s["n_clusters"] == 1


def test_cluster_length_mismatch_rejected():
    with pytest.raises(ValueError):
        jp.win_stats(["hard"], "hard", "medium", 10, clusters=["a", "b"])


def test_cluster_bootstrap_reproducible():
    results, clusters, _ = _doubled(9, 3)
    assert jp.win_stats(results, "hard", "medium", 500, 3, clusters) == jp.win_stats(results, "hard", "medium", 500, 3, clusters)


def test_h1_summary_clusters_by_dialogue_everywhere():
    results, clusters, _ = _doubled(11, 4)
    pairs = _pairs(results)
    for p, c in zip(pairs, clusters):
        p["dialogue_id"] = c
    s = rd.h1_summary(pairs, 500)
    assert s["pairs"]["hard-medium"]["n_clusters"] == 15
    assert s["length_sensitivity"]["pairs"]["hard-medium"]["n_clusters"] == 15
    assert s["breakdown"]["round=1"]["hard-medium"]["n_clusters"] == 15
    assert s["pairs"]["hard-medium"]["ci_low"] == jp.win_stats(results, "hard", "medium", 500, clusters=clusters)["ci_low"]
    line = "\n".join(rd._h1_lines(s["pairs"]))
    assert "15 hoi thoai" in line and "theo trang thai" in line


# ---------------- 3.3 sua dang ky 3: H2 theo dung quy tac 3d ----------------


def _stop(arm, k, kind, failed_round=2, flips=()):
    return _rec(arm, list(flips), status="ai_failed", k=k, failed_round=failed_round, failure_kind=kind)


@pytest.mark.parametrize("kind", ["side_flip", "reviewer_unavailable"])
def test_h2_stance_stop_counts_as_flip_at_that_round(kind):
    recs = _level_recs({"LM": [[]] * 4, "LH": [[]] * 3}) + [_stop("LH", 3, kind)]
    s = rd.h2_summary(recs, n_boot=100)
    paired = s["compare"]["LH-LM"]["paired"]
    assert paired["n_pairs"] == 4 and paired["diff"] == pytest.approx(1 / 4) and paired["unpaired"] == []
    assert [r["dialogue_id"] for r in s["stopped"]["LH"]["stance"]] == ["LH|M3|pro|moi_nhuong_bo"]
    assert s["stopped"]["LH"]["content"] == []


def test_h2_stance_stop_does_not_double_count_flipped_round():
    recs = _level_recs({"LM": [[]] * 2, "LH": [[]]}) + [_stop("LH", 1, "side_flip", failed_round=3, flips=[1])]
    assert rd.h2_summary(recs, n_boot=50)["compare"]["LH-LM"]["paired"]["diff"] == pytest.approx(2 / 2)


@pytest.mark.parametrize("kind", ["target_level_mismatch", "target_not_in_premises", "invalid_json"])
def test_h2_content_stop_not_a_flip_and_reported_separately(kind):
    recs = _level_recs({"LM": [[]] * 4, "LH": [[]] * 3}) + [_stop("LH", 3, kind)]
    s = rd.h2_summary(recs, n_boot=100)
    paired = s["compare"]["LH-LM"]["paired"]
    assert paired["n_pairs"] == 3 and paired["diff"] == 0 and len(paired["unpaired"]) == 1
    assert s["stopped"]["LH"]["content"] == [{"dialogue_id": "LH|M3|pro|moi_nhuong_bo", "round": 2, "failure_kind": kind}]
    assert s["stopped"]["LH"]["stance"] == []
    text = "\n".join(rd._stopped_lines(s["stopped"]))
    assert "loi noi dung 1" in text and f"[content] LH|M3|pro|moi_nhuong_bo vong 2: {kind}" in text


def test_h2_other_stops_outside_main_as_in_3d():
    recs = _level_recs({"LM": [[]] * 4, "LH": [[]]}) + [
        _stop("LH", 1, "side_flip", failed_round=0), _stop("LH", 2, "provider_error"),
        _rec("LH", [], status="sim_invalid", k=3, failed_round=2),
    ]
    s = rd.h2_summary(recs, n_boot=50)
    st = s["stopped"]["LH"]
    assert (len(st["stance"]), len(st["stance_round0"]), len(st["infra"]), len(st["sim_invalid"])) == (0, 1, 1, 1)
    assert s["compare"]["LH-LM"]["paired"]["n_pairs"] == 1


def test_decide_insufficient_h3_not_accepted():
    h3 = {**H3_OK, "hard": {"status": rd.INSUFFICIENT}}
    d = rd.decide({"pairs": _table()}, H2_OK, h3, None)
    assert d["h3_not_passed"] == {"hard": rd.INSUFFICIENT} and not d["accept_three_levels"]


def test_judge_by_level_means():
    s = rd.judge_by_level(_pairs(["hard"] * 2))
    assert s["hard"]["points_answered_mean"] == 2.0 and s["hard"]["attacks_foundational_rate"] == 1.0
    assert s["medium"]["attacks_foundational_rate"] == 0.5 and s["easy"]["points_answered_mean"] is None


async def test_full_report_end_to_end_with_fakes(tmp_path):
    records = []
    for arm in pc.LEVEL_ARMS:
        for strategy in pc.STRATEGIES:
            record, _ = await _run_arm(arm, strategy=strategy)
            records.append(record)
    lm = [r for r in records if r["arm"] == "LM"]
    states = [await br.branch_state(r, snap, SETTINGS, Harness().factories) for r in lm for snap in br.SNAPSHOT_ROUNDS]
    path = tmp_path / "p.jsonl"
    await jp.run_all(states, lambda: PairFake([], lambda u: V_("tie")), SETTINGS, CFG, path, out=lambda _: None)
    pairs = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert len(states) == 4 and len(pairs) == 12
    s = rd.summarize(records, states, pairs, n_boot=100)
    assert s["h1"]["pairs"]["hard-medium"]["ties"] == 4
    assert s["h3"]["easy"]["turns"] > 0 and s["h3"]["easy"]["target_first_attempt_rate"] == 1.0
    assert set(s["h2"]["compare"]) == {"LE-LM", "LH-LM"}
    assert s["branch"]["levels"]["easy"]["ok"] == 4 and s["judge_cost"]["calls"] == 24
    assert s["decision"]["h1_pass"] is False  # toan hoa -> chua tach duoc
    text = rd.format_report(s)
    for needle in ("H1 — thu tu do kho", "H1 do nhay do dai", "H2 — NoF", "H3 — tuan thu cap", "QUYET DINH", "CHUA CHOT",
                   "chua co nhan nguoi pairwise"):
        assert needle in text
    assert "NHAN 3 cap do" not in text and "CHUA nhan 3 cap do" not in text
    json.dumps(s, ensure_ascii=False, default=list)
    # Giam khao toan hoa, nguoi deu chon 1 bai -> dong thuan 0% -> toan bao cao khong ket luan
    labels = [{"pair_id": p["pair_id"], "human_winner": p["high"]} for p in pairs]
    no_evidence = rd.summarize(records, states, pairs, labels, n_boot=50, label_required=len(labels))
    assert no_evidence["decision"]["h1_status"] == rd.NO_EVIDENCE
    text = rd.format_report(no_evidence)
    assert "CHUA DU BANG CHUNG" in text and "NHAN 3 cap do" not in text and "CHUA nhan 3 cap do" not in text
    assert "H1 chua du bang chung" in text
    # Cung cac nhan do nhung chua du 24 -> chua chot, khong phai chua du bang chung
    partial = rd.format_report(rd.summarize(records, states, pairs, labels, n_boot=50))
    assert "chua du nhan (12/24)" in partial and "CHUA CHOT" in partial and "CHUA DU BANG CHUNG" not in partial


# ---------------- 6. nhan nguoi ----------------


def _label_pool():
    pool = []
    for high, low in jp.PAIR_TYPES:
        for i in range(12):
            pool += _pairs(["tie"], f"{high}-{low}")
            pool[-1].update(pair_id=f"s{i}|{high}-{low}", state_id=f"s{i}", result=high if i % 2 else low)
    return pool


def test_select_samples_stratified_8_each_reproducible():
    pool = _label_pool()
    a, b = lp.select_samples(pool), lp.select_samples(list(reversed(pool)))
    assert len(a) == 24 and [s["pair_id"] for s in a] == [s["pair_id"] for s in b]
    assert [s["shown_first"] for s in a] == [s["shown_first"] for s in b]
    for high, low in jp.PAIR_TYPES:
        assert sum(s["pair_type"] == f"{high}-{low}" for s in a) == 8
    assert len({s["shown_first"] == s["high"] for s in a}) == 2  # thu tu hien thi co ca hai chieu
    assert [s["pair_id"] for s in a] != [s["pair_id"] for s in lp.select_samples(pool, seed=1)]


def test_build_pool_drops_judge_missing():
    assert lp.build_pool(_pairs(["hard", jp.JUDGE_MISSING])) == _pairs(["hard"])


def test_render_hides_level_and_true_order():
    s = {**_pairs(["hard"])[0], "shown_first": "medium", "ai_side": "con", "texts": {"hard": "BÀI X", "medium": "BÀI Y"}}
    text = lp.render_sample(s, 1, 24)
    for word in ("hard", "medium", "easy", "s0|", "con |"):
        assert word not in text
    assert text.index("BÀI Y") < text.index("BÀI X") and "«L»" in text


def test_label_flow_resumable(tmp_path):
    samples = lp.select_samples(_label_pool(), per_type=1)
    path = tmp_path / "l.csv"
    answers = iter(["x", "1", "q"])
    assert lp.label_samples(samples, path, input_fn=lambda _: next(answers), out=lambda _: None) is False
    rows = lp.read_csv(path)
    assert len(rows) == 1 and rows[0]["human_winner"] == samples[0]["shown_first"]
    answers = iter(["2", "h"])
    assert lp.label_samples(samples, path, input_fn=lambda _: next(answers), out=lambda _: None) is True
    rows = lp.read_csv(path)
    assert len(rows) == 3 and rows[2]["human_winner"] == "tie"
    s = samples[1]
    assert rows[1]["human_winner"] == (s["low"] if s["shown_first"] == s["high"] else s["high"])


def _labels(pool, winners):
    return [{"pair_id": p["pair_id"], "human_winner": w} for p, w in zip(pool, winners)]


def test_report_agreement_excludes_human_ties():
    pool = _pairs(["hard"] * 4 + ["medium"])
    labels = _labels(pool, ["hard", "hard", "hard", "tie", "hard"])  # 3 dong y, 1 hoa (bo), 1 lech
    r = lp.build_report(labels, pool, n_boot=100, required=5)
    assert (r["n"], r["human_ties"], r["n_compared"]) == (5, 1, 4)
    assert r["agreement"] == 0.75 and r["judge_trusted"] is True  # dung nguong
    assert r["kappa"] is not None


def test_report_judge_tie_counts_as_disagreement_and_below_threshold():
    pool = _pairs(["hard", jp.TIE, jp.TIE_INCONSISTENT, "hard"])
    r = lp.build_report(_labels(pool, ["hard"] * 4), pool, n_boot=100, required=4)
    assert r["agreement"] == 0.5 and r["judge_trusted"] is False


def test_report_human_h1_and_format():
    pool = _pairs(["hard"] * 8)
    r = lp.build_report(_labels(pool, ["hard"] * 7 + ["medium"]), pool, n_boot=100, required=8)
    assert r["human_h1"]["hard-medium"]["wins"] == 7 and r["human_h1"]["hard-medium"]["losses"] == 1
    assert "Dieu kien tin giam khao" in lp.format_report(r)


def test_report_no_labels():
    r = lp.build_report([], _pairs(["hard"]), n_boot=10)
    assert r["agreement"] is None and r["judge_trusted"] is False


def test_output_dirs_under_experiments():
    assert br.OUT_DIR == Path(pc.ROOT) / "experiments" / "difficulty_eval" and jp.OUT_DIR == br.OUT_DIR
