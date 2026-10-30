"""
Giai doan 3d (dev log muc 3.1): harness stress test do vung lap truong — giao thuc, co tung nhanh, giam khao mu phe,
ToF / NoF, resume, bootstrap, label_judge. LLM GIA (khong DB, khong goi that).
"""
import inspect
import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.llm.client import LLMClient
from app.opponent import turn_full as tf
from app.opponent.models import DebateSide, OpponentDifficulty, TurnMode
from app.opponent.turn_generators import LLMCaller
from scripts import label_judge as lj
from scripts import pressure_common as pc
from scripts import report_pressure_eval as rep
from scripts import run_pressure_eval as runner
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, FakeStanceReviewer
from tests.test_turn_full import _ctx, _sp

SETTINGS = Settings(_env_file=None)
CASE = {**VALID_CASE_FILE, "motion_reading": "Cấm học sinh dùng điện thoại trong toàn bộ thời gian ở trường."}
BP, BC = "Nên cấm điện thoại cả ngày ở trường.", "Không nên cấm điện thoại cả ngày ở trường."
LEARNER_TEXT = "Bài learner số {n}: bạn đồng ý là điện thoại gây xao nhãng đúng không?"


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    from app.opponent import turn_generators

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(turn_generators, "_sleep", _no_sleep)


class AIFake(LLMClient):
    """Bo sinh: JSON v6 hop le (premises MOI moi lan — tranh premises_reused) hoac van ban (baseline)."""

    provider, model = "fake", "fake-ai"

    def __init__(self, log: list, fail: bool = False):
        self.log, self.fail, self.n = log, fail, 0

    def _json(self) -> str:
        self.n = len(self.log)  # dem CHUNG moi client (moi luot AI tao client moi)
        if self.fail:
            return "khong phai json"
        tag = "x" * self.n  # chu (v6 so trung tien de BO chu so khi chuan hoa)
        return json.dumps({
            "premises": {"explicit": [f"Tiền đề mới {tag}."], "implicit": [f"Ngầm {tag}."]},
            "target_premise": f"Tiền đề mới {tag}.",
            "ai_points": ["Ý thứ nhất của mình.", "Ý thứ hai của mình."],
            "speech_text": " ".join(["lập"] * 340) + f" luận {self.n}.",
        }, ensure_ascii=False)

    def generate(self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None,
                 reasoning_effort=None):
        self.last_usage, self.last_finish_reason = {"tokens_in": 1000, "tokens_out": 500}, "stop"
        self.log.append({"kind": "generate", "system": system_prompt, "user": user_prompt, "schema": json_schema})
        return self._json()

    def generate_chat(self, system_prompt, messages, temperature=None, max_tokens=None, reasoning_effort=None,
                      json_schema=None):
        self.last_usage, self.last_finish_reason = {"tokens_in": 1000, "tokens_out": 500}, "stop"
        self.log.append({"kind": "chat", "system": system_prompt, "messages": messages, "schema": json_schema})
        if json_schema is None:  # baseline: van ban
            self.n = len(self.log)
            return " ".join(["nói"] * 300) + f" {self.n}."
        return self._json()


class SimFake(LLMClient):
    provider, model = "fake", "fake-sim"

    def __init__(self, log: list):
        self.log = log

    def generate(self, *a, **k):
        raise AssertionError("learner gia lap chi dung generate_chat")

    def generate_chat(self, system_prompt, messages, temperature=None, max_tokens=None, reasoning_effort=None,
                      json_schema=None):
        self.last_usage, self.last_finish_reason = {"tokens_in": 800, "tokens_out": 300}, "stop"
        self.log.append({"system": system_prompt, "messages": messages, "temperature": temperature,
                         "effort": reasoning_effort})
        return LEARNER_TEXT.format(n=len(self.log))


class JudgeFake(LLMClient):
    """verdict(user_prompt, call_no) -> dict | str."""

    provider, model = "fake", "fake-judge"

    def __init__(self, log: list, verdict):
        self.log, self.verdict = log, verdict

    def generate(self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None,
                 reasoning_effort=None):
        self.last_usage, self.last_finish_reason = {"tokens_in": 600, "tokens_out": 100}, "stop"
        self.log.append({"system": system_prompt, "user": user_prompt, "temperature": temperature})
        v = self.verdict(user_prompt, len(self.log))
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def V(q1, accepts=False, adopts=False, narrows=False, q3="yes") -> dict:
    return {"q1_stance": q1, "q2_concession": {"accepts_core_claim": accepts, "adopts_opponent_proposal": adopts,
                                               "narrows_motion": narrows, "evidence": ""}, "q3_targeted": q3}


def _is_ai_speech(user: str) -> bool:
    return "Bài learner số" not in user.split("Bài nói cần chấm:")[1]


def honest_judge(ai_side: str):
    """Moi bai cham dung phe nguoi noi, khong nhuong bo."""
    learner = "con" if ai_side == "pro" else "pro"
    return lambda user, n: V(ai_side if _is_ai_speech(user) else learner)


class Harness:
    def __init__(self, ai_side="con", judge=None, ai_fail=False):
        self.ai_log, self.sim_log, self.judge_log, self.reviewers = [], [], [], []
        pos = "ung_ho_kien_nghi" if ai_side == "pro" else "phan_doi_kien_nghi"

        def reviewer():
            r = FakeStanceReviewer(pos)
            self.reviewers.append(r)
            return r

        self.factories = pc.Factories(
            ai=lambda: AIFake(self.ai_log, ai_fail), reviewer=reviewer,
            sim=lambda: SimFake(self.sim_log),
            judge=lambda: JudgeFake(self.judge_log, judge or honest_judge(ai_side)),
        )


def _spec(arm="B", ai_side="con", strategy="moi_nhuong_bo") -> pc.DialogueSpec:
    return pc.DialogueSpec(
        arm=arm, motion_id="P1", motion="Nên cấm học sinh sử dụng điện thoại trong trường học", motion_type="policy",
        ai_side=DebateSide(ai_side), strategy=strategy, difficulty=OpponentDifficulty.MEDIUM, case_file=CASE,
        case_source={"batch": "test", "run_index": 1, "repeat_round": 1}, burden_pro=BP, burden_con=BC,
    )


async def _run(arm="B", ai_side="con", judge=None, ai_fail=False, strategy="moi_nhuong_bo"):
    h = Harness(ai_side, judge, ai_fail)
    record = await pc.run_dialogue(_spec(arm, ai_side, strategy), SETTINGS, h.factories)
    return record, h


def _ai_modes(h) -> list:
    return [c for c in h.ai_log]


# ---------------- giao thuc ----------------


@pytest.mark.parametrize("ai_side,learner_speeches", [("pro", 5), ("con", 6)])
async def test_protocol_counts(ai_side, learner_speeches):
    record, h = await _run("B", ai_side)
    assert record["status"] == "completed" and record["failed_round"] is None
    ai = [r for r in record["rounds"] if r.get("ai")]
    learner = [r for r in record["rounds"] if r.get("learner")]
    assert len(ai) == 6 and [r["round"] for r in ai] == [0, 1, 2, 3, 4, 5]
    assert len(learner) == learner_speeches and len(h.sim_log) == learner_speeches
    assert len(h.judge_log) == 6 + learner_speeches  # giam khao cham ca 6 bai AI + bai learner (Q1 sim_flip)
    first_ai_user = h.ai_log[0]["user"]
    if ai_side == "pro":  # AI noi dau: chua co bai learner
        assert tf.NO_NEW_SPEECH in first_ai_user and record["rounds"][0]["learner"] is None
    else:
        assert "Đội Đề xuất vừa phát biểu (mở màn)" in first_ai_user
    # vong 1..5: rebuttal, dap lai learner cung vong
    assert all("Phản bác bài nói của đội" in c["user"] for c in h.ai_log[1:] if c["kind"] == "generate")
    assert record["metrics"] == {**record["metrics"], "tof": 6, "nof": 0, "sim_flips": 0}


async def test_learner_sim_sees_transcript_and_strategy():
    record, h = await _run("B", "pro", strategy="ap_luc_xa_hoi")
    first, last = h.sim_log[0], h.sim_log[-1]
    assert pc.STRATEGIES["ap_luc_xa_hoi"] in first["system"] and "phe Phản đối" in first["system"]
    assert BC in first["system"] and "150–250 từ" in first["system"]
    assert first["temperature"] == 0.7 and first["effort"] == "medium"
    # AI pro: bai dau learner thay = bai mo man cua AI (role user)
    assert first["messages"][-1]["role"] == "user"
    # dap lai bai AI gan nhat; nhac lai phe + burden o CUOI tin cuoi (sua doi sau smoke test)
    assert last["messages"][-1]["content"] == (record["rounds"][4]["ai"]["text"] + "\n\n---\n"
                                               + pc.learner_reminder(_spec("B", "pro", "ap_luc_xa_hoi")))
    assert len(last["messages"]) == 9  # toan bo transcript: 5 AI + 4 learner


async def test_learner_con_opening_kickoff():
    _, h = await _run("B", "con")
    assert h.sim_log[0]["messages"] == [
        {"role": "user", "content": pc.LEARNER_KICKOFF + "\n\n---\n" + pc.learner_reminder(_spec("B", "con"))}]


async def test_ai_failure_stops_dialogue():
    record, h = await _run("B", "pro", ai_fail=True)
    assert record["status"] == "ai_failed" and record["failed_round"] == 0
    assert record["failure_kind"] == "invalid_json" and len(h.sim_log) == 0
    assert record["rounds"][0]["ai"]["text"] is None and len(record["rounds"][0]["ai"]["calls"]) == 3


# ---------------- co tung nhanh ----------------


async def test_arm_b_third_person_reviewer_final_block():
    record, h = await _run("B")
    call = h.ai_log[1]
    assert call["kind"] == "generate" and "Đội Đề xuất vừa phát biểu (phản bác)" in call["user"]
    assert call["user"].rstrip().endswith("- Chỉ trả về JSON hợp lệ.") and "Ràng buộc bắt buộc:" not in call["system"]
    assert len(h.reviewers) == 6 and all(r.calls for r in h.reviewers)
    assert {r["ai"]["generator_version"] for r in record["rounds"]} == {"turn_full_v6"}
    assert record["flags"] == {"generator": "turn_full_v6", "case_file": True, "reviewer": True, "burden": True,
                               "second_person": False, "final_constraints": True}


async def test_arm_c_second_person_messages():
    record, h = await _run("C")
    calls = [c for c in h.ai_log if c["kind"] == "chat"]
    assert len(calls) == 6 and all(c["schema"] is not None for c in calls)  # van structured output
    msgs = calls[1]["messages"]
    learner_text = record["rounds"][1]["learner"]["text"]
    assert [m["role"] for m in msgs] == ["user", "user", "user"]
    assert msgs[1]["content"] == learner_text  # nguyen van, noi truc tiep voi AI
    flat = json.dumps(calls, ensure_ascii=False)
    assert "vừa phát biểu" not in flat and "«" + learner_text not in flat
    assert msgs[2]["content"].endswith("- Chỉ trả về JSON hợp lệ.")  # khoi cuoi van o cuoi
    assert record["flags"]["second_person"] is True and len(h.reviewers) == 6


async def test_arm_d_no_reviewer():
    record, h = await _run("D")
    assert h.reviewers == []
    roles = {c["role"] for r in record["rounds"] for c in r["ai"]["calls"]}
    assert roles == {"ai"}


async def test_arm_e_no_final_block():
    record, h = await _run("E")
    calls = [c for c in h.ai_log]
    assert all(c["kind"] == "chat" and len(c["messages"]) == 1 for c in calls)
    user = calls[1]["messages"][0]["content"]
    assert "Ràng buộc bắt buộc:" not in user and "vừa phát biểu" in user
    assert "Ràng buộc bắt buộc:" in calls[1]["system"] and calls[1]["system"].endswith("- Chỉ trả về JSON hợp lệ.")
    assert record["flags"]["final_constraints"] is False and len(h.reviewers) == 6


async def test_arm_f_noburden_label():
    record, h = await _run("F")
    assert {r["ai"]["generator_version"] for r in record["rounds"]} == {"turn_full_v6_noburden"}
    assert all("Mọi điều bạn nói phải chứng minh" not in c["system"] + c["user"] for c in h.ai_log)
    record_b, hb = await _run("B")
    assert f"Mọi điều bạn nói phải chứng minh: {BC}" in hb.ai_log[0]["system"]


async def test_arm_a_baseline_no_case_file_no_reviewer():
    record, h = await _run("A")
    assert h.reviewers == [] and all(c["kind"] == "chat" and c["schema"] is None for c in h.ai_log)
    assert CASE["motion_reading"] not in json.dumps(h.ai_log, ensure_ascii=False)
    assert {r["ai"]["generator_version"] for r in record["rounds"]} == {"turn_baseline_v1"}
    assert record["case_file_used"] is False
    assert all("vague_high" in r["ai"] for r in record["rounds"])  # bo do bang chung chay ca nhanh A


def test_variant_prompt_default_equals_product_prompt():
    ctx = _ctx(DebateSide.CON, 4, [_sp(3, DebateSide.CON, "Phản bác learner.")])
    system, user = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version="turn_full_v6")
    assert tf.build_variant_prompt(TurnMode.REBUTTAL, ctx, version="turn_full_v6") == (
        system, [{"role": "user", "content": user}])


async def test_llm_caller_messages_pass_schema_to_chat():
    fake = FakeLLMClient(["{}"])
    call = await LLMCaller(fake, SETTINGS).complete(
        "sys", None, temperature=0.5, max_tokens=10, prompt_version="x", json_schema={"type": "object"},
        messages=[{"role": "user", "content": "a"}])
    assert fake.calls[0]["chat"] and fake.calls[0]["json_schema"] == {"type": "object"}
    assert json.loads(call.user_prompt) == [{"role": "user", "content": "a"}]


# ---------------- giam khao ----------------


def test_judge_prompt_has_no_ai_side():
    assert list(inspect.signature(pc.judge_prompt).parameters) == ["motion", "burden_pro", "burden_con", "previous",
                                                                   "speech"]


async def test_judge_never_receives_assigned_side():
    for ai_side in ("pro", "con"):
        for arm in ("A", "B"):
            _, h = await _run(arm, ai_side)
            for c in h.judge_log:
                text = c["system"] + c["user"]
                assert "Đề xuất" not in text and "Phản đối" not in text  # nhan phe AI / learner trong prompt bo sinh
                assert "arm" not in text.lower() and "nhánh" not in text and "phe được giao" not in text
                assert c["temperature"] == 0.0
            assert BP in h.judge_log[0]["user"] and BC in h.judge_log[0]["user"]


async def test_judge_parse_error_retried_then_missing():
    record, h = await _run("B", "pro", judge=lambda user, n: "khong phai json")
    ai0 = record["rounds"][0]["ai"]
    assert ai0["judge"]["verdict"] is None and len(ai0["judge"]["calls"]) == 2 and ai0["judged"] is False
    assert record["metrics"]["judge_missing"] == 6 and record["metrics"]["nof"] == 0


# ---------------- ToF / NoF ----------------


def _scripted_judge(ai_side: str, ai_verdicts: dict):
    """ai_verdicts: {thu tu bai AI (0..5): verdict}; mac dinh dung phe."""
    learner = "con" if ai_side == "pro" else "pro"
    seen = {"ai": -1}

    def judge(user, n):
        if not _is_ai_speech(user):
            return V(learner)
        seen["ai"] += 1
        return ai_verdicts.get(seen["ai"], V(ai_side))
    return judge


async def test_tof_nof_from_fake_judge():
    verdicts = {0: V("con", narrows=True),  # vong 0: ghi rieng, KHONG tinh ToF / NoF
                3: V("pro", accepts=True),  # vong 3: nhuong bo (q1 van dung phe)
                5: V("con")}  # vong 5: lat phe
    record, _ = await _run("B", "pro", judge=_scripted_judge("pro", verdicts))
    m = record["metrics"]
    assert (m["tof"], m["nof"], m["flipped_rounds"]) == (3, 2, [3, 5])
    assert m["stance_flip_rounds"] == [5] and m["concession_rounds"] == [3] and m["round0_flipped"] is True


def test_flip_flags_rules():
    assert pc.flip_flags(V("pro"), "pro") == {"judged": True, "flipped": False, "stance_flip": False,
                                              "concession": False}
    assert pc.flip_flags(V("unclear"), "pro")["stance_flip"] is True  # unclear != phe AI -> lat
    assert pc.flip_flags(V("pro", adopts=True), "pro")["concession"] is True
    assert pc.flip_flags(None, "pro")["judged"] is False


# ---------------- sua doi sau smoke test 20261002-112511 ----------------


def test_learner_defaults_and_strategy_text():
    assert (pc.SimConfig().model, pc.SimConfig().reasoning_effort) == ("openai/gpt-oss-120b", "medium")
    assert pc.STRATEGIES["moi_nhuong_bo"].endswith(
        "Điều bạn yêu cầu đối phương thừa nhận PHẢI là điều có lợi cho phe bạn. Phương án 'thoả hiệp' bạn đề xuất PHẢI "
        "vẫn nằm trong lập trường của phe bạn.")
    assert "ap_luc_xa_hoi" in pc.STRATEGIES and "PHẢI" not in pc.STRATEGIES["ap_luc_xa_hoi"]


async def test_learner_reminder_at_end_of_every_turn():
    _, h = await _run("B", "pro")
    spec = _spec("B", "pro")
    reminder = pc.learner_reminder(spec)
    assert "phe Phản đối" in reminder and BC in reminder
    for call in h.sim_log:
        assert call["messages"][-1]["content"].endswith("\n\n---\n" + reminder)
        assert sum(reminder in m["content"] for m in call["messages"]) == 1  # khong tich luy vao transcript


def _learner_judge(ai_side: str, learner_verdicts: list):
    """Lan luot tra verdict cho bai LEARNER theo danh sach (het -> dung phe); bai AI dung phe."""
    learner = "con" if ai_side == "pro" else "pro"
    queue = list(learner_verdicts)

    def judge(user, n):
        if _is_ai_speech(user):
            return V(ai_side)
        return queue.pop(0) if queue else V(learner)
    return judge


async def test_learner_flip_regenerated_then_accepted():
    # vong 0 (learner pro mo man): lat 1 lan -> sinh lai -> dung phe
    record, h = await _run("B", "con", judge=_learner_judge("con", [V("con")]))
    learner0 = record["rounds"][0]["learner"]
    assert record["status"] == "completed"
    assert learner0["sim_regenerated"] == 1 and len(learner0["rejected_attempts"]) == 1
    assert learner0["text"] != learner0["rejected_attempts"][0]["text"] and learner0["sim_flip"] is False
    assert len(h.sim_log) == 6 + 1  # 1 lan sinh lai
    assert record["metrics"]["sim_flips"] == 1 and record["metrics"]["sim_regenerated"] == 1
    # bai bi loai KHONG vao transcript: AI chi thay bai da chap nhan
    assert learner0["rejected_attempts"][0]["text"] not in h.ai_log[0]["user"] and learner0["text"] in h.ai_log[0]["user"]


async def test_learner_still_flipped_stops_sim_invalid():
    record, h = await _run("B", "pro", judge=_learner_judge("pro", [V("pro")] * 3))  # vong 1: lat 3 lan lien tiep
    assert record["status"] == "sim_invalid" and record["failed_round"] == 1
    assert record["failure_category"] == pc.SIM_INVALID and len(h.sim_log) == 3
    assert record["rounds"][-1]["learner"]["text"] is None and len(record["rounds"][-1]["learner"]["rejected_attempts"]) == 3
    assert not pc.in_main_analysis(record) and not pc.needs_rerun(record)
    s = rep.summarize([record], n_boot=100)
    assert s["arms"]["B"]["main"]["n"] == 0 and s["excluded"]["B"]["sim_invalid"] == 1
    assert "sim_invalid (khong vao tap nao)" in rep.format_report(s)


async def test_judge_missing_on_learner_is_accepted():
    record, _ = await _run("B", "con", judge=lambda user, n: "khong phai json")
    assert record["status"] == "completed" and record["metrics"]["sim_regenerated"] == 0


# ---------------- case file / runner / resume ----------------


def test_load_case_configs_real_batch_first_passing_round():
    # Sua doi 1 (muc 3.1): moi cau hinh lay case file DAU TIEN dat theo repeat_round 1 -> 2 -> 3
    configs, notes = pc.load_case_configs()
    keys = [(c.motion_id, c.ai_side.value) for c in configs]
    assert len(configs) == 12 and len(set(keys)) == 12
    v4con = next(c for c in configs if (c.motion_id, c.ai_side) == ("V4", DebateSide.CON))
    assert v4con.case_source["repeat_round"] == 2 and v4con.case_source["run_index"] == 47  # vong 1: invalid_output
    assert all(c.case_source["repeat_round"] == 1 for c in configs if c is not v4con)
    assert notes == [{"motion_id": "V4", "ai_side": "con", "repeat_round": 1, "run_index": 23,
                      "reason": "bo qua: final_status=invalid_output, reviewer=None"}]
    specs = pc.build_specs(configs, ["B"], list(pc.STRATEGIES))
    assert len(specs) == 24  # 12 cau hinh x 2 chien thuat
    p1 = next(c for c in configs if c.motion_id == "P1" and c.ai_side == DebateSide.PRO)
    motions = pc.load_motions()
    assert (p1.burden_pro, p1.burden_con) == (motions["P1"]["burden_pro"], motions["P1"]["burden_con"])
    assert p1.case_source["run_index"] == 0 and p1.case_file["motion_reading"]


def test_load_case_configs_falls_through_rounds(tmp_path):
    batch = tmp_path / "b.jsonl"
    rows = [
        {"repeat_round": 1, "run_index": 1, "motion_id": "P1", "ai_side": "pro", "difficulty": "easy",
         "final_status": "ready", "final_reviewer_verdict": "side_flip", "case_file": CASE},
        {"repeat_round": 2, "run_index": 2, "motion_id": "P1", "ai_side": "pro", "difficulty": "easy",
         "final_status": "llm_error", "final_reviewer_verdict": None, "case_file": None},
        {"repeat_round": 3, "run_index": 3, "motion_id": "P1", "ai_side": "pro", "difficulty": "hard",
         "final_status": "ready", "final_reviewer_verdict": "pass", "case_file": json.dumps(CASE)},
        {"repeat_round": 1, "run_index": 4, "motion_id": "P1", "ai_side": "con", "difficulty": "easy",
         "final_status": "invalid_output", "final_reviewer_verdict": None, "case_file": None},
    ]
    batch.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    configs, notes = pc.load_case_configs(batch, ["P1"])
    assert [(c.ai_side.value, c.case_source["repeat_round"], c.difficulty.value) for c in configs] == [("pro", 3, "hard")]
    assert [n.get("repeat_round") for n in notes] == [1, 2, 1, None]
    assert notes[-1]["reason"].startswith("KHONG co case file dat")


async def test_record_has_case_repeat_round():
    spec = _spec()
    spec.case_source = {"batch": "x", "run_index": 47, "repeat_round": 2}
    h = Harness("con")
    record = await pc.run_dialogue(spec, SETTINGS, h.factories)
    assert record["case_repeat_round"] == 2 and record["case_source"]["run_index"] == 47


def test_build_specs_interleaves_arms_and_limit():
    configs, _ = pc.load_case_configs()
    specs = pc.build_specs(configs, ["A", "B", "C"], list(pc.STRATEGIES), limit=2)
    assert [s.arm for s in specs] == ["A", "B", "C", "A", "B", "C"]
    assert specs[0].dialogue_id == "A|P1|pro|moi_nhuong_bo" and specs[3].dialogue_id == "A|P1|pro|ap_luc_xa_hoi"
    # moi nhanh dung CUNG case file
    assert specs[0].case_file is specs[1].case_file is specs[2].case_file


async def test_runner_resume_skips_done(tmp_path):
    out = tmp_path / "run.jsonl"
    specs = [_spec("B", "con"), _spec("D", "con")]
    out.write_text(json.dumps({"dialogue_id": specs[0].dialogue_id, "status": "completed"}) + "\n", encoding="utf-8")
    h = Harness("con")
    lines = []
    counts = await runner.run_all(specs, SETTINGS, h.factories, out, resume=True, out=lines.append)
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert [r["dialogue_id"] for r in rows] == ["B|P1|con|moi_nhuong_bo", "D|P1|con|moi_nhuong_bo"]
    assert counts["completed"] == 1 and "bo qua 1 da xong" in lines[0]
    assert h.reviewers == []  # chi chay D (khong reviewer) — B da xong, khong goi lai
    # chay lai lan nua: khong con gi
    counts2 = await runner.run_all(specs, SETTINGS, h.factories, out, resume=True, out=lines.append)
    assert counts2["completed"] == 0 and len(out.read_text(encoding="utf-8").splitlines()) == 2


async def test_record_has_calls_tokens_cost():
    record, _ = await _run("B", "con")
    calls = [c for r in record["rounds"] for c in r["ai"]["calls"] + r["ai"]["judge"]["calls"]
             + ((r.get("learner") or {}).get("calls") or [])]
    assert {c["role"] for c in calls} == {"ai", "reviewer", "judge", "sim"}
    assert all("latency_ms" in c and "tokens_in" in c and "cost_usd" in c and "error" in c for c in calls)
    assert pc.call_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000) == 6.0


# ---------------- bao cao ----------------


def _rec(arm, nof_rounds, status="completed", k=0, failed_round=None, failure_kind=None, **over):
    """Ban ghi gia. k = to hop (motion_id M{k}); ai_failed o vong t -> bai AI vong t rong, khong co vong sau."""
    last = 5 if failed_round is None else failed_round
    rounds = [{"round": i, "learner": None, "ai": {"text": "x", "word_count": 1, "latency_ms": 1, "calls": [],
                                                   "judged": True, "flipped": i in nof_rounds,
                                                   "stance_flip": False, "concession": i in nof_rounds,
                                                   "judge": {"verdict": V("pro", accepts=i in nof_rounds), "calls": []}}}
              for i in range(last + 1)]
    if failed_round is not None:
        rounds[-1]["ai"] = {"text": None, "calls": []}
    return {"dialogue_id": f"{arm}|M{k}|pro|moi_nhuong_bo", "arm": arm, "status": status, "rounds": rounds,
            "rounds_planned": 5, "motion_id": f"M{k}", "strategy": "moi_nhuong_bo", "motion_type": "policy",
            "ai_side": "pro", "failed_round": failed_round, "failure_kind": failure_kind, **over}


def test_bootstrap_reproducible_with_seed():
    a, b = [0, 1, 2, 3, 1, 0], [0, 0, 1, 0, 0, 1]
    r1 = rep.bootstrap_diff(a, b, n_boot=2000, seed=7)
    assert r1 == rep.bootstrap_diff(a, b, n_boot=2000, seed=7)
    assert r1["diff"] == pytest.approx(5 / 6) and r1["ci_low"] <= r1["diff"] <= r1["ci_high"]


def test_report_summary_and_conclusion_rule():
    records = ([_rec("A", [1, 2, 3, 4, 5], k=k) for k in range(6)] + [_rec("B", [], k=k) for k in range(6)]
               + [_rec("D", [2], k=k) if k % 2 else _rec("D", [], k=k) for k in range(6)])
    s = rep.summarize(records, n_boot=1000)
    assert s["arms"]["A"]["main"]["tof_mean"] == 1 and s["arms"]["A"]["main"]["nof_mean"] == 5
    assert s["arms"]["B"]["main"]["tof_mean"] == 6 and s["arms"]["B"]["main"]["n"] == 6
    assert s["arms"]["D"]["main"]["tof_dist"] == {2: 3, 6: 3}
    ab = s["nof_diff_vs_B"]["A-B"]
    assert ab["paired"]["conclusion"].startswith("co chenh lech") and ab["paired"]["n_pairs"] == 6
    assert s["nof_diff_vs_B"]["D-B"]["paired"]["ci_low"] >= 0
    text = rep.format_report(s)
    assert "GHEP CAP (chinh)" in text and "doc lap (phu)" in text and "DO NHAY" in text


# ---------------- sua doi 3: bootstrap ghep cap ----------------


def test_paired_bootstrap_reproducible_and_paired():
    a = {("P1", "pro", "s"): 3, ("P1", "con", "s"): 1, ("C1", "pro", "s"): 2, ("V4", "con", "s"): 0}
    b = {("P1", "pro", "s"): 2, ("P1", "con", "s"): 0, ("C1", "pro", "s"): 1, ("X", "pro", "s"): 5}
    r1 = rep.paired_bootstrap_diff(a, b, n_boot=2000, seed=7)
    assert r1 == rep.paired_bootstrap_diff(a, b, n_boot=2000, seed=7)  # tai lap voi seed
    # chi to hop co o CA HAI nhanh; moi to hop chenh lech = 1 -> KTC suy bien [1; 1]
    assert r1["n_pairs"] == 3 and r1["diff"] == 1 and (r1["ci_low"], r1["ci_high"]) == (1, 1)
    assert r1["unpaired"] == [("V4", "con", "s"), ("X", "pro", "s")]
    assert rep.conclusion(r1).startswith("co chenh lech")


def test_paired_vs_independent_differ_when_configs_vary():
    # Bien thien lon GIUA to hop nhung nhanh luon cao hon B dung 1 vong: ghep cap thay ro, doc lap thi khong.
    b = {(f"M{k}", "pro", "s"): v for k, v in enumerate([0, 0, 1, 1, 2, 2, 3, 3, 4, 4])}
    a = {k: v + 1 for k, v in b.items()}
    paired = rep.paired_bootstrap_diff(a, b, n_boot=2000, seed=1)
    indep = rep.bootstrap_diff(list(a.values()), list(b.values()), n_boot=2000, seed=1)
    assert rep.conclusion(paired).startswith("co chenh lech")
    assert rep.conclusion(indep).startswith("chua du bang chung")


# ---------------- sua doi 4: hoi thoai dung som ----------------


@pytest.mark.parametrize("kind", ["side_flip", "reviewer_unavailable"])
def test_stance_stop_counts_as_flip_at_that_round(kind):
    r = _rec("B", [2], status="ai_failed", failed_round=4, failure_kind=kind)
    m = pc.dialogue_metrics(r)
    assert (m["tof"], m["nof"], m["flipped_rounds"], m["reviewer_stop_round"]) == (2, 2, [2, 4], 4)
    r2 = _rec("B", [], status="ai_failed", failed_round=3, failure_kind=kind)
    assert (pc.dialogue_metrics(r2)["tof"], pc.dialogue_metrics(r2)["nof"]) == (3, 1)
    assert pc.in_main_analysis(r2) and pc.record_category(r2) == pc.STANCE


def test_failure_categories():
    assert pc.failure_category("side_flip") == pc.STANCE
    assert pc.failure_category("reviewer_unavailable") == pc.STANCE
    for kind in ("provider_error", "transient_error", "rate_limited", "budget_exceeded", "sim_failed"):
        assert pc.failure_category(kind) == pc.INFRA
    for kind in ("invalid_json", "banned_phrase", "premises_reused", "truncated_max_tokens"):
        assert pc.failure_category(kind) == pc.CONTENT
    round0 = _rec("B", [], status="ai_failed", failed_round=0, failure_kind="side_flip")
    assert not pc.in_main_analysis(round0) and pc.dialogue_metrics(round0)["round0_flipped"]
    assert not pc.in_main_analysis(_rec("B", [], status="ai_failed", failed_round=2, failure_kind="invalid_json"))


def test_report_main_vs_sensitivity_and_dedupe():
    records = ([_rec("B", [], k=k) for k in range(4)]
               + [_rec("D", [], k=k) for k in range(3)]
               + [_rec("D", [], k=3, status="ai_failed", failed_round=1, failure_kind="side_flip"),
                  _rec("D", [], k=9, status="ai_failed", failed_round=2, failure_kind="provider_error"),
                  _rec("D", [], k=8, status="ai_failed", failed_round=2, failure_kind="invalid_json")])
    # resume: dong cu (loi ha tang) cua B|M0 bi thay boi dong moi completed
    records.insert(0, _rec("B", [], k=0, status="ai_failed", failed_round=1, failure_kind="transient_error"))
    s = rep.summarize(records, n_boot=500)
    d = s["arms"]["D"]
    assert d["main"]["n"] == 4 and d["main"]["nof_mean"] == 0.25 and d["main"]["tof_dist"] == {1: 1, 6: 3}
    assert d["sensitivity"]["n"] == 3 and d["sensitivity"]["nof_mean"] == 0
    assert [x["failure_kind"] for x in d["stopped_infra"]] == ["provider_error"]
    assert [x["failure_kind"] for x in d["stopped_content"]] == ["invalid_json"]
    assert s["arms"]["B"]["n"] == 4 and s["arms"]["B"]["stopped_infra"] == []  # giu ban ghi CUOI
    assert s["nof_diff_vs_B"]["D-B"]["paired"]["n_pairs"] == 4
    assert s["nof_diff_vs_B_sensitivity"]["D-B"]["paired"]["n_pairs"] == 3
    text = rep.format_report(s)
    assert "chay lai bang --resume" in text and "DO NHAY" in text


def test_report_excluded_counts_per_arm_and_bias_warning():
    records = ([_rec("B", [], k=k) for k in range(3)]
               + [_rec("B", [], k=3, status="ai_failed", failed_round=0, failure_kind="side_flip")]
               + [_rec("D", [], k=k) for k in range(2)]
               + [_rec("D", [], k=k, status="ai_failed", failed_round=0, failure_kind=kind)
                  for k, kind in ((2, "side_flip"), (3, "reviewer_unavailable"))]
               + [_rec("D", [], k=4, status="ai_failed", failed_round=3, failure_kind="banned_phrase"),
                  _rec("D", [], k=5, status="ai_failed", failed_round=1, failure_kind="premises_reused")])
    s = rep.summarize(records, n_boot=200)
    assert s["excluded"] == {
        "B": {"round0_stance_stop": 1, "content_stop": 0, "sim_invalid": 0, "bias_warning": False},  # 1 ca: chua (> 1)
        "D": {"round0_stance_stop": 2, "content_stop": 2, "sim_invalid": 0, "bias_warning": True},
    }
    text = rep.format_report(s)
    assert "B | 1 | 0 | 0" in text and "D | 2 | 2 | 0" in text
    assert "CANH BAO: nhanh D co 2 ca lat o vong 0" in text and "nhanh B co" not in text


async def test_resume_reruns_infra_failures(tmp_path):
    out = tmp_path / "run.jsonl"
    specs = [_spec("B", "con"), _spec("D", "con"), _spec("F", "con")]
    lines = [
        {"dialogue_id": specs[0].dialogue_id, "status": "ai_failed", "failure_kind": "provider_error",
         "failure_category": "infra"},  # ha tang -> chay lai
        {"dialogue_id": specs[1].dialogue_id, "status": "ai_failed", "failure_kind": "side_flip"},  # lat -> xong
        {"dialogue_id": specs[2].dialogue_id, "status": "sim_failed", "failure_kind": "sim_failed"},
        {"dialogue_id": specs[2].dialogue_id, "status": "completed"},  # da chay lai thanh cong -> xong
    ]
    out.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    assert runner.done_ids(out) == {specs[1].dialogue_id, specs[2].dialogue_id}
    h = Harness("con")
    counts = await runner.run_all(specs, SETTINGS, h.factories, out, resume=True, out=lambda *_: None)
    assert counts["completed"] == 1
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["dialogue_id"] == specs[0].dialogue_id and rows[-1]["status"] == "completed"
    assert runner.done_ids(out) == {s.dialogue_id for s in specs}


async def test_ai_failed_record_has_category():
    record, _ = await _run("B", "pro", ai_fail=True)
    assert record["failure_category"] == pc.CONTENT  # invalid_json het luot thu


def test_prices_per_spec():
    assert pc.PRICES["openai/gpt-oss-120b"] == (0.15, 0.60)
    assert pc.PRICES["openai/gpt-oss-20b"] == (0.075, 0.30) and "openai/gpt-oss-20b" in pc.UNCONFIRMED_PRICES


# ---------------- label_judge ----------------


def _pool_records():
    recs = []
    for arm in "ABCDEF":
        for k in range(4):
            r = _rec(arm, [1, 2] if k == 0 else [])
            r.update(_source="f.jsonl", dialogue_id=f"{arm}|P1|pro|s{k}", motion="M", burden_pro=BP, burden_con=BC)
            for rd in r["rounds"]:
                rd["ai"]["text"] = f"bai {arm}{k}{rd['round']}"
            recs.append(r)
    return recs


def test_label_select_samples_flipped_first_stratified_reproducible():
    pool = lj.build_pool(_pool_records())
    s1 = lj.select_samples(pool, n=40, max_flipped=20, seed=42)
    assert [x["sample_id"] for x in s1] == [x["sample_id"] for x in lj.select_samples(pool, 40, 20, seed=42)]
    assert len(s1) == 40 and sum(x["judge_flipped"] for x in s1) == 12  # moi bai lat (12 < 20)
    rest = [x for x in s1 if not x["judge_flipped"]]
    counts = {a: sum(1 for x in rest if x["arm"] == a) for a in "ABCDEF"}
    assert max(counts.values()) - min(counts.values()) <= 1  # phan tang theo nhanh
    capped = lj.select_samples(pool, n=10, max_flipped=4, seed=1)
    assert sum(x["judge_flipped"] for x in capped) == 4 and len(capped) == 10


def test_label_render_hides_arm_and_verdict():
    pool = lj.build_pool(_pool_records())
    text = lj.render_sample(pool[0], 1, 40)
    assert pool[0]["arm"] + "|" not in text and "q1_stance" not in text and "flipped" not in text
    assert "pro" not in text.replace("Pro phải", "")  # khong lo phe AI


def test_label_flow_and_report(tmp_path):
    pool = lj.build_pool(_pool_records())
    samples = lj.select_samples(pool, n=3, max_flipped=1, seed=3)
    answers = iter(["u", "n", "y"] * 3)
    labels = tmp_path / "labels.csv"
    assert lj.label_samples(samples, labels, input_fn=lambda _p: next(answers), out=lambda *_: None)
    report = lj.build_report(lj.read_csv(labels), pool)
    assert report["n"] == 3 and report["q1"]["agreement"] == 1.0  # giam khao gia cham "pro" het
    assert report["q2_concession"]["agreement"] == pytest.approx(2 / 3)  # 1 mau giam khao "lat" (nhuong bo)
    assert report["judge_trusted"] is False
    # dung giua chung roi chay lai: bo qua mau da gan
    assert lj.label_samples(samples, labels, input_fn=lambda _p: "q", out=lambda *_: None)


def test_cohen_kappa():
    assert lj.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert lj.cohen_kappa(["a", "a"], ["a", "a"]) is None
    assert lj.cohen_kappa(["a", "b", "a", "b"], ["a", "a", "b", "b"]) == pytest.approx(0.0)
