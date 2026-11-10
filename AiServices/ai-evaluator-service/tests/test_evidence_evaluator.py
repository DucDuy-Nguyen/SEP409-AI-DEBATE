"""
Test cham Argument co kiem chung RAG theo phuong an D (dev log muc 3.21): prompt cham khong doi, Evidence dieu chinh
bang code. LLM gia va pipeline gia: khong can DB, khong goi LLM that, khong load model.
"""
import json
import os
import subprocess
import sys
import threading
import time
from uuid import UUID

import pytest

from app.config import Settings
from app.prompts.evaluator_prompt import build_evaluation_prompt
from app.rag.schemas import ClaimVerification, EvidenceCheckResult, RetrievedFact, VerdictLabel
from app.schemas import EVIDENCE_CHECK_VERSION, ArgumentEvaluationRequest, DebateSide
from app.services.evaluator import evaluate_argument
from app.services.evidence_evaluator import adjust_evidence, apply_adjustment, evaluate_argument_with_evidence, summarize
from app.services.llm_client import LLMClient

ARGUMENT = "Theo bao cao, 29.383 met vuong dat da duoc xu ly dioxin tai san bay Bien Hoa."
OTHERS = {"Logic": 4, "Relevance": 4, "Structure": 3, "Persuasiveness": 4}


def _payload(evidence_score: int) -> dict:
    criteria = [{"name": name, "score": score, "reasoning": "Ly do."} for name, score in OTHERS.items()]
    criteria.insert(1, {"name": "Evidence", "score": evidence_score, "reasoning": "Co so lieu cu the."})
    return {"criteria": criteria, "overall_reasoning": "Lap luan tot.", "strengths": [], "weaknesses": [],
            "suggestions": ["Goi y cu."]}


class CapturingLLM(LLMClient):
    def __init__(self, evidence_score: int = 5, delay: float = 0.0):
        self.payload, self.delay = _payload(evidence_score), delay
        self.prompts: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append((system_prompt, user_prompt))
        time.sleep(self.delay)
        return json.dumps(self.payload, ensure_ascii=False)


def _request(topic="environment") -> ArgumentEvaluationRequest:
    return ArgumentEvaluationRequest(motion="Hop tac quoc te giup xu ly o nhiem", side=DebateSide.PRO,
                                     argument_text=ARGUMENT, topic=topic)


def _check_result(*labels: str) -> EvidenceCheckResult:
    claims = []
    for n, label in enumerate(labels, start=1):
        fact = RetrievedFact(fact_id=UUID(int=n), content="x" * 400, citation="Chinh Phu - https://vd", score=0.9)
        fact_ids = [str(fact.fact_id)] if label != "NOT_FOUND" else []
        claims.append(ClaimVerification(claim=f"claim {n}", label=VerdictLabel(label), fact_ids=fact_ids,
                                        reason=f"Nguon ghi so dung la {n * 10}.", retrieved=[fact]))
    counts = {label.value: 0 for label in VerdictLabel}
    for label in labels:
        counts[label] += 1
    return EvidenceCheckResult(claims=claims, counts=counts, skipped_reason=None if labels else "Khong co claim")


def _checker(result=None, error: Exception = None, delay: float = 0.0):
    calls = []

    def check(argument_text, motion, topic, settings):
        calls.append((argument_text, motion, topic, threading.current_thread().name))
        time.sleep(delay)
        if error is not None:
            raise error
        return result

    check.calls = calls
    return check


def _evidence(result) -> int:
    return next(c.score for c in result.criteria if c.name == "Evidence")


def _rag(**overrides) -> Settings:
    return Settings(rag_enabled=True, **overrides)


# --------------------------------------------------------------------------- hanh vi cu


@pytest.mark.parametrize(
    "settings,topic", [(Settings(rag_enabled=False), "environment"), (_rag(), None), (Settings(), None)]
)
def test_without_rag_or_topic_prompt_and_result_are_unchanged(settings, topic):
    llm, checker = CapturingLLM(5), _checker(error=AssertionError("khong duoc goi"))
    req = _request(topic)
    result = evaluate_argument_with_evidence(req, settings, llm, checker)

    assert llm.prompts == [build_evaluation_prompt(req)]
    assert checker.calls == []
    assert result.evidence_check is None and result.overall_score == 8.0


def test_topic_field_does_not_change_the_old_prompt():
    assert build_evaluation_prompt(_request("technology")) == build_evaluation_prompt(_request(None))


@pytest.mark.parametrize("labels", [("CONTRADICTED", "SUPPORTED"), ("NOT_FOUND",), ()])
def test_grading_prompt_never_contains_rag_results(labels):
    llm = CapturingLLM(4)
    req = _request()
    evaluate_argument_with_evidence(req, _rag(), llm, _checker(_check_result(*labels)))
    assert llm.prompts == [build_evaluation_prompt(req)]


# --------------------------------------------------------------------------- luat dieu chinh


@pytest.mark.parametrize("base", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("labels", [["NOT_FOUND"], ["NOT_FOUND"] * 5, ["NOT_FOUND", "SUPPORTED"], ["SUPPORTED"], []])
@pytest.mark.parametrize("bonus", [False, True])
def test_not_found_never_lowers_evidence(base, labels, bonus):
    after, _ = adjust_evidence(base, labels, bonus)
    assert after >= base


@pytest.mark.parametrize(
    "base,labels,expected",
    [
        (5, ["CONTRADICTED", "SUPPORTED", "SUPPORTED"], 3),   # 1/3 < nua: min(5,4) - 1
        (5, ["CONTRADICTED", "SUPPORTED"], 2),                # 1/2 khong duoi nua: min(5,4) - 2
        (3, ["CONTRADICTED", "NOT_FOUND", "NOT_FOUND"], 2),   # 3 - 1
        (4, ["CONTRADICTED", "CONTRADICTED", "SUPPORTED"], 2),  # 2/3 >= nua: 4 - 2
        (2, ["CONTRADICTED"], 1),                             # 2 - 2 -> san 1
        (1, ["CONTRADICTED", "SUPPORTED", "SUPPORTED"], 1),   # san 1
    ],
)
def test_contradicted_penalty_levels(base, labels, expected):
    assert adjust_evidence(base, labels)[0] == expected


@pytest.mark.parametrize(
    "base,labels,bonus,expected",
    [
        (3, ["SUPPORTED", "NOT_FOUND"], True, 4),
        (5, ["SUPPORTED"], True, 5),                          # toi da 5
        (3, ["SUPPORTED", "NOT_FOUND", "NOT_FOUND"], True, 3),  # 1/3 < nua: khong thuong
        (3, ["SUPPORTED", "NOT_FOUND"], False, 3),            # mac dinh tat thuong
        (3, ["CONTRADICTED", "SUPPORTED", "SUPPORTED"], True, 2),  # co CONTRADICTED thi khong thuong
    ],
)
def test_bonus_variant(base, labels, bonus, expected):
    assert adjust_evidence(base, labels, bonus)[0] == expected


def test_contradicted_adjusts_only_evidence_and_recomputes_overall():
    llm, checker = CapturingLLM(5), _checker(_check_result("CONTRADICTED", "SUPPORTED"))
    result = evaluate_argument_with_evidence(_request(), _rag(), llm, checker)

    assert _evidence(result) == 2
    assert {c.name: c.score for c in result.criteria if c.name != "Evidence"} == OTHERS
    assert result.overall_score == 6.5  # 2 x 0.25 x (4 + 2 + 4 + 3)
    summary = result.evidence_check
    assert (summary.status, summary.evidence_score_before, summary.evidence_score_after) == ("checked", 5, 2)
    assert "CONTRADICTED" in summary.rule_applied and summary.version == EVIDENCE_CHECK_VERSION == "v4_detail_conflict"
    assert "[Điều chỉnh theo kiểm chứng số liệu: 5 -> 2." in next(c.reasoning for c in result.criteria if c.name == "Evidence")


@pytest.mark.parametrize("labels", [("SUPPORTED",), ("NOT_FOUND",), ("NOT_FOUND", "SUPPORTED"), ()])
def test_other_criteria_and_evidence_unchanged_without_contradicted(labels):
    off = evaluate_argument(_request(), Settings(), CapturingLLM(4))
    on = evaluate_argument_with_evidence(_request(), _rag(), CapturingLLM(4), _checker(_check_result(*labels)))

    assert [(c.name, c.score) for c in on.criteria] == [(c.name, c.score) for c in off.criteria]
    assert on.overall_score == off.overall_score
    assert on.evidence_check.status == ("checked" if labels else "no_claims")
    assert on.evidence_check.evidence_score_before == on.evidence_check.evidence_score_after == 4


def test_bonus_flag_from_settings():
    result = evaluate_argument_with_evidence(_request(), _rag(rag_evidence_bonus=True), CapturingLLM(3),
                                             _checker(_check_result("SUPPORTED")))
    assert _evidence(result) == 4 and result.evidence_check.evidence_score_after == 4


# --------------------------------------------------------------------------- feedback


def test_contradicted_claims_are_added_to_suggestions_with_reason_and_source():
    result = evaluate_argument_with_evidence(_request(), _rag(), CapturingLLM(4),
                                             _checker(_check_result("CONTRADICTED", "NOT_FOUND", "SUPPORTED")))
    assert result.suggestions[0] == "Goi y cu."
    added = result.suggestions[1:]
    assert len(added) == 1  # chi claim CONTRADICTED
    assert '"claim 1"' in added[0] and "Nguon ghi so dung la 10." in added[0] and "Nguồn: Chinh Phu - https://vd." in added[0]
    citation = result.evidence_check.claims[0].citations[0]
    assert len(citation.content) == 300


# --------------------------------------------------------------------------- RAG loi, timeout, song song


def test_pipeline_error_keeps_base_score_and_reports_unavailable():
    req = _request()
    llm = CapturingLLM(5)
    result = evaluate_argument_with_evidence(req, _rag(), llm, _checker(error=ConnectionError("DB tat")))

    assert llm.prompts == [build_evaluation_prompt(req)]
    assert _evidence(result) == 5 and result.overall_score == 8.0
    summary = result.evidence_check
    assert summary.status == "unavailable" and "ConnectionError: DB tat" in summary.error
    assert summary.evidence_score_before == summary.evidence_score_after == 5
    assert result.suggestions == ["Goi y cu."]


def test_timeout_keeps_base_score():
    checker = _checker(_check_result("CONTRADICTED"), delay=1.0)
    result = evaluate_argument_with_evidence(_request(), _rag(rag_check_timeout_seconds=0.1), CapturingLLM(5), checker)
    assert result.evidence_check.status == "unavailable" and "Timeout" in result.evidence_check.error
    assert _evidence(result) == 5


def test_check_runs_in_parallel_with_grading():
    checker = _checker(_check_result("CONTRADICTED"), delay=0.4)
    started = time.perf_counter()
    evaluate_argument_with_evidence(_request(), _rag(), CapturingLLM(5, delay=0.4), checker)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.7  # tuan tu se mat >= 0.8 s
    assert checker.calls[0][3].startswith("rag-check")


def test_parallel_result_equals_sequential_computation():
    labels = ("CONTRADICTED", "NOT_FOUND", "SUPPORTED")
    parallel = evaluate_argument_with_evidence(_request(), _rag(), CapturingLLM(5), _checker(_check_result(*labels)))

    sequential = evaluate_argument(_request(), Settings(), CapturingLLM(5))
    summary = summarize(_check_result(*labels))
    apply_adjustment(sequential, summary, bonus=False)
    sequential.evidence_check = summary

    assert parallel.model_dump(exclude={"raw_model_output"}) == sequential.model_dump(exclude={"raw_model_output"})


def test_evaluate_endpoint_accepts_topic_and_rag_off_does_not_import_rag():
    code = (
        "import sys; from fastapi.testclient import TestClient; from app.main import app; "
        "r = TestClient(app).post('/evaluate', json={'motion': 'm', 'side': 'pro', 'argument_text': 'a', 'topic': 'bad'}); "
        "print(r.status_code, sorted(m for m in ('app.rag.pipeline', 'torch', 'psycopg') if m in sys.modules))"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                            env={**os.environ, "RAG_ENABLED": "false", "EVAL_AUDIT_LOG_PATH": ""})
    assert output.stdout.strip() == "422 []"


# --------------------------------------------------------------------------- CONFLICTING (muc 3.21.2)


def _conflicting_result(*labels: str) -> EvidenceCheckResult:
    """Nhu _check_result nhung claim CONFLICTING co 2 fact: 1 supports, 1 contradicts."""
    base = _check_result(*[("SUPPORTED" if label == "CONFLICTING" else label) for label in labels])
    for claim, label in zip(base.claims, labels):
        if label == "CONFLICTING":
            other = RetrievedFact(fact_id=UUID(int=900), content="y" * 50, citation="Bao khac - https://khac", score=0.8)
            claim.label = VerdictLabel.CONFLICTING
            claim.retrieved = claim.retrieved + [other]
            claim.fact_ids = claim.fact_ids + [str(other.fact_id)]
            claim.fact_stances = {claim.fact_ids[0]: "supports", str(other.fact_id): "contradicts"}
    base.counts = {label.value: [l for l in labels].count(label.value) for label in VerdictLabel}
    return base


@pytest.mark.parametrize("base", [1, 3, 5])
@pytest.mark.parametrize("labels", [["CONFLICTING"], ["CONFLICTING", "NOT_FOUND"], ["CONFLICTING"] * 3 + ["NOT_FOUND"]])
def test_conflicting_and_not_found_never_lower_evidence(base, labels):
    assert adjust_evidence(base, labels)[0] == base


def test_conflicting_counts_in_n_but_not_in_n_c():
    # 1 CONTRADICTED tren 3 claim (1 la CONFLICTING): 1 < 3/2 nen tru 1, khong phai tru 2
    assert adjust_evidence(5, ["CONTRADICTED", "CONFLICTING", "SUPPORTED"])[0] == 3
    # Khong co CONFLICTING trong n thi 1/2 -> tru 2
    assert adjust_evidence(5, ["CONTRADICTED", "SUPPORTED"])[0] == 2


def test_conflicting_feedback_lists_both_sides_with_sources():
    result = evaluate_argument_with_evidence(_request(), _rag(), CapturingLLM(4), _checker(_conflicting_result("CONFLICTING")))
    assert _evidence(result) == 4
    [added] = result.suggestions[1:]
    assert added.startswith('Nguồn chưa thống nhất về "claim 1" (không trừ điểm).')
    assert "Nguồn khớp: \"" in added and "(Chinh Phu - https://vd)" in added
    assert "Nguồn khác: \"" + "y" * 50 + "\" (Bao khac - https://khac)" in added
    citations = result.evidence_check.claims[0].citations
    assert {c.stance for c in citations} == {"supports", "contradicts"}
    assert result.evidence_check.claims[0].label == "CONFLICTING"


def test_argument_topic_without_approved_facts_is_no_fact_base():
    checker = _checker(error=AssertionError("khong duoc goi LLM extract/verify"))
    req = ArgumentEvaluationRequest(motion="m", side=DebateSide.PRO, argument_text=ARGUMENT, topic="society")
    result = evaluate_argument_with_evidence(req, _rag(), CapturingLLM(5), checker, lambda topic, settings: 0)
    summary = result.evidence_check
    assert checker.calls == [] and summary.status == "no_fact_base"
    assert summary.evidence_score_before == summary.evidence_score_after == 5 and _evidence(result) == 5
    assert result.suggestions == ["Goi y cu."]
