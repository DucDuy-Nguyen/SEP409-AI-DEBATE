"""
Retry CO PHAN HOI (moi loai loi), prompt v4 / v5 + chon version.
Bo do bang chung mo ho moi: tests/test_vague_detector.py. Tu sua ten truong: tests/test_key_repair.py.
"""
import copy
import difflib
import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.opponent.models import DebateSide, LLMCallPurpose, OpponentDifficulty, ReviewerVerdict
from app.opponent.prompts import case_plan_v3, case_plan_v4, case_plan_v5
from app.opponent.service import FailureKind, generate_case_file
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, FakeStanceReviewer, SchemaRejected, make_case_file

PRO, CON = DebateSide.PRO, DebateSide.CON
MEDIUM = OpponentDifficulty.MEDIUM
HEADER = "[PHẢN HỒI LẦN THỬ TRƯỚC]"
GOOD = json.dumps(VALID_CASE_FILE)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _with(path_value: dict) -> str:
    """VALID_CASE_FILE sua theo {('arguments', 0, 'example'): '...'}."""
    data = copy.deepcopy(VALID_CASE_FILE)
    for path, value in path_value.items():
        node = data
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
    return json.dumps(data, ensure_ascii=False)


async def _run(responses, reviewer=None, **settings):
    fake = FakeLLMClient(list(responses))
    outcome = await generate_case_file("M", CON, PRO, MEDIUM, fake, _settings(**settings), reviewer)
    return outcome, fake


# ---------------- phan hoi cho tung loai loi ----------------

REAL_SCHEMA_ERROR = (
    "Generated JSON does not match the expected schema. Please adjust your prompt. See 'failed_generation' for more "
    "details. Error: jsonschema: '/arguments/1' does not validate with /properties/arguments/items/$ref/type: "
    "expected object, but got string"
)


class RealSchemaRejected(SchemaRejected):
    """Cau truc loi that cua Groq: message nam trong dict error (str(e) co ca 'type')."""

    def __str__(self):
        return "Error code: 400 - {'error': {'message': \"" + REAL_SCHEMA_ERROR + "\", 'type': 'invalid_request_error'}}"


@pytest.mark.parametrize(
    "bad_output,kind,expected_in_feedback",
    [
        ("day khong phai json", FailureKind.INVALID_JSON, ["không phải một JSON object hợp lệ"]),
        (
            _with({("arguments", 0, "example"): "Một trường ở Hà Nội đã làm vậy."}),
            FailureKind.SCHEMA_VALIDATION,
            ["`arguments[0].example`", "Giả sử"],
        ),
        (
            json.dumps(make_case_file(2)),
            FailureKind.ARGUMENT_COUNT,
            ["`arguments`", "cần ĐÚNG 3 luận điểm, bạn trả về 2"],
        ),
        (
            # cau THAT cua v3 (docs/samples/case_plan_v3_rerun.md, mau 2, O2) — bang chung mo ho muc HIGH
            _with({("anticipated_opponent_arguments", 1, "planned_response"): "Nhiều quốc gia đã áp dụng mô hình này."}),
            FailureKind.BANNED_PHRASE,
            ["`anticipated_opponent_arguments[1].planned_response`", "bằng chứng mơ hồ \"Nhiều quốc gia đã áp dụng\"",
             "lập luận dựa trên cơ chế"],
        ),
    ],
)
async def test_feedback_names_field_and_violation(bad_output, kind, expected_in_feedback):
    outcome, fake = await _run([bad_output, GOOD])

    assert outcome.case_file is not None
    failed = outcome.attempts[0]
    assert failed.failure_kind == kind and failed.success is False
    assert failed.retry_feedback.startswith(HEADER)
    for text in expected_in_feedback:
        assert text in failed.retry_feedback, text
    # phan hoi DA GUI dung nhu da log
    assert fake.calls[1]["user"].endswith(failed.retry_feedback)


async def test_feedback_for_misspelled_field_names_wrong_and_right_key():
    # Duong kiem tra CUC BO (khong JSON schema / provider khac): go sai <= 3 ky tu -> "bạn đã viết X, tên đúng là Y"
    data = copy.deepcopy(VALID_CASE_FILE)
    data["motion_readng"] = data.pop("motion_reading")

    outcome, _ = await _run([json.dumps(data), GOOD], case_plan_use_json_schema=False)

    feedback = outcome.attempts[0].retry_feedback
    assert "`motion_readng`: bạn đã viết 'motion_readng', tên đúng là 'motion_reading'" in feedback
    assert "thiếu trường bắt buộc" not in feedback  # key thieu da duoc neu trong dong "tên đúng là"


async def test_feedback_lists_both_missing_and_unknown_keys_when_too_different():
    # Ten cu go sai (khoang cach > 3 so voi motion_reading) -> khong doan, neu CA key la lan key thieu
    data = copy.deepcopy(VALID_CASE_FILE)
    data["motion_interinterpretation"] = data.pop("motion_reading")

    outcome, _ = await _run([json.dumps(data), GOOD], case_plan_use_json_schema=False)

    feedback = outcome.attempts[0].retry_feedback
    assert "`motion_interinterpretation`: trường lạ, không có trong cấu trúc mẫu — bỏ đi" in feedback
    assert "`motion_reading`: thiếu trường bắt buộc" in feedback


async def test_feedback_for_groq_schema_rejection_includes_detail():
    outcome, _ = await _run([RealSchemaRejected(), GOOD])

    rejected = outcome.attempts[0]
    assert rejected.failure_kind == FailureKind.SCHEMA_REJECTED
    assert "'/arguments/1' does not validate" in rejected.retry_feedback
    assert "expected object, but got string" in rejected.retry_feedback


async def test_side_flip_retry_is_neutral_no_feedback():
    # Muc 2.4m: reviewer co the bao sai -> KHONG noi generator "da lat phe" (tranh ep doi phe that); sinh lai tu prompt goc.
    reviewer = FakeStanceReviewer("phan_doi_kien_nghi")
    reviewer.positions = {"A2": "ung_ho_kien_nghi"}  # A2 lat phe o moi lan review

    outcome, fake = await _run([GOOD, GOOD], reviewer=reviewer, case_plan_max_attempts=2)
    plans = [a for a in outcome.attempts if a.purpose == LLMCallPurpose.CASE_PLAN]
    flipped = plans[0]

    assert flipped.failure_kind == FailureKind.SIDE_FLIP and flipped.reviewer_verdict == ReviewerVerdict.SIDE_FLIP
    assert flipped.retry_feedback is None
    assert flipped.reviewer_detail["retry"] == "side_flip_neutral_retry"
    assert fake.calls[1]["user"] == fake.calls[0]["user"]  # request retry = prompt goc
    for leak in ("PHẢN HỒI", "Trọng tài", "lật phe", "PHẢI bảo vệ phe"):
        assert leak not in fake.calls[1]["user"]
    assert len(plans) == 2 and outcome.case_file is None  # van tinh vao so lan thu: 2 lan side_flip -> het luot


async def test_side_flip_counts_toward_max_attempts():
    reviewer = FakeStanceReviewer("ung_ho_kien_nghi")  # moi muc nguoc phe Phan doi
    outcome, fake = await _run([GOOD, GOOD], reviewer=reviewer, case_plan_max_attempts=2)
    plans = [a for a in outcome.attempts if a.purpose == LLMCallPurpose.CASE_PLAN]
    assert outcome.case_file is None and len(fake.calls) == 2
    assert [p.reviewer_detail.get("retry") for p in plans] == ["side_flip_neutral_retry", None]  # lan cuoi: het luot


async def test_schema_error_keeps_feedback_then_side_flip_drops_it():
    # Loi schema -> VAN retry co phan hoi; lan sau bi side_flip -> retry tiep theo quay ve prompt goc (bo phan hoi cu).
    reviewer = FakeStanceReviewer("phan_doi_kien_nghi")
    reviewer.positions = {"A2": "ung_ho_kien_nghi"}
    outcome, fake = await _run([RealSchemaRejected(), GOOD, GOOD], reviewer=reviewer, case_plan_max_attempts=3)

    rejected = outcome.attempts[0]
    assert rejected.failure_kind == FailureKind.SCHEMA_REJECTED and rejected.retry_feedback
    base = fake.calls[0]["user"]
    assert fake.calls[1]["user"] == base + "\n\n" + rejected.retry_feedback
    assert fake.calls[2]["user"] == base


async def test_feedback_is_not_cumulative_and_last_failure_has_none():
    bad1 = "khong phai json"
    bad2 = json.dumps(make_case_file(2))
    outcome, fake = await _run([bad1, bad2, "van sai"], case_plan_max_attempts=3)

    first, second, third = outcome.attempts
    base = fake.calls[0]["user"]
    assert fake.calls[1]["user"] == base + "\n\n" + first.retry_feedback
    assert fake.calls[2]["user"] == base + "\n\n" + second.retry_feedback  # KHONG con phan hoi lan 1
    assert third.retry_feedback is None  # het luot -> khong gui phan hoi nao
    assert outcome.case_file is None


# ---------------- prompt v4 + chon version ----------------


MECHANISM_RULE = (
    "Khi đề xuất giải pháp thay thế hoặc khẳng định một điều khả thi, hãy lập luận dựa trên cơ chế hoạt "
    "động của nó, không dựa trên việc nơi khác đã áp dụng hay đã được chứng minh."
)


@pytest.mark.parametrize("ai_side,learner_side", [(PRO, CON), (CON, PRO)])
@pytest.mark.parametrize("difficulty", list(OpponentDifficulty))
def test_v4_differs_from_v3_only_in_rule_3(ai_side, learner_side, difficulty):
    s3, u3 = case_plan_v3.build_case_plan_prompt("Nên cấm dạy thêm", ai_side, learner_side, difficulty)
    s4, u4 = case_plan_v4.build_case_plan_prompt("Nên cấm dạy thêm", ai_side, learner_side, difficulty)
    assert u3 == u4
    changed = [line for line in difflib.ndiff(s3.splitlines(), s4.splitlines()) if line[:1] in "+-"]
    assert changed == [
        "- 3. KHÔNG viện dẫn bằng chứng mơ hồ như 'nghiên cứu cho thấy', 'nhiều quốc gia đã áp dụng thành công', "
        "'đã được chứng minh', 'các chuyên gia cho rằng'.",
        f"+ 3. {MECHANISM_RULE}",
    ]


def test_v3_and_v4_share_schema_and_counts():
    assert case_plan_v4.build_response_schema is case_plan_v3.build_response_schema
    assert case_plan_v4.ARGUMENT_COUNT_BY_DIFFICULTY is case_plan_v3.ARGUMENT_COUNT_BY_DIFFICULTY


def test_prompt_version_setting():
    assert _settings().case_plan_prompt_version == "case_plan_v5"
    assert _settings(case_plan_prompt_version="case_plan_v3").case_plan_prompt_version == "case_plan_v3"
    assert _settings(case_plan_prompt_version="case_plan_v4").case_plan_prompt_version == "case_plan_v4"
    with pytest.raises(ValidationError):
        _settings(case_plan_prompt_version="case_plan_v2")


@pytest.mark.parametrize(
    "version,module",
    [("case_plan_v3", case_plan_v3), ("case_plan_v4", case_plan_v4), ("case_plan_v5", case_plan_v5)],
)
async def test_generate_uses_configured_prompt(version, module):
    outcome, fake = await _run([GOOD], case_plan_prompt_version=version)
    expected_system, expected_user = module.build_case_plan_prompt("M", CON, PRO, MEDIUM)
    assert outcome.prompt_version == version
    assert fake.calls[0]["system"] == expected_system and fake.calls[0]["user"] == expected_user


# ---------------- prompt v5 ----------------

V5_NEW_RULES = [
    "Con số trong tình huống giả định phải hợp lý về độ lớn và KHÔNG được gắn với địa điểm, tổ chức, cơ quan hay "
    "thiết bị đo lường có thật (ví dụ tên thành phố cụ thể, trạm quan trắc).",
    "Không khẳng định rằng một điều đã xảy ra hay đã được quan sát ngoài đời thật với chủ thể chung chung như "
    "'nhiều sinh viên', 'nhiều nơi', 'một số nước'.",
]


@pytest.mark.parametrize("ai_side,learner_side", [(PRO, CON), (CON, PRO)])
@pytest.mark.parametrize("difficulty", list(OpponentDifficulty))
def test_v5_adds_exactly_two_rules_to_v4(ai_side, learner_side, difficulty):
    s4, u4 = case_plan_v4.build_case_plan_prompt("Nên cấm dạy thêm", ai_side, learner_side, difficulty)
    s5, u5 = case_plan_v5.build_case_plan_prompt("Nên cấm dạy thêm", ai_side, learner_side, difficulty)
    assert u4 == u5
    changed = [line for line in difflib.ndiff(s4.splitlines(), s5.splitlines()) if line[:1] in "+-"]
    assert changed == [
        f"+ 11. {V5_NEW_RULES[0]}",
        f"+ 12. {V5_NEW_RULES[1]}",
        "- 11. Mọi nội dung viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ.",
        "+ 13. Mọi nội dung viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ.",
    ]
    assert s5.rstrip().endswith("13. Mọi nội dung viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ.")


def test_all_versions_use_motion_reading_key():
    for module in (case_plan_v3, case_plan_v4, case_plan_v5):
        _, user = module.build_case_plan_prompt("M", PRO, CON, MEDIUM)
        assert '"motion_reading"' in user and "motion_interpretation" not in user
        assert "motion_reading" in module.build_response_schema(MEDIUM)["required"]
