"""
turn_full_v5 (dev log muc 2.18) = v4 + sua loi tu 4 tran thu 30/09. Test: v5 khac v4 DUNG cac diem trong spec. LLM gia.
"""
import json

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent import turn_full as tf
from app.opponent.match_format import TurnMode
from app.opponent.models import DebateSide, LLMCallPurpose, OpponentLLMCall, OpponentTurn
from app.opponent.turn_generators import Ledger
from tests.conftest import SchemaRejected
from tests.test_turn_full import _ctx, _out, _sp
from tests.test_turns_api import _learner, _ready_session, _session_id, _turn

PRO, CON = DebateSide.PRO, DebateSide.CON
BURDEN = "Không nên áp dụng lệnh cấm học sinh sử dụng điện thoại di động trong toàn bộ thời gian ở trường."

# Mac dinh tu muc 2.19 la turn_full_v6. File nay kiem tra hanh vi v5 -> GHIM v5 cho test qua API.
V5_SETTINGS = Settings(_env_file=None, turn_generator_version="turn_full_v5")


@pytest.fixture(autouse=True)
def pin_turn_full_v5(request):
    if "client" in request.fixturenames:
        request.getfixturevalue("client")
        app.dependency_overrides[get_settings] = lambda: V5_SETTINGS


def _out5(mode, n_words=None, speech=None, **over) -> str:
    """Output v5: KHONG co learner_claims."""
    data = json.loads(_out(mode, n_words=n_words, speech=speech, **over))
    data.pop("learner_claims")
    return json.dumps(data, ensure_ascii=False)


def _ctx5(ai_side, turn, history=(), ledger=None, burden=BURDEN):
    ctx = _ctx(ai_side, turn, history, ledger)
    ctx.ai_burden = burden
    return ctx


# ---------------- prompt: v5 khac v4 DUNG cac diem spec ----------------


@pytest.mark.parametrize("burden", [BURDEN, None])
def test_v5_prompt_differs_from_v4_only_in_spec_points(burden):
    ledger = Ledger(learner_claims=["Claim kieu cu."], learner_premises=["Tiền đề tường minh cũ."],
                    ai_points=["Ý cũ."], attacked_premises=["Tiền đề đã đánh."])
    ctx = _ctx5(CON, 4, [_sp(3, CON, "Phản bác learner.")], ledger, burden)
    v4 = "turn_full_v4" if burden else "turn_full_v4_noburden"
    v5 = "turn_full_v5" if burden else "turn_full_v5_noburden"
    s4, u4 = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version=v4)
    s5, u5 = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version=v5)

    # 1. system: bo "CỐ ĐỊNH"
    reading = ctx.case_file["motion_reading"]
    assert s5 == s4.replace(f"Cách hiểu kiến nghị của trận này là CỐ ĐỊNH: '{reading}'.",
                            f"Cách hiểu kiến nghị trong trận này: '{reading}'.")
    assert "CỐ ĐỊNH" not in s5
    # 2. khong learner_claims trong dinh dang JSON; ledger luan diem nguoi hoc tu premises.explicit
    # 3. 3 rang buoc moi ngay sau NO_RULE_ECHO_RULE
    expected = (u4
                .replace("\n- learner_claims: các luận điểm chính trong (các) bài nói MỚI của đội Đề xuất ở trên.", "")
                .replace("Các luận điểm người học đã nêu trước đó:\n- Claim kieu cu.",
                         "Các luận điểm người học đã nêu trước đó:\n- Tiền đề tường minh cũ.")
                .replace(tf.NO_RULE_ECHO_RULE, tf.NO_RULE_ECHO_RULE + "\n" + "\n".join(tf.V5_RULES)))
    assert u5 == expected
    for rule in ("- Mọi trường trong JSON, kể cả ai_points, viết bằng tiếng Việt.",
                 "- Không lặp lại cùng một câu hay cùng một ý hai lần.",
                 "- ai_points là các khẳng định ngắn, không mở đầu bằng 'Mình sẽ…', 'Mình nhấn mạnh rằng…'. Bài nói diễn đạt "
                 "các ý đó bằng lời nói tự nhiên, không chép nguyên văn dàn ý."):
        assert rule in u5
    assert u5.endswith("- Chỉ trả về JSON hợp lệ.")
    # rang buoc khong dinh nghia lai van o khoi cuoi
    assert "KHÔNG thu hẹp, mở rộng hay định nghĩa lại kiến nghị" in u5.split("Ràng buộc bắt buộc:")[1]
    # 6. burden nhu v4
    sentence = f"BẠN là phe Phản đối. Mọi điều bạn nói phải chứng minh: {BURDEN}"
    assert (sentence in s5 and f"- {sentence}" in u5) is bool(burden)


@pytest.mark.parametrize("mode", list(TurnMode))
def test_v5_schema_is_v4_without_learner_claims(mode):
    s4 = tf.build_response_schema(mode, True, "turn_full_v4")
    s5 = tf.build_response_schema(mode, True, "turn_full_v5")
    assert list(s5["properties"]) == s5["required"] == ["premises", "target_premise", "ai_points", "speech_text"]
    s4["properties"].pop("learner_claims")
    assert s5["properties"] == s4["properties"] and s5["additionalProperties"] is False


# ---------------- parse ----------------


def test_v5_parse_ignores_learner_claims_and_v4_still_requires_it():
    out = tf.parse_turn_output(_out5(TurnMode.REBUTTAL), TurnMode.REBUTTAL, 320, "turn_full_v5")
    assert out.learner_claims == []
    out = tf.parse_turn_output(_out(TurnMode.REBUTTAL), TurnMode.REBUTTAL, 320, "turn_full_v5")  # model van tra
    assert out.learner_claims == []
    with pytest.raises(tf._Invalid):
        tf.parse_turn_output(_out5(TurnMode.REBUTTAL), TurnMode.REBUTTAL, 320, "turn_full_v4")


# ---------------- kiem tra chi log ----------------


def test_v5_log_checks_toi_english_and_repeats():
    speech = ("Tôi đồng ý một phần. Mình thấy cấm là hợp lý. Mình thấy cấm là hợp lý! Giả sử có 40 học sinh. "
              "Mỗi tiết có 45 phút.")
    points = ["Phones are essential learning tools", "Điện thoại làm học sinh mất tập trung", "OK"]
    checks = tf.speech_checks_v5(speech, points)
    assert checks["toi_pronoun"] == ["Tôi đồng ý một phần."]
    assert checks["ai_points_english"] == ["Phones are essential learning tools"]
    assert checks["repeated_sentences"] == ["Mình thấy cấm là hợp lý."]
    assert checks["numbers_without_gia_su"] == ["Mỗi tiết có 45 phút."]  # kiem tra cu van con
    assert set(tf.speech_checks(speech)) == {"numbers_without_gia_su", "em_pronoun"}  # v1-v4 khong doi


# ---------------- qua API (mac dinh v5) ----------------


async def _turn_rows(db_session, ext):
    sid = await _session_id(db_session, ext)
    return (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN)
        .order_by(OpponentLLMCall.created_at))).all()


async def test_v5_default_ledger_from_explicit_premises_and_claims_null(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    t3 = json.loads(_out5(TurnMode.REBUTTAL))
    t3["premises"] = {"explicit": ["Trường đã có phòng máy tính."], "implicit": ["Ngầm."]}
    fake_llm.responses = [_out5(TurnMode.OPENING_FIRST), json.dumps(t3, ensure_ascii=False), _out5(TurnMode.CLOSING)]
    assert (await _turn(client, ext, 1)).status_code == 201
    assert (await _turn(client, ext, 3, [_learner(2)])).status_code == 201
    assert (await _turn(client, ext, 6, [_learner(4), _learner(5)])).status_code == 201

    planner = [c for c in fake_llm.calls if "user" in c]
    assert "learner_claims" not in json.dumps(planner[0]["json_schema"])
    assert "Các luận điểm người học đã nêu trước đó:\n- Trường đã có phòng máy tính." in planner[2]["user"]
    assert "CỐ ĐỊNH" not in planner[0]["system"]
    sid = await _session_id(db_session, ext)
    turns = (await db_session.scalars(select(OpponentTurn).where(OpponentTurn.session_id == sid)
                                      .order_by(OpponentTurn.turn_index))).all()
    assert [t.generator_version for t in turns] == ["turn_full_v5_noburden"] * 3  # session test khong co burden
    assert all(t.learner_claims is None for t in turns)  # cot DB de null
    assert turns[1].premises["explicit"] == ["Trường đã có phòng máy tính."]
    rows = await _turn_rows(db_session, ext)
    assert all({"toi_pronoun", "ai_points_english", "repeated_sentences"} <= set(r.speech_checks) for r in rows)


async def test_v5_length_inside_half_range_accepted_without_retry(client, db_session, fake_llm, fake_reviewer):
    # Tran 18:10 luot 6: closing 363 tu (muc tieu 260, chap nhan 182-325) -> v4 retry; v5: trong [130, 390] -> nhan ngay
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [_out5(TurnMode.OPENING_REPLY, n_words=560)]  # opening: [200, 600]; chap nhan [280, 500]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert len([c for c in fake_llm.calls if "user" in c]) == 1
    [row] = await _turn_rows(db_session, ext)
    assert row.success and row.speech_checks["length_soft_accept"] == {"word_count": 560, "accept_min": 280,
                                                                       "accept_max": 500}


@pytest.mark.parametrize("n_words", [150, 650])  # < 0,5x (200) hoac > 1,5x (600) cua opening 400
async def test_v5_length_far_outside_retries(client, db_session, fake_llm, fake_reviewer, n_words):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [_out5(TurnMode.OPENING_REPLY, n_words=n_words), _out5(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    rows = await _turn_rows(db_session, ext)
    assert [(r.success, r.failure_kind) for r in rows] == [(False, "word_count"), (True, None)]


async def test_v5_schema_rejected_array_repair_without_claims(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    data = json.loads(_out5(TurnMode.OPENING_REPLY))
    split = [{"premises": data["premises"]}, "target_premise", ":", data["target_premise"], "ai_points", ":",
             data["ai_points"], "speech_text", ":", *data["speech_text"].split(", ")]
    fake_llm.responses = [SchemaRejected(json.dumps(split, ensure_ascii=False))]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    [row] = await _turn_rows(db_session, ext)
    assert row.success and row.key_repairs["event"] == "array_repaired"


async def test_v5_burden_and_ablation_label(client, db_session, fake_llm, fake_reviewer):
    from tests.test_turn_v4_burden import _ready_with_burden

    ext = await _ready_with_burden(client, fake_llm, fake_reviewer)
    fake_llm.responses = [_out5(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert "Mọi điều bạn nói phải chứng minh" in fake_llm.calls[-1]["system"]
    sid = await _session_id(db_session, ext)
    assert (await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))).generator_version \
        == "turn_full_v5"

    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, turn_generator_version="turn_full_v5", turn_burden_enabled=False)
    ext_off = await _ready_with_burden(client, fake_llm, fake_reviewer, ai_side="pro")
    fake_llm.responses = [_out5(TurnMode.OPENING_FIRST)]
    assert (await _turn(client, ext_off, 1)).status_code == 201
    assert "Mọi điều bạn nói phải chứng minh" not in fake_llm.calls[-1]["system"]
    sid_off = await _session_id(db_session, ext_off)
    assert (await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid_off))).generator_version \
        == "turn_full_v5_noburden"


def test_default_is_v7_since_3_2():
    assert Settings(_env_file=None).turn_generator_version == "turn_full_v7"
