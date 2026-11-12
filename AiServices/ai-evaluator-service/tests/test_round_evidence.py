"""
/evaluate/round co kiem chung tung luot learner (docs/RAG_REPORT_INTEGRATION_SPEC.md muc A4). LLM gia va pipeline gia:
khong can DB, khong goi LLM that, khong load model.
"""
import json
import threading
import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.prompts.round_prompt import build_round_evaluation_prompt
from app.rag.schemas import ClaimVerification, EvidenceCheckResult, RetrievedFact, VerdictLabel
from app.schemas import (
    ArgumentTurn,
    DebateSide,
    DebateStage,
    RoundEvaluationRequest,
    SessionEvaluationRequest,
    TurnSpeaker,
)
from app.services import evidence_evaluator
from app.services.evidence_evaluator import adjust_evidence, evaluate_round_with_evidence
from app.services.llm_client import LLMClient
from app.services.round_evaluator import evaluate_round

LEARNER_1 = "Theo VVOB, phuong phap nay tiep can hon 14.695 truong tieu hoc."
OPPONENT = "Con so do khong noi len chat luong."
LEARNER_2 = "Ngoai ra co 90.000 giao vien da duoc tap huan."
OTHERS = {"Logic": 4, "Relevance": 4, "Structure": 3, "Persuasiveness": 4}


def _payload(evidence_score: int) -> dict:
    criteria = [{"name": name, "score": score, "reasoning": "Ly do."} for name, score in OTHERS.items()]
    criteria.insert(1, {"name": "Evidence", "score": evidence_score, "reasoning": "Co so lieu."})
    return {"criteria": criteria, "consistency_note": "Nhat quan.", "strengths": [], "weaknesses": [],
            "suggestions": ["Goi y cu."]}


class CapturingLLM(LLMClient):
    def __init__(self, evidence_score: int = 5, delay: float = 0.0):
        self.payload, self.delay = _payload(evidence_score), delay
        self.prompts: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append((system_prompt, user_prompt))
        time.sleep(self.delay)
        return json.dumps(self.payload, ensure_ascii=False)


def _request(topic="education", check_evidence=True, turns=None) -> RoundEvaluationRequest:
    turns = turns or [ArgumentTurn(speaker=TurnSpeaker.LEARNER, text=LEARNER_1),
                      ArgumentTurn(speaker=TurnSpeaker.OPPONENT, text=OPPONENT),
                      ArgumentTurn(speaker=TurnSpeaker.LEARNER, text=LEARNER_2)]
    return RoundEvaluationRequest(motion="Hoc thong qua choi nen duoc nhan rong", side=DebateSide.PRO,
                                  stage=DebateStage.REBUTTAL, turns=turns, topic=topic, check_evidence=check_evidence)


def _result(*labels: str) -> EvidenceCheckResult:
    claims = []
    for n, label in enumerate(labels, start=1):
        fact = RetrievedFact(fact_id=UUID(int=n), content="VVOB du kien tiep can hon 14.695 truong va 230.000 giao vien.",
                             citation="Thanh Nien - https://vd", score=0.9)
        fact_ids = [] if label == "NOT_FOUND" else [str(fact.fact_id)]
        stances = {str(fact.fact_id): "contradicts" if label == "CONTRADICTED" else "supports"} if fact_ids else {}
        claims.append(ClaimVerification(claim=f"claim {n}", label=VerdictLabel(label), fact_ids=fact_ids,
                                        fact_stances=stances, reason=f"Nguon ghi 230.000 giao vien (claim {n}).",
                                        retrieved=[fact]))
    counts = {label.value: list(labels).count(label.value) for label in VerdictLabel}
    return EvidenceCheckResult(claims=claims, counts=counts, skipped_reason=None if labels else "Khong co claim")


def _checker(results_by_text=None, error: Exception = None, delay: float = 0.0):
    calls = []

    def check(text, motion, topic, settings):
        calls.append((text, topic, threading.current_thread().name))
        time.sleep(delay)
        if error is not None:
            raise error
        return results_by_text[text]

    check.calls = calls
    return check


def _rag(**overrides) -> Settings:
    return Settings(rag_enabled=True, **overrides)


def _evidence(result) -> int:
    return next(c.score for c in result.criteria if c.name == "Evidence")


# 1 --------------------------------------------------------------------------- hanh vi cu


@pytest.mark.parametrize("settings,topic", [(Settings(rag_enabled=False), "education"), (_rag(), None), (Settings(), None)])
def test_without_topic_or_rag_prompt_and_result_unchanged(settings, topic):
    llm, checker = CapturingLLM(5), _checker(error=AssertionError("khong duoc goi"))
    req = _request(topic)
    result = evaluate_round_with_evidence(req, settings, llm, checker)
    old = evaluate_round(_request(topic), Settings(), CapturingLLM(5))

    assert llm.prompts == [build_round_evaluation_prompt(req)]
    assert checker.calls == []
    assert result.evidence_checks == [] and result.evidence_score_before is None and result.evidence_rule_applied == ""
    assert result.model_dump() == old.model_dump()


def test_topic_and_check_evidence_fields_do_not_change_the_round_prompt():
    assert build_round_evaluation_prompt(_request("education")) == build_round_evaluation_prompt(_request(None, False))


# 2 ---------------------------------------------------------------------------


def test_check_evidence_false_does_not_call_checker():
    checker = _checker(error=AssertionError("khong duoc goi"))
    result = evaluate_round_with_evidence(_request(check_evidence=False), _rag(), CapturingLLM(5), checker,
                                          lambda topic, settings: 10)
    assert checker.calls == [] and result.evidence_checks == []


# 3 ---------------------------------------------------------------------------


def test_only_learner_turns_are_checked_with_their_turn_index():
    checker = _checker({LEARNER_1: _result("SUPPORTED"), LEARNER_2: _result("NOT_FOUND")})
    result = evaluate_round_with_evidence(_request(), _rag(), CapturingLLM(5), checker)

    assert sorted(call[0] for call in checker.calls) == sorted([LEARNER_1, LEARNER_2])
    assert all(call[1] == "education" for call in checker.calls)
    assert [c.turn_index for c in result.evidence_checks] == [0, 2]
    assert result.evidence_checks[0].excerpt == LEARNER_1[:200]


def test_excerpt_is_cut_to_200_chars():
    long_text = "x" * 500
    turns = [ArgumentTurn(speaker=TurnSpeaker.LEARNER, text=long_text)]
    result = evaluate_round_with_evidence(_request(turns=turns), _rag(), CapturingLLM(4),
                                          _checker({long_text: _result("SUPPORTED")}))
    assert result.evidence_checks[0].excerpt == "x" * 200


# 4 ---------------------------------------------------------------------------


def test_contradicted_turn_adjusts_evidence_and_round_score():
    checker = _checker({LEARNER_1: _result("SUPPORTED"), LEARNER_2: _result("CONTRADICTED")})
    result = evaluate_round_with_evidence(_request(), _rag(), CapturingLLM(5), checker)

    expected, rule = adjust_evidence(5, ["SUPPORTED", "CONTRADICTED"])  # 1/2 claim: min(5,4) - 2 = 2
    assert expected == 2
    assert _evidence(result) == expected
    assert (result.evidence_score_before, result.evidence_score_after, result.evidence_rule_applied) == (5, 2, rule)
    assert result.round_score == 6.5  # 2 x 0.25 x (4 + 2 + 4 + 3)
    assert {c.name: c.score for c in result.criteria if c.name != "Evidence"} == OTHERS
    assert result.suggestions[0] == "Goi y cu."
    assert any("claim 1" in s and "mâu thuẫn với nguồn" in s for s in result.suggestions[1:])


# 5 ---------------------------------------------------------------------------


def test_only_not_found_keeps_scores():
    checker = _checker({LEARNER_1: _result("NOT_FOUND"), LEARNER_2: _result("NOT_FOUND", "NOT_FOUND")})
    result = evaluate_round_with_evidence(_request(), _rag(), CapturingLLM(5), checker)

    assert _evidence(result) == 5 and result.round_score == 8.0
    assert (result.evidence_score_before, result.evidence_score_after) == (5, 5)
    assert result.suggestions == ["Goi y cu."]


def test_no_claims_in_any_turn_leaves_round_untouched():
    checker = _checker({LEARNER_1: _result(), LEARNER_2: _result()})
    result = evaluate_round_with_evidence(_request(), _rag(), CapturingLLM(5), checker)
    assert [c.evidence_check.status for c in result.evidence_checks] == ["no_claims", "no_claims"]
    assert result.evidence_score_before is None and result.evidence_rule_applied == "" and result.round_score == 8.0


# 6 ---------------------------------------------------------------------------


def test_checker_error_keeps_round_and_reports_unavailable():
    result = evaluate_round_with_evidence(_request(), _rag(), CapturingLLM(5), _checker(error=ConnectionError("DB tat")))
    assert _evidence(result) == 5 and result.round_score == 8.0
    assert [c.evidence_check.status for c in result.evidence_checks] == ["unavailable", "unavailable"]
    assert "ConnectionError: DB tat" in result.evidence_checks[0].evidence_check.error


def test_timeout_keeps_round_and_reports_unavailable():
    checker = _checker({LEARNER_1: _result("CONTRADICTED"), LEARNER_2: _result("CONTRADICTED")}, delay=1.0)
    started = time.perf_counter()
    result = evaluate_round_with_evidence(_request(), _rag(rag_round_check_timeout_seconds=0.2), CapturingLLM(5), checker)
    assert time.perf_counter() - started < 0.9  # khong cho het thoi gian cua tung luot noi tiep nhau
    assert [c.evidence_check.status for c in result.evidence_checks] == ["unavailable", "unavailable"]
    assert "Timeout" in result.evidence_checks[0].evidence_check.error and _evidence(result) == 5


def test_endpoint_returns_200_when_rag_fails(monkeypatch):
    from app.main import app

    monkeypatch.setattr(evidence_evaluator, "get_settings", lambda: _rag())
    monkeypatch.setattr(evidence_evaluator, "_default_fact_counter", lambda topic, settings: 10)

    def broken_checker(*args):
        raise RuntimeError("embed loi")

    monkeypatch.setattr(evidence_evaluator, "_default_checker", broken_checker)
    real_evaluate_round = evidence_evaluator.evaluate_round
    monkeypatch.setattr(evidence_evaluator, "evaluate_round",
                        lambda req, settings, llm_client: real_evaluate_round(req, settings, CapturingLLM(4)))

    response = TestClient(app).post("/evaluate/round", json=json.loads(_request().model_dump_json()))
    assert response.status_code == 200
    body = response.json()
    assert [c["evidence_check"]["status"] for c in body["evidence_checks"]] == ["unavailable", "unavailable"]
    assert body["round_score"] == 7.5


# 7 ---------------------------------------------------------------------------


def test_topic_without_approved_facts_is_no_fact_base_and_skips_llm():
    checker = _checker(error=AssertionError("khong duoc goi LLM extract/verify"))
    counted = []
    result = evaluate_round_with_evidence(_request("society"), _rag(), CapturingLLM(5), checker,
                                          lambda topic, settings: counted.append(topic) or 0)
    assert checker.calls == [] and counted == ["society", "society"]
    assert [c.evidence_check.status for c in result.evidence_checks] == ["no_fact_base", "no_fact_base"]
    assert result.evidence_score_before is None and result.round_score == 8.0


def test_default_fact_counter_is_cached(monkeypatch):
    queries = []

    class FakeStore:
        def __init__(self, url):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def count_approved(self, topic):
            queries.append(topic)
            return 3

    import app.rag.store as store_module

    monkeypatch.setattr(store_module, "FactStore", FakeStore)
    monkeypatch.setattr(evidence_evaluator, "_fact_base_cache", {})
    assert evidence_evaluator._default_fact_counter("technology", _rag()) == 3
    assert evidence_evaluator._default_fact_counter("technology", _rag()) == 3
    assert queries == ["technology"]


# --------------------------------------------------------------------------- song song, Session


def test_checks_run_in_parallel_with_grading_and_each_other():
    checker = _checker({LEARNER_1: _result("SUPPORTED"), LEARNER_2: _result("SUPPORTED")}, delay=0.4)
    started = time.perf_counter()
    evaluate_round_with_evidence(_request(), _rag(), CapturingLLM(5, delay=0.4), checker)
    assert time.perf_counter() - started < 0.75  # tuan tu se mat >= 1.2 s
    assert all(call[2].startswith("rag-round-check") for call in checker.calls)


def test_session_accepts_rounds_with_evidence_checks():
    result = evaluate_round_with_evidence(_request(), _rag(), CapturingLLM(5),
                                          _checker({LEARNER_1: _result("SUPPORTED"), LEARNER_2: _result("CONTRADICTED")}))
    session = SessionEvaluationRequest(motion="m", side=DebateSide.PRO, rounds=[json.loads(result.model_dump_json())])
    assert session.rounds[0].evidence_checks[1].evidence_check.claims[0].label == "CONTRADICTED"
    assert session.rounds[0].round_score == 6.5


def test_round_without_learner_turn_skips_checks():
    # Validator chan qua API; model_construct de chac ham khong tao ThreadPoolExecutor(0)
    req = RoundEvaluationRequest.model_construct(
        motion="m", side=DebateSide.PRO, stage=DebateStage.OPENING, reference_turns=[], topic="education",
        check_evidence=True, turns=[ArgumentTurn(speaker=TurnSpeaker.OPPONENT, text=OPPONENT)],
    )
    checker = _checker(error=AssertionError("khong duoc goi"))
    result = evaluate_round_with_evidence(req, _rag(), CapturingLLM(4), checker)
    assert checker.calls == [] and result.evidence_checks == []
