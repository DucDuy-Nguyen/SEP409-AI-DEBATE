"""
Loi go ten truong (gpt-oss-120b lap lai "motion_interinterpretation"): tu sua khi Groq tu choi schema, phan hoi
neu CA key thieu lan key la.
"""
import copy
import json

import pytest

from app.core.config import Settings
from app.opponent.models import DebateSide, OpponentDifficulty, ReviewerVerdict
from app.opponent.service import (
    KEY_REPAIR_MAX_DISTANCE,
    FailureKind,
    edit_distance,
    generate_case_file,
    key_issues,
    repair_keys,
)
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, FakeStanceReviewer, SchemaRejected, make_case_file

GOOD = json.dumps(VALID_CASE_FILE, ensure_ascii=False)


def _typo(key: str, typo: str, *, nested: tuple | None = None) -> dict:
    data = copy.deepcopy(VALID_CASE_FILE)
    obj = data if nested is None else data[nested[0]][nested[1]]
    obj[typo] = obj.pop(key)
    return data


def _rejected(data: dict, missing: str = "motion_reading") -> SchemaRejected:
    """Groq 400 json_validate_failed THAT: chi bao key thieu dau tien, failed_generation = output bi tu choi."""
    e = SchemaRejected(json.dumps(data, ensure_ascii=False))
    e.args = (f"Error code: 400 - {{'error': {{'message': \"Generated JSON does not match the expected schema. "
              f"Error: jsonschema: '' does not validate with /required: missing properties: '{missing}'\", "
              f"'type': 'invalid_request_error'}}}}",)
    return e


async def _run(responses, reviewer=None, **settings):
    fake = FakeLLMClient(list(responses))
    outcome = await generate_case_file(
        "M", DebateSide.CON, DebateSide.PRO, OpponentDifficulty.MEDIUM, fake, Settings(_env_file=None, **settings), reviewer
    )
    return outcome, fake


# ---------------- ham thuan ----------------


def test_edit_distance():
    assert edit_distance("motion_reading", "motion_reading") == 0
    assert edit_distance("motion_readng", "motion_reading") == 1
    assert edit_distance("motoin_reading", "motion_reading") == 2
    assert edit_distance("motion_interinterpretation", "motion_reading") > KEY_REPAIR_MAX_DISTANCE == 3


def test_repair_renames_close_typo_top_level_and_nested():
    data = _typo("motion_reading", "motion_readng")
    data["arguments"][1]["reasonig"] = data["arguments"][1].pop("reasoning")

    fixed, renames = repair_keys(data)

    assert "motion_reading" in fixed and "motion_readng" not in fixed
    assert "reasoning" in fixed["arguments"][1]
    assert renames == [
        {"path": "motion_reading", "from": "motion_readng", "to": "motion_reading"},
        {"path": "arguments[1].reasoning", "from": "reasonig", "to": "reasoning"},
    ]
    assert "motion_readng" in data  # ban goc khong bi sua


def test_repair_skips_far_or_ambiguous_keys():
    far = _typo("motion_reading", "motion_interinterpretation")
    assert repair_keys(far)[1] == []
    ambiguous = copy.deepcopy(VALID_CASE_FILE)
    ambiguous.pop("motion_reading")
    ambiguous["motion_readinx"] = "a"
    ambiguous["motion_readiny"] = "b"  # 2 key la cach deu 1 -> khong doan
    assert repair_keys(ambiguous)[1] == []


def test_key_issues_lists_missing_and_unknown():
    issues = key_issues(_typo("motion_reading", "motion_interinterpretation"))
    assert issues == [
        "`motion_interinterpretation`: trường lạ, không có trong cấu trúc mẫu — bỏ đi",
        "`motion_reading`: thiếu trường bắt buộc",
    ]
    assert key_issues(_typo("motion_reading", "motion_readng")) == [
        "`motion_readng`: bạn đã viết 'motion_readng', tên đúng là 'motion_reading'"
    ]


# ---------------- trong Case Planning ----------------


async def test_schema_rejection_with_close_typo_is_repaired_without_calling_llm_again():
    outcome, fake = await _run([_rejected(_typo("motion_reading", "motion_readng"))])

    assert outcome.case_file is not None and outcome.case_file.motion_reading
    assert len(fake.calls) == 1  # KHONG goi lai LLM
    [record] = outcome.attempts
    assert record.success is True and record.failure_kind is None and record.error is None
    assert record.schema_rejected is True  # Groq that su da tu choi
    assert record.retry_feedback is None
    assert record.key_repairs["event"] == "key_repaired"
    assert record.key_repairs["renames"] == [{"path": "motion_reading", "from": "motion_readng", "to": "motion_reading"}]
    assert "missing properties: 'motion_reading'" in record.key_repairs["provider_error"]
    assert record.vague_evidence == []  # case file sua xong van duoc quet


async def test_repaired_case_file_still_goes_through_stance_review():
    reviewer = FakeStanceReviewer("ung_ho_kien_nghi")  # moi muc lat phe (AI la con)
    outcome, fake = await _run(
        [_rejected(_typo("motion_reading", "motion_readng")), GOOD], reviewer=reviewer, case_plan_max_attempts=2
    )
    first = outcome.attempts[0]
    assert first.key_repairs is not None and first.reviewer_verdict == ReviewerVerdict.SIDE_FLIP
    assert first.failure_kind == FailureKind.SIDE_FLIP and len(fake.calls) == 2


async def test_far_typo_is_not_repaired_and_feedback_names_both_keys():
    outcome, fake = await _run([_rejected(_typo("motion_reading", "motion_interinterpretation")), GOOD])

    first = outcome.attempts[0]
    assert first.failure_kind == FailureKind.SCHEMA_REJECTED and first.key_repairs is None
    assert "missing properties: 'motion_reading'" in first.retry_feedback  # chi tiet Groq
    assert "`motion_interinterpretation`: trường lạ, không có trong cấu trúc mẫu — bỏ đi" in first.retry_feedback
    assert "`motion_reading`: thiếu trường bắt buộc" in first.retry_feedback
    assert outcome.case_file is not None and len(fake.calls) == 2


async def test_repaired_but_invalid_content_retries_with_all_issues():
    data = _typo("motion_reading", "motion_readng")
    data["arguments"] = data["arguments"][:2]  # medium can 3
    outcome, fake = await _run([_rejected(data), GOOD])

    first = outcome.attempts[0]
    assert first.failure_kind == FailureKind.SCHEMA_REJECTED and first.key_repairs is None
    assert "`motion_readng`: bạn đã viết 'motion_readng', tên đúng là 'motion_reading'" in first.retry_feedback
    assert "cần ĐÚNG 3 luận điểm, bạn trả về 2" in first.retry_feedback
    assert len(fake.calls) == 2


async def test_unparseable_failed_generation_falls_back_to_groq_detail():
    broken = SchemaRejected('{"arguments": ["A2 bi tra ve dang chuoi"')  # khong parse duoc
    outcome, _ = await _run([broken, GOOD])
    first = outcome.attempts[0]
    assert first.failure_kind == FailureKind.SCHEMA_REJECTED
    assert "bị nhà cung cấp từ chối vì không khớp JSON schema" in first.retry_feedback


async def test_structure_broken_output_is_not_repaired():
    # Mau that v4 M07 con medium: phan sau cua object bi nhet vao mang arguments (chuoi thay vi object)
    data = copy.deepcopy(VALID_CASE_FILE)
    data["arguments"] = [data["arguments"][0], json.dumps(data["arguments"][1:], ensure_ascii=False),
                         "anticipated_opponent_arguments", ":", data.pop("anticipated_opponent_arguments")]
    data.pop("weighing")
    outcome, fake = await _run([_rejected(data, missing="anticipated_opponent_arguments', 'weighing"), GOOD])
    first = outcome.attempts[0]
    assert first.key_repairs is None and first.failure_kind == FailureKind.SCHEMA_REJECTED
    assert "`anticipated_opponent_arguments`: thiếu trường bắt buộc" in first.retry_feedback
    assert "`weighing`: thiếu trường bắt buộc" in first.retry_feedback
    assert len(fake.calls) == 2
