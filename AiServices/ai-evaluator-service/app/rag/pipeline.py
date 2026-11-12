"""Tach claim roi verify: luot lap luan khong co claim thuc chung thi khong goi verify."""
from typing import TYPE_CHECKING, Optional

from app.config import Settings, get_settings
from app.rag.claim_extractor import extract_claims
from app.rag.llm_usage import LLMCallStats
from app.rag.schemas import EvidenceCheckResult, VerdictLabel
from app.rag.verifier import verify_claims
from app.services.llm_client import LLMClient

if TYPE_CHECKING:
    from app.rag.embedder import Embedder
    from app.rag.store import FactStore

NO_CLAIM_REASON = "Lập luận không có claim thực chứng cần kiểm chứng."


def check_evidence(
    argument_text: str,
    motion: str,
    topic: str,
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
    store: "Optional[FactStore]" = None,
    embedder: "Optional[Embedder]" = None,
    stats: Optional[LLMCallStats] = None,
) -> EvidenceCheckResult:
    settings = settings or get_settings()
    counts = {label.value: 0 for label in VerdictLabel}

    claims = extract_claims(argument_text, motion, settings, llm_client, stats)
    if not claims:
        return EvidenceCheckResult(counts=counts, skipped_reason=NO_CLAIM_REASON)

    verifications = verify_claims(
        [claim.text for claim in claims], topic, settings, llm_client, store, embedder, stats
    )
    for verification in verifications:
        counts[verification.label.value] += 1
    return EvidenceCheckResult(claims=verifications, counts=counts)
