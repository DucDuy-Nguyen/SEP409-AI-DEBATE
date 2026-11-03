"""Test reference_turns (ngu canh cac round truoc, muc 3.17 cua dev log). KHONG goi API that."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.prompts.coaching_prompt import build_round_coaching_prompt
from app.prompts.round_prompt import build_round_evaluation_prompt
from app.schemas import (
    ArgumentTurn,
    CriterionScore,
    DebateSide,
    DebateStage,
    ReferenceTurn,
    RoundCoachingRequest,
    RoundEvaluationRequest,
    RoundEvaluationResult,
    TurnSpeaker,
)
from app.services.llm_client import LLMClient
from app.services.round_evaluator import evaluate_round

SESSION = json.loads((Path(__file__).parent / "fixtures" / "session13_ai_regulation.json").read_text(encoding="utf-8"))
ROUND_OF = {"opening": 1, "rebuttal": 2, "closing": 3}


def _turn_text(stage: str, speaker: str) -> str:
    return next(t["text"] for t in SESSION["turns"] if t["stage"] == stage and t["speaker"] == speaker)


def _references_before(stage: str) -> list[ReferenceTurn]:
    return [
        ReferenceTurn(round=t["round"], order=i, speaker=TurnSpeaker(t["speaker"]), side=DebateSide(t["side"]), text=t["text"])
        for i, t in enumerate(SESSION["turns"], start=1)
        if t["round"] < ROUND_OF[stage]
    ]


def _request(stage: str, with_references: bool = True) -> RoundEvaluationRequest:
    return RoundEvaluationRequest(
        motion=SESSION["motion"],
        side=DebateSide.PRO,
        stage=DebateStage(stage),
        turns=[ArgumentTurn(speaker=TurnSpeaker(t["speaker"]), text=t["text"]) for t in SESSION["turns"] if t["stage"] == stage],
        reference_turns=_references_before(stage) if with_references else [],
    )


def _reference(**overrides) -> ReferenceTurn:
    fields = {"round": 1, "order": 1, "speaker": TurnSpeaker.LEARNER, "side": DebateSide.PRO, "text": "Bai noi"}
    return ReferenceTurn(**{**fields, **overrides})


# ---- Tuong thich nguoc ----


@pytest.mark.parametrize("stage", ["closing", "rebuttal"])
def test_without_reference_turns_prompts_have_no_trace_of_the_feature(stage):
    system_prompt, user_prompt = build_round_evaluation_prompt(_request(stage, with_references=False))

    assert "NGU CANH" not in system_prompt
    assert "NGU CANH" not in user_prompt
    assert "chat van" not in system_prompt


def test_empty_list_and_missing_field_give_identical_prompts():
    missing = RoundEvaluationRequest(
        motion="M", side=DebateSide.PRO, stage=DebateStage.CLOSING,
        turns=[ArgumentTurn(speaker=TurnSpeaker.LEARNER, text="Bai noi")],
    )
    empty = missing.model_copy(update={"reference_turns": []})

    assert missing.reference_turns == []
    assert build_round_evaluation_prompt(missing) == build_round_evaluation_prompt(empty)


# ---- Noi dung prompt ----


def test_context_section_is_separate_and_ordered_and_comes_before_the_graded_turns():
    _, user_prompt = build_round_evaluation_prompt(_request("closing"))

    context_at = user_prompt.index("[NGU CANH CAC ROUND TRUOC - KHONG CHAM]")
    graded_at = user_prompt.index("[TOAN BO CAC LUOT NOI TRONG ROUND")
    assert context_at < graded_at
    context, graded = user_prompt[context_at:graded_at], user_prompt[graded_at:]

    assert _turn_text("rebuttal", "opponent") in context
    assert _turn_text("rebuttal", "opponent") not in graded
    assert _turn_text("closing", "learner") in graded
    assert _turn_text("closing", "learner") not in context
    assert context.index(_turn_text("opening", "learner")) < context.index(_turn_text("rebuttal", "opponent"))
    assert f"Round 2, thu tu 4 - DOI PHUONG (phe Con): {_turn_text('rebuttal', 'opponent')}" in context
    assert f"Round 1, thu tu 1 - LEARNER (phe Pro): {_turn_text('opening', 'learner')}" in context


def test_turns_are_sorted_by_order_not_by_input_position():
    request = _request("closing").model_copy(update={"reference_turns": list(reversed(_references_before("closing")))})

    _, user_prompt = build_round_evaluation_prompt(request)

    assert user_prompt.index(_turn_text("opening", "learner")) < user_prompt.index(_turn_text("rebuttal", "opponent"))


def test_system_prompt_states_the_three_rules_only_when_references_exist():
    system_prompt, _ = build_round_evaluation_prompt(_request("closing"))

    assert "KHONG cham" in system_prompt
    assert "CHI cham cac luot LEARNER trong muc [TOAN BO CAC LUOT NOI TRONG ROUND]" in system_prompt
    assert "DOI PHUONG chua tra loi, KHONG phai learner khong tra loi" in system_prompt


def test_system_prompt_format_placeholders_are_all_filled():
    system_prompt, _ = build_round_evaluation_prompt(_request("closing"))
    plain_prompt, _ = build_round_evaluation_prompt(_request("closing", with_references=False))

    assert "{reference_rules}" not in system_prompt
    assert "{reference_rules}" not in plain_prompt
    assert '"weaknesses": ["<diem yeu' in plain_prompt


def test_learner_con_labels_follow_the_request_side():
    request = RoundEvaluationRequest(
        motion="M", side=DebateSide.CON, stage=DebateStage.REBUTTAL,
        turns=[ArgumentTurn(speaker=TurnSpeaker.LEARNER, text="Bai noi")],
        reference_turns=[_reference(side=DebateSide.CON), _reference(order=2, speaker=TurnSpeaker.OPPONENT, side=DebateSide.PRO)],
    )

    _, user_prompt = build_round_evaluation_prompt(request)

    assert "Round 1, thu tu 1 - LEARNER (phe Con): Bai noi" in user_prompt
    assert "Round 1, thu tu 2 - DOI PHUONG (phe Pro): Bai noi" in user_prompt


# ---- Validate payload (422 qua API) ----


@pytest.mark.parametrize(
    "references,message",
    [
        ([_reference(side=DebateSide.CON)], "phai la phe pro"),
        ([_reference(speaker=TurnSpeaker.OPPONENT, side=DebateSide.PRO)], "phai la phe con"),
        ([_reference(round=3)], "khong nam truoc round hien tai"),
        ([_reference(), _reference()], "bi trung"),
    ],
)
def test_inconsistent_references_are_rejected(references, message):
    with pytest.raises(ValidationError, match=message):
        RoundEvaluationRequest(
            motion="M", side=DebateSide.PRO, stage=DebateStage.CLOSING,
            turns=[ArgumentTurn(speaker=TurnSpeaker.LEARNER, text="Bai noi")],
            reference_turns=references,
        )


def test_opening_round_cannot_have_references():
    with pytest.raises(ValidationError, match="khong nam truoc round hien tai"):
        RoundEvaluationRequest(
            motion="M", side=DebateSide.PRO, stage=DebateStage.OPENING,
            turns=[ArgumentTurn(speaker=TurnSpeaker.LEARNER, text="Bai noi")],
            reference_turns=[_reference()],
        )


@pytest.mark.parametrize("field,value", [("text", "   "), ("text", ""), ("round", 0), ("order", 0)])
def test_invalid_reference_fields_are_rejected(field, value):
    with pytest.raises(ValidationError):
        _reference(**{field: value})


# ---- Di qua service va coaching ----


class CapturingClient(LLMClient):
    def __init__(self, response: str):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.response


def test_service_sends_context_to_the_llm_and_score_still_comes_from_criteria():
    names = ("Logic", "Evidence", "Relevance", "Structure", "Persuasiveness")
    response = json.dumps({
        "criteria": [{"name": n, "score": 4, "reasoning": "x"} for n in names],
        "consistency_note": "On dinh.",
        "weaknesses": ["Thieu so lieu"],
    })
    client = CapturingClient(response)

    result = evaluate_round(_request("closing"), llm_client=client)

    assert result.round_score == 8.0
    assert result.weaknesses == ["Thieu so lieu"]
    assert _turn_text("rebuttal", "opponent") in client.calls[0][1]
    assert "CHI cham cac luot LEARNER" in client.calls[0][0]


def test_coaching_request_with_references_is_labelled_as_context():
    names = ("Logic", "Evidence", "Relevance", "Structure", "Persuasiveness")
    evaluation = RoundEvaluationResult(
        stage=DebateStage.CLOSING,
        round_score=8.0,
        criteria=[CriterionScore(name=n, score=4, reasoning="x") for n in names],
        consistency_note="On dinh.",
    )
    coaching = RoundCoachingRequest(request=_request("closing"), evaluation=evaluation)

    _, user_prompt = build_round_coaching_prompt(coaching, ["Evidence"])

    assert "[NGU CANH CAC ROUND TRUOC - KHONG CHAM]" in user_prompt
