"""
turn_full_v1 / v2 (Giai doan 3b, muc 2.9 + 2.10): schema, prompt, validator (do dai MEM, output bi cat), ledger qua
API, reasoning_effort; baseline khong bi anh huong. LLM gia.
"""
import json

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent import match_format as mf
from app.opponent import turn_full as tf
from app.opponent.match_format import TurnMode
from app.opponent.models import DebateSide, LLMCallPurpose, OpponentDifficulty, OpponentLLMCall, OpponentTurn
from app.opponent.turn_generators import Ledger, SpeechItem, TurnContext
from tests.conftest import VALID_CASE_FILE, SchemaRejected
from tests.test_turns_api import _learner, _ready_session, _session_id, _turn

PRO, CON = DebateSide.PRO, DebateSide.CON
SETTINGS = Settings(_env_file=None)
TARGET = {TurnMode.OPENING_FIRST: 400, TurnMode.OPENING_REPLY: 400, TurnMode.REBUTTAL: 320, TurnMode.CLOSING: 260}
CASE = {**VALID_CASE_FILE, "motion_reading": "Cấm mang và dùng điện thoại trong suốt thời gian ở trường."}


def _words(n: int, word: str = "lập") -> str:
    return " ".join([word] * (n - 1) + ["luận."])


def _out(mode: TurnMode, n_words: int | None = None, speech: str | None = None, **over) -> str:
    first, attack = mode == TurnMode.OPENING_FIRST, tf.needs_target(mode)
    data = {
        "learner_claims": [] if first else ["Điện thoại giúp học tập."],
        "premises": {"explicit": [] if first else ["Học sinh dùng điện thoại để học."],
                     "implicit": [] if first else ["Học sinh tự kiểm soát được."]},
        "target_premise": "Học sinh tự kiểm soát được." if attack else None,
        "ai_points": ["Ý thứ nhất của mình.", "Ý thứ hai của mình."],
        "speech_text": speech if speech is not None else _words(n_words or TARGET[mode]),
    }
    data.update(over)
    return json.dumps(data, ensure_ascii=False)


def _ctx(ai_side, turn_index, history=(), ledger=None, difficulty=OpponentDifficulty.MEDIUM) -> TurnContext:
    rt = mf.turn_spec(turn_index).round_type
    return TurnContext(
        motion="Nên cấm học sinh sử dụng điện thoại trong trường học", ai_side=ai_side,
        learner_side=CON if ai_side == PRO else PRO, difficulty=difficulty, turn_index=turn_index, round_type=rt,
        target_words=mf.target_words(rt, SETTINGS), history=list(history), case_file=CASE, ledger=ledger or Ledger(),
    )


def _sp(t, ai_side, text):
    return SpeechItem(t, mf.turn_spec(t).round_type, mf.speaker_of(t, ai_side), text)


# ---------------- schema ----------------


@pytest.mark.parametrize("mode", list(TurnMode))
def test_schema_field_order_and_target_by_mode(mode):
    schema = tf.build_response_schema(mode)
    order = ["learner_claims", "premises", "target_premise", "ai_points", "speech_text"]
    assert list(schema["properties"]) == schema["required"] == order
    dumped = json.dumps(schema)
    assert [dumped.index(f'"{k}"') for k in order] == sorted(dumped.index(f'"{k}"') for k in order)
    assert schema["additionalProperties"] is False and schema["properties"]["premises"]["additionalProperties"] is False
    assert schema["properties"]["target_premise"] == ({"type": "string"} if tf.needs_target(mode) else {"type": "null"})
    ai_points = schema["properties"]["ai_points"]
    assert (ai_points["minItems"], ai_points["maxItems"]) == (2, 4)
    empty = mode == TurnMode.OPENING_FIRST
    assert (schema["properties"]["learner_claims"].get("maxItems") == 0) is empty


def test_needs_target_only_opening_reply_and_rebuttal():
    assert [m for m in TurnMode if tf.needs_target(m)] == [TurnMode.OPENING_REPLY, TurnMode.REBUTTAL]
    assert tf.word_range(400) == (320, 480) and tf.word_range(320) == (256, 384) and tf.word_range(260) == (208, 312)


# ---------------- prompt ----------------


def test_prompt_has_motion_reading_case_ledger_third_person_and_constraints_last():
    history = [_sp(1, CON, "Bài mở màn learner."), _sp(2, CON, "Bài AI 2."), _sp(3, CON, "Điện thoại là công cụ học tập.")]
    ledger = Ledger(learner_claims=["Điện thoại giúp liên lạc."], ai_points=["Mình đã nói điện thoại gây mất tập trung."],
                    attacked_premises=["Học sinh tự kiểm soát được."])
    system, user = tf.build_full_prompt(TurnMode.REBUTTAL, _ctx(CON, 4, history, ledger))

    assert system == (
        "Bạn là một debater đang thi đấu, thuộc phe Phản đối về kiến nghị: "
        "'Nên cấm học sinh sử dụng điện thoại trong trường học'.\n"
        f"Cách hiểu kiến nghị của trận này là CỐ ĐỊNH: '{CASE['motion_reading']}'.\n"
        "Người học thuộc phe Đề xuất. Phe của bạn không bao giờ thay đổi."
    )
    assert user.startswith("Case của bạn (đã chuẩn bị trước trận):\n- [A1] Luận điểm 1: Khẳng định 1 của phe AI.")
    assert CASE["weighing"] in user
    assert ("Những điều bạn ĐÃ khẳng định ở các lượt trước (không được mâu thuẫn):\n"
            "- Mình đã nói điện thoại gây mất tập trung.") in user
    assert "Các luận điểm người học đã nêu trước đó:\n- Điện thoại giúp liên lạc." in user
    assert "Các tiền đề bạn đã tấn công:\n- Học sinh tự kiểm soát được." in user
    # CHI bai learner moi (sau luot AI 2), ngoi thu ba
    assert "Đội Đề xuất vừa phát biểu (phản bác):\n«Điện thoại là công cụ học tập.»" in user
    assert "Bài mở màn learner." not in user and "Bài AI 2." not in user
    assert "Phản bác bài nói của đội Đề xuất và bảo vệ các luận điểm của bạn đã bị tấn công." in user
    assert tf.TARGET_RULE[OpponentDifficulty.MEDIUM] in user
    assert "Không tấn công lại tiền đề đã tấn công, trừ khi người học chưa đáp lại nó." in user
    # thu tu (a) -> (f), khoi rang buoc CUOI CUNG
    order = ["Case của bạn", "Những điều bạn ĐÃ", "Các luận điểm người học", "Các tiền đề bạn đã tấn công",
             "Đội Đề xuất vừa phát biểu", "Nhiệm vụ lượt này", "Ràng buộc bắt buộc:"]
    assert [user.index(x) for x in order] == sorted(user.index(x) for x in order)
    block = tf.constraints_block(_ctx(CON, 4))
    assert user.endswith(block) and block.endswith("- Chỉ trả về JSON hợp lệ.")
    assert "- Độ dài speech_text: từ 256 đến 384 từ." in block
    assert "KHÔNG đề xuất như giải pháp của mình một phương án mà đội Đề xuất đã đưa ra" in block
    assert "Xưng 'mình', gọi người học là 'bạn'." in block


def test_prompt_skips_empty_ledger_sections():
    _, user = tf.build_full_prompt(TurnMode.OPENING_REPLY, _ctx(CON, 2, [_sp(1, CON, "Mở màn learner.")]))
    for header in ("Những điều bạn ĐÃ", "Các luận điểm người học", "Các tiền đề bạn đã tấn công"):
        assert header not in user
    assert "Đội Đề xuất vừa phát biểu (mở màn):\n«Mở màn learner.»" in user
    assert "phản bác sơ bộ bài mở màn của đội Đề xuất" in user


def test_opening_first_has_no_target_premise_and_nothing_to_rebut():
    _, user = tf.build_full_prompt(TurnMode.OPENING_FIRST, _ctx(PRO, 1))
    assert "Chưa có gì để phản bác." in user
    assert "Chọn target_premise" not in user and "Đội Phản đối vừa phát biểu" not in user
    assert "- target_premise: null" in user and "để cả hai mảng rỗng" in user


def test_closing_forbids_new_arguments():
    _, user = tf.build_full_prompt(TurnMode.CLOSING, _ctx(PRO, 6))
    assert "KHÔNG đưa lập luận mới, KHÔNG liệt kê lại toàn bộ luận điểm." in user
    assert "- target_premise: null" in user and "Chọn target_premise" not in user
    assert user.endswith(tf.constraints_block(_ctx(PRO, 6))) and "từ 208 đến 312 từ" in user


@pytest.mark.parametrize("difficulty,phrase", [
    (OpponentDifficulty.EASY, "một tiền đề TƯỜNG MINH bất kỳ"),
    (OpponentDifficulty.MEDIUM, "vừa nền tảng (gần gốc lập luận) vừa được chứng minh chưa đầy đủ"),
    (OpponentDifficulty.HARD, "xét cả tiền đề NGẦM"),
])
def test_target_rule_by_difficulty(difficulty, phrase):
    _, user = tf.build_full_prompt(TurnMode.OPENING_REPLY, _ctx(CON, 2, [_sp(1, CON, "x")], difficulty=difficulty))
    assert phrase in user


def test_retry_feedback_goes_before_constraints_block():
    _, user = tf.build_full_prompt(TurnMode.CLOSING, _ctx(PRO, 6), feedback="\n\n[PHẢN HỒI LẦN THỬ TRƯỚC] sai")
    assert user.index("[PHẢN HỒI LẦN THỬ TRƯỚC] sai") < user.index("Ràng buộc bắt buộc:")
    assert user.endswith("- Chỉ trả về JSON hợp lệ.")


# ---------------- validator + kiem tra chi log ----------------


def test_length_is_soft_and_high_evidence_is_hard():
    # Do dai: validator KHONG nem loi (generator xu ly loi mem); khoang chap nhan [0.7, 1.25], prompt van [0.8, 1.2]
    out = tf.parse_turn_output(_out(TurnMode.REBUTTAL, n_words=500), TurnMode.REBUTTAL, 320)
    assert out.speech_text.count(" ") == 499
    assert tf.accept_range(400) == (280, 500) and tf.accept_range(320) == (224, 400) and tf.accept_range(260) == (182, 325)
    assert tf.word_range(260) == (208, 312)  # yeu cau trong prompt khong doi
    assert [tf.length_distance(n, 260) for n in (181, 182, 325, 330)] == [1, 0, 0, 5]
    assert tf.length_issue(500, 320) == "`speech_text` hiện dài 500 từ, yêu cầu từ 256 đến 384 từ — viết ngắn lại."

    bad = "Nhiều nghiên cứu cho thấy điện thoại gây hại. " + _words(600)
    with pytest.raises(tf._Invalid) as e:
        tf.parse_turn_output(_out(TurnMode.REBUTTAL, speech=bad), TurnMode.REBUTTAL, 320)
    assert e.value.kind == "banned_phrase" and "nghiên cứu cho thấy" in e.value.issues[0]
    assert "hiện dài 609 từ" in e.value.issues[-1]  # HIGH + sai do dai: phan hoi neu ca hai


def test_validator_mode_rules():
    out = tf.parse_turn_output(_out(TurnMode.CLOSING, target_premise="lỡ điền"), TurnMode.CLOSING, 260)
    assert out.target_premise is None  # closing: bo qua, khong retry
    out = tf.parse_turn_output(
        _out(TurnMode.OPENING_FIRST, learner_claims=["bịa"]), TurnMode.OPENING_FIRST, 400
    )
    assert out.learner_claims == [] and out.premises.explicit == []
    with pytest.raises(tf._Invalid, match="target_premise"):
        tf.parse_turn_output(_out(TurnMode.REBUTTAL, target_premise=None), TurnMode.REBUTTAL, 320)
    with pytest.raises(tf._Invalid) as e:
        tf.parse_turn_output(_out(TurnMode.REBUTTAL, ai_points=["một ý"]), TurnMode.REBUTTAL, 320)
    assert e.value.kind == "schema_validation"


def test_speech_checks_log_numbers_outside_gia_su_and_em():
    text = ("Giả sử một lớp có 40 học sinh. Mỗi môn chỉ có 45 phút. Em nghĩ bạn sai. "
            "Trẻ em cần ngủ đủ. Mình tôn trọng bạn.")
    checks = tf.speech_checks(text)
    assert checks["numbers_without_gia_su"] == ["Mỗi môn chỉ có 45 phút."]
    assert checks["em_pronoun"] == ["Em nghĩ bạn sai.", "Trẻ em cần ngủ đủ."]  # chap nhan bat nham "trẻ em"


# ---------------- qua API (mac dinh turn_full_v1) ----------------


def _calls(fake_llm):
    return [c for c in fake_llm.calls if "user" in c and not c.get("chat")]


async def test_full_match_ai_pro_three_turns_builds_ledger(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    t1 = json.loads(_out(TurnMode.OPENING_FIRST))
    t1["ai_points"] = ["Mở màn: điện thoại làm mất tập trung.", "Mở màn: điện thoại gây bắt nạt mạng."]
    t3 = json.loads(_out(TurnMode.REBUTTAL))
    t3.update(learner_claims=["Điện thoại là công cụ học tập."], target_premise="Trường không có thiết bị thay thế.",
              ai_points=["Phản bác: trường có phòng máy.", "Phản bác: liên lạc qua giám thị."])
    t6 = json.loads(_out(TurnMode.CLOSING))
    t6["learner_claims"] = ["Cấm là cứng nhắc."]
    fake_llm.responses = [json.dumps(x, ensure_ascii=False) for x in (t1, t3, t6)]

    r1 = await _turn(client, ext, 1)
    assert r1.status_code == 201, r1.text
    assert r1.json()["mode"] == "opening_first" and r1.json()["speech_text"] == t1["speech_text"]
    assert (await _turn(client, ext, 3, [_learner(2, "Bài mở màn phe phản đối.")])).status_code == 201
    r6 = await _turn(client, ext, 6, [_learner(4, "Phản bác lượt 4."), _learner(5, "Tổng kết lượt 5.")])
    assert r6.status_code == 201, r6.text

    calls = _calls(fake_llm)
    assert len(calls) == 3
    assert calls[0]["json_schema"] == tf.build_response_schema(TurnMode.OPENING_FIRST)
    assert calls[0]["max_tokens"] == 6000 and calls[0]["temperature"] == 0.5 and calls[0]["reasoning_effort"] == "medium"  # muc 2.11
    # Luot 3: ledger co ai_points luot 1; luot 1 khong co learner_claims / tien de
    u3 = calls[1]["user"]
    assert "- Mở màn: điện thoại làm mất tập trung." in u3 and "Các luận điểm người học" not in u3
    assert "Đội Phản đối vừa phát biểu (mở màn):\n«Bài mở màn phe phản đối.»" in u3
    # Luot 6: ai_points luot 1 + 3, learner_claims luot 3, tien de da tan cong luot 3; CHI bai learner 4, 5
    u6 = calls[2]["user"]
    for x in t1["ai_points"] + t3["ai_points"]:
        assert f"- {x}" in u6
    assert "Các luận điểm người học đã nêu trước đó:\n- Điện thoại là công cụ học tập." in u6
    assert "Các tiền đề bạn đã tấn công:\n- Trường không có thiết bị thay thế." in u6
    assert "«Phản bác lượt 4.»" in u6 and "«Tổng kết lượt 5.»" in u6 and "Bài mở màn phe phản đối." not in u6
    assert u6.endswith("- Chỉ trả về JSON hợp lệ.")

    sid = await _session_id(db_session, ext)
    turns = (await db_session.scalars(select(OpponentTurn).where(OpponentTurn.session_id == sid)
                                      .order_by(OpponentTurn.turn_index))).all()
    assert [t.generator_version for t in turns] == ["turn_full_v3"] * 3  # mac dinh tu muc 2.12
    assert turns[0].target_premise is None and turns[0].learner_claims == [] and turns[0].ai_points == t1["ai_points"]
    assert turns[1].target_premise == "Trường không có thiết bị thay thế."
    assert turns[1].premises == t3["premises"] and turns[1].learner_claims == t3["learner_claims"]
    assert turns[2].target_premise is None and turns[2].word_count == 260
    logged = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN))).all()
    assert len(logged) == 3 and all(c.turn_id and c.success and c.vague_evidence == [] for c in logged)
    base_checks = {"numbers_without_gia_su": [], "em_pronoun": []}
    assert [c.speech_checks for c in sorted(logged, key=lambda c: c.created_at)] == [
        base_checks, base_checks,
        {**base_checks, "analysis_coerced": {"premises": 2}},  # luot 6 closing: premises bi ep rong (muc 2.11)
    ]


async def test_retry_with_feedback_when_length_wrong(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY, n_words=700), _out(TurnMode.OPENING_REPLY)]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201, resp.text

    first, second = _calls(fake_llm)
    assert "[PHẢN HỒI LẦN THỬ TRƯỚC]" not in first["user"]
    assert "`speech_text` hiện dài 700 từ, yêu cầu từ 320 đến 480 từ — viết ngắn lại." in second["user"]
    assert second["user"].index("[PHẢN HỒI LẦN THỬ TRƯỚC]") < second["user"].index("Ràng buộc bắt buộc:")
    sid = await _session_id(db_session, ext)
    logged = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN)
        .order_by(OpponentLLMCall.attempt))).all()
    # attempt danh so CHUNG voi loi goi Stance Reviewer (lan 2 = review ban 1) — xem test_reviewer_*
    assert [(c.attempt, c.success, c.failure_kind) for c in logged] == [(1, False, "word_count"), (3, True, None)]
    assert "700 từ" in logged[0].retry_feedback and logged[1].retry_feedback is None
    assert logged[0].turn_id == logged[1].turn_id is not None


async def test_retry_when_high_vague_evidence_and_low_is_only_logged(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    bad = "Nhiều nghiên cứu cho thấy học sinh cần điện thoại. " + _words(380)
    ok = "Các trung tâm nghiên cứu đều ở thành phố. Mỗi tiết học có 45 phút. " + _words(380)
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY, speech=bad), _out(TurnMode.OPENING_REPLY, speech=ok)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert "nghiên cứu cho thấy" in _calls(fake_llm)[1]["user"]

    sid = await _session_id(db_session, ext)
    logged = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN)
        .order_by(OpponentLLMCall.attempt))).all()
    assert logged[0].failure_kind == "banned_phrase"
    assert [h["level"] for h in logged[0].vague_evidence] == ["high"]
    assert [(h["rule"], h["level"]) for h in logged[1].vague_evidence] == [("nghien_cuu", "low")]
    assert logged[1].speech_checks["numbers_without_gia_su"] == ["Mỗi tiết học có 45 phút."]


async def _turn_calls(db_session, ext):
    sid = await _session_id(db_session, ext)
    return (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN)
        .order_by(OpponentLLMCall.attempt))).all()


async def test_hard_error_every_attempt_is_502(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["khong phai json"] * 3
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 502
    assert len(_calls(fake_llm)) == 3  # TURN_MAX_ATTEMPTS mac dinh 3
    sid = await _session_id(db_session, ext)
    assert await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid)) is None


async def test_length_soft_accept_after_one_retry_picks_closest(client, db_session, fake_llm, fake_reviewer):
    # Tran 15:11 luot 5: hut 1-2 tu x nhieu lan -> luot that bai. Nay: 1 lan thu lai roi chap nhan ban gan nhat.
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY, n_words=560), _out(TurnMode.OPENING_REPLY, n_words=700),
                          _out(TurnMode.OPENING_REPLY)]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201, resp.text
    assert len(_calls(fake_llm)) == 2  # chi 1 lan thu lai vi do dai (con 1 luot TURN_MAX_ATTEMPTS nhung khong dung)
    assert resp.json()["speech_text"].count(" ") == 559  # ban 560 tu (cach khoang 500 it hon ban 700)

    first, second = await _turn_calls(db_session, ext)
    assert (first.success, first.failure_kind, first.error) == (True, None, None)
    assert first.speech_checks["length_soft_accept"] == {"word_count": 560, "accept_min": 280, "accept_max": 500}
    assert "560 từ, yêu cầu từ 320 đến 480" in first.retry_feedback  # phan hoi da gui van duoc giu
    assert (second.success, second.failure_kind) == (False, "word_count")
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.id == first.turn_id))
    assert turn.word_count == 560


async def test_length_inside_accept_range_needs_no_retry(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY, n_words=290)]  # < 320 (prompt) nhung >= 280 (chap nhan)
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert len(_calls(fake_llm)) == 1


async def test_length_candidate_kept_when_later_attempts_fail_hard(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    high = "Nhiều nghiên cứu cho thấy học sinh cần điện thoại. " + _words(380)
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY, n_words=600), _out(TurnMode.OPENING_REPLY, speech=high),
                          _out(TurnMode.OPENING_REPLY, speech=high)]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201, resp.text  # khong bao gio that bai chi vi do dai
    assert resp.json()["speech_text"].count(" ") == 599
    kinds = [(c.success, c.failure_kind) for c in await _turn_calls(db_session, ext)]
    assert kinds == [(True, None), (False, "banned_phrase"), (False, "banned_phrase")]


@pytest.mark.parametrize("how", ["empty_failed_generation", "finish_length", "empty_content"])
async def test_truncated_output_is_its_own_failure_kind_and_retried(client, db_session, fake_llm, fake_reviewer, how):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    if how == "empty_failed_generation":  # tran 15:11 luot 5: Groq 400 json_validate_failed, failed_generation ""
        first = SchemaRejected("")
    elif how == "finish_length":
        first = '{"learner_claims": ["cắt giữa chừ'
        fake_llm.finish_reasons = ["length"]
        fake_llm.usages = [{"tokens_in": 1900, "tokens_out": 6000, "reasoning_tokens": 5200}]
    else:
        first = ""
    fake_llm.responses = [first, _out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201

    truncated, ok = await _turn_calls(db_session, ext)
    assert truncated.failure_kind == "truncated_max_tokens" and not truncated.success
    assert "truncated_max_tokens" in truncated.error and truncated.retry_feedback
    assert "RỖNG hoặc bị CẮT" in _calls(fake_llm)[1]["user"]
    if how == "finish_length":
        assert (truncated.finish_reason, truncated.tokens_out, truncated.reasoning_tokens) == ("length", 6000, 5200)
        assert "tokens_out=6000/6000" in truncated.error
    assert ok.success and ok.finish_reason == "stop"


async def test_schema_rejected_with_content_is_still_schema_rejected(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [SchemaRejected('{"x": 1}'), _out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert (await _turn_calls(db_session, ext))[0].failure_kind == "schema_rejected"


# ---------------- v2 + reasoning_effort ----------------


def test_v2_adds_natural_speech_rule_v1_unchanged():
    ctx = _ctx(CON, 4)
    v1, v2 = tf.constraints_block(ctx, "turn_full_v1"), tf.constraints_block(ctx, "turn_full_v2")
    rule = ("- Nói tự nhiên như một người tranh luận; KHÔNG đọc ra các thuật ngữ phân tích như 'tiền đề', "
            "'tiền đề ngầm' hay trích nguyên văn nhãn phân tích.")
    assert rule not in v1 and rule in v2
    assert v2.replace("\n" + rule, "") == v1  # chi them dung 1 dong
    assert v2.endswith("- Chỉ trả về JSON hợp lệ.")
    _, user = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version="turn_full_v2")
    assert user.endswith(v2)
    assert Settings(_env_file=None).turn_generator_version == "turn_full_v3"  # mac dinh tu muc 2.12


async def test_v1_still_selectable(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, turn_generator_version="turn_full_v1")
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert "Nói tự nhiên" not in _calls(fake_llm)[0]["user"]
    assert (await _turn_calls(db_session, ext))[0].prompt_version == "turn_full_v1"


async def test_turn_reasoning_effort_sent_and_logged(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, turn_reasoning_effort="low")
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY)]
    fake_llm.usages = [{"tokens_in": 1800, "tokens_out": 2100, "reasoning_tokens": 900}]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert _calls(fake_llm)[0]["reasoning_effort"] == "low"
    call = (await _turn_calls(db_session, ext))[0]
    assert (call.reasoning_effort, call.reasoning_tokens, call.tokens_out) == ("low", 900, 2100)


async def test_case_plan_reasoning_effort_only_for_planner(client, db_session, fake_llm, fake_reviewer):
    from tests.test_opponent_api import _payload

    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, case_plan_reasoning_effort="high")
    fake_llm.responses = [json.dumps(VALID_CASE_FILE, ensure_ascii=False)]
    payload = _payload()
    resp = await client.post("/opponent/sessions", json=payload)
    assert resp.status_code == 201, resp.text
    assert fake_llm.calls[0]["reasoning_effort"] == "high"
    assert fake_reviewer.calls[0]["reasoning_effort"] is None  # Stance Reviewer khong nhan
    sid = await _session_id(db_session, payload["external_session_id"])
    rows = (await db_session.scalars(select(OpponentLLMCall).where(OpponentLLMCall.session_id == sid)
                                     .order_by(OpponentLLMCall.attempt))).all()
    assert [(r.purpose.value, r.reasoning_effort) for r in rows] == [("case_plan", "high"), ("stance_review", None)]


def test_reasoning_effort_default_medium():
    s = Settings(_env_file=None)
    # muc 2.11: gui TUONG MINH "medium" (tran low 15:34 lat phe ca tran)
    assert s.turn_reasoning_effort == "medium" and s.case_plan_reasoning_effort == "medium" and s.turn_max_tokens == 6000


async def test_schema_rejected_with_typo_key_is_repaired_without_new_call(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    data = json.loads(_out(TurnMode.OPENING_REPLY))
    data["speech_txt"] = data.pop("speech_text")
    fake_llm.responses = [SchemaRejected(json.dumps(data, ensure_ascii=False))]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201, resp.text
    assert len(_calls(fake_llm)) == 1
    sid = await _session_id(db_session, ext)
    call = await db_session.scalar(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN))
    assert call.success and call.key_repairs["renames"] == [{"path": "speech_text", "from": "speech_txt", "to": "speech_text"}]


async def test_schema_rejected_unrepairable_retries_with_feedback(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [SchemaRejected('{"noi_dung": "x"}'), _out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    second = _calls(fake_llm)[1]["user"]
    assert "không khớp JSON schema" in second and "`speech_text`: thiếu trường bắt buộc" in second


async def test_baseline_unaffected_by_full_settings(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, turn_generator_version="turn_baseline_v1", turn_max_attempts=5, turn_max_tokens=9999
    )
    fake_llm.responses = ["", "", "khong dung toi"]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 502  # baseline: van 2 lan thu (3a), khong doc TURN_MAX_ATTEMPTS
    chats = [c for c in fake_llm.calls if c.get("chat")]
    assert len(chats) == 2 and all(c["max_tokens"] == 3000 for c in chats)
    assert not _calls(fake_llm)  # khong goi generate() JSON
