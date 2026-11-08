"""
Cham Argument co kiem chung so lieu bang RAG (docs/RAG_STEP3_SPEC.md, phuong an C, dev log muc 3.21).

- RAG tat hoac request khong co `topic`: goi thang evaluate_argument cu, prompt/ket qua y het truoc, evidence_check=None.
- Co topic + RAG bat: kiem chung bang pipeline buoc 2, dua ket qua vao prompt (app/prompts/evidence_prompt.py),
  roi ap luat mem bang code: co it nhat 1 claim CONTRADICTED thi Evidence khong duoc 5 (ha ve 4), overall tinh lai.
- RAG loi (DB tat, embed loi, verify loi/timeout): cham nhu khong co RAG, evidence_check.status = "unavailable".

Tach khoi app/services/evaluator.py va app/prompts/evaluator_prompt.py de 2 file do (va config_hash cua
scripts/config_fingerprint.py) giu nguyen tung byte.
"""
import logging
from typing import Callable, Optional

from app.config import Settings, get_settings
from app.prompts.evaluator_prompt import build_evaluation_prompt
from app.prompts.evidence_prompt import build_evidence_block
from app.schemas import (
    ArgumentEvaluationRequest,
    ArgumentEvaluationResult,
    EvidenceCheckSummary,
    EvidenceCitation,
    EvidenceClaimSummary,
)
from app.services.evaluator import _build_result, evaluate_argument
from app.services.json_utils import call_llm_with_retry
from app.services.llm_client import LLMClient, get_llm_client
from app.services.scoring import compute_weighted_score

logger = logging.getLogger(__name__)

EVIDENCE_CRITERION = "Evidence"
EVIDENCE_CAP_SCORE = 4  # Co claim CONTRADICTED thi Evidence toi da 4
CITATION_MAX_CHARS = 300
CAP_NOTE = " [Hạ từ 5 xuống 4 vì có số liệu/sự kiện mâu thuẫn với nguồn (CONTRADICTED).]"

# (argument_text, motion, topic, settings) -> EvidenceCheckResult cua app/rag (kieu de lazy, tranh import RAG khi tat)
EvidenceChecker = Callable[[str, str, str, Settings], object]


def _default_checker(argument_text: str, motion: str, topic: str, settings: Settings):
    # Import tai day: RAG tat thi khong nap module RAG nao (torch, psycopg)
    from app.rag.embedder import get_default_embedder
    from app.rag.pipeline import check_evidence

    return check_evidence(argument_text, motion, topic, settings, embedder=get_default_embedder())


def summarize(result) -> EvidenceCheckSummary:
    """EvidenceCheckResult (app/rag/schemas.py) -> EvidenceCheckSummary tra kem ket qua cham."""
    claims = []
    for verification in result.claims:
        cited = set(verification.fact_ids)
        citations = [
            EvidenceCitation(fact_id=str(fact.fact_id), content=fact.content[:CITATION_MAX_CHARS], citation=fact.citation)
            for fact in verification.retrieved
            if str(fact.fact_id).lower() in cited
        ]
        claims.append(
            EvidenceClaimSummary(
                claim=verification.claim, label=verification.label.value, reason=verification.reason, citations=citations
            )
        )
    status = "no_claims" if not claims else "checked"
    return EvidenceCheckSummary(status=status, claims=claims, counts=dict(result.counts))


def apply_soft_cap(result: ArgumentEvaluationResult, summary: EvidenceCheckSummary) -> None:
    """Luat mem bang code (sau khi parse ket qua LLM): co CONTRADICTED ma Evidence = 5 thi ha ve 4, tinh lai overall."""
    if summary.status != "checked" or summary.counts.get("CONTRADICTED", 0) <= 0:
        return
    for criterion in result.criteria:
        if criterion.name == EVIDENCE_CRITERION and criterion.score > EVIDENCE_CAP_SCORE:
            summary.evidence_score_before_cap = criterion.score
            criterion.score = EVIDENCE_CAP_SCORE
            criterion.reasoning = criterion.reasoning.rstrip() + CAP_NOTE
            summary.evidence_capped = True
            result.overall_score = compute_weighted_score(result.criteria)
            return


def evaluate_argument_with_evidence(
    req: ArgumentEvaluationRequest,
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
    evidence_checker: Optional[EvidenceChecker] = None,
) -> ArgumentEvaluationResult:
    settings = settings or get_settings()
    if not (settings.rag_enabled and req.topic):
        return evaluate_argument(req, settings, llm_client)

    checker = evidence_checker or _default_checker
    try:
        summary = summarize(checker(req.argument_text, req.motion, req.topic, settings))
    except Exception as exc:  # RAG loi thi van cham diem, khong bao gio tra 5xx chi vi RAG
        logger.warning("Kiem chung RAG that bai, cham khong co RAG: %s: %s", type(exc).__name__, exc)
        summary = EvidenceCheckSummary(status="unavailable", error=f"{type(exc).__name__}: {exc}")

    block = build_evidence_block(summary)
    if block is None:
        result = evaluate_argument(req, settings, llm_client)
    else:
        client = llm_client or get_llm_client(settings)
        system_prompt, user_prompt = build_evaluation_prompt(req)
        user_prompt = f"{user_prompt}\n\n{block}"
        result = call_llm_with_retry(
            generate_fn=lambda up: client.generate(system_prompt, up),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            build_result_fn=_build_result,
            audit_label="argument_rag",
        )
        apply_soft_cap(result, summary)
    result.evidence_check = summary
    return result
