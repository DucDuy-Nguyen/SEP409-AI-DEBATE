"""
Test logic parse/validate cua evaluator.py bang FakeLLMClient — KHONG goi API that,
nen chay duoc ma khong can API key. Chay bang: pytest tests/
"""
import json

import pytest
from pydantic import ValidationError

from app.prompts.evaluator_prompt import ArgumentContext, build_evaluation_prompt, infer_argument_context
from app.schemas import ArgumentEvaluationRequest, DebateSide, DebateStage
from app.services.evaluator import EvaluationParseError, evaluate_argument
from app.services.llm_client import LLMClient

VALID_CRITERIA = [
    {"name": "Logic", "score": 4, "reasoning": "Lap luan chat che, khong mau thuan."},
    {"name": "Evidence", "score": 3, "reasoning": "Co vi du nhung chua du thuyet phuc."},
    {"name": "Relevance", "score": 5, "reasoning": "Bam sat motion va phan bien dung diem doi phuong."},
    {"name": "Structure", "score": 4, "reasoning": "Co claim-reasoning-example ro rang."},
    {"name": "Persuasiveness", "score": 4, "reasoning": "Thuyet phuc, con thieu impact ro rang."},
]
# overall_score LUON duoc TINH BANG CONG THUC tu 5 tieu chi con (da dao nguoc
# lai tu thiet ke holistic doc lap — xem app/prompts/evaluator_prompt.py va
# docs/AI_DEVELOPMENT_LOG.md): (4+3+5+4+4)/25*10 = 8.0
EXPECTED_OVERALL = 8.0

EXPECTED_OVERALL_REASONING = (
    "Du Evidence chi dat 3/5 nhung Logic va Relevance rat manh nen tong the van thuyet phuc."
)

# LUU Y: khong con "overall_score" trong VALID_PAYLOAD — field nay khong con
# bat buoc trong JSON tu LLM nua, vi overall_score luon duoc code tu tinh tu
# "criteria", khong doc tu JSON.
VALID_PAYLOAD = {
    "criteria": VALID_CRITERIA,
    "overall_reasoning": EXPECTED_OVERALL_REASONING,
    "strengths": ["Logic chat che"],
    "weaknesses": ["Thieu bang chung cu the"],
    "suggestions": ["Them so lieu thuc te de tang tinh thuyet phuc"],
}


class FakeLLMClient(LLMClient):
    """Client gia lap: tra ve tung phan tu trong `responses` theo thu tu moi lan generate() duoc goi."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.call_count = 0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        if not self._responses:
            raise RuntimeError("FakeLLMClient: het response da chuan bi san")
        return self._responses.pop(0)


def _sample_request() -> ArgumentEvaluationRequest:
    return ArgumentEvaluationRequest(
        motion="THBT social media does more harm than good",
        side=DebateSide.PRO,
        stage=DebateStage.REBUTTAL,
        argument_text="Social media lam giam thoi gian tuong tac truc tiep giua con nguoi...",
        opponent_argument_text="Social media giup ket noi nguoi o xa nhau...",
    )


def test_valid_json_parsed_correctly():
    client = FakeLLMClient([json.dumps(VALID_PAYLOAD)])
    result = evaluate_argument(_sample_request(), llm_client=client)

    assert result.overall_score == EXPECTED_OVERALL
    assert result.overall_reasoning == EXPECTED_OVERALL_REASONING
    assert len(result.criteria) == 5
    assert result.criteria[0].name == "Logic"
    assert result.strengths == ["Logic chat che"]
    assert client.call_count == 1


def test_markdown_fenced_json_is_stripped():
    fenced = "```json\n" + json.dumps(VALID_PAYLOAD) + "\n```"
    client = FakeLLMClient([fenced])
    result = evaluate_argument(_sample_request(), llm_client=client)

    assert result.overall_score == EXPECTED_OVERALL
    assert client.call_count == 1


def test_overall_score_always_computed_via_formula():
    """
    overall_score LUON duoc tinh bang cong thuc (tong 5 tieu chi / 25) * 10 tu
    "criteria" — KHONG con la field bat buoc trong JSON LLM tra ve (khac voi
    thiet ke holistic doc lap truoc day). VALID_PAYLOAD khong co "overall_score"
    va van phai cho ra ket qua dung.
    """
    assert "overall_score" not in VALID_PAYLOAD
    client = FakeLLMClient([json.dumps(VALID_PAYLOAD)])

    result = evaluate_argument(_sample_request(), llm_client=client)

    assert result.overall_score == EXPECTED_OVERALL
    assert client.call_count == 1


def test_overall_score_ignores_ai_provided_value():
    """
    Neu LLM van tra ve 1 field "overall_score" rieng (du khong duoc yeu cau),
    gia tri do PHAI bi BO QUA hoan toan — ket qua cuoi cung LUON la gia tri tinh
    tu cong thuc, khong bao gio la gia tri AI tu dua ra. Dung criteria khac
    VALID_CRITERIA (tat ca deu 3/5 -> formula = 15/25*10 = 6.0) de dam bao gia
    tri "AI tu cham" (9.9) khac han gia tri cong thuc, tranh trung hop ngau nhien.
    """
    criteria_all_average = [
        {"name": "Logic", "score": 3, "reasoning": "Trung binh."},
        {"name": "Evidence", "score": 3, "reasoning": "Trung binh."},
        {"name": "Relevance", "score": 3, "reasoning": "Trung binh."},
        {"name": "Structure", "score": 3, "reasoning": "Trung binh."},
        {"name": "Persuasiveness", "score": 3, "reasoning": "Trung binh."},
    ]
    payload = {
        "criteria": criteria_all_average,
        "overall_score": 9.9,  # gia tri AI "tu bia" — PHAI bi bo qua
        "overall_reasoning": EXPECTED_OVERALL_REASONING,
        "strengths": [], "weaknesses": [], "suggestions": [],
    }
    client = FakeLLMClient([json.dumps(payload)])

    result = evaluate_argument(_sample_request(), llm_client=client)

    assert result.overall_score == 6.0  # (3+3+3+3+3)/25*10 = 6.0, KHONG PHAI 9.9


def test_missing_overall_reasoning_triggers_retry_then_raises():
    """
    overall_reasoning van la field BAT BUOC (gio la nhan xet TONG HOP ve 5 tieu
    chi, khong con giai thich cho 1 overall_score AI tu cham), giu nguyen tac
    Chain-of-Thought ap dung cho tung tieu chi con (CriterionScore.reasoning).
    Neu LLM quen tra ve field nay, phai duoc coi la loi dinh dang JSON va kich
    hoat retry, KHONG duoc tu bia 1 cau reasoning mac dinh de lap vao.
    """
    payload = dict(VALID_PAYLOAD)
    del payload["overall_reasoning"]
    client = FakeLLMClient([json.dumps(payload), json.dumps(payload)])

    with pytest.raises(EvaluationParseError):
        evaluate_argument(_sample_request(), llm_client=client)

    assert client.call_count == 2  # xac nhan da retry, khong tu bia reasoning


def test_blank_overall_reasoning_triggers_retry_then_raises():
    """Chuoi rong cung phai bi coi nhu thieu — khong duoc chap nhan '' lam ly do hop le."""
    payload = dict(VALID_PAYLOAD)
    payload["overall_reasoning"] = ""
    client = FakeLLMClient([json.dumps(payload), json.dumps(payload)])

    with pytest.raises(EvaluationParseError):
        evaluate_argument(_sample_request(), llm_client=client)


def test_missing_overall_reasoning_recovers_if_retry_succeeds():
    payload_missing = dict(VALID_PAYLOAD)
    del payload_missing["overall_reasoning"]
    client = FakeLLMClient([json.dumps(payload_missing), json.dumps(VALID_PAYLOAD)])

    result = evaluate_argument(_sample_request(), llm_client=client)

    assert result.overall_reasoning == EXPECTED_OVERALL_REASONING
    assert client.call_count == 2


def test_retries_once_then_succeeds():
    client = FakeLLMClient([
        "day khong phai JSON, model bi loi dinh dang",
        json.dumps(VALID_PAYLOAD),
    ])
    result = evaluate_argument(_sample_request(), llm_client=client)

    assert result.overall_score == EXPECTED_OVERALL
    assert client.call_count == 2  # xac nhan da retry dung 1 lan


def test_fails_after_two_invalid_attempts():
    client = FakeLLMClient([
        "khong phai json lan 1",
        "khong phai json lan 2",
    ])
    with pytest.raises(EvaluationParseError):
        evaluate_argument(_sample_request(), llm_client=client)

    assert client.call_count == 2


def test_wrong_number_of_criteria_raises_after_retries():
    bad_payload = dict(VALID_PAYLOAD)
    bad_payload["criteria"] = VALID_CRITERIA[:3]  # thieu 2 tieu chi
    client = FakeLLMClient([json.dumps(bad_payload), json.dumps(bad_payload)])

    with pytest.raises(EvaluationParseError):
        evaluate_argument(_sample_request(), llm_client=client)


def test_request_rejects_blank_argument_text():
    with pytest.raises(ValidationError):
        ArgumentEvaluationRequest(
            motion="THBT social media does more harm than good",
            side=DebateSide.PRO,
            argument_text="   ",
        )


def test_criterion_score_out_of_range_is_rejected():
    """
    overall_score gio khong con doc truc tiep tu LLM nen khong the "vuot thang
    0-10" theo kieu cu (cong thuc luon cho ra gia tri trong [2.0, 10.0] vi moi
    tieu chi con bi CriterionScore rang buoc 1-5). Bien the con lai dang kiem
    chung duoc: neu 1 tieu chi con co score ngoai thang 1-5 (vi du 6), pydantic
    ValidationError phai duoc call_llm_with_retry bat va kich hoat retry.
    """
    bad_payload = dict(VALID_PAYLOAD)
    bad_criteria = [dict(c) for c in VALID_CRITERIA]
    bad_criteria[0]["score"] = 6  # vuot thang 1-5
    bad_payload["criteria"] = bad_criteria
    client = FakeLLMClient([json.dumps(bad_payload), json.dumps(bad_payload)])

    with pytest.raises(EvaluationParseError):
        evaluate_argument(_sample_request(), llm_client=client)

    assert client.call_count == 2


def test_infer_argument_context_from_opponent_argument_text():
    """
    ArgumentContext PHAI duoc suy tu opponent_argument_text co/khong co gia tri,
    KHONG duoc suy tu stage — vi trong debate that, speaker o stage "opening" cua
    phe thu 2 van co the co noi dung phe truoc de phan hoi (xem evaluator_prompt.py).
    """
    req_no_opponent = ArgumentEvaluationRequest(
        motion="THBT social media does more harm than good",
        side=DebateSide.PRO,
        stage=DebateStage.OPENING,
        argument_text="Mot bai mo dau doc lap, khong co doi phuong.",
        opponent_argument_text=None,
    )
    req_with_opponent = ArgumentEvaluationRequest(
        motion="THBT social media does more harm than good",
        side=DebateSide.PRO,
        stage=DebateStage.OPENING,  # CUNG la stage "opening" nhu tren, chi khac o co/khong opponent
        argument_text="Mot bai mo dau nhung van co doi phuong de phan hoi.",
        opponent_argument_text="Lap luan cua phe truoc.",
    )

    assert infer_argument_context(req_no_opponent) == ArgumentContext.SOLO
    assert infer_argument_context(req_with_opponent) == ArgumentContext.INTERACTIVE


def test_system_prompt_omits_opponent_rebuttal_when_no_opponent():
    """Khi KHONG co opponent_argument_text, prompt sinh ra khong duoc nhac den
    viec phan bien doi phuong trong mo ta tieu chi Relevance."""
    req = ArgumentEvaluationRequest(
        motion="THBT social media does more harm than good",
        side=DebateSide.PRO,
        stage=DebateStage.OPENING,
        argument_text="Mot bai mo dau doc lap, khong co doi phuong.",
        opponent_argument_text=None,
    )
    system_prompt, _ = build_evaluation_prompt(req)

    assert "phan bien" not in system_prompt.lower() or "doi phuong" not in system_prompt.lower()


def test_system_prompt_includes_opponent_rebuttal_when_opponent_present():
    """Khi CO opponent_argument_text, prompt sinh ra PHAI con nhac den viec phan
    bien dung luan diem doi phuong trong mo ta tieu chi Relevance."""
    req = ArgumentEvaluationRequest(
        motion="THBT social media does more harm than good",
        side=DebateSide.PRO,
        stage=DebateStage.REBUTTAL,
        argument_text="Mot luot phan bien co doi phuong.",
        opponent_argument_text="Lap luan cua doi phuong.",
    )
    system_prompt, _ = build_evaluation_prompt(req)

    assert "phan bien" in system_prompt.lower() and "doi phuong" in system_prompt.lower()
