"""
Test logic tinh toan + tong hop cua session_evaluator.py.
"""
import json

import pytest
from pydantic import ValidationError

from app.prompts.session_prompt import SESSION_SYSTEM_PROMPT, build_session_evaluation_prompt
from app.schemas import (
    SCORING_VERSION_CURRENT,
    CriterionScore,
    DebateSide,
    DebateStage,
    RoundEvaluationResult,
    SessionEvaluationRequest,
)
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


def test_session_accepts_mixed_scoring_versions_and_pins_to_the_first_round():
    """Session KHONG tu choi (422) khi cac round khac scoring_version: ghim theo round DAU TIEN (quyet dinh o muc 3.15)."""
    old = _make_round(DebateStage.OPENING, 6.0).model_copy(update={"scoring_version": "v1_5x20"})
    new = _make_round(DebateStage.REBUTTAL, 8.0).model_copy(update={"scoring_version": "v2_4x25"})

    req = SessionEvaluationRequest(motion="m", side=DebateSide.PRO, rounds=[old, new])  # khong nem ValidationError
    result = evaluate_session(req, llm_client=FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)]))
    assert result.scoring_version == "v1_5x20"
    assert result.overall_score == 7.0  # van la trung binh round_score cua ca hai round

    req_reversed = SessionEvaluationRequest(motion="m", side=DebateSide.PRO, rounds=[new, old])
    result_reversed = evaluate_session(req_reversed, llm_client=FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)]))
    assert result_reversed.scoring_version == "v2_4x25"


def test_session_result_carries_the_common_scoring_version_and_missing_means_legacy():
    new_rounds = [
        _make_round(DebateStage.OPENING, 6.0).model_copy(update={"scoring_version": "v2_4x25"}),
        _make_round(DebateStage.REBUTTAL, 8.0).model_copy(update={"scoring_version": "v2_4x25"}),
    ]
    client = FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)])
    result = evaluate_session(SessionEvaluationRequest(motion="m", side=DebateSide.PRO, rounds=new_rounds), llm_client=client)
    assert result.scoring_version == "v2_4x25"

    # ban ghi round cu khong co truong scoring_version -> mac dinh la ban cu
    legacy = RoundEvaluationResult.model_validate(
        {k: v for k, v in json.loads(_make_round(DebateStage.OPENING, 6.0).model_dump_json()).items() if k != "scoring_version"}
    )
    assert legacy.scoring_version == "v1_5x20"


# ---- skipped_stages (docs/AI_DEVELOPMENT_LOG.md muc 3.18) ----


def _request_skipping_rebuttal() -> SessionEvaluationRequest:
    return SessionEvaluationRequest(
        motion="THBT mang xa hoi gay hai nhieu hon loi",
        side=DebateSide.PRO,
        rounds=[_make_round(DebateStage.OPENING, 7.0), _make_round(DebateStage.CLOSING, 8.0)],
        skipped_stages=[DebateStage.REBUTTAL],
    )


def test_skipped_stage_counts_as_zero_in_overall_score_only():
    client = FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)])

    result = evaluate_session(_request_skipping_rebuttal(), llm_client=client)

    assert result.overall_score == 5.0
    assert result.stage_breakdown == {"opening": 7.0, "closing": 8.0}
    assert result.skipped_stages == [DebateStage.REBUTTAL]


def test_two_skipped_stages_divide_by_three():
    request = SessionEvaluationRequest(
        motion="M", side=DebateSide.PRO, rounds=[_make_round(DebateStage.CLOSING, 8.0)],
        skipped_stages=[DebateStage.OPENING, DebateStage.REBUTTAL],
    )

    result = evaluate_session(request, llm_client=FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)]))

    assert result.overall_score == 2.67


def test_without_skipped_stages_score_response_and_prompts_are_unchanged():
    request = _sample_session_request()

    result = evaluate_session(request, llm_client=FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)]))
    system_prompt, user_prompt = build_session_evaluation_prompt(request)

    assert result.overall_score == 7.0
    assert result.skipped_stages == []
    assert system_prompt == SESSION_SYSTEM_PROMPT
    assert "GIAI DOAN BO TRONG" not in user_prompt


def test_prompts_name_the_skipped_stage_and_forbid_inventing_its_content():
    system_prompt, user_prompt = build_session_evaluation_prompt(_request_skipping_rebuttal())

    assert "[GIAI DOAN BO TRONG] Phan bien" in user_prompt
    assert "KHONG duoc suy dien" in system_prompt


def test_scoring_version_still_follows_the_first_round():
    round_result = _make_round(DebateStage.CLOSING, 8.0).model_copy(update={"scoring_version": SCORING_VERSION_CURRENT})
    request = SessionEvaluationRequest(
        motion="M", side=DebateSide.PRO, rounds=[round_result], skipped_stages=[DebateStage.OPENING]
    )

    result = evaluate_session(request, llm_client=FakeLLMClient([json.dumps(VALID_SESSION_PAYLOAD)]))

    assert result.scoring_version == SCORING_VERSION_CURRENT


@pytest.mark.parametrize(
    "skipped,message",
    [
        (["rebuttal", "rebuttal"], "trung"),
        (["opening"], "da co trong rounds"),
        (["khong_ton_tai"], "skipped_stages"),
    ],
)
def test_invalid_skipped_stages_are_rejected(skipped, message):
    with pytest.raises(ValidationError, match=message):
        SessionEvaluationRequest(
            motion="M", side=DebateSide.PRO, rounds=[_make_round(DebateStage.OPENING, 7.0)], skipped_stages=skipped
        )
