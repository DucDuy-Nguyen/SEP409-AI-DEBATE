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
import threading
import time
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
    RoundEvaluationRequest,
    RoundEvaluationResult,
    TurnEvidenceCheck,
    TurnSpeaker,
)
from app.services.evaluator import evaluate_argument
from app.services.llm_client import LLMClient
from app.services.round_evaluator import evaluate_round
from app.services.scoring import compute_weighted_score

logger = logging.getLogger(__name__)

EVIDENCE_CRITERION = "Evidence"
MIN_SCORE, MAX_SCORE = 1, 5
CONTRADICTED_CAP = 4  # Co CONTRADICTED thi tinh tu toi da 4 truoc khi tru
CITATION_MAX_CHARS = 300
SUGGESTION_SNIPPET_CHARS = 160  # Noi dung rut gon cua fact trong goi y CONFLICTING

EXCERPT_MAX_CHARS = 200  # Doan dau cua luot learner tra kem ket qua kiem chung o /evaluate/round
FACT_BASE_CACHE_SECONDS = 300

# (argument_text, motion, topic, settings) -> EvidenceCheckResult cua app/rag (kieu de lazy, tranh import RAG khi tat)
EvidenceChecker = Callable[[str, str, str, Settings], object]
# (topic, settings) -> so fact approved cua topic trong kho
FactCounter = Callable[[str, Settings], int]

_fact_base_cache: dict[str, tuple[float, int]] = {}
_fact_base_lock = threading.Lock()


def _default_fact_counter(topic: str, settings: Settings) -> int:
    """So fact approved cua topic, cache FACT_BASE_CACHE_SECONDS (1 query count, khong load model)."""
    now = time.monotonic()
    with _fact_base_lock:
        cached = _fact_base_cache.get(topic)
        if cached and now - cached[0] < FACT_BASE_CACHE_SECONDS:
            return cached[1]
    from app.rag.store import FactStore

    with FactStore(settings.rag_database_url) as store:
        count = store.count_approved(topic)
    with _fact_base_lock:
        _fact_base_cache[topic] = (now, count)
    return count


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


UNAVAILABLE_RULE = "Kiểm chứng không chạy được: giữ nguyên điểm Evidence."
NO_FACT_BASE_RULE = "Chủ đề chưa có kho dữ kiện đã duyệt: giữ nguyên điểm Evidence."


def _adjust_evidence_criterion(criteria, labels: list[str], bonus: bool) -> tuple[int, int, str]:
    """Dieu chinh tieu chi Evidence tai cho (dung chung /evaluate va /evaluate/round). Tra (goc, sau, luat)."""
    evidence = next(c for c in criteria if c.name == EVIDENCE_CRITERION)
    base = evidence.score
    after, rule = adjust_evidence(base, labels, bonus)
    if after != base:
        evidence.score = after
        evidence.reasoning = f"{evidence.reasoning.rstrip()} [Điều chỉnh theo kiểm chứng số liệu: {base} -> {after}. {rule}]"
    return base, after, rule


def apply_adjustment(result: ArgumentEvaluationResult, summary: EvidenceCheckSummary, bonus: bool) -> None:
    if summary.status in ("unavailable", "no_fact_base"):
        base = next(c.score for c in result.criteria if c.name == EVIDENCE_CRITERION)
        summary.evidence_score_before = summary.evidence_score_after = base
        summary.rule_applied = UNAVAILABLE_RULE if summary.status == "unavailable" else NO_FACT_BASE_RULE
        return

    base, after, rule = _adjust_evidence_criterion(result.criteria, [claim.label for claim in summary.claims], bonus)
    summary.evidence_score_before, summary.evidence_score_after, summary.rule_applied = base, after, rule
    if after != base:
        result.overall_score = compute_weighted_score(result.criteria)
    result.suggestions = list(result.suggestions) + contradiction_suggestions(summary)


def _resolve_fact_counter(evidence_checker: Optional[EvidenceChecker], fact_counter: Optional[FactCounter]):
    """
    Kiem tra "topic co fact approved khong" la 1 phan cua pipeline that: dung bo dem mac dinh (query DB) khi dung checker
    mac dinh. Checker truyen vao (test, script) la ban thay the tron goi, chi kiem tra kho khi truyen kem fact_counter.
    """
    if fact_counter is not None:
        return fact_counter
    return _default_fact_counter if evidence_checker is None else None


def _check_text(
    checker: EvidenceChecker, fact_counter: Optional[FactCounter], text: str, motion: str, topic: str, settings: Settings
) -> EvidenceCheckSummary:
    """Kiem chung 1 doan van; khong bao gio nem loi (RAG loi -> unavailable, kho trong -> no_fact_base)."""
    try:
        if fact_counter is not None and fact_counter(topic, settings) == 0:
            return EvidenceCheckSummary(status="no_fact_base")  # Khong goi LLM tach claim / verify
        return summarize(checker(text, motion, topic, settings))
    except Exception as exc:  # RAG loi thi van cham diem
        logger.warning("Kiem chung RAG that bai, giu diem goc: %s: %s", type(exc).__name__, exc)
        return EvidenceCheckSummary(status="unavailable", error=f"{type(exc).__name__}: {exc}")


def _check(
    checker: EvidenceChecker,
    req: ArgumentEvaluationRequest,
    settings: Settings,
    fact_counter: Optional[FactCounter] = None,
) -> EvidenceCheckSummary:
    return _check_text(checker, fact_counter, req.argument_text, req.motion, req.topic, settings)


def evaluate_argument_with_evidence(
    req: ArgumentEvaluationRequest,
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
    evidence_checker: Optional[EvidenceChecker] = None,
    fact_counter: Optional[FactCounter] = None,
) -> ArgumentEvaluationResult:
    settings = settings or get_settings()
    if not (settings.rag_enabled and req.topic):
        return evaluate_argument(req, settings, llm_client)

    checker = evidence_checker or _default_checker
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-check")
    try:
        future = pool.submit(_check, checker, req, settings, _resolve_fact_counter(evidence_checker, fact_counter))
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


def evaluate_round_with_evidence(
    req: RoundEvaluationRequest,
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
    evidence_checker: Optional[EvidenceChecker] = None,
    fact_counter: Optional[FactCounter] = None,
) -> RoundEvaluationResult:
    """
    /evaluate/round co kiem chung (docs/RAG_REPORT_INTEGRATION_SPEC.md muc A2). Luot cham goi evaluate_round cu nguyen
    ven (prompt khong doi); moi luot learner duoc kiem chung song song voi luot cham, luot opponent khong kiem. Nhan cua
    moi claim trong cac luot "checked" duoc gop lai de dieu chinh Evidence cua round bang adjust_evidence.
    """
    settings = settings or get_settings()
    if not (settings.rag_enabled and req.topic and req.check_evidence):
        return evaluate_round(req, settings, llm_client)

    checker = evidence_checker or _default_checker
    counter = _resolve_fact_counter(evidence_checker, fact_counter)
    learner_turns = [(index, turn) for index, turn in enumerate(req.turns) if turn.speaker == TurnSpeaker.LEARNER]
    if not learner_turns:
        # Validator cua RoundEvaluationRequest da chan; giu de ThreadPoolExecutor khong bao gio nhan max_workers=0
        return evaluate_round(req, settings, llm_client)
    pool = ThreadPoolExecutor(max_workers=len(learner_turns), thread_name_prefix="rag-round-check")
    try:
        started = time.monotonic()
        futures = [
            (index, turn, pool.submit(_check_text, checker, counter, turn.text, req.motion, req.topic, settings))
            for index, turn in learner_turns
        ]
        # Luot cham chay o thread hien tai, cung luc voi kiem chung; prompt y het luong khong co RAG
        result = evaluate_round(req, settings, llm_client)
        deadline = started + settings.rag_round_check_timeout_seconds
        checks = []
        for index, turn, future in futures:
            try:
                summary = future.result(timeout=max(deadline - time.monotonic(), 0))
            except FutureTimeout:
                logger.warning("Kiem chung luot %s qua %ss, giu diem goc", index, settings.rag_round_check_timeout_seconds)
                summary = EvidenceCheckSummary(
                    status="unavailable", error=f"Timeout: quá {settings.rag_round_check_timeout_seconds} giây"
                )
            checks.append(TurnEvidenceCheck(turn_index=index, excerpt=turn.text[:EXCERPT_MAX_CHARS], evidence_check=summary))
    finally:
        # Khong cho thread kiem chung con chay (vd khi timeout hoac luot cham loi)
        pool.shutdown(wait=False, cancel_futures=True)

    checked = [c.evidence_check for c in checks if c.evidence_check.status == "checked"]
    labels = [claim.label for summary in checked for claim in summary.claims]
    if labels:
        before, after, rule = _adjust_evidence_criterion(result.criteria, labels, settings.rag_evidence_bonus)
        result.evidence_score_before, result.evidence_score_after, result.evidence_rule_applied = before, after, rule
        if after != before:
            result.round_score = compute_weighted_score(result.criteria)
        result.suggestions = list(result.suggestions) + [
            suggestion for summary in checked for suggestion in contradiction_suggestions(summary)
        ]
    result.evidence_checks = checks
    return result
