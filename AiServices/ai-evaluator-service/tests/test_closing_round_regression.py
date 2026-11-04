"""
Test hoi quy tu phien that (DebateSessionId 13, learner = PRO, vong Closing CON -> PRO).

3 nhom:
- Offline, PASS: xac nhan learner duoc gan dung luot o moi thu tu noi (loai tru nghi van "gan nham luot").
- Offline, fix A da ap dung (muc 3.16 cua dev log; fix C da revert, muc 3.17).
- Offline, xfail(strict): dac ta fix D, CHUA lam theo quyet dinh. Khi lam, test se XPASS -> strict bao fail, luc do
  bo marker xfail.
- Live (RUN_LIVE_LLM=1): goi LLM that, ton token, mac dinh skip. Chay: RUN_LIVE_LLM=1 python -m pytest tests/test_closing_round_regression.py -k live -s
"""
import json
import os
import re
import unicodedata
from pathlib import Path

import pytest

from app.prompts.evaluator_prompt import RUBRIC
from app.prompts.round_prompt import build_round_evaluation_prompt
from app.prompts.session_prompt import build_session_user_prompt
from app.schemas import (
    ArgumentTurn,
    CriterionScore,
    DebateSide,
    DebateStage,
    RoundEvaluationRequest,
    RoundEvaluationResult,
    SessionEvaluationRequest,
    TurnSpeaker,
)
from app.services.llm_client import LLMClient
from app.services.round_evaluator import evaluate_round

SESSION = json.loads((Path(__file__).parent / "fixtures" / "session13_ai_regulation.json").read_text(encoding="utf-8"))

# Nhan xet learner "khong phan hoi" doi phuong; LLM viet tieng Viet co dau.
_NO_RESPONSE_RE = re.compile(r"(chưa|không)\s+(được\s+)?(phản hồi|trả lời)", re.IGNORECASE)


def _fold(text: str) -> str:
    """Bo dau, de test dac ta khong phu thuoc prompt/rubric viet co dau hay khong dau."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _round_request(stage: str) -> RoundEvaluationRequest:
    return RoundEvaluationRequest(
        motion=SESSION["motion"],
        side=DebateSide.PRO,
        stage=DebateStage(stage),
        turns=[
            ArgumentTurn(speaker=TurnSpeaker(t["speaker"]), text=t["text"]) for t in SESSION["turns"] if t["stage"] == stage
        ],
    )


def _turn_text(stage: str, speaker: str) -> str:
    return next(t["text"] for t in SESSION["turns"] if t["stage"] == stage and t["speaker"] == speaker)


def _no_response_claims(result: RoundEvaluationResult) -> list[str]:
    return [w for w in result.weaknesses if _NO_RESPONSE_RE.search(w)]


class CapturingLLMClient(LLMClient):
    def __init__(self, response: str):
        self.response = response
        self.user_prompts: list[str] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.user_prompts.append(user_prompt)
        return self.response


VALID_RESPONSE = json.dumps(
    {
        "criteria": [
            {"name": c["name"], "score": 4, "reasoning": "Luan diem ro rang."} for c in RUBRIC
        ],
        "consistency_note": "Giu vung lap truong.",
        "strengths": ["Phan bac dung trong tam"],
        "weaknesses": ["Phản biện của đối phương chưa được phản hồi cụ thể."],
        "suggestions": ["Trich dan nguon"],
    }
)


# ---- Offline, dang PASS: khong co loi gan nham luot ----


def test_fixture_closing_is_con_then_pro():
    assert [(t["side"], t["speaker"]) for t in SESSION["turns"] if t["stage"] == "closing"] == [
        ("con", "opponent"),
        ("pro", "learner"),
    ]


@pytest.mark.parametrize(
    "stage,first,second",
    [("closing", "DOI PHUONG", "LEARNER"), ("rebuttal", "LEARNER", "DOI PHUONG")],
)
def test_each_turn_keeps_its_speaker_label_regardless_of_order(stage, first, second):
    _, user_prompt = build_round_evaluation_prompt(_round_request(stage))
    by_label = {"LEARNER": "learner", "DOI PHUONG": "opponent"}

    sides = {"LEARNER": "LEARNER (phe Pro)", "DOI PHUONG": "DOI PHUONG (phe Con)"}

    assert f"Luot 1 - {sides[first]}: {_turn_text(stage, by_label[first])}" in user_prompt
    assert f"Luot 2 - {sides[second]}: {_turn_text(stage, by_label[second])}" in user_prompt


def test_closing_is_graded_as_learner_turn_through_the_service():
    client = CapturingLLMClient(VALID_RESPONSE)

    result = evaluate_round(_round_request("closing"), llm_client=client)

    assert result.stage == DebateStage.CLOSING
    assert result.round_score == 8.0
    assert f"Luot 2 - LEARNER (phe Pro): {_turn_text('closing', 'learner')}" in client.user_prompts[0]
    assert f"LEARNER (phe Pro): {_turn_text('closing', 'opponent')}" not in client.user_prompts[0]


def test_session_prompt_never_receives_the_transcript():
    round_result = RoundEvaluationResult(
        stage=DebateStage.CLOSING,
        round_score=8.0,
        criteria=[CriterionScore(name=c["name"], score=4, reasoning="x") for c in RUBRIC],
        consistency_note="Giu vung lap truong.",
    )

    prompt = build_session_user_prompt(
        SessionEvaluationRequest(motion=SESSION["motion"], side=DebateSide.PRO, rounds=[round_result])
    )

    for turn in SESSION["turns"]:
        assert turn["text"] not in prompt


def test_closing_payload_lacks_the_round_2_statement_the_learner_refutes():
    # Learner trich "kiem duyet AI y te" tu bai rebuttal cua CON; payload closing khong co cau goc de doi chieu.
    assert "y tế" in _turn_text("rebuttal", "opponent")

    turns = _round_request("closing").turns

    assert "y tế" in next(t.text for t in turns if t.speaker == TurnSpeaker.LEARNER)
    assert "y tế" not in next(t.text for t in turns if t.speaker == TurnSpeaker.OPPONENT)
    assert _turn_text("rebuttal", "opponent") not in [t.text for t in turns]


def test_detector_catches_the_real_false_claim():
    claim = "Một số phản biện của đối phương (về chi phí tuân thủ cho doanh nghiệp nhỏ) chưa được phản hồi cụ thể."
    assert _NO_RESPONSE_RE.search(claim)
    assert not _NO_RESPONSE_RE.search("Thiếu bằng chứng, số liệu cụ thể")


# ---- Offline: fix A da ap dung; rieng test Evidence cuoi nhom la xfail(strict) vi fix D chua lam ----


def test_prompt_names_the_opponent_side():
    _, user_prompt = build_round_evaluation_prompt(_round_request("closing"))
    assert "phan doi (con)" in _fold(user_prompt)


@pytest.mark.parametrize("stage,order", [("closing", "DOI PHUONG -> LEARNER"), ("rebuttal", "LEARNER -> DOI PHUONG")])
def test_prompt_states_the_speaking_order(stage, order):
    _, user_prompt = build_round_evaluation_prompt(_round_request(stage))
    assert f"[THU TU NOI] {order}" in user_prompt


def test_prompt_exempts_opponent_turn_spoken_after_the_learner():
    system_prompt, user_prompt = build_round_evaluation_prompt(_round_request("rebuttal"))
    assert "chua co co hoi tra loi" in _fold(system_prompt + user_prompt)


@pytest.mark.xfail(strict=True, reason="CHUA lam theo quyet dinh (dev log 3.14.2, 3.16): Evidence neu ro hiep uoc/su kien la dan chung hop le")
def test_evidence_rubric_accepts_named_precedents():
    evidence = _fold(next(c for c in RUBRIC if c["name"] == "Evidence")["description"])
    assert "hiep uoc" in evidence and "su kien" in evidence


# ---- Live: goi LLM that ----


@pytest.mark.skipif(os.environ.get("RUN_LIVE_LLM") != "1", reason="Goi LLM that, ton token: dat RUN_LIVE_LLM=1 de chay")
def test_live_closing_not_lower_than_rebuttal_and_no_false_no_response_claim():
    runs = int(os.environ.get("LIVE_RUNS", "3"))  # 1 lan cham dao dong ~0.6 diem, chi so sanh trung binh
    closing = [evaluate_round(_round_request("closing")) for _ in range(runs)]
    rebuttal = [evaluate_round(_round_request("rebuttal")) for _ in range(runs)]

    closing_mean = sum(r.round_score for r in closing) / runs
    rebuttal_mean = sum(r.round_score for r in rebuttal) / runs
    claims = [c for r in rebuttal for c in _no_response_claims(r)]
    print(f"closing={[r.round_score for r in closing]} rebuttal={[r.round_score for r in rebuttal]} claims={claims}")

    assert closing_mean >= rebuttal_mean
    assert claims == []
