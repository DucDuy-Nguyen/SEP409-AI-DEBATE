"""
Test cham Argument co kiem chung RAG (phuong an C, docs/RAG_STEP3_SPEC.md) bang LLM gia va pipeline gia:
khong can DB, khong goi LLM that, khong load model.
"""
import json
import subprocess
import sys
from uuid import UUID

import pytest

from app.config import Settings
from app.prompts.evaluator_prompt import build_evaluation_prompt
from app.rag.schemas import ClaimVerification, EvidenceCheckResult, RetrievedFact, VerdictLabel
from app.schemas import ArgumentEvaluationRequest, DebateSide
from app.services.evidence_evaluator import CAP_NOTE, evaluate_argument_with_evidence
from app.services.llm_client import LLMClient

ARGUMENT = "Theo bao cao, 29.383 met vuong dat da duoc xu ly dioxin tai san bay Bien Hoa."


def _payload(evidence_score: int) -> dict:
    return {
        "criteria": [
            {"name": "Logic", "score": 4, "reasoning": "Chat che."},
            {"name": "Evidence", "score": evidence_score, "reasoning": "Co so lieu cu the."},
            {"name": "Relevance", "score": 4, "reasoning": "Bam sat motion."},
            {"name": "Structure", "score": 3, "reasoning": "Ro rang."},
            {"name": "Persuasiveness", "score": 4, "reasoning": "Kha thuyet phuc."},
        ],
        "overall_reasoning": "Lap luan tot.",
        "strengths": [],
        "weaknesses": [],
        "suggestions": [],
    }


class CapturingLLM(LLMClient):
    def __init__(self, evidence_score: int = 5):
        self.payload = _payload(evidence_score)
        self.prompts: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append((system_prompt, user_prompt))
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
                                        reason=f"ly do {n}", retrieved=[fact]))
    counts = {label.value: 0 for label in VerdictLabel}
    for label in labels:
        counts[label] += 1
    return EvidenceCheckResult(claims=claims, counts=counts,
                               skipped_reason=None if labels else "Khong co claim")


def _checker(result=None, error: Exception = None):
    calls = []

    def check(argument_text, motion, topic, settings):
        calls.append((argument_text, motion, topic))
        if error is not None:
            raise error
        return result

    check.calls = calls
    return check


def _old_prompt(req: ArgumentEvaluationRequest) -> tuple[str, str]:
    return build_evaluation_prompt(req)


@pytest.mark.parametrize(
    "settings,topic",
    [(Settings(rag_enabled=False), "environment"), (Settings(rag_enabled=True), None), (Settings(), None)],
)
def test_without_rag_or_topic_prompt_and_result_are_unchanged(settings, topic):
    llm, checker = CapturingLLM(5), _checker(error=AssertionError("khong duoc goi"))
    req = _request(topic)
    result = evaluate_argument_with_evidence(req, settings, llm, checker)

    assert llm.prompts == [_old_prompt(req)]
    assert checker.calls == []
    assert result.evidence_check is None
    assert result.overall_score == 8.0  # 2 x 0.25 x (4 + 5 + 4 + 3), khong bi ha


def test_topic_field_does_not_change_the_old_prompt():
    with_topic = build_evaluation_prompt(_request("technology"))
    without_topic = build_evaluation_prompt(_request(None))
    assert with_topic == without_topic


def test_pipeline_error_still_grades_with_old_prompt_and_reports_unavailable():
    llm, checker = CapturingLLM(5), _checker(error=ConnectionError("DB tat"))
    req = _request()
    result = evaluate_argument_with_evidence(req, Settings(rag_enabled=True), llm, checker)

    assert llm.prompts == [_old_prompt(req)]
    assert result.evidence_check.status == "unavailable"
    assert "ConnectionError" in result.evidence_check.error and "DB tat" in result.evidence_check.error
    assert result.overall_score == 8.0


def test_contradicted_with_evidence_five_is_capped_to_four_and_overall_recomputed():
    llm, checker = CapturingLLM(5), _checker(_check_result("CONTRADICTED", "SUPPORTED"))
    result = evaluate_argument_with_evidence(_request(), Settings(rag_enabled=True), llm, checker)

    evidence = next(c for c in result.criteria if c.name == "Evidence")
    assert evidence.score == 4 and evidence.reasoning.endswith(CAP_NOTE)
    assert result.overall_score == 7.5  # 2 x 0.25 x (4 + 4 + 4 + 3)
    summary = result.evidence_check
    assert (summary.status, summary.evidence_capped, summary.evidence_score_before_cap) == ("checked", True, 5)
    assert summary.counts == {"SUPPORTED": 1, "CONTRADICTED": 1, "NOT_FOUND": 0}
    assert checker.calls == [(ARGUMENT, "Hop tac quoc te giup xu ly o nhiem", "environment")]


@pytest.mark.parametrize("evidence_score", [1, 3, 4])
def test_contradicted_with_evidence_four_or_less_is_unchanged(evidence_score):
    llm, checker = CapturingLLM(evidence_score), _checker(_check_result("CONTRADICTED"))
    result = evaluate_argument_with_evidence(_request(), Settings(rag_enabled=True), llm, checker)

    assert next(c for c in result.criteria if c.name == "Evidence").score == evidence_score
    assert result.evidence_check.evidence_capped is False
    assert result.evidence_check.evidence_score_before_cap is None


@pytest.mark.parametrize("labels", [("SUPPORTED",), ("NOT_FOUND", "SUPPORTED"), ()])
def test_without_contradicted_evidence_five_is_kept(labels):
    llm, checker = CapturingLLM(5), _checker(_check_result(*labels))
    result = evaluate_argument_with_evidence(_request(), Settings(rag_enabled=True), llm, checker)

    assert next(c for c in result.criteria if c.name == "Evidence").score == 5
    assert result.overall_score == 8.0
    assert result.evidence_check.evidence_capped is False
    assert result.evidence_check.status == ("checked" if labels else "no_claims")


def test_checked_prompt_appends_block_with_labels_reasons_and_short_citations():
    llm, checker = CapturingLLM(4), _checker(_check_result("CONTRADICTED", "NOT_FOUND"))
    req = _request()
    result = evaluate_argument_with_evidence(req, Settings(rag_enabled=True), llm, checker)

    old_system, old_user = _old_prompt(req)
    [(system_prompt, user_prompt)] = llm.prompts
    assert system_prompt == old_system  # chi them vao user prompt
    assert user_prompt.startswith(old_user + "\n\n[KET QUA KIEM CHUNG SO LIEU]")
    assert "Nhan: CONTRADICTED" in user_prompt and "Ly do: ly do 1" in user_prompt
    assert "NOT_FOUND: KHONG coi la sai" in user_prompt
    assert "CHI anh huong tieu chi Evidence" in user_prompt
    assert "x" * 300 + " (nguon: Chinh Phu - https://vd)" in user_prompt and "x" * 301 not in user_prompt

    claims = result.evidence_check.claims
    assert [c.label for c in claims] == ["CONTRADICTED", "NOT_FOUND"]
    assert len(claims[0].citations[0].content) == 300 and claims[0].citations[0].citation == "Chinh Phu - https://vd"
    assert claims[1].citations == []  # NOT_FOUND khong trich fact nao


def test_no_claims_prompt_block_says_grade_evidence_normally():
    llm, checker = CapturingLLM(3), _checker(_check_result())
    evaluate_argument_with_evidence(_request(), Settings(rag_enabled=True), llm, checker)
    user_prompt = llm.prompts[0][1]
    assert "khong co claim thuc chung" in user_prompt and "Danh gia Evidence nhu binh thuong" in user_prompt


def test_evaluate_endpoint_accepts_topic_and_rag_off_does_not_import_rag():
    code = (
        "import sys, json; from fastapi.testclient import TestClient; from app.main import app; "
        "r = TestClient(app).post('/evaluate', json={'motion': 'm', 'side': 'pro', 'argument_text': 'a', 'topic': 'bad'}); "
        "print(r.status_code, sorted(m for m in ('app.rag.pipeline', 'torch', 'psycopg') if m in sys.modules))"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                            env={**__import__("os").environ, "RAG_ENABLED": "false", "EVAL_AUDIT_LOG_PATH": ""})
    # topic sai gia tri -> 422 truoc khi goi LLM; khong module RAG nao bi nap
    assert output.stdout.strip() == "422 []"
