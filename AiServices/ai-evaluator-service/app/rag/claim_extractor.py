"""Tach claim thuc chung tu 1 luot lap luan bang LLM (1 lan goi, toi da settings.rag_max_claims claim)."""
from typing import Optional

from pydantic import ValidationError

from app.config import Settings, get_settings
from app.rag.llm_usage import LLMCallStats, tracking_generate
from app.rag.prompts import build_extract_prompt
from app.rag.schemas import ExtractedClaim
from app.services.json_utils import EvaluationParseError, call_llm_with_retry
from app.services.llm_client import LLMClient, get_llm_client


def _build_claims(parsed: dict, max_claims: int) -> list[ExtractedClaim]:
    items = parsed.get("claims")
    if not isinstance(items, list):
        raise EvaluationParseError("LLM khong tra ve mang 'claims'")
    try:
        claims = [ExtractedClaim(**item) for item in items]
    except (TypeError, ValidationError) as exc:
        raise EvaluationParseError(f"Claim khong hop le: {exc}") from exc
    # Prompt da gioi han, code cat lai de khong bao gio vuot
    return claims[:max_claims]


def extract_claims(
    argument_text: str,
    motion: str,
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
    stats: Optional[LLMCallStats] = None,
) -> list[ExtractedClaim]:
    """Luot lap luan rong thi tra [] ma khong goi LLM."""
    if not argument_text.strip():
        return []
    settings = settings or get_settings()
    client = llm_client or get_llm_client(settings)
    system_prompt, user_prompt = build_extract_prompt(argument_text, motion, settings.rag_max_claims)
    if stats is not None:
        stats.requests += 1
    return call_llm_with_retry(
        generate_fn=tracking_generate(client, system_prompt, stats),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        build_result_fn=lambda parsed, raw: _build_claims(parsed, settings.rag_max_claims),
        audit_label="rag_extract",
    )
