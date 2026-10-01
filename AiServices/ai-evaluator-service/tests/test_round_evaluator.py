"""
Test logic parse/validate cua round_evaluator.py bang FakeLLMClient — KHONG goi
API that. Chay bang: pytest tests/
"""
import json

import pytest
from pydantic import ValidationError

from app.prompts.round_prompt import build_round_evaluation_prompt
from app.schemas import ArgumentTurn, DebateSide, DebateStage, RoundEvaluationRequest, TurnSpeaker
from app.services.llm_client import LLMClient
from app.services.round_evaluator import EvaluationParseError, evaluate_round

VALID_CRITERIA = [
    {"name": "Logic", "score": 4, "reasoning": "Giu vung lap truong xuyen suot round."},
    {"name": "Evidence", "score": 3, "reasoning": "Co mot vi du nhung chua manh."},
    {"name": "Relevance", "score": 5, "reasoning": "Phan bien dung diem doi phuong o ca 2 luot."},
    {"name": "Structure", "score": 4, "reasoning": "Cau truc ro rang qua cac luot."},
    {"name": "Persuasiveness", "score": 4, "reasoning": "Thuyet phuc, hoi thieu impact cu the."},
]
# round_score LUON duoc TINH BANG CONG THUC tu 5 tieu chi con (da ap dung dung
# nguyen tac cua overall_score o Argument-level — xem app/services/round_evaluator.py
# va docs/AI_DEVELOPMENT_LOG.md muc 3.8): (4+3+5+4+4)/25*10 = 8.0
EXPECTED_ROUND_SCORE = 8.0

# LUU Y: khong con "round_score" trong VALID_ROUND_PAYLOAD — field nay khong
# con bat buoc trong JSON tu LLM nua, vi round_score luon duoc code tu tinh tu
# "criteria", khong doc tu JSON.
VALID_ROUND_PAYLOAD = {
    "criteria": VALID_CRITERIA,
    "consistency_note": "Learner giu vung lap truong Pro xuyen suot round, khong bi lung lay.",
    "strengths": ["Nhat quan lap truong"],
    "weaknesses": ["Thieu bang chung o luot 2"],
    "suggestions": ["Them so lieu cho luot phan bien tiep theo"],
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


def _sample_round_request() -> RoundEvaluationRequest:
    return RoundEvaluationRequest(
        motion="THBT mang xa hoi gay hai nhieu hon loi",
        side=DebateSide.PRO,
        stage=DebateStage.REBUTTAL,
        turns=[
            ArgumentTurn(speaker=TurnSpeaker.OPPONENT, text="Mang xa hoi giup ket noi nguoi o xa nhau."),
            ArgumentTurn(speaker=TurnSpeaker.LEARNER, text="Ket noi so luong khong dong nghia chat luong."),
            ArgumentTurn(speaker=TurnSpeaker.OPPONENT, text="Nhung no van giup duy tri quan he."),
            ArgumentTurn(speaker=TurnSpeaker.LEARNER, text="Duy tri quan he ao khong thay the duoc tuong tac thuc."),
        ],
    )


def test_valid_round_json_parsed_correctly():
    client = FakeLLMClient([json.dumps(VALID_ROUND_PAYLOAD)])
    result = evaluate_round(_sample_round_request(), llm_client=client)

    assert result.round_score == EXPECTED_ROUND_SCORE
    assert len(result.criteria) == 5
    assert result.stage == DebateStage.REBUTTAL
    assert "giu vung lap truong" in result.consistency_note.lower()
    assert client.call_count == 1


def test_round_score_always_computed_via_formula():
    """
    round_score LUON duoc tinh bang cong thuc (tong 5 tieu chi / 25) * 10 tu
    "criteria" — KHONG con la field bat buoc trong JSON LLM tra ve (khac voi
    thiet ke truoc day cho phep AI tu tra ve gia tri rieng). VALID_ROUND_PAYLOAD
    khong co "round_score" va van phai cho ra ket qua dung.
    """
    assert "round_score" not in VALID_ROUND_PAYLOAD
    client = FakeLLMClient([json.dumps(VALID_ROUND_PAYLOAD)])

    result = evaluate_round(_sample_round_request(), llm_client=client)

    expected = round(sum(c["score"] for c in VALID_CRITERIA) / (len(VALID_CRITERIA) * 5) * 10, 2)
    assert result.round_score == expected == EXPECTED_ROUND_SCORE
    assert client.call_count == 1


def test_round_score_ignores_ai_provided_value():
    """
    Neu LLM van tra ve 1 field "round_score" rieng (du khong duoc yeu cau),
    gia tri do PHAI bi BO QUA hoan toan — ket qua cuoi cung LUON la gia tri
    tinh tu cong thuc. Dung chinh xac tinh huong da xay ra thuc te: AI tra ve
    round_score=14.0 (vuot thang 0-10) gay ValidationError phai retry — gio
    gia tri nay phai bi bo qua thay vi lam hong ket qua.
    """
    payload = dict(VALID_ROUND_PAYLOAD)
    payload["round_score"] = 14.0  # gia tri AI "tu bia", vuot ca thang 0-10 — PHAI bi bo qua
    client = FakeLLMClient([json.dumps(payload)])

    result = evaluate_round(_sample_round_request(), llm_client=client)

    assert result.round_score == EXPECTED_ROUND_SCORE  # 8.0, KHONG PHAI 14.0
    assert client.call_count == 1  # khong retry vi khong doc/validate round_score tu JSON


def test_round_missing_consistency_note_raises():
    payload = dict(VALID_ROUND_PAYLOAD)
    del payload["consistency_note"]
    client = FakeLLMClient([json.dumps(payload), json.dumps(payload)])

    with pytest.raises(EvaluationParseError):
        evaluate_round(_sample_round_request(), llm_client=client)


def test_round_requires_at_least_one_learner_turn():
    with pytest.raises(ValidationError):
        RoundEvaluationRequest(
            motion="THBT mang xa hoi gay hai nhieu hon loi",
            side=DebateSide.PRO,
            stage=DebateStage.REBUTTAL,
            turns=[ArgumentTurn(speaker=TurnSpeaker.OPPONENT, text="Chi co doi phuong noi.")],
        )


def test_round_requires_at_least_one_turn():
    with pytest.raises(ValidationError):
        RoundEvaluationRequest(
            motion="THBT mang xa hoi gay hai nhieu hon loi",
            side=DebateSide.PRO,
            stage=DebateStage.REBUTTAL,
            turns=[],
        )


def test_round_system_prompt_omits_opponent_rebuttal_when_no_opponent_turn():
    """
    Round CHI co luot LEARNER (khong co luot OPPONENT nao) -> ArgumentContext.SOLO
    -> prompt sinh ra KHONG duoc nhac den viec phan bien doi phuong trong mo ta
    tieu chi Relevance. Day chinh la sua loi hallucination da ghi trong
    docs/AI_DEVELOPMENT_LOG.md muc 3.4 (case S01/S03: round Closing chi co 1
    luot noi, AI bi "thieu ngu canh" nen bia noi dung khong ton tai).
    """
    req = RoundEvaluationRequest(
        motion="THBT mang xa hoi gay hai nhieu hon loi",
        side=DebateSide.PRO,
        stage=DebateStage.CLOSING,
        turns=[ArgumentTurn(speaker=TurnSpeaker.LEARNER, text="Tom lai, mang xa hoi gay hai nhieu hon loi.")],
    )
    system_prompt, _ = build_round_evaluation_prompt(req)

    assert "phan bien" not in system_prompt.lower() or "doi phuong" not in system_prompt.lower()


def test_round_system_prompt_includes_opponent_rebuttal_when_opponent_turn_present():
    """Round CO it nhat 1 luot OPPONENT trong turns -> ArgumentContext.INTERACTIVE
    -> prompt sinh ra PHAI con nhac den viec phan bien dung luan diem doi phuong."""
    system_prompt, _ = build_round_evaluation_prompt(_sample_round_request())

    assert "phan bien" in system_prompt.lower() and "doi phuong" in system_prompt.lower()
