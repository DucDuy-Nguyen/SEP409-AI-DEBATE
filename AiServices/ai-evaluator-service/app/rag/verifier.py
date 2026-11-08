"""
Verify claim bang LLM, chi dua tren fact retrieve duoc (hoac fact truyen san, vd gold evidence o che do oracle).

Rang buoc cung bang code: SUPPORTED/CONTRADICTED ma fact_ids rong hoac co id khong nam trong fact da dua vao
cua CHINH claim do -> ep ve NOT_FOUND, coerced=True. Claim khong co fact nao thi tra NOT_FOUND luon, khong goi LLM.
"""
from typing import TYPE_CHECKING, Optional, Sequence

from app.config import Settings, get_settings
from app.rag.llm_usage import LLMCallStats, tracking_generate
from app.rag.prompts import build_verify_prompt
from app.rag.schemas import ClaimVerification, RetrievedFact, VerdictLabel
from app.services.json_utils import EvaluationParseError, call_llm_with_retry
from app.services.llm_client import LLMClient, get_llm_client

if TYPE_CHECKING:
    from app.rag.embedder import Embedder
    from app.rag.store import FactStore

VERIFY_BATCH_SIZE = 5  # So claim toi da trong 1 lan goi LLM

NO_FACT_REASON = "Không tìm thấy fact nào trong kho cho claim này."
COERCED_PREFIX = "[Ép về NOT_FOUND vì thiếu fact_id hợp lệ] "


def _build_batch_results(
    parsed: dict, claims: Sequence[str], facts_per_claim: Sequence[Sequence[RetrievedFact]]
) -> list[ClaimVerification]:
    items = parsed.get("results")
    if not isinstance(items, list):
        raise EvaluationParseError("LLM khong tra ve mang 'results'")

    by_index: dict[int, dict] = {}
    for item in items:
        index_value = item.get("claim_index") if isinstance(item, dict) else None
        # bool la lop con cua int: true khong duoc hieu la claim 1
        if not isinstance(index_value, int) or isinstance(index_value, bool):
            raise EvaluationParseError(f"Phan tu thieu claim_index: {item}")
        by_index[item["claim_index"]] = item
    if sorted(by_index) != list(range(1, len(claims) + 1)) or len(items) != len(claims):
        raise EvaluationParseError(f"Ky vong claim_index 1..{len(claims)}, nhan {sorted(by_index)}")

    results = []
    for index, (claim, facts) in enumerate(zip(claims, facts_per_claim), start=1):
        item = by_index[index]
        try:
            label = VerdictLabel(str(item.get("label", "")).strip().upper())
        except ValueError as exc:
            raise EvaluationParseError(f"Nhan khong hop le: {item.get('label')}") from exc
        raw_ids = item.get("fact_ids", [])
        reason = item.get("reason")
        if not isinstance(raw_ids, list) or not isinstance(reason, str) or not reason.strip():
            raise EvaluationParseError(f"fact_ids/reason khong hop le o claim {index}")

        allowed = {str(fact.fact_id).lower() for fact in facts}
        fact_ids = [str(fact_id).strip().lower() for fact_id in raw_ids]
        valid_ids = [fact_id for fact_id in fact_ids if fact_id in allowed]
        coerced = False
        if label != VerdictLabel.NOT_FOUND and (not fact_ids or len(valid_ids) != len(fact_ids)):
            label, coerced, reason = VerdictLabel.NOT_FOUND, True, COERCED_PREFIX + reason
        results.append(
            ClaimVerification(
                claim=claim,
                label=label,
                fact_ids=valid_ids,
                reason=reason.strip(),
                coerced=coerced,
                retrieved=list(facts),
            )
        )
    return results


def verify_with_facts(
    claims: Sequence[str],
    facts_per_claim: Sequence[Sequence[RetrievedFact]],
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
    stats: Optional[LLMCallStats] = None,
) -> list[ClaimVerification]:
    """Verify voi fact da co san cho tung claim; gop toi da VERIFY_BATCH_SIZE claim moi lan goi LLM."""
    if len(claims) != len(facts_per_claim):
        raise ValueError("claims va facts_per_claim phai cung do dai")

    results: list[Optional[ClaimVerification]] = [None] * len(claims)
    pending = []
    for position, (claim, facts) in enumerate(zip(claims, facts_per_claim)):
        if facts:
            pending.append(position)
        else:
            results[position] = ClaimVerification(claim=claim, label=VerdictLabel.NOT_FOUND, reason=NO_FACT_REASON)

    client = None
    for start in range(0, len(pending), VERIFY_BATCH_SIZE):
        positions = pending[start : start + VERIFY_BATCH_SIZE]
        batch_claims = [claims[position] for position in positions]
        batch_facts = [facts_per_claim[position] for position in positions]
        if client is None:
            client = llm_client if llm_client is not None else get_llm_client(settings or get_settings())
        system_prompt, user_prompt = build_verify_prompt(batch_claims, batch_facts)
        if stats is not None:
            stats.requests += 1
        batch_results = call_llm_with_retry(
            generate_fn=tracking_generate(client, system_prompt, stats),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            build_result_fn=lambda parsed, raw, c=batch_claims, f=batch_facts: _build_batch_results(parsed, c, f),
            audit_label="rag_verify",
        )
        for position, result in zip(positions, batch_results):
            results[position] = result
            if stats is not None and result.coerced:
                stats.coerced += 1
    return results


def verify_claims(
    claims: Sequence[str],
    topic: str,
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
    store: "Optional[FactStore]" = None,
    embedder: "Optional[Embedder]" = None,
    stats: Optional[LLMCallStats] = None,
) -> list[ClaimVerification]:
    """Retrieve hybrid top settings.rag_top_k cho tung claim roi verify."""
    from app.rag.retriever import retrieve

    settings = settings or get_settings()
    if store is None:
        from app.rag.store import FactStore

        with FactStore() as own_store:
            return verify_claims(claims, topic, settings, llm_client, own_store, embedder, stats)
    if embedder is None:
        from app.rag.embedder import get_default_embedder

        embedder = get_default_embedder()

    facts_per_claim = [retrieve(claim, topic, settings.rag_top_k, "hybrid", store, embedder) for claim in claims]
    return verify_with_facts(claims, facts_per_claim, settings, llm_client, stats)
