"""
Cham Argument co kiem chung so lieu bang RAG — phuong an D (docs/AI_DEVELOPMENT_LOG.md muc 3.21).

- Luot cham LUON dung dung prompt cu (evaluate_argument), khong chen ket qua kiem chung: phuong an C (chen vao prompt)
  da cho thay LLM van tru diem NOT_FOUND va ket qua kiem chung lan sang Logic/Persuasiveness.
- RAG tat hoac khong co `topic`: chi cham nhu cu, evidence_check=None.
- Co topic + RAG bat: pipeline kiem chung (buoc 2) chay SONG SONG voi luot cham, roi CODE dieu chinh Evidence:
    n = so claim da kiem (S + C + N), n_c = so CONTRADICTED
    n_c = 0            -> giu nguyen (bien the co thuong, co rag_evidence_bonus: +1 neu n >= 1 va n_s >= n/2, toi da 5)
    CONFLICTING (nguon chua thong nhat, muc 3.21.2) dem vao n nhung khong vao n_c: khong bao gio bi tru
    n_c >= 1           -> min(goc, 4) - (1 neu n_c < n/2, nguoc lai 2), toi thieu 1
  NOT_FOUND khong bao gio lam giam Evidence. 4 tieu chi con lai giu nguyen; overall tinh lai bang compute_weighted_score.
- RAG loi hoac qua rag_check_timeout_seconds: giu diem goc, status "unavailable". Khong bao gio tra 5xx chi vi RAG.
- Claim CONTRADICTED duoc them vao `suggestions` kem ly do + nguon cua verify; claim CONFLICTING ghi "nguon chua thong
  nhat" kem fact moi phia (khong goi LLM them).

Tach khoi app/services/evaluator.py va app/prompts/evaluator_prompt.py de 2 file do (va config_hash cua
scripts/config_fingerprint.py) giu nguyen tung byte.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Callable, Optional

from app.config import Settings, get_settings
from app.schemas import (
    ArgumentEvaluationRequest,
    ArgumentEvaluationResult,
    EvidenceCheckSummary,
    EvidenceCitation,
    EvidenceClaimSummary,
)
from app.services.evaluator import evaluate_argument
from app.services.llm_client import LLMClient
from app.services.scoring import compute_weighted_score

logger = logging.getLogger(__name__)

EVIDENCE_CRITERION = "Evidence"
MIN_SCORE, MAX_SCORE = 1, 5
CONTRADICTED_CAP = 4  # Co CONTRADICTED thi tinh tu toi da 4 truoc khi tru
CITATION_MAX_CHARS = 300
SUGGESTION_SNIPPET_CHARS = 160  # Noi dung rut gon cua fact trong goi y CONFLICTING

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
        cited = {fact_id.lower() for fact_id in verification.fact_ids}
        citations = [
            EvidenceCitation(
                fact_id=str(fact.fact_id), content=fact.content[:CITATION_MAX_CHARS], citation=fact.citation,
                stance=verification.fact_stances.get(str(fact.fact_id).lower()),
            )
            for fact in verification.retrieved
            if str(fact.fact_id).lower() in cited
        ]
        claims.append(
            EvidenceClaimSummary(
                claim=verification.claim, label=verification.label.value, reason=verification.reason, citations=citations
            )
        )
    return EvidenceCheckSummary(status="checked" if claims else "no_claims", claims=claims, counts=dict(result.counts))


def adjust_evidence(base: int, labels: list[str], bonus: bool = False) -> tuple[int, str]:
    """Diem Evidence moi va mo ta luat da ap. Ham thuan: NOT_FOUND khong bao gio lam giam diem."""
    # CONFLICTING (nguon chua thong nhat) duoc dem vao n nhung khong vao n_c: khong bao gio bi tru
    n = len(labels)
    n_contradicted = labels.count("CONTRADICTED")
    n_supported = labels.count("SUPPORTED")
    if n == 0:
        return base, "Không có claim thực chứng: giữ nguyên điểm Evidence."
    if n_contradicted == 0:
        if bonus and n_supported >= n / 2:
            after = min(base + 1, MAX_SCORE)
            return after, f"Không có claim CONTRADICTED, {n_supported}/{n} claim SUPPORTED: +1 (tối đa 5)."
        return base, f"Không có claim CONTRADICTED ({n} claim đã kiểm): giữ nguyên điểm Evidence."
    penalty = 1 if n_contradicted < n / 2 else 2
    after = max(min(base, CONTRADICTED_CAP) - penalty, MIN_SCORE)
    return after, (
        f"{n_contradicted}/{n} claim CONTRADICTED: lấy min(điểm gốc, {CONTRADICTED_CAP}) rồi trừ {penalty} "
        f"({'dưới' if penalty == 1 else 'từ'} một nửa số claim), tối thiểu {MIN_SCORE}."
    )


def _cite(citation: EvidenceCitation) -> str:
    snippet = citation.content[:SUGGESTION_SNIPPET_CHARS].rstrip()
    if len(citation.content) > SUGGESTION_SNIPPET_CHARS:
        snippet += "..."
    return f"\"{snippet}\"" + (f" ({citation.citation})" if citation.citation else "")


def contradiction_suggestions(summary: EvidenceCheckSummary) -> list[str]:
    """
    Goi y cho claim CONTRADICTED (sua so lieu theo nguon) va CONFLICTING (nguon chua thong nhat, kem fact moi phia),
    lay tu ly do + fact cua verify, khong goi LLM.
    """
    suggestions = []
    for claim in summary.claims:
        if claim.label == "CONTRADICTED":
            sources = "; ".join(dict.fromkeys(c.citation for c in claim.citations if c.citation))
            text = f"Kiểm tra lại số liệu: \"{claim.claim}\" mâu thuẫn với nguồn. {claim.reason}"
            suggestions.append(text + (f" Nguồn: {sources}." if sources else ""))
        elif claim.label == "CONFLICTING":
            supports = "; ".join(_cite(c) for c in claim.citations if c.stance == "supports")
            contradicts = "; ".join(_cite(c) for c in claim.citations if c.stance == "contradicts")
            suggestions.append(
                f"Nguồn chưa thống nhất về \"{claim.claim}\" (không trừ điểm). "
                f"Nguồn khớp: {supports}. Nguồn khác: {contradicts}. Nên nêu rõ nguồn mình dùng."
            )
    return suggestions


def apply_adjustment(result: ArgumentEvaluationResult, summary: EvidenceCheckSummary, bonus: bool) -> None:
    evidence = next(c for c in result.criteria if c.name == EVIDENCE_CRITERION)
    base = evidence.score
    summary.evidence_score_before = base
    if summary.status == "unavailable":
        summary.evidence_score_after = base
        summary.rule_applied = "Kiểm chứng không chạy được: giữ nguyên điểm Evidence."
        return

    after, rule = adjust_evidence(base, [claim.label for claim in summary.claims], bonus)
    summary.evidence_score_after = after
    summary.rule_applied = rule
    if after != base:
        evidence.score = after
        evidence.reasoning = f"{evidence.reasoning.rstrip()} [Điều chỉnh theo kiểm chứng số liệu: {base} -> {after}. {rule}]"
        result.overall_score = compute_weighted_score(result.criteria)
    result.suggestions = list(result.suggestions) + contradiction_suggestions(summary)


def _check(checker: EvidenceChecker, req: ArgumentEvaluationRequest, settings: Settings) -> EvidenceCheckSummary:
    try:
        return summarize(checker(req.argument_text, req.motion, req.topic, settings))
    except Exception as exc:  # RAG loi thi van cham diem
        logger.warning("Kiem chung RAG that bai, giu diem goc: %s: %s", type(exc).__name__, exc)
        return EvidenceCheckSummary(status="unavailable", error=f"{type(exc).__name__}: {exc}")


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
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-check")
    try:
        future = pool.submit(_check, checker, req, settings)
        # Luot cham chay o thread hien tai, cung luc voi kiem chung; prompt y het luong khong co RAG
        result = evaluate_argument(req, settings, llm_client)
        try:
            summary = future.result(timeout=settings.rag_check_timeout_seconds)
        except FutureTimeout:
            logger.warning("Kiem chung RAG qua %ss, giu diem goc", settings.rag_check_timeout_seconds)
            summary = EvidenceCheckSummary(
                status="unavailable", error=f"Timeout: quá {settings.rag_check_timeout_seconds} giây"
            )
    finally:
        # Khong cho thread kiem chung con chay (vd khi timeout hoac luot cham loi)
        pool.shutdown(wait=False, cancel_futures=True)

    apply_adjustment(result, summary, settings.rag_evidence_bonus)
    result.evidence_check = summary
    return result
