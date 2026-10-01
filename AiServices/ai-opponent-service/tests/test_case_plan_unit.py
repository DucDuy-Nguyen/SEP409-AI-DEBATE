"""
Test khong can DB: schema case_file, parse JSON, prompt builder, generate_case_file.
"""
import copy
import json
import unicodedata

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.llm.client import AnthropicClient, GeminiClient, GroqClient, OpenAIClient, schema_rejected_output
from app.llm.json_utils import LLMOutputParseError, extract_json
from app.opponent.models import DebateSide, OpponentDifficulty
from app.opponent.prompts import case_plan_v3
from app.opponent.schemas import AnticipatedArgument, CaseFile
from app.opponent.service import generate_case_file
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, RateLimited, SchemaRejected, make_case_file

PRO, CON = DebateSide.PRO, DebateSide.CON


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_stale_and_budget_defaults():
    s = _settings()
    assert s.case_plan_total_budget_seconds == 240
    assert s.case_plan_stale_after_seconds == 360  # > 240 + 60


@pytest.mark.parametrize(
    "overrides",
    [
        {"case_plan_stale_after_seconds": 300},  # bang dung 240 + 60 -> van tu choi
        {"case_plan_total_budget_seconds": 300},  # 360 <= 300 + 60
        {"case_plan_stale_after_seconds": 100},
    ],
)
def test_stale_threshold_not_above_budget_plus_margin_is_rejected(overrides):
    with pytest.raises(ValidationError, match="CASE_PLAN_STALE_AFTER_SECONDS"):
        _settings(**overrides)


def test_stale_threshold_ignores_llm_timeout_now():
    # Cong thuc cu (timeout x 3 x attempts) da bo: timeout lon khong con lam hong khoi dong.
    s = _settings(llm_timeout_seconds=600, case_plan_stale_after_seconds=301)
    assert s.case_plan_stale_after_seconds == 301


@pytest.mark.parametrize(
    "cls,key_field",
    [(OpenAIClient, "openai_api_key"), (AnthropicClient, "anthropic_api_key"), (GroqClient, "groq_api_key")],
)
def test_sdk_clients_created_with_max_retries_zero(cls, key_field):
    client = cls(_settings(**{key_field: "test-key-not-real"}))
    assert client._client.max_retries == 0


def test_gemini_client_has_no_sdk_retry_and_has_timeout():
    client = GeminiClient(_settings(gemini_api_key="test-key-not-real", llm_timeout_seconds=45))
    http_options = client._client._api_client._http_options
    assert http_options.retry_options.attempts == 1
    assert http_options.timeout == 45_000


def test_case_file_valid():
    cf = CaseFile.model_validate(VALID_CASE_FILE)
    assert [a.id for a in cf.arguments] == ["A1", "A2", "A3"]


def test_case_file_has_no_stance_and_uses_example():
    assert "stance" not in CaseFile.model_fields
    data = copy.deepcopy(VALID_CASE_FILE)
    data["arguments"][0]["evidence"] = data["arguments"][0].pop("example")  # schema cu
    with pytest.raises(ValidationError):
        CaseFile.model_validate(data)


def test_case_file_rejects_duplicate_ids():
    data = copy.deepcopy(VALID_CASE_FILE)
    data["arguments"][1]["id"] = "A1"
    with pytest.raises(ValidationError):
        CaseFile.model_validate(data)


def test_extract_json_handles_markdown_fence():
    raw = "```json\n" + json.dumps(VALID_CASE_FILE) + "\n```"
    assert extract_json(raw)["weighing"] == VALID_CASE_FILE["weighing"]


def test_extract_json_rejects_non_object():
    with pytest.raises(LLMOutputParseError):
        extract_json("[1, 2, 3]")
    with pytest.raises(LLMOutputParseError):
        extract_json("khong phai json")


def test_argument_count_by_difficulty_matches_spec():
    assert case_plan_v3.ARGUMENT_COUNT_BY_DIFFICULTY == {
        OpponentDifficulty.EASY: 2,
        OpponentDifficulty.MEDIUM: 3,
        OpponentDifficulty.HARD: 3,
    }


@pytest.mark.parametrize("ai_side,learner_side", [(PRO, CON), (CON, PRO)])
@pytest.mark.parametrize("difficulty", list(OpponentDifficulty))
def test_prompt_v3_contains_required_sentences(ai_side, learner_side, difficulty):
    system, user = case_plan_v3.build_case_plan_prompt("Cấm điện thoại trong trường", ai_side, learner_side, difficulty)
    ai_label, learner_label = case_plan_v3.SIDE_LABEL[ai_side], case_plan_v3.SIDE_LABEL[learner_side]
    required = [
        # giu tu v2
        f"Bạn thuộc phe {ai_label}. Người học thuộc phe {learner_label}. "
        "Phe của bạn là CỐ ĐỊNH và không bao giờ thay đổi.",
        "KHÔNG bịa số liệu thống kê, tỷ lệ phần trăm, tên nghiên cứu, tên tổ chức hay trích dẫn cụ thể. "
        "Chỉ dùng lý lẽ logic, ví dụ đời thường, hoặc tình huống giả định được ghi rõ là giả định.",
        "Ưu tiên bối cảnh Việt Nam (giáo dục, gia đình, xã hội Việt Nam) khi phù hợp; "
        "tránh mặc định áp khung văn hoá phương Tây.",
        "Mọi nội dung viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ.",
        # moi o v3
        "Trước khi trả kết quả, kiểm tra: không lập luận nào tấn công hay dựa vào điều mà chính phần "
        "định nghĩa của bạn đã loại trừ.",
        "KHÔNG viện dẫn bằng chứng mơ hồ như 'nghiên cứu cho thấy', 'nhiều quốc gia đã áp dụng thành công', "
        "'đã được chứng minh', 'các chuyên gia cho rằng'.",
        "Mọi ví dụ PHẢI bắt đầu bằng 'Giả sử'.",
        "Impact phải tương xứng với reasoning; không khẳng định những hệ quả lớn (như giảm tỷ lệ trầm cảm, "
        "tự tử, thất nghiệp) nếu reasoning không trực tiếp chứng minh.",
        "Chỉ dùng tiếng Việt, kể cả tên phe (Đề xuất / Phản đối).",
    ]
    for sentence in required:
        assert sentence in system, sentence
    assert "Cấm điện thoại trong trường" in user
    assert f"ĐÚNG {case_plan_v3.ARGUMENT_COUNT_BY_DIFFICULTY[difficulty]}" in user
    assert '"learner_claim"' in user and '"opponent_claim"' not in user
    for english in ("Proposition", "Opposition", "MOTION"):
        assert english not in system + user


def test_prompt_v3_side_rule_matches_ai_side():
    pro_rule = (
        "Định nghĩa kiến nghị một cách công bằng và hợp lý, như cách một trọng tài trung lập sẽ hiểu. "
        "KHÔNG mô tả sai hiện trạng để làm lập luận của mình mạnh hơn. "
        "Nếu không chắc về một chi tiết thực tế, đừng nêu nó."
    )
    con_rule = (
        "Chấp nhận cách hiểu phổ biến và hợp lý nhất của kiến nghị. "
        "KHÔNG thêm ngoại lệ hay điều kiện làm hẹp kiến nghị."
    )
    pro_system, _ = case_plan_v3.build_case_plan_prompt("M", PRO, CON, OpponentDifficulty.MEDIUM)
    con_system, _ = case_plan_v3.build_case_plan_prompt("M", CON, PRO, OpponentDifficulty.MEDIUM)
    assert pro_rule in pro_system and con_rule not in pro_system
    assert con_rule in con_system and pro_rule not in con_system
    assert "Bạn thuộc phe Đề xuất. Người học thuộc phe Phản đối." in pro_system


@pytest.mark.parametrize("difficulty", list(OpponentDifficulty))
def test_response_schema_is_strict_and_matches_case_file(difficulty):
    schema = case_plan_v3.build_response_schema(difficulty)
    n = case_plan_v3.ARGUMENT_COUNT_BY_DIFFICULTY[difficulty]
    assert schema["properties"]["arguments"]["minItems"] == n == schema["properties"]["arguments"]["maxItems"]
    argument = schema["$defs"]["CaseArgument"]
    assert argument["properties"]["example"]["pattern"] == "^Giả sử"
    assert "title" in argument["properties"]  # field ten "title" khong bi xoa nham cung metadata
    assert set(schema["properties"]) == set(CaseFile.model_fields)
    assert set(schema["$defs"]["AnticipatedArgument"]["properties"]) == {"id", "learner_claim", "planned_response"}
    for obj in [schema, *schema["$defs"].values()]:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])  # strict mode: moi truong bat buoc


def test_example_must_start_with_gia_su():
    ok = copy.deepcopy(VALID_CASE_FILE)
    ok["arguments"][0]["example"] = "  Giả sử một phụ huynh ở Đà Nẵng..."
    assert CaseFile.model_validate(ok).arguments[0].example.startswith("Giả sử")

    nfd = copy.deepcopy(VALID_CASE_FILE)
    nfd["arguments"][0]["example"] = unicodedata.normalize("NFD", "Giả sử học sinh A...")
    CaseFile.model_validate(nfd)  # dang to hop (NFD) van hop le

    for bad_example in ("Ví dụ: một học sinh lớp 9...", "Một học sinh, giả sử là A...", "Gia su hoc sinh A"):
        bad = copy.deepcopy(VALID_CASE_FILE)
        bad["arguments"][1]["example"] = bad_example
        with pytest.raises(ValidationError, match="Giả sử"):
            CaseFile.model_validate(bad)


def test_anticipated_uses_learner_claim_not_opponent_claim():
    assert "learner_claim" in AnticipatedArgument.model_fields
    assert "opponent_claim" not in AnticipatedArgument.model_fields
    old = copy.deepcopy(VALID_CASE_FILE)
    for item in old["anticipated_opponent_arguments"]:
        item["opponent_claim"] = item.pop("learner_claim")
    with pytest.raises(ValidationError):
        CaseFile.model_validate(old)


async def test_generate_case_file_uses_case_plan_params():
    fake = FakeLLMClient([json.dumps(make_case_file(2))])
    settings = _settings(case_plan_temperature=0.9, case_plan_max_tokens=1234)

    outcome = await generate_case_file("M", CON, PRO, OpponentDifficulty.EASY, fake, settings)

    assert outcome.case_file is not None
    assert outcome.prompt_version == "case_plan_v5"  # mac dinh CASE_PLAN_PROMPT_VERSION
    assert fake.calls[0]["temperature"] == 0.9
    assert fake.calls[0]["max_tokens"] == 1234


async def test_generate_case_file_retries_on_wrong_argument_count():
    # easy can dung 2 luan diem: lan 1 tra 3 -> khong hop le -> retry, lan 2 tra 2 -> OK
    fake = FakeLLMClient([json.dumps(make_case_file(3)), json.dumps(make_case_file(2))])

    outcome = await generate_case_file("M", PRO, CON, OpponentDifficulty.EASY, fake, _settings())

    assert outcome.case_file is not None and len(outcome.case_file.arguments) == 2
    assert [a.success for a in outcome.attempts] == [False, True]
    assert "can dung 2 luan diem" in outcome.attempts[0].error


async def test_generate_case_file_stops_on_provider_error():
    fake = FakeLLMClient([RuntimeError("401 invalid api key"), json.dumps(VALID_CASE_FILE)])

    outcome = await generate_case_file("M", PRO, CON, OpponentDifficulty.MEDIUM, fake, _settings())

    # Loi provider khong retry (retry khong giup duoc) — chi retry khi output khong hop le.
    assert outcome.case_file is None
    assert "invalid api key" in outcome.llm_error
    assert len(fake.calls) == 1


async def test_rate_limit_is_retried_by_service_and_logged():
    fake = FakeLLMClient([RateLimited("429 too many"), RateLimited("429 too many"), json.dumps(VALID_CASE_FILE)])
    settings = _settings(case_plan_rate_limit_wait_seconds=0)

    outcome = await generate_case_file("M", PRO, CON, OpponentDifficulty.MEDIUM, fake, settings)

    assert outcome.case_file is not None
    assert [a.attempt for a in outcome.attempts] == [1, 2, 3]
    assert [a.success for a in outcome.attempts] == [False, False, True]
    assert all("RateLimited" in a.error for a in outcome.attempts[:2])


async def test_rate_limit_retries_exhausted_is_llm_error():
    fake = FakeLLMClient([RateLimited("429")] * 3)
    settings = _settings(case_plan_rate_limit_wait_seconds=0, case_plan_rate_limit_retries=2)

    outcome = await generate_case_file("M", PRO, CON, OpponentDifficulty.MEDIUM, fake, settings)

    assert outcome.case_file is None and "RateLimited" in outcome.llm_error
    assert len(outcome.attempts) == 3  # 1 lan dau + 2 lan retry, deu duoc log


async def test_budget_exceeded_while_waiting_for_llm():
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    fake.delay_seconds = 1.0
    settings = _settings(case_plan_total_budget_seconds=0.2)

    outcome = await generate_case_file("M", PRO, CON, OpponentDifficulty.MEDIUM, fake, settings)

    assert outcome.budget_exceeded and outcome.case_file is None
    [attempt] = outcome.attempts
    assert attempt.error.startswith("budget_exceeded") and "dang cho LLM tra loi" in attempt.error
    assert attempt.latency_ms >= 150


async def test_budget_covers_rate_limit_waits():
    fake = FakeLLMClient([RateLimited("429"), json.dumps(VALID_CASE_FILE)])
    settings = _settings(case_plan_total_budget_seconds=0.2, case_plan_rate_limit_wait_seconds=5)

    outcome = await generate_case_file("M", PRO, CON, OpponentDifficulty.MEDIUM, fake, settings)

    assert outcome.budget_exceeded
    assert [a.attempt for a in outcome.attempts] == [1, 2]
    assert "chua goi LLM" in outcome.attempts[1].error
    assert len(fake.calls) == 1  # het budget trong luc cho, khong goi lan 2


async def test_schema_rejected_by_provider_is_retried_as_invalid_output():
    fake = FakeLLMClient([SchemaRejected('{"arguments": ["A2 bi tra ve dang chuoi"]}'), json.dumps(VALID_CASE_FILE)])

    outcome = await generate_case_file("M", CON, PRO, OpponentDifficulty.MEDIUM, fake, _settings())

    assert outcome.case_file is not None and outcome.llm_error is None
    first, second = outcome.attempts
    assert not first.success and "SchemaRejected" in first.error
    assert first.raw_output == '{"arguments": ["A2 bi tra ve dang chuoi"]}'  # failed_generation duoc luu
    assert "[PHẢN HỒI LẦN THỬ TRƯỚC]" in fake.calls[1]["user"]
    assert second.success


async def test_schema_rejected_every_time_is_invalid_output_not_llm_error():
    fake = FakeLLMClient([SchemaRejected()] * 3)

    outcome = await generate_case_file("M", CON, PRO, OpponentDifficulty.MEDIUM, fake, _settings())

    assert outcome.case_file is None
    assert outcome.llm_error is None  # -> CasePlanningError (502 "khong hop le"), khong phai LLMCallError
    assert len(outcome.attempts) == 3  # CASE_PLAN_MAX_ATTEMPTS mac dinh = 3


def test_default_max_attempts_is_three():
    assert _settings().case_plan_max_attempts == 3


def test_schema_rejected_output_ignores_other_400():
    class OtherBadRequest(Exception):
        status_code = 400
        code = "invalid_api_key"
        body = {"failed_generation": "x"}

    assert schema_rejected_output(OtherBadRequest()) is None
    assert schema_rejected_output(SchemaRejected("abc")) == "abc"


# --- Hoi quy tu output THAT cua prompt v2 (docs/samples/case_plan_v2_real_runs.md, mau 2) ---

def test_real_v2_sample2_example_without_gia_su_is_rejected():
    data = copy.deepcopy(VALID_CASE_FILE)
    data["arguments"][1]["example"] = (
        "Một trường trung học ở Hà Nội quyết định đánh giá học sinh qua các dự án cộng đồng "
        "và bài thuyết trình thay vì điểm thi."
    )
    with pytest.raises(ValidationError, match="Giả sử"):
        CaseFile.model_validate(data)


def test_real_v2_sample2_misspelled_field_is_rejected():
    # Loi go that (mau v2 so 2, 3/4 lan Groq tu choi o batch v4) — voi ten truong moi `motion_reading`.
    data = copy.deepcopy(VALID_CASE_FILE)
    data["motion_interinterpretation"] = data.pop("motion_reading")
    with pytest.raises(ValidationError, match="motion_reading"):
        CaseFile.model_validate(data)
    schema = case_plan_v3.build_response_schema(OpponentDifficulty.MEDIUM)
    assert schema["additionalProperties"] is False and "motion_reading" in schema["required"]
    assert "motion_interpretation" not in schema["properties"]
