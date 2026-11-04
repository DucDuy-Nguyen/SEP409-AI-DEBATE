"""
turn_full_v6 (dev log muc 2.19) = v5 + sua loi chep tien de. Test: v6 khac v5 DUNG cac diem trong spec; hoi quy kiem tra
trung tien de bang dung du lieu luot 2 / 4 tran 20261002-001136 (learner pro). LLM gia.
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
from scripts import try_match as tm
from tests.conftest import FakeLLMClient
from tests.test_turn_full import _sp
from tests.test_turn_v5 import BURDEN, _ctx5, _out5
from tests.test_turns_api import _learner, _ready_session, _session_id, _turn

PRO, CON = DebateSide.PRO, DebateSide.CON
SETTINGS = Settings(_env_file=None)
# Mac dinh tu muc 3.2 la turn_full_v7. File nay kiem tra hanh vi v6 -> GHIM v6 cho test qua API.
V6_SETTINGS = Settings(_env_file=None, turn_generator_version="turn_full_v6")


@pytest.fixture(autouse=True)
def pin_turn_full_v6(request):
    if "client" in request.fixturenames:
        request.getfixturevalue("client")
        app.dependency_overrides[get_settings] = lambda: V6_SETTINGS

# Tran 20261002-001136 (experiments/matches/..._turn_full_v5_effort-medium.json): premises.explicit luot 2 == luot 4
MATCH_T2_EXPLICIT = [
    "Điện thoại làm học sinh mất tập trung trong giờ học.",
    "Điện thoại làm giảm sự giao tiếp giữa các bạn trong giờ ra chơi.",
    "Điện thoại có thể gây bắt nạt trên mạng.",
    "Liên lạc khẩn cấp có thể được đáp ứng bằng điện thoại ở phòng giám thị, nên không đủ mạnh.",
]
MATCH_T4_EXPLICIT = list(MATCH_T2_EXPLICIT)
MATCH_T4_TARGET = "Điện thoại có thể gây bắt nạt trên mạng."
LEARNER_T3 = next(s["text"] for s in tm.load_fixture("M01", "pro")["speeches"] if s["turn_index"] == 3)
FRESH_EXPLICIT = ["Trường đã có phòng máy và thư viện để tra cứu.", "Học sinh khó tự kiểm soát việc dùng điện thoại."]


def _ledger_match() -> Ledger:
    return Ledger(learner_premises=list(MATCH_T2_EXPLICIT), ai_points=["Ý cũ."], attacked_premises=["Tiền đề đã đánh."])


def _ctx_t4(burden=BURDEN, history=None):
    hist = [_sp(3, CON, LEARNER_T3)] if history is None else history
    return _ctx5(CON, 4, hist, _ledger_match(), burden)


def _rebuttal(explicit, target=MATCH_T4_TARGET, **over) -> str:
    return _out5(TurnMode.REBUTTAL, premises={"explicit": explicit, "implicit": ["Ngầm."]}, target_premise=target,
                 **over)


# ---------------- prompt: v6 khac v5 DUNG cac diem spec ----------------


@pytest.mark.parametrize("burden", [BURDEN, None])
def test_v6_prompt_differs_from_v5_only_in_spec_points(burden):
    ctx = _ctx_t4(burden)
    v5 = "turn_full_v5" if burden else "turn_full_v5_noburden"
    v6 = "turn_full_v6" if burden else "turn_full_v6_noburden"
    s5, u5 = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version=v5)
    s6, u6 = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version=v6)
    assert s6 == s5  # system khong doi
    rule = "premises chỉ được trích từ (các) bài nói MỚI của đội Đề xuất ở mục trên, không lấy từ các lượt trước."
    expected = (u5
                # 1. ledger: tieu de khong goi la "tien de" / khong trung ten truong output
                .replace("Các luận điểm người học đã nêu trước đó:\n",
                         "Những ý người học đã nêu ở các lượt TRƯỚC (chỉ để tham khảo, đừng chép lại):\n")
                # 2. chi dan trich xuat NGAY TRUOC mo ta JSON
                .replace("\n\nTrả về JSON, ĐÚNG thứ tự", "\n\n" + rule + "\n\nTrả về JSON, ĐÚNG thứ tự")
                # 5. rang buoc cuoi bo "cố định"
                .replace("so với cách hiểu cố định ở trên.", "so với cách hiểu ở trên."))
    assert u6 == expected and u6 != u5
    assert "- " + MATCH_T2_EXPLICIT[0] in u6  # ledger van liet ke (gach dau dong)
    assert "so với cách hiểu cố định" not in u6  # NO_RULE_ECHO_RULE (v3) van liet ke 'cách hiểu cố định': khong doi
    assert "tiền đề" not in u6.split("Những ý người học")[1].split("\n")[0]
    assert u6.endswith(tf.constraints_block(ctx, v6))


@pytest.mark.parametrize("mode,turn,history", [
    (TurnMode.OPENING_FIRST, 1, []),  # chua co bai learner
    (TurnMode.REBUTTAL, 4, []),  # khong co bai learner MOI
    (TurnMode.CLOSING, 5, [_sp(3, CON, "Phản bác learner.")]),  # tong ket khong phan tich tien de
])
def test_v6_extraction_rule_only_when_premises_analysed(mode, turn, history):
    ctx = _ctx5(CON if turn != 1 else PRO, turn, history, _ledger_match())
    _, u6 = tf.build_full_prompt(mode, ctx, version="turn_full_v6")
    assert "premises chỉ được trích từ" not in u6


def test_older_versions_keep_fixed_reading_constraint():
    ctx = _ctx_t4()
    for version in ("turn_full_v3", "turn_full_v4", "turn_full_v5"):
        assert "so với cách hiểu cố định ở trên." in tf.constraints_block(ctx, version)


# ---------------- 3. kiem tra chep tien de ----------------


def test_regression_match_001136_turn4_copies_turn2():
    assert tf.premises_reuse_ratio(MATCH_T4_EXPLICIT, MATCH_T2_EXPLICIT) == 1.0 >= tf.PREMISES_REUSED_RATIO
    # chuan hoa: hoa / thuong, dau cau, khoang trang
    variant = [p.upper().rstrip(".") + " " for p in MATCH_T4_EXPLICIT]
    assert tf.premises_reuse_ratio(variant, MATCH_T2_EXPLICIT) == 1.0
    assert tf.premises_reuse_ratio(FRESH_EXPLICIT, MATCH_T2_EXPLICIT) == 0.0
    assert tf.premises_reuse_ratio([], MATCH_T2_EXPLICIT) == 0.0
    # 3/4 = 75% >= 70% -> chep; 2/4 = 50% -> khong
    assert tf.premises_reuse_ratio(MATCH_T2_EXPLICIT[:3] + FRESH_EXPLICIT[:1], MATCH_T2_EXPLICIT) == 0.75
    assert tf.premises_reuse_ratio(MATCH_T2_EXPLICIT[:2] + FRESH_EXPLICIT, MATCH_T2_EXPLICIT) == 0.5


async def test_regression_match_001136_v6_rejects_and_retries_with_feedback():
    fake = FakeLLMClient([_rebuttal(MATCH_T4_EXPLICIT), _rebuttal(FRESH_EXPLICIT, target=FRESH_EXPLICIT[1])])
    result = await tf.FullTurnGeneratorV6(fake, SETTINGS).generate(TurnMode.REBUTTAL, _ctx_t4())
    assert result.text and result.premises["explicit"] == FRESH_EXPLICIT
    assert [(c.success, c.failure_kind) for c in result.calls] == [(False, "premises_reused"), (True, None)]
    assert "premises_reused" in result.calls[0].error
    assert tf.PREMISES_REUSED_ISSUE in result.calls[0].retry_feedback
    assert tf.PREMISES_REUSED_ISSUE in fake.calls[1]["user"] and tf.PREMISES_REUSED_ISSUE not in fake.calls[0]["user"]


async def test_regression_match_001136_v5_accepted_the_copy():
    fake = FakeLLMClient([_rebuttal(MATCH_T4_EXPLICIT)])
    result = await tf.FullTurnGeneratorV5(fake, SETTINGS).generate(TurnMode.REBUTTAL, _ctx_t4())
    assert result.premises["explicit"] == MATCH_T4_EXPLICIT and len(result.calls) == 1  # hanh vi v5 giu nguyen


async def test_v6_premises_reused_on_every_attempt_fails_turn():
    fake = FakeLLMClient([_rebuttal(MATCH_T4_EXPLICIT)] * SETTINGS.turn_max_attempts)
    result = await tf.FullTurnGeneratorV6(fake, SETTINGS).generate(TurnMode.REBUTTAL, _ctx_t4())
    assert result.text is None and result.failure_kind == "premises_reused"
    assert len(result.calls) == SETTINGS.turn_max_attempts


async def test_v6_reuse_check_skipped_without_new_learner_speech():
    # khong co bai learner moi: premises bi ep rong (coerce_analysis), KHONG reject vi chep
    fake = FakeLLMClient([_rebuttal(MATCH_T4_EXPLICIT)])
    result = await tf.FullTurnGeneratorV6(fake, SETTINGS).generate(TurnMode.REBUTTAL, _ctx_t4(history=[]))
    assert result.text and [c.failure_kind for c in result.calls] == [None]


async def test_v6_below_threshold_accepted():
    fake = FakeLLMClient([_rebuttal(MATCH_T2_EXPLICIT[:2] + FRESH_EXPLICIT)])
    result = await tf.FullTurnGeneratorV6(fake, SETTINGS).generate(TurnMode.REBUTTAL, _ctx_t4())
    assert result.text and len(result.calls) == 1


# ---------------- 4. chuan hoa xung ho ----------------


@pytest.mark.parametrize("text,expected,n", [
    # cau that tran 001136 luot 2 / 5
    ("Tôi muốn phản bác nguyên tắc cơ bản rằng điện thoại làm học sinh mất tập trung.",
     "Mình muốn phản bác nguyên tắc cơ bản rằng điện thoại làm học sinh mất tập trung.", 1),
    ("Bạn nói điện thoại làm học sinh mất tập trung trong giờ học, tôi đồng ý rằng một số học sinh có thể lạm dụng.",
     "Bạn nói điện thoại làm học sinh mất tập trung trong giờ học, mình đồng ý rằng một số học sinh có thể lạm dụng.", 1),
    ("Tôi nghĩ vậy, và tôi tin chúng tôi đúng.", "Mình nghĩ vậy, và mình tin chúng mình đúng.", 3),
    ("Mình đồng ý.", "Mình đồng ý.", 0),
])
def test_normalize_first_person_replaces(text, expected, n):
    assert tf.normalize_first_person(text) == (expected, n)


@pytest.mark.parametrize("text", [
    'Bạn nói "tôi không cần điện thoại" nhưng thực tế khác.',  # trich dan ngoac kep
    "Bạn nói “Tôi tự kiểm soát được” — điều đó chưa chắc.",  # ngoac kep cong
    "Học sinh nói « tôi sẽ cất máy » nhưng không làm.",  # ngoac «»
    "Cấm toàn phần không giúp tôi luyện tính tự giác.",  # tu ghep "tôi luyện"
    "Không ai muốn làm tôi tớ cho thiết bị.",  # tu ghep "tôi tớ"
    "Ăn tối xong mới dùng điện thoại.",  # "tối" khong phai "tôi"
])
def test_normalize_first_person_does_not_replace(text):
    assert tf.normalize_first_person(text) == (text, 0)


def test_normalize_first_person_mixed_quote_and_pronoun():
    text = 'Tôi trích lời bạn: "tôi cần điện thoại", nhưng tôi không đồng ý.'
    assert tf.normalize_first_person(text) == ('Mình trích lời bạn: "tôi cần điện thoại", nhưng mình không đồng ý.', 2)


async def test_v6_replaces_toi_after_accept_and_logs_count():
    speech = "Tôi phản đối. " + " ".join(["từ"] * 380) + ' Bạn nói "tôi cần máy", nhưng tôi không thấy vậy.'
    fake = FakeLLMClient([_rebuttal(FRESH_EXPLICIT, speech=speech)])
    result = await tf.FullTurnGeneratorV6(fake, SETTINGS).generate(TurnMode.REBUTTAL, _ctx_t4())
    assert result.text.startswith("Mình phản đối.") and result.text.endswith('"tôi cần máy", nhưng mình không thấy vậy.')
    checks = result.calls[-1].speech_checks
    assert checks["toi_replaced"] == 2
    assert len(checks["toi_pronoun"]) == 2  # log truoc khi thay: van thay model dung "tôi"


async def test_v5_does_not_replace_toi():
    speech = "Tôi phản đối. " + " ".join(["từ"] * 380)
    fake = FakeLLMClient([_rebuttal(FRESH_EXPLICIT, speech=speech)])
    result = await tf.FullTurnGeneratorV5(fake, SETTINGS).generate(TurnMode.REBUTTAL, _ctx_t4())
    assert result.text.startswith("Tôi phản đối.") and "toi_replaced" not in result.calls[-1].speech_checks


# ---------------- 6. so khong co "Giả sử" ----------------

T2_CENTURY = "Cuối cùng, cấm toàn thời gian ngăn học sinh rèn luyện kỹ năng số cần thiết cho thế kỷ 21."
T4_CENTURY = ("Cuối cùng, cấm toàn thời gian còn làm giảm khả năng học sinh thực hành quản lý an toàn trên thiết bị cá "
              "nhân, một kỹ năng thiết yếu cho thế kỷ 21.")


@pytest.mark.parametrize("sentence", [
    T2_CENTURY, T4_CENTURY, "Đây là kỹ năng của thế kỷ XXI.", "Lý do thứ 2 là an toàn.", "Học sinh lớp 12 cần ôn thi.",
])
def test_v6_number_check_ignores_non_statistics(sentence):
    assert tf.speech_checks_v5(sentence, [], ignore_non_stat_numbers=True)["numbers_without_gia_su"] == []
    if "XXI" not in sentence:  # so La Ma: v5 von khong bat (khong co chu so)
        assert tf.speech_checks_v5(sentence, [])["numbers_without_gia_su"] == [sentence]  # v5: van bat (khong doi)


@pytest.mark.parametrize("sentence", [
    "80% học sinh dùng điện thoại trong giờ.", "Học sinh lớp 12 dành 3 giờ mỗi ngày cho điện thoại.",
])
def test_v6_number_check_still_flags_statistics(sentence):
    assert tf.speech_checks_v5(sentence, [], ignore_non_stat_numbers=True)["numbers_without_gia_su"] == [sentence]


async def test_v6_generator_logs_with_new_number_rule():
    speech = T2_CENTURY + " " + " ".join(["từ"] * 380)
    fake = FakeLLMClient([_rebuttal(FRESH_EXPLICIT, speech=speech)])
    result = await tf.FullTurnGeneratorV6(fake, SETTINGS).generate(TurnMode.REBUTTAL, _ctx_t4())
    assert result.calls[-1].speech_checks["numbers_without_gia_su"] == []


# ---------------- nhan / mac dinh / API ----------------


async def test_v6_generator_version_label_depends_on_burden():
    for burden, label in ((BURDEN, "turn_full_v6"), (None, "turn_full_v6_noburden")):
        fake = FakeLLMClient([_rebuttal(FRESH_EXPLICIT)])
        result = await tf.FullTurnGeneratorV6(fake, SETTINGS).generate(TurnMode.REBUTTAL, _ctx_t4(burden))
        assert result.generator_version == label and result.calls[0].prompt_version == label


async def test_v6_via_api_rejects_copied_premises(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    t2 = json.loads(_out5(TurnMode.OPENING_REPLY, speech=None))
    t2["premises"] = {"explicit": MATCH_T2_EXPLICIT, "implicit": ["Ngầm."]}
    t2["speech_text"] = "Tôi xin mở đầu. " + " ".join(["từ"] * 395)
    fake_llm.responses = [json.dumps(t2, ensure_ascii=False), _rebuttal(MATCH_T4_EXPLICIT),
                          _rebuttal(FRESH_EXPLICIT, target=FRESH_EXPLICIT[1])]
    r2 = await _turn(client, ext, 2, [_learner(1)])
    assert r2.status_code == 201 and r2.json()["speech_text"].startswith("Mình xin mở đầu.")
    assert (await _turn(client, ext, 4, [_learner(3, LEARNER_T3)])).status_code == 201

    planner = [c for c in fake_llm.calls if "user" in c]
    assert "Những ý người học đã nêu ở các lượt TRƯỚC (chỉ để tham khảo, đừng chép lại):\n- " \
           + MATCH_T2_EXPLICIT[0] in planner[1]["user"]
    sid = await _session_id(db_session, ext)
    turns = (await db_session.scalars(select(OpponentTurn).where(OpponentTurn.session_id == sid)
                                      .order_by(OpponentTurn.turn_index))).all()
    assert [t.generator_version for t in turns] == ["turn_full_v6_noburden"] * 2
    assert turns[1].premises["explicit"] == FRESH_EXPLICIT
    rows = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN)
        .order_by(OpponentLLMCall.created_at))).all()
    assert [(r.success, r.failure_kind) for r in rows] == [(True, None), (False, "premises_reused"), (True, None)]
    assert rows[0].speech_checks["toi_replaced"] == 1
