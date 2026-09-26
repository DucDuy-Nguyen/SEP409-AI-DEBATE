"""
Test logic tinh toan + tong hop cua session_evaluator.py.
"""
import json

import pytest

from app.schemas import CriterionScore, DebateSide, DebateStage, RoundEvaluationResult, SessionEvaluationRequest
from app.services.llm_client import LLMClient
from app.services.session_evaluator import EvaluationParseError, evaluate_session

VALID_SESSION_PAYLOAD = {
    "progress_trend": "Learner cai thien ro ret tu Opening sang Rebuttal, nhung giam nhe o Closing.",
    "overall_strengths": ["Nhat quan lap truong xuyen suot phien"],
    "overall_weaknesses": ["Thieu bang chung o hau het cac round"],
    "overall_suggestions": ["Tap trung them so lieu cu the cho lan luyen tap sau"],
}


class FakeLLMClient(LLMClient):
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.call_count = 0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        if not self._responses:
            raise RuntimeError("FakeLLMClient: het response da chuan bi san")
        return self._responses.pop(0)


def _make_round(stage: DebateStage, round_score: float) -> RoundEvaluationResult:
    criteria = [
        CriterionScore(name="Logic", score=4, reasoning="ok"),
        CriterionScore(name="Evidence", score=3, reasoning="ok"),
        CriterionScore(name="Relevance", score=4, reasoning="ok"),
        CriterionScore(name="Structure", score=4, reasoning="ok"),
        CriterionScore(name="Persuasiveness", score=3, reasoning="ok"),
    ]
    return RoundEvaluationResult(
        stage=stage,
        round_score=round_score,
        criteria=criteria,
        consistency_note="Giu vung lap truong.",
        strengths=["diem manh"],
        weaknesses=["diem yeu"],
        suggestions=["goi y"],
    )


def _sample_session_request() -> SessionEvaluationRequest:
    return SessionEvaluationRequest(
        motion="THBT mang xa hoi gay hai nhieu hon loi",
        side=DebateSide.PRO,
        rounds=[
            _make_round(DebateStage.OPENING, 6.0),
            _make_round(DebateStage.REBUTTAL, 8.0),
            _make_round(DebateStage.CLOSING, 7.0),
        ],
    )


def test_overall_score_is_average_of_round_scores():
    client = FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)])
    result = evaluate_session(_sample_session_request(), llm_client=client)

    assert result.overall_score == 7.0
    assert client.call_count == 1


def test_stage_breakdown_maps_each_stage_correctly():
    client = FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)])
    result = evaluate_session(_sample_session_request(), llm_client=client)

    assert result.stage_breakdown == {"opening": 6.0, "rebuttal": 8.0, "closing": 7.0}


def test_stage_breakdown_averages_duplicate_stage():
    req = SessionEvaluationRequest(
        motion="THBT mang xa hoi gay hai nhieu hon loi",
        side=DebateSide.PRO,
        rounds=[
            _make_round(DebateStage.REBUTTAL, 6.0),
            _make_round(DebateStage.REBUTTAL, 8.0),
        ],
    )
    client = FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)])
    result = evaluate_session(req, llm_client=client)

    assert result.stage_breakdown == {"rebuttal": 7.0}
    assert result.overall_score == 7.0


def test_score_is_correct_even_if_llm_synthesis_fails_after_retries():
    client = FakeLLMClient(["khong phai json lan 1", "khong phai json lan 2"])

    with pytest.raises(EvaluationParseError):
        evaluate_session(_sample_session_request(), llm_client=client)

    assert client.call_count == 2


def test_missing_progress_trend_raises():
    payload = dict(VALID_SESSION_PAYLOAD)
    del payload["progress_trend"]
    client = FakeLLMClient([json.dumps(payload), json.dumps(payload)])

    with pytest.raises(EvaluationParseError):
        evaluate_session(_sample_session_request(), llm_client=client)
