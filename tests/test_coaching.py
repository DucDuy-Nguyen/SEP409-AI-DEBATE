"""
Test logic chon tieu chi + parse/validate cua app/services/coaching.py bang
FakeLLMClient — KHONG goi API that. Chay bang: pytest tests/
"""
import json
import os

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder-not-real")

from fastapi.testclient import TestClient

from app.main import app
from app.prompts.coaching_prompt import build_coaching_prompt, build_round_coaching_prompt
from app.schemas import (
    ArgumentCoachingRequest,
    ArgumentEvaluationRequest,
    ArgumentEvaluationResult,
    ArgumentTurn,
    CriterionScore,
    DebateSide,
    DebateStage,
    RoundCoachingRequest,
    RoundEvaluationRequest,
    RoundEvaluationResult,
    TurnSpeaker,
)
from app.services.coaching import EvaluationParseError, _select_focus_criteria, coach_argument, coach_round
from app.services.llm_client import LLMClient

CRITERIA_NAMES = ["Logic", "Evidence", "Relevance", "Structure", "Persuasiveness"]


class FakeLLMClient(LLMClient):
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.call_count = 0

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        if not self._responses:
            raise RuntimeError("FakeLLMClient: het response da chuan bi san")
        return self._responses.pop(0)


def _evaluation(scores: list[int]) -> ArgumentEvaluationResult:
    criteria = [
        CriterionScore(name=name, score=score, reasoning=f"Nhan xet {name}.")
        for name, score in zip(CRITERIA_NAMES, scores)
    ]
    return ArgumentEvaluationResult(
        overall_score=round(sum(scores) / 25 * 10, 2),
        overall_reasoning="Lap luan dung de tai nhung thieu bang chung.",
        criteria=criteria,
        weaknesses=["Thieu so lieu cu the"],
    )


def _coaching_request(scores: list[int], opponent: str | None = "Mang xa hoi giup ket noi.") -> ArgumentCoachingRequest:
    return ArgumentCoachingRequest(
        request=ArgumentEvaluationRequest(
            motion="THBT mang xa hoi gay hai nhieu hon loi",
            side=DebateSide.PRO,
            stage=DebateStage.REBUTTAL,
            argument_text="Mang xa hoi lam giam tuong tac truc tiep, gay suy giam ky nang giao tiep.",
            opponent_argument_text=opponent,
        ),
        evaluation=_evaluation(scores),
    )


def _payload(names: list[str]) -> dict:
    return {
        "focus_criteria": [
            {
                "name": name,
                "current_score": 5,  # so LLM tu bia — PHAI bi bo qua
                "diagnosis": f"Van de {name}.",
                "methods": ["Phuong phap 1", "Phuong phap 2"],
                "application": f"Ap dung cho {name}.",
            }
            for name in names
        ],
        "idea_development": {
            "core_claim": "Mang xa hoi lam suy giam ky nang giao tiep truc tiep.",
            "directions": ["Giai thich co che", "Phan tich tac dong len gioi tre"],
            "evidence_to_look_for": ["So lieu khao sat ve thoi gian dung mang xa hoi"],
        },
    }


def test_select_focus_picks_weak_criteria_sorted_and_capped():
    # Evidence=1, Logic=2, Structure=2, Persuasiveness=3 deu <= 3 -> lay 3 tieu chi thap nhat;
    # hoa diem (Logic, Structure = 2) thi theo thu tu RUBRIC.
    evaluation = _evaluation([2, 1, 4, 2, 3])

    focus = _select_focus_criteria(evaluation.criteria)

    assert [c.name for c in focus] == ["Evidence", "Logic", "Structure"]


def test_select_focus_picks_single_lowest_when_all_strong():
    evaluation = _evaluation([5, 4, 5, 5, 5])

    focus = _select_focus_criteria(evaluation.criteria)

    assert [c.name for c in focus] == ["Evidence"]


def test_valid_coaching_parsed_and_score_taken_from_evaluation():
    req = _coaching_request([2, 1, 4, 2, 3])
    client = FakeLLMClient([json.dumps(_payload(["Evidence", "Logic", "Structure"]))])

    result = coach_argument(req, llm_client=client)

    assert [c.name for c in result.focus_criteria] == ["Evidence", "Logic", "Structure"]
    # current_score lay tu ket qua cham (1, 2, 2), KHONG phai 5 ma LLM tra ve
    assert [c.current_score for c in result.focus_criteria] == [1, 2, 2]
    assert result.idea_development.core_claim
    assert client.call_count == 1


def test_wrong_criteria_names_trigger_retry_then_raise():
    req = _coaching_request([2, 1, 4, 2, 3])
    wrong = json.dumps(_payload(["Logic", "Relevance"]))  # sai va thieu so voi focus
    client = FakeLLMClient([wrong, wrong])

    with pytest.raises(EvaluationParseError):
        coach_argument(req, llm_client=client)

    assert client.call_count == 2


def test_missing_core_claim_triggers_retry_then_raise():
    req = _coaching_request([2, 1, 4, 2, 3])
    payload = _payload(["Evidence", "Logic", "Structure"])
    payload["idea_development"]["core_claim"] = ""
    client = FakeLLMClient([json.dumps(payload), json.dumps(payload)])

    with pytest.raises(EvaluationParseError):
        coach_argument(req, llm_client=client)

    assert client.call_count == 2


def test_solo_prompt_omits_opponent_rebuttal_and_forbids_rewriting():
    req = _coaching_request([2, 1, 4, 2, 3], opponent=None)

    system_prompt, user_prompt = build_coaching_prompt(req, ["Evidence", "Logic", "Structure"])

    assert "phan bien" not in system_prompt.lower() or "doi phuong" not in system_prompt.lower()
    assert "khong viet lai bai" in system_prompt.lower()
    assert "Evidence, Logic, Structure" in user_prompt


def test_api_rejects_evaluation_with_missing_criteria():
    client = TestClient(app)
    req = _coaching_request([2, 1, 4, 2, 3])
    body = json.loads(req.model_dump_json())
    body["evaluation"]["criteria"] = body["evaluation"]["criteria"][:4]

    response = client.post("/coaching/argument", json=body)

    assert response.status_code == 422


def test_api_rejects_invalid_side():
    client = TestClient(app)
    body = json.loads(_coaching_request([2, 1, 4, 2, 3]).model_dump_json())
    body["request"]["side"] = "team_a"

    response = client.post("/coaching/argument", json=body)

    assert response.status_code == 422


# ============================================================================
# Round-level: /coaching/round
# ============================================================================

def _round_coaching_request(scores: list[int], with_opponent: bool = True) -> RoundCoachingRequest:
    turns = [ArgumentTurn(speaker=TurnSpeaker.LEARNER, text="Ket noi so luong khong dong nghia chat luong.")]
    if with_opponent:
        turns = [ArgumentTurn(speaker=TurnSpeaker.OPPONENT, text="Mang xa hoi giup ket noi.")] + turns
    criteria = [
        CriterionScore(name=name, score=score, reasoning=f"Nhan xet {name}.")
        for name, score in zip(CRITERIA_NAMES, scores)
    ]
    return RoundCoachingRequest(
        request=RoundEvaluationRequest(
            motion="THBT mang xa hoi gay hai nhieu hon loi",
            side=DebateSide.PRO,
            stage=DebateStage.REBUTTAL,
            turns=turns,
        ),
        evaluation=RoundEvaluationResult(
            stage=DebateStage.REBUTTAL,
            round_score=round(sum(scores) / 25 * 10, 2),
            criteria=criteria,
            consistency_note="Giu vung lap truong xuyen suot round.",
            weaknesses=["Thieu bang chung"],
        ),
    )


def test_round_coaching_parsed_and_score_taken_from_evaluation():
    req = _round_coaching_request([3, 1, 4, 4, 2])  # Evidence=1, Persuasiveness=2, Logic=3
    client = FakeLLMClient([json.dumps(_payload(["Evidence", "Persuasiveness", "Logic"]))])

    result = coach_round(req, llm_client=client)

    assert [c.name for c in result.focus_criteria] == ["Evidence", "Persuasiveness", "Logic"]
    assert [c.current_score for c in result.focus_criteria] == [1, 2, 3]
    assert client.call_count == 1


def test_round_coaching_wrong_criteria_triggers_retry_then_raise():
    req = _round_coaching_request([3, 1, 4, 4, 2])
    wrong = json.dumps(_payload(["Logic"]))
    client = FakeLLMClient([wrong, wrong])

    with pytest.raises(EvaluationParseError):
        coach_round(req, llm_client=client)

    assert client.call_count == 2


def test_round_coaching_prompt_solo_vs_interactive():
    focus = ["Evidence", "Persuasiveness", "Logic"]
    solo_prompt, _ = build_round_coaching_prompt(_round_coaching_request([3, 1, 4, 4, 2], with_opponent=False), focus)
    interactive_prompt, _ = build_round_coaching_prompt(_round_coaching_request([3, 1, 4, 4, 2]), focus)

    assert "phan bien" not in solo_prompt.lower() or "doi phuong" not in solo_prompt.lower()
    assert "doi phuong" in interactive_prompt.lower()
    assert "khong viet lai bai" in solo_prompt.lower()


def test_round_coaching_api_rejects_stage_mismatch():
    client = TestClient(app)
    body = json.loads(_round_coaching_request([3, 1, 4, 4, 2]).model_dump_json())
    body["evaluation"]["stage"] = "closing"  # ket qua cua round khac

    response = client.post("/coaching/round", json=body)

    assert response.status_code == 422


def test_round_coaching_api_rejects_missing_criteria():
    client = TestClient(app)
    body = json.loads(_round_coaching_request([3, 1, 4, 4, 2]).model_dump_json())
    body["evaluation"]["criteria"] = body["evaluation"]["criteria"][:3]

    response = client.post("/coaching/round", json=body)

    assert response.status_code == 422
