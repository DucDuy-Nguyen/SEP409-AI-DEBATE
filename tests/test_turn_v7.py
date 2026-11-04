"""
turn_full_v7 (dev log muc 3.2) = v6 + 3 cap do doi thu. Cac khoi prompt duoi day chep NGUYEN VAN spec (khong import tu
turn_full.py) de test bat duoc sai chu. LLM gia.
"""
import json

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent import match_format as mf
from app.opponent import turn_full as tf
from app.opponent.json_repair import repair_split_array
from app.opponent.match_format import TurnMode
from app.opponent.models import (
    DebateSide,
    LLMCallPurpose,
    OpponentDifficulty,
    OpponentLLMCall,
    OpponentTurn,
)
from scripts import try_match as tm
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, FakeStanceReviewer, SchemaRejected
from tests.test_turn_full import _ctx, _sp
from tests.test_turn_v5 import BURDEN, _out5
from tests.test_turns_api import MOTION, _learner, _session_id, _turn

PRO, CON = DebateSide.PRO, DebateSide.CON
EASY, MEDIUM, HARD = OpponentDifficulty.EASY, OpponentDifficulty.MEDIUM, OpponentDifficulty.HARD
LEVELS = (EASY, MEDIUM, HARD)
SETTINGS = Settings(_env_file=None)
OFF = Settings(_env_file=None, turn_difficulty_enabled=False)
LEARNER = "Đề xuất"  # AI con -> learner la doi Đề xuất

LABEL = {EASY: "DỄ", MEDIUM: "TRUNG BÌNH", HARD: "KHÓ"}
COMMON_LINE = ("Độ khó của trận: {}. Độ khó chỉ quyết định cách bạn chọn điểm tấn công và mức độ bạn đáp lại; nó KHÔNG "
               "làm thay đổi lập trường: bạn vẫn bảo vệ phe của mình đến hết trận ở mọi độ khó.")
TARGET_BLOCK = {
    EASY: ("target_premise: một tiền đề TƯỜNG MINH trong bài của đội Đề xuất. Chỉ phản bác ĐÚNG MỘT ý chính, không cần "
           "đáp các ý còn lại. Dùng câu ngắn, từ ngữ đơn giản, một ví dụ dễ hình dung. Có thể ghi nhận ngắn một ý đúng của "
           "đối phương rồi nêu rõ vì sao phe bạn vẫn đúng."),
    MEDIUM: ("target_premise: một tiền đề TƯỜNG MINH vừa nền tảng (gần gốc lập luận) vừa được chứng minh chưa đầy đủ. "
             "Phản bác ý chính đó và, nếu còn chỗ, thêm một ý liên quan. Lập luận chặt chẽ ở mức khá, có cơ chế rõ ràng."),
    HARD: ("target_premise: có thể là tiền đề NGẦM; chọn tiền đề nền tảng mà nếu sai thì lập luận của đối phương đổ theo. "
           "Đáp ÍT NHẤT hai ý chính của đội Đề xuất và chỉ ra ít nhất một ý họ chưa chứng minh hoặc bỏ ngỏ. Chủ động chặn "
           "trước phản biện sắp tới của họ bằng mục 'Những phản biện bạn đã dự đoán'. So sánh mức độ tác động của hai bên "
           "(quy mô, ai bị ảnh hưởng, thời gian)."),
}
OPENING_FIRST_EXTRA = {
    EASY: "Giọng đơn giản, câu ngắn, mỗi luận điểm một ví dụ dễ hình dung.",
    HARD: ("Chặn trước một đến hai phản biện phổ biến dựa trên mục 'Những phản biện bạn đã dự đoán', và kết bằng một câu "
           "so sánh mức độ tác động."),
}
CLOSING_BLOCK = {
    EASY: "Nêu 2 điểm tranh chấp chính.",
    MEDIUM: "Nêu 2 đến 3 điểm tranh chấp chính.",
    HARD: ("Nêu 3 điểm tranh chấp chính; với mỗi điểm so sánh quy mô, xác suất và thời gian tác động; đáp lại điểm mạnh "
           "nhất của đội Đề xuất và chỉ ra điều họ chưa chứng minh được."),
}
ANTICIPATED_TITLE = "Những phản biện bạn đã dự đoán từ phía đội Đề xuất (đã chuẩn bị sẵn cách đáp):"
POINTS_RULE = ("points_addressed chỉ lấy từ premises.explicit của (các) bài nói MỚI, đúng nguyên văn mục đã trích; rỗng "
               "nếu không có bài mới.")
ANY_BLOCKS = {**{("target", k): v for k, v in TARGET_BLOCK.items()},
              **{("first", k): v for k, v in OPENING_FIRST_EXTRA.items()},
              **{("closing", k): v for k, v in CLOSING_BLOCK.items()}}

EXPLICIT = ["Điện thoại làm học sinh mất tập trung trong giờ học.", "Trường đã có phòng máy tính và thư viện để tra cứu."]
IMPLICIT = ["Học sinh không thể tự kiểm soát việc dùng điện thoại."]
PREMISES = {"explicit": EXPLICIT, "implicit": IMPLICIT}
NEW_SPEECH = "Bài nói mới của người học."


def _case(mode: TurnMode, level=MEDIUM, burden=BURDEN):
    """(mode, context) dung so luot THAT trong format 6 luot: AI pro chi con luot 1, 3, 6; AI con 2, 4, 5."""
    ai_side, turn, history = {
        TurnMode.OPENING_FIRST: (PRO, 1, []),
        TurnMode.OPENING_REPLY: (CON, 2, [_sp(1, CON, NEW_SPEECH)]),
        TurnMode.REBUTTAL: (CON, 4, [_sp(3, CON, NEW_SPEECH)]),
        TurnMode.CLOSING: (CON, 5, [_sp(4, CON, "Bài AI lượt 4.")]),
    }[mode]
    ctx = _ctx(ai_side, turn, history, difficulty=level)
    ctx.ai_burden = burden
    return ctx


def _closing_with_new(level=MEDIUM):
    """AI pro luot 6: closing CO bai learner moi (luot 5)."""
    ctx = _ctx(PRO, 6, [_sp(5, PRO, NEW_SPEECH)], difficulty=level)
    ctx.ai_burden = BURDEN
    return ctx


def _out7(mode=TurnMode.REBUTTAL, target=EXPLICIT[0], points=(EXPLICIT[0],), premises=PREMISES, **over) -> str:
    return _out5(mode, premises=premises, target_premise=target, points_addressed=list(points), **over)


async def _run(responses, mode=TurnMode.REBUTTAL, ctx=None, level=MEDIUM, reviewer=None, settings=SETTINGS):
    fake = FakeLLMClient(list(responses))
    gen = tf.FullTurnGeneratorV7(fake, settings, reviewer)
    return await gen.generate(mode, ctx or _case(mode, level)), fake


# ---------------- 1. prompt: mode x cap ----------------


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("mode", list(TurnMode))
def test_common_line_in_every_mode_only_own_label(mode, level):
    _, user = tf.build_full_prompt(mode, _case(mode, level), version="turn_full_v7")
    assert COMMON_LINE.format(LABEL[level]) in user
    assert user.count("Độ khó của trận:") == 1


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("mode", [TurnMode.OPENING_REPLY, TurnMode.REBUTTAL])
def test_target_modes_use_own_block_replacing_old_rule(mode, level):
    _, user = tf.build_full_prompt(mode, _case(mode, level), version="turn_full_v7")
    assert TARGET_BLOCK[level] in user
    for key, block in ANY_BLOCKS.items():
        if key != ("target", level):
            assert block not in user, key
    for old in tf.TARGET_RULE.values():
        assert old not in user
    assert "Chọn target_premise (" not in user
    assert "Không tấn công lại tiền đề đã tấn công, trừ khi người học chưa đáp lại nó." in user


@pytest.mark.parametrize("level", LEVELS)
def test_opening_first_block(level):
    ctx = _case(TurnMode.OPENING_FIRST, level)
    _, user = tf.build_full_prompt(TurnMode.OPENING_FIRST, ctx, version="turn_full_v7")
    base = "Trình bày phần mở màn: giới thiệu cách hiểu kiến nghị và các luận điểm trong case của bạn. Chưa có gì để phản bác."
    extra = OPENING_FIRST_EXTRA.get(level)
    # bo sung vao chi dan hien co; trung binh khong them gi
    assert f"Nhiệm vụ lượt này: {base}{' ' + extra if extra else ''}\n" in user
    for key, block in ANY_BLOCKS.items():
        if key != ("first", level):
            assert block not in user, key


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("ctx_of", [lambda lv: _case(TurnMode.CLOSING, lv), _closing_with_new], ids=["no_new", "has_new"])
def test_closing_block_replaces_point_count_keeps_no_new_arguments(level, ctx_of):
    _, user = tf.build_full_prompt(TurnMode.CLOSING, ctx_of(level), version="turn_full_v7")
    learner = "Đề xuất" if ctx_of(level).ai_side == CON else "Phản đối"
    assert CLOSING_BLOCK[level].replace("đội Đề xuất", f"đội {learner}") in user
    for key, block in ANY_BLOCKS.items():
        if key != ("closing", level):
            assert block.replace("đội Đề xuất", f"đội {learner}") not in user, key
    assert "nêu 2–3 điểm" not in user
    assert "KHÔNG đưa lập luận mới, KHÔNG liệt kê lại toàn bộ luận điểm." in user
    # moi cap van yeu cau so sanh + dap lai dung 1 lan (KHO: nam trong khoi rieng)
    assert user.count("đáp lại điểm mạnh nhất") == 1


def test_blocks_format_learner_side_when_ai_is_pro():
    ctx = _ctx(PRO, 3, [_sp(2, PRO, NEW_SPEECH)], difficulty=HARD)
    _, user = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version="turn_full_v7")
    assert TARGET_BLOCK[HARD].replace("đội Đề xuất", "đội Phản đối") in user and "{learner}" not in user


# ---------------- muc phan bien du doan ----------------


@pytest.mark.parametrize("mode", [TurnMode.OPENING_FIRST, TurnMode.OPENING_REPLY, TurnMode.REBUTTAL])
def test_anticipated_only_hard_three_modes_before_task(mode):
    ctx = _case(mode, HARD)
    learner = tf.SIDE_LABEL[ctx.learner_side]
    _, user = tf.build_full_prompt(mode, ctx, version="turn_full_v7")
    assert ANTICIPATED_TITLE.replace("Đề xuất", learner) in user
    for a in VALID_CASE_FILE["anticipated_opponent_arguments"]:
        assert a["learner_claim"] in user and a["planned_response"] in user
    assert user.index("Những phản biện bạn đã dự đoán từ phía") < user.index("Nhiệm vụ lượt này:")
    if mode != TurnMode.OPENING_FIRST:
        assert user.index(NEW_SPEECH) < user.index("Những phản biện bạn đã dự đoán từ phía")  # sau bai learner moi
    assert user.endswith(tf.constraints_block(ctx, "turn_full_v7"))  # khoi rang buoc van cuoi cung


@pytest.mark.parametrize("mode,level", [(m, lv) for m in TurnMode for lv in (EASY, MEDIUM)] + [(TurnMode.CLOSING, HARD)])
def test_anticipated_absent_otherwise(mode, level):
    _, user = tf.build_full_prompt(mode, _case(mode, level), version="turn_full_v7")
    assert "Những phản biện bạn đã dự đoán từ phía" not in user
    for a in VALID_CASE_FILE["anticipated_opponent_arguments"]:
        assert a["learner_claim"] not in user and a["planned_response"] not in user


def test_anticipated_absent_in_hard_closing_with_new_speech():
    _, user = tf.build_full_prompt(TurnMode.CLOSING, _closing_with_new(HARD), version="turn_full_v7")
    assert "Những phản biện bạn đã dự đoán từ phía" not in user


def test_anticipated_skipped_when_case_file_has_none():
    ctx = _case(TurnMode.REBUTTAL, HARD)
    ctx.case_file = {k: v for k, v in VALID_CASE_FILE.items() if k != "anticipated_opponent_arguments"}
    _, user = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version="turn_full_v7")
    assert "Những phản biện bạn đã dự đoán từ phía" not in user


@pytest.mark.parametrize("level", LEVELS)
def test_v6_never_gets_v7_blocks(level):
    _, user = tf.build_full_prompt(TurnMode.REBUTTAL, _case(TurnMode.REBUTTAL, level), version="turn_full_v6")
    assert tf.TARGET_RULE[level] in user and "Độ khó của trận:" not in user and "points_addressed" not in user
    assert "Những phản biện bạn đã dự đoán" not in user


# ---------------- 2. schema + points_addressed ----------------


def test_schema_field_order_and_nguyen_van_rule():
    schema = tf.build_response_schema(TurnMode.REBUTTAL, True, "turn_full_v7")
    assert list(schema["properties"]) == ["premises", "target_premise", "points_addressed", "ai_points", "speech_text"]
    assert schema["required"] == list(schema["properties"]) and schema["additionalProperties"] is False
    assert "maxItems" not in schema["properties"]["points_addressed"]
    _, user = tf.build_full_prompt(TurnMode.REBUTTAL, _case(TurnMode.REBUTTAL), version="turn_full_v7")
    assert POINTS_RULE in user
    assert user.index("- target_premise:") < user.index("- points_addressed:") < user.index("- ai_points:")


@pytest.mark.parametrize("mode,has_new", [(TurnMode.OPENING_FIRST, False), (TurnMode.CLOSING, True),
                                          (TurnMode.CLOSING, False), (TurnMode.REBUTTAL, False)])
def test_schema_forces_points_empty_when_no_analysis(mode, has_new):
    points = tf.build_response_schema(mode, has_new, "turn_full_v7")["properties"]["points_addressed"]
    assert points["maxItems"] == 0


@pytest.mark.parametrize("mode,ctx", [
    (TurnMode.OPENING_FIRST, _case(TurnMode.OPENING_FIRST)),
    (TurnMode.CLOSING, _case(TurnMode.CLOSING)),  # AI con luot 5: khong co bai moi
    (TurnMode.CLOSING, _closing_with_new()),  # co bai moi nhung tong ket khong phan tich
    (TurnMode.REBUTTAL, _ctx(CON, 4, [])),  # khong co bai learner moi
], ids=["opening_first", "closing_con_t5", "closing_pro_t6", "rebuttal_no_new"])
async def test_points_coerced_empty_when_no_new_speech(mode, ctx):
    target = EXPLICIT[0] if tf.needs_target(mode) else None
    result, _ = await _run([_out7(mode, target=target, points=["Model trả thừa."], premises={"explicit": [], "implicit": []})],
                           mode, ctx)
    assert result.text and result.points_addressed == []
    assert result.calls[-1].speech_checks[tf.ANALYSIS_COERCED]["points_addressed"] == 1


async def test_points_kept_and_counted():
    result, _ = await _run([_out7(points=EXPLICIT)], level=HARD)
    assert result.points_addressed == EXPLICIT
    assert result.calls[-1].speech_checks["points_addressed_count"] == 2


@pytest.mark.parametrize("points,count", [
    ([EXPLICIT[0].upper().rstrip(".") + "  "], 1),  # chuan hoa
    ([EXPLICIT[0], EXPLICIT[0]], 1),  # lap lai khong tinh 2
    (["Một ý không có trong danh sách trích."], 0),
    ([IMPLICIT[0]], 0),  # implicit khong tinh
    ([], 0),
])
async def test_count_only_matched_explicit(points, count):
    result, _ = await _run([_out7(points=points)])
    assert result.calls[-1].speech_checks["points_addressed_count"] == count
    assert result.points_addressed == points  # luu nguyen output, count moi la so da khop


def _rejected_array(**over) -> str:
    """Dang "mang tach" (json_repair, muc 2.12) co them points_addressed."""
    fields = {"target_premise": EXPLICIT[0], "points_addressed": [EXPLICIT[0]], "ai_points": ["Ý một.", "Ý hai."],
              **over}
    items = [{"premises": PREMISES}]
    for key, value in fields.items():
        items += [key, ":", value]
    words = " ".join(["từ"] * 160)
    items += ["speech_text", ":", words, words]
    return json.dumps(items, ensure_ascii=False)


def test_json_repair_knows_points_addressed_key():
    data, info = repair_split_array(_rejected_array(), tf.FIELD_ORDER_V7)
    assert data["points_addressed"] == [EXPLICIT[0]] and "points_addressed" in info["keys"]
    assert repair_split_array(_rejected_array(), tf.FIELD_ORDER_V5) is None  # danh sach cu: key la -> khong doan


async def test_split_array_with_new_field_repaired_without_new_call():
    result, fake = await _run([SchemaRejected(_rejected_array())])
    assert result.text and len(fake.calls) == 1 and result.points_addressed == [EXPLICIT[0]]
    assert result.calls[0].key_repairs["event"] == "array_repaired"


async def test_split_array_empty_points_value_repaired():
    result, _ = await _run([SchemaRejected(_rejected_array(points_addressed=[]))])
    assert result.text and result.points_addressed == []


async def test_points_key_typo_repaired():
    raw = json.loads(_out7())
    raw["points_addresed"] = raw.pop("points_addressed")
    result, fake = await _run([SchemaRejected(json.dumps(raw, ensure_ascii=False))])
    assert result.text and len(fake.calls) == 1 and result.points_addressed == [EXPLICIT[0]]


async def test_missing_points_addressed_is_schema_error_with_feedback():
    raw = json.loads(_out7())
    del raw["points_addressed"]
    result, fake = await _run([json.dumps(raw, ensure_ascii=False), _out7()])
    assert [c.failure_kind for c in result.calls] == ["schema_validation", None]
    assert "`points_addressed`: thiếu trường bắt buộc" in fake.calls[1]["user"]


def test_v6_still_treats_points_addressed_as_unknown():
    data = {"learner_claims": [], "premises": PREMISES, "target_premise": "x", "ai_points": ["a", "b"], "speech_text": "s",
            "points_addressed": []}
    assert tf._key_diffs(data, "turn_full_v6")[0]["unknown"] == ["points_addressed"]
    assert tf._key_diffs(data, "turn_full_v7") == []


# ---------------- 3. validator ----------------


@pytest.mark.parametrize("target,kind", [
    (EXPLICIT[0], "explicit"),
    (IMPLICIT[0], "implicit"),
    ("  ĐIỆN THOẠI làm học sinh mất tập trung, trong giờ học!!! ", "explicit"),  # hoa thuong, dau cau, khoang trang
    ("Điện thoại làm học sinh mất tập trung trong giờ", "explicit"),  # khop mo
    ("Học sinh không tự kiểm soát việc dùng điện thoại", "implicit"),  # khop mo
    ("Trường học nên mở thêm câu lạc bộ thể thao.", None),
    ("", None),
    ("...", None),
])
def test_premise_kind(target, kind):
    assert tf.premise_kind(target, tf.Premises(**PREMISES)) == kind


def test_premise_kind_threshold_is_085():
    base = "a" * 100
    premises = tf.Premises(explicit=[base], implicit=[])
    assert tf.premise_kind("a" * 74, premises) == "explicit"  # ratio 148/174 = 0.8506
    assert tf.premise_kind("a" * 73, premises) is None  # ratio 146/173 = 0.8439


def test_premise_kind_same_item_in_both_lists_counts_explicit():
    assert tf.premise_kind("Cùng một ý.", tf.Premises(explicit=["Cùng một ý."], implicit=["Cùng một ý."])) == "explicit"


def test_premise_kind_picks_closest_list():
    premises = tf.Premises(explicit=["Học sinh không thể tự kiểm soát việc dùng máy."], implicit=[IMPLICIT[0]])
    assert tf.premise_kind(IMPLICIT[0], premises) == "implicit"


@pytest.mark.parametrize("level", LEVELS)
async def test_target_not_in_premises_retried_with_feedback(level):
    result, fake = await _run([_out7(target="Một tiền đề model tự nghĩ ra, không hề được trích."), _out7()], level=level)
    assert result.text and [(c.success, c.failure_kind) for c in result.calls] == [
        (False, "target_not_in_premises"), (True, None)]
    issue = tf.TARGET_NOT_IN_PREMISES_ISSUE if level == HARD else tf.TARGET_EXPLICIT_ONLY_ISSUE
    assert issue in result.calls[0].retry_feedback
    assert issue in fake.calls[1]["user"] and issue not in fake.calls[0]["user"]
    assert fake.calls[1]["user"].endswith(tf.constraints_block(_case(TurnMode.REBUTTAL, level), "turn_full_v7"))


@pytest.mark.parametrize("level", [EASY, MEDIUM])
@pytest.mark.parametrize("mode", [TurnMode.OPENING_REPLY, TurnMode.REBUTTAL])
async def test_easy_medium_implicit_retried(mode, level):
    result, fake = await _run([_out7(mode, target=IMPLICIT[0]), _out7(mode)], mode, level=level)
    assert [(c.success, c.failure_kind) for c in result.calls] == [(False, "target_level_mismatch"), (True, None)]
    assert tf.TARGET_LEVEL_MISMATCH_ISSUE in result.calls[0].retry_feedback
    assert tf.TARGET_LEVEL_MISMATCH_ISSUE in fake.calls[1]["user"]
    assert result.target_premise == EXPLICIT[0]


@pytest.mark.parametrize("target", [IMPLICIT[0], EXPLICIT[1]])
async def test_hard_accepts_implicit_and_explicit(target):
    result, fake = await _run([_out7(target=target, points=EXPLICIT)], level=HARD)
    assert result.target_premise == target and len(fake.calls) == 1 and result.calls[0].failure_kind is None


@pytest.mark.parametrize("kind,responses", [
    ("target_not_in_premises", _out7(target="Tiền đề khác hẳn, không được trích ra.")),
    ("target_level_mismatch", _out7(target=IMPLICIT[0])),
])
async def test_target_failure_counts_as_content_attempts_then_fails(kind, responses):
    result, fake = await _run([responses] * SETTINGS.turn_max_attempts, level=MEDIUM)
    assert result.text is None and result.failure_kind == kind
    assert len(fake.calls) == SETTINGS.turn_max_attempts
    assert [c.failure_kind for c in result.calls] == [kind] * SETTINGS.turn_max_attempts


async def test_length_candidate_still_accepted_after_target_failures():
    """Het luot: con ban hop le chi sai do dai -> chap nhan (nhu cac loi noi dung khac, _give_up)."""
    settings = Settings(_env_file=None, turn_max_attempts=2)
    short = _out7(n_words=50)  # ngoai [0,5x; 1,5x] -> loi mem, thu lai
    result, _ = await _run([short, _out7(target=IMPLICIT[0])], settings=settings)
    assert result.text and word_count_of(result) == 50
    assert result.calls[0].speech_checks[tf.LENGTH_SOFT_ACCEPT]["word_count"] == 50


def word_count_of(result) -> int:
    return mf.word_count(result.text)


async def test_rejected_target_does_not_call_reviewer():
    reviewer = FakeStanceReviewer("phan_doi_kien_nghi")
    result, _ = await _run([_out7(target=IMPLICIT[0]), _out7()], reviewer=reviewer)
    assert result.text and len(reviewer.calls) == 1  # chi ban hop le


@pytest.mark.parametrize("mode,ctx", [(TurnMode.OPENING_FIRST, _case(TurnMode.OPENING_FIRST)),
                                      (TurnMode.CLOSING, _closing_with_new(EASY))], ids=["opening_first", "closing"])
async def test_validator_not_applied_without_needs_target(mode, ctx):
    result, fake = await _run([_out5(mode, points_addressed=[])], mode, ctx)
    assert result.text and len(fake.calls) == 1 and result.target_premise is None
    assert "points_addressed_count" not in result.calls[0].speech_checks


async def test_validator_skipped_when_no_new_speech_no_premises_to_check():
    ctx = _ctx(CON, 4, [], difficulty=EASY)
    empty = {"explicit": [], "implicit": []}
    result, fake = await _run([_out7(target="Bất kỳ.", points=[], premises=empty)], ctx=ctx)
    assert result.text and len(fake.calls) == 1


@pytest.mark.parametrize("level,points,flag", [
    (EASY, EXPLICIT[:1], False), (EASY, [], True), (EASY, EXPLICIT, True),  # de: dung 1
    (HARD, EXPLICIT, False), (HARD, EXPLICIT[:1], True), (HARD, [], True),  # kho: >= 2
    (MEDIUM, [], False), (MEDIUM, EXPLICIT[:1], False), (MEDIUM, EXPLICIT, False),  # trung binh: khong ky vong
])
async def test_points_below_expected_only_logged(level, points, flag):
    result, fake = await _run([_out7(points=points)], level=level)
    assert result.text and len(fake.calls) == 1  # KHONG reject
    assert result.calls[0].speech_checks["points_below_expected"] is flag


# ---------------- 4. co cau hinh + nhan ----------------


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("burden,v6,off", [(BURDEN, "turn_full_v6", "turn_full_v7_nodifficulty"),
                                           (None, "turn_full_v6_noburden", "turn_full_v7_nodifficulty_noburden")])
@pytest.mark.parametrize("mode", list(TurnMode))
def test_flag_off_prompt_and_schema_identical_to_v6(mode, burden, v6, off, level):
    ctx = _case(mode, level, burden)
    assert tf.build_full_prompt(mode, ctx, version=off) == tf.build_full_prompt(mode, ctx, version=v6)
    assert tf.build_full_prompt(mode, ctx, "Phản hồi.", off) == tf.build_full_prompt(mode, ctx, "Phản hồi.", v6)
    for has_new in (True, False):
        a = tf.build_response_schema(mode, has_new, off)
        assert json.dumps(a, ensure_ascii=False) == json.dumps(tf.build_response_schema(mode, has_new, v6), ensure_ascii=False)


@pytest.mark.parametrize("level", LEVELS)
async def test_flag_off_generator_sends_same_as_v6_no_validator(level):
    # target ngoai premises: v6 chap nhan -> tat co cung phai chap nhan
    out = _out5(TurnMode.REBUTTAL, premises=PREMISES, target_premise="Không có trong premises.")
    ctx = _case(TurnMode.REBUTTAL, level)
    fake6, fake7 = FakeLLMClient([out]), FakeLLMClient([out])
    r6 = await tf.FullTurnGeneratorV6(fake6, SETTINGS).generate(TurnMode.REBUTTAL, ctx)
    r7 = await tf.FullTurnGeneratorV7(fake7, OFF).generate(TurnMode.REBUTTAL, ctx)
    assert fake7.calls == fake6.calls
    assert r7.text == r6.text and r7.points_addressed is None and r7.generator_version == "turn_full_v7_nodifficulty"
    assert "points_addressed_count" not in r7.calls[0].speech_checks


@pytest.mark.parametrize("settings,burden,label", [
    (SETTINGS, BURDEN, "turn_full_v7"), (SETTINGS, None, "turn_full_v7_noburden"),
    (OFF, BURDEN, "turn_full_v7_nodifficulty"), (OFF, None, "turn_full_v7_nodifficulty_noburden"),
])
async def test_labels(settings, burden, label):
    ctx = _case(TurnMode.REBUTTAL, burden=burden)
    result, _ = await _run([_out7()], ctx=ctx, settings=settings)
    assert result.generator_version == label and result.calls[0].prompt_version == label
    assert len(label) <= 50  # cot generator_version / prompt_version
    # burden theo dung quy tac cu
    assert (BURDEN in result.calls[0].system_prompt) is (burden is not None)


def test_new_failure_kinds_fit_column():
    assert all(len(k) <= 30 for k in ("target_not_in_premises", "target_level_mismatch"))


def test_defaults():
    assert SETTINGS.turn_generator_version == "turn_full_v7" and SETTINGS.turn_difficulty_enabled is True


def test_v6_behaviors_kept_in_v7():
    ctx = _case(TurnMode.REBUTTAL)
    assert tf.is_v6("turn_full_v7") and tf.is_v5("turn_full_v7") and tf.uses_burden("turn_full_v7")
    assert not tf.uses_burden("turn_full_v7_noburden") and not tf.is_v7_difficulty("turn_full_v7_nodifficulty")
    assert tf.constraints_block(ctx, "turn_full_v7") == tf.constraints_block(ctx, "turn_full_v6")


async def test_v7_keeps_premises_reused_and_toi_replacement():
    ctx = _case(TurnMode.REBUTTAL)
    ctx.ledger.learner_premises = list(EXPLICIT)
    fresh = {"explicit": ["Một tiền đề mới hoàn toàn của bài này."], "implicit": []}
    speech = "Tôi phản đối. " + " ".join(["từ"] * 320)
    result, _ = await _run([_out7(), _out7(target=fresh["explicit"][0], points=fresh["explicit"], premises=fresh, speech=speech)],
                           ctx=ctx)
    assert [c.failure_kind for c in result.calls] == ["premises_reused", None]
    assert result.text.startswith("Mình phản đối.")


# ---------------- do kho KHONG doi tham so ----------------


@pytest.mark.parametrize("mode", list(TurnMode))
async def test_llm_params_and_length_do_not_depend_on_difficulty(mode):
    seen = []
    for level in LEVELS:
        ctx = _case(mode, level)
        target = EXPLICIT[0] if tf.needs_target(mode) else None
        premises = PREMISES if tf.analyzes_premises(mode, bool(tf.new_learner_speeches(ctx))) else {"explicit": [], "implicit": []}
        result, fake = await _run([_out7(mode, target=target, points=[], premises=premises)], mode, ctx)
        call = fake.calls[0]
        seen.append((call["temperature"], call["max_tokens"], call["reasoning_effort"], ctx.target_words,
                     result.temperature, tf.word_range(ctx.target_words), tf.accept_range(ctx.target_words)))
    assert seen[0] == seen[1] == seen[2]
    assert seen[0][:3] == (SETTINGS.turn_temperature, SETTINGS.turn_max_tokens, SETTINGS.turn_reasoning_effort)


@pytest.mark.parametrize("mode", list(TurnMode))
def test_system_prompt_constraints_and_schema_do_not_depend_on_difficulty(mode):
    ctxs = [_case(mode, level) for level in LEVELS]
    systems = {tf.build_full_prompt(mode, c, version="turn_full_v7")[0] for c in ctxs}
    constraints = {tf.constraints_block(c, "turn_full_v7") for c in ctxs}
    assert len(systems) == 1 and len(constraints) == 1
    # lap truong: rang buoc phe van con o moi cap
    assert "và phải bảo vệ phe này đến hết trận." in constraints.pop()


# ---------------- qua API ----------------


async def _session(client, fake_llm, fake_reviewer, ai_side="con", difficulty="medium") -> str:
    from tests.conftest import make_case_file
    import uuid

    ext = f"main-{uuid.uuid4()}"
    fake_llm.responses = [json.dumps(make_case_file(2 if difficulty == "easy" else 3), ensure_ascii=False)]
    fake_reviewer.default_position = "ung_ho_kien_nghi" if ai_side == "pro" else "phan_doi_kien_nghi"
    resp = await client.post("/opponent/sessions", json={
        "external_session_id": ext, "motion": MOTION, "ai_side": ai_side,
        "learner_side": "con" if ai_side == "pro" else "pro", "difficulty": difficulty,
    })
    assert resp.status_code == 201 and resp.json()["status"] == "ready", resp.text
    fake_llm.calls.clear()
    return ext


@pytest.mark.parametrize("difficulty,label", [("easy", "DỄ"), ("medium", "TRUNG BÌNH"), ("hard", "KHÓ")])
async def test_api_uses_session_difficulty_and_stores_points(client, db_session, fake_llm, fake_reviewer, difficulty, label):
    ext = await _session(client, fake_llm, fake_reviewer, difficulty=difficulty)
    fake_llm.responses = [_out7(TurnMode.OPENING_REPLY, points=EXPLICIT[:1])]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201, resp.text
    assert set(resp.json()) == {"turn_index", "round_type", "mode", "speech_text"}  # API khong doi
    prompt = next(c for c in fake_llm.calls if "user" in c)["user"]
    assert f"Độ khó của trận: {label}." in prompt
    sid = await _session_id(db_session, ext)
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))
    assert turn.points_addressed == EXPLICIT[:1] and turn.generator_version == "turn_full_v7_noburden"
    log = await db_session.scalar(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN))
    assert log.speech_checks["points_addressed_count"] == 1


async def test_api_replay_is_idempotent_no_new_llm_call(client, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, difficulty="hard")
    fake_llm.responses = [_out7(TurnMode.OPENING_REPLY, points=EXPLICIT)]
    first = await _turn(client, ext, 2, [_learner(1)])
    n_calls = len(fake_llm.calls)
    again = await _turn(client, ext, 2, [_learner(1)])
    assert (first.status_code, again.status_code) == (201, 200) and again.json() == first.json()
    assert len(fake_llm.calls) == n_calls


async def test_api_failed_validator_returns_502_and_keeps_logs(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, difficulty="easy")
    fake_llm.responses = [_out7(TurnMode.OPENING_REPLY, target=IMPLICIT[0])] * SETTINGS.turn_max_attempts
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 502
    sid = await _session_id(db_session, ext)
    rows = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN))).all()
    assert {r.failure_kind for r in rows} == {"target_level_mismatch"} and len(rows) == SETTINGS.turn_max_attempts


async def test_api_flag_off_column_null(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer)
    app.dependency_overrides[get_settings] = lambda: OFF
    fake_llm.responses = [_out5(TurnMode.OPENING_REPLY, premises=PREMISES, target_premise="Không có trong premises.")]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    sid = await _session_id(db_session, ext)
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))
    assert turn.points_addressed is None and turn.generator_version == "turn_full_v7_nodifficulty_noburden"


async def test_older_generator_column_null(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, turn_generator_version="turn_full_v6")
    fake_llm.responses = [_out5(TurnMode.OPENING_REPLY, premises=PREMISES, target_premise=EXPLICIT[0])]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    sid = await _session_id(db_session, ext)
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))
    assert turn.points_addressed is None


# ---------------- try_match ----------------


def test_try_match_cli_flags():
    parser = tm.build_parser()
    args = parser.parse_args(["--no-difficulty", "--difficulty", "hard", "--generator", "turn_full_v7"])
    assert args.no_difficulty and args.difficulty == "hard"
    updated = tm.apply_overrides(SETTINGS, args)
    assert updated.turn_difficulty_enabled is False and updated.turn_generator_version == "turn_full_v7"
    assert parser.parse_args([]).no_difficulty is False
    assert tm.apply_overrides(SETTINGS, parser.parse_args([])) is SETTINGS


@pytest.mark.parametrize("level,label", [(EASY, "DỄ"), (MEDIUM, "TRUNG BÌNH"), (HARD, "KHÓ")])
async def test_try_match_difficulty_reaches_every_ai_turn(db_session, level, label):
    case = json.dumps(_two_args() if level == EASY else VALID_CASE_FILE, ensure_ascii=False)
    second = {"explicit": ["Có phòng máy và thư viện để học."], "implicit": []}
    fake = FakeLLMClient([case, _out7(TurnMode.OPENING_REPLY, points=EXPLICIT),
                          _out7(TurnMode.REBUTTAL, target=second["explicit"][0], points=second["explicit"], premises=second),
                          _out5(TurnMode.CLOSING, points_addressed=[])])
    lines: list[str] = []
    result = await tm.run_match(
        db_session, SETTINGS, tm.load_fixture("M01", "pro"), PRO, level, f"try-match-v7-{level.value}", lambda: fake,
        lambda: FakeStanceReviewer("phan_doi_kien_nghi"), out=lines.append,
    )
    assert result["ok"], result["error"]
    prompts = [c["user"] for c in fake.calls[1:]]
    assert len(prompts) == 3 and all(f"Độ khó của trận: {label}." in p for p in prompts)
    assert any(x.startswith("[points_addressed]") for x in lines)
    assert [x["points_addressed"] for x in result["transcript"] if x["speaker"] == "ai"][-1] == []


def _two_args():
    from tests.conftest import make_case_file

    return make_case_file(2)


# ---------------- sua dang ky muc 3.2: points_unsupported ----------------


@pytest.mark.parametrize("point,speech,unsupported", [
    ("Điện thoại làm mất tập trung.", "Mình cho rằng điện thoại không phải vấn đề.", False),  # 2 tu noi dung: điện, thoại
    ("Trường có thư viện.", "Thư viện không đủ chỗ.", False),  # thư, viện
    ("  ĐIỆN THOẠI gây phiền!! ", "điện thoại", False),  # chuan hoa
    ("Bắt nạt trên mạng tăng.", "Mình bàn về chuyện học phí.", True),  # khong trung
    ("Bắt nạt rất nguy hiểm.", "Bắt bóng là môn hay.", True),  # chi 1 tu
    ("Và là của có không.", "Và là của có không.", True),  # chi stopword khong tinh
    ("Thư thư thư.", "Thư viện.", True),  # tu lap chi tinh 1 lan
])
def test_points_unsupported(point, speech, unsupported):
    assert tf.points_unsupported([point], speech) == ([point] if unsupported else [])


def test_points_unsupported_is_weak_on_topic_words():
    """Ghi nhan han che (dev log 3.2): chi trung tu chu de van qua, du bai noi khong dap y do."""
    assert tf.points_unsupported(["Điện thoại gây bắt nạt."], "Điện thoại rất hữu ích cho việc học.") == []


async def test_points_unsupported_logged_not_rejected():
    other = "Bắt nạt qua mạng xã hội ngày càng tăng."
    result, fake = await _run([_out7(points=[EXPLICIT[0], other])])
    assert result.text and len(fake.calls) == 1
    assert result.calls[0].speech_checks["points_unsupported"] == [EXPLICIT[0], other]  # bai gia toan chu "từ"


async def test_points_unsupported_empty_when_speech_mentions_point():
    speech = "Điện thoại làm mất tập trung là chưa chắc. " + " ".join(["từ"] * 320)
    result, _ = await _run([_out7(speech=speech)])
    assert result.calls[0].speech_checks["points_unsupported"] == []


# ---------------- sua dang ky muc 3.2: du lieu TUNG lan thu ----------------


async def test_every_attempt_logs_target_points_and_failure_kind():
    banned = _out7(target=EXPLICIT[1], speech="Nghiên cứu cho thấy cấm là sai. " + " ".join(["từ"] * 320))
    responses = [banned, _out7(target=IMPLICIT[0], points=EXPLICIT[:1]), _out7(points=EXPLICIT)]
    result, _ = await _run(responses)
    assert [c.failure_kind for c in result.calls] == ["banned_phrase", "target_level_mismatch", None]
    logged = [(c.speech_checks["content_attempt"], c.speech_checks["target_premise"], c.speech_checks["points_addressed"],
               c.speech_checks["target_kind"], c.speech_checks["target_level_ok"]) for c in result.calls]
    assert logged == [
        (1, EXPLICIT[1], [EXPLICIT[0]], "explicit", True),
        (2, IMPLICIT[0], [EXPLICIT[0]], "implicit", False),
        (3, EXPLICIT[0], EXPLICIT, "explicit", True),
    ]


@pytest.mark.parametrize("level,target,kind,ok", [
    (EASY, EXPLICIT[0], "explicit", True), (EASY, IMPLICIT[0], "implicit", False), (EASY, "Ý lạ hoàn toàn khác.", None, False),
    (MEDIUM, IMPLICIT[0], "implicit", False),
    (HARD, IMPLICIT[0], "implicit", True), (HARD, EXPLICIT[0], "explicit", True), (HARD, "Ý lạ hoàn toàn khác.", None, False),
])
async def test_first_attempt_level_agrees_with_validator(level, target, kind, ok):
    result, _ = await _run([_out7(target=target), _out7(points=EXPLICIT)], level=level)
    first = result.calls[0]
    assert (first.speech_checks["target_kind"], first.speech_checks["target_level_ok"]) == (kind, ok)
    assert (first.failure_kind is None) is ok


async def test_premises_reused_attempt_still_logs_target():
    ctx = _case(TurnMode.REBUTTAL)
    ctx.ledger.learner_premises = list(EXPLICIT)
    fresh = {"explicit": ["Một tiền đề mới hoàn toàn của bài này."], "implicit": []}
    result, _ = await _run([_out7(target=IMPLICIT[0]), _out7(target=fresh["explicit"][0], points=[], premises=fresh)], ctx=ctx)
    first = result.calls[0]
    assert first.failure_kind == "premises_reused" and first.speech_checks["target_premise"] == IMPLICIT[0]
    assert first.speech_checks["target_level_ok"] is False  # do duoc du bi loai vi ly do khac


async def test_schema_invalid_attempt_logs_what_it_can():
    raw = json.loads(_out7(target=EXPLICIT[1]))
    del raw["ai_points"]
    result, _ = await _run([json.dumps(raw, ensure_ascii=False), _out7()])
    first = result.calls[0]
    assert first.failure_kind == "schema_validation" and first.speech_checks["target_premise"] == EXPLICIT[1]
    assert first.speech_checks["points_addressed"] == [EXPLICIT[0]] and first.speech_checks["content_attempt"] == 1


@pytest.mark.parametrize("bad", [
    {"premises": "sai kiểu", "target_premise": 123, "points_addressed": "sai"},
    {"premises": {"explicit": [1, None], "implicit": "x"}, "target_premise": None, "points_addressed": [1]},
    {},
])
def test_attempt_checks_tolerates_malformed_output(bad):
    checks = tf.attempt_checks(bad, HARD)
    assert checks["target_kind"] is None and checks["target_level_ok"] is False and checks["points_addressed_count"] == 0


def test_attempt_checks_non_dict_is_empty():
    assert tf.attempt_checks(["mảng"], HARD) == {} and tf.attempt_checks(None, HARD) == {}


async def test_unparseable_attempt_keeps_attempt_number_and_failure_kind():
    result, _ = await _run(["không phải json", _out7()])
    first = result.calls[0]
    assert first.failure_kind == "invalid_json" and first.raw_output == "không phải json"
    assert first.speech_checks == {"content_attempt": 1}
    assert result.calls[1].speech_checks["content_attempt"] == 2


async def test_split_array_attempt_logged_with_structured_fields():
    result, _ = await _run([SchemaRejected(_rejected_array(target_premise=EXPLICIT[1]))])
    checks = result.calls[0].speech_checks
    assert checks["target_premise"] == EXPLICIT[1] and checks["points_addressed"] == [EXPLICIT[0]]


async def test_content_attempt_not_shifted_by_429_or_reviewer(monkeypatch):
    from app.opponent import turn_generators
    from tests.conftest import RateLimited

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(turn_generators, "_sleep", _no_sleep)
    reviewer = FakeStanceReviewer("phan_doi_kien_nghi")
    fake = FakeLLMClient([RateLimited("Please try again in 1s."), _out7(target=IMPLICIT[0]), _out7()])
    gen = tf.FullTurnGeneratorV7(fake, SETTINGS, reviewer)
    result = await gen.generate(TurnMode.REBUTTAL, _case(TurnMode.REBUTTAL))
    rows = [(c.attempt, c.purpose, c.failure_kind, (c.speech_checks or {}).get("content_attempt")) for c in result.calls]
    assert rows == [
        (1, LLMCallPurpose.TURN, "rate_limited", None),
        (2, LLMCallPurpose.TURN, "target_level_mismatch", 1),
        (3, LLMCallPurpose.TURN, None, 2),
        (4, LLMCallPurpose.STANCE_REVIEW, None, None),
    ]


@pytest.mark.parametrize("settings,mode,ctx", [
    (OFF, TurnMode.REBUTTAL, _case(TurnMode.REBUTTAL)),
    (SETTINGS, TurnMode.OPENING_FIRST, _case(TurnMode.OPENING_FIRST)),
    (SETTINGS, TurnMode.CLOSING, _case(TurnMode.CLOSING)),
], ids=["flag_off", "opening_first", "closing"])
async def test_attempt_log_only_for_target_modes_with_difficulty_on(settings, mode, ctx):
    target = EXPLICIT[0] if tf.needs_target(mode) else None
    empty = {"explicit": [], "implicit": []}
    out = _out7(mode, target=target, points=[], premises=PREMISES if tf.needs_target(mode) else empty)
    result, _ = await _run([out], mode, ctx, settings=settings)
    for key in ("content_attempt", "target_kind", "points_unsupported", "points_addressed_count"):
        assert key not in (result.calls[0].speech_checks or {})


async def test_v6_speech_checks_unchanged():
    out = _out5(TurnMode.REBUTTAL, premises=PREMISES, target_premise=EXPLICIT[0])
    result = await tf.FullTurnGeneratorV6(FakeLLMClient([out]), SETTINGS).generate(TurnMode.REBUTTAL, _case(TurnMode.REBUTTAL))
    assert not {"content_attempt", "target_kind", "points_unsupported"} & set(result.calls[0].speech_checks)


async def _turn_rows(db_session, ext):
    sid = await _session_id(db_session, ext)
    return (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN)
        .order_by(OpponentLLMCall.attempt))).all()


async def test_db_keeps_rejected_attempts_of_accepted_turn(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, difficulty="easy")
    fake_llm.responses = [_out7(TurnMode.OPENING_REPLY, target=IMPLICIT[0]), _out7(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    rows = await _turn_rows(db_session, ext)
    assert [(r.failure_kind, r.speech_checks["content_attempt"], r.speech_checks["target_premise"]) for r in rows] == [
        ("target_level_mismatch", 1, IMPLICIT[0]), (None, 2, EXPLICIT[0])]
    assert rows[0].speech_checks["points_addressed"] == [EXPLICIT[0]] and "points_unsupported" in rows[0].speech_checks
    assert rows[0].turn_id is not None and rows[0].turn_id == rows[1].turn_id


async def test_db_keeps_every_attempt_of_failed_turn(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, difficulty="medium")
    fake_llm.responses = [_out7(TurnMode.OPENING_REPLY, target=f"Ý lạ thứ {i} hoàn toàn khác biệt.") for i in range(3)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 502
    rows = await _turn_rows(db_session, ext)
    assert [(r.failure_kind, r.speech_checks["content_attempt"], r.turn_id) for r in rows] == [
        ("target_not_in_premises", i, None) for i in (1, 2, 3)]
    assert [r.speech_checks["target_kind"] for r in rows] == [None, None, None]
    assert rows[0].speech_checks["target_premise"] == "Ý lạ thứ 0 hoàn toàn khác biệt."
