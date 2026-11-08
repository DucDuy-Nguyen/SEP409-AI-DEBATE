"""
Verify claim bang LLM, chi dua tren fact retrieve duoc (hoac fact truyen san, vd gold evidence o che do oracle).

Rang buoc cung bang code: SUPPORTED/CONTRADICTED ma fact_ids rong hoac co id khong nam trong fact da dua vao
cua CHINH claim do -> ep ve NOT_FOUND, coerced=True. SUPPORTED ma con chi tiet khong co trong fact (unsupported_details
khac rong) -> ha xuong NOT_FOUND, downgraded=True. Co it nhat 1 fact "supports" VA 1 fact "contradicts" (sau khi bo
fact_id la) -> CONFLICTING, bat ke nhan LLM gan. Claim khong co fact nao thi tra NOT_FOUND luon, khong goi LLM.
"""
from typing import TYPE_CHECKING, Optional, Sequence

from app.config import Settings, get_settings
from app.rag.llm_usage import LLMCallStats, tracking_generate
from app.rag.prompts import build_verify_prompt
from app.rag.schemas import ClaimDetail, ClaimVerification, RetrievedFact, VerdictLabel
from app.services.json_utils import EvaluationParseError, call_llm_with_retry
from app.services.llm_client import LLMClient, get_llm_client

if TYPE_CHECKING:
    from app.rag.embedder import Embedder
    from app.rag.store import FactStore

VERIFY_BATCH_SIZE = 5  # So claim toi da trong 1 lan goi LLM

NO_FACT_REASON = "Không tìm thấy fact nào trong kho cho claim này."
COERCED_PREFIX = "[Ép về NOT_FOUND vì thiếu fact_id hợp lệ] "
DOWNGRADED_PREFIX = "[Hạ xuống NOT_FOUND vì có chi tiết không có trong fact] "


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
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise EvaluationParseError(f"reason khong hop le o claim {index}")

        allowed = {str(fact.fact_id).lower() for fact in facts}
        cited = _parse_cited_facts(item, index)
        fact_ids = [fact_id for fact_id, _ in cited]
        # fact_id la bi loai TRUOC khi xet CONFLICTING, de id bia khong tao mau thuan gia
        stances = {fact_id: stance for fact_id, stance in cited if fact_id in allowed and stance}
        valid_ids = [fact_id for fact_id in fact_ids if fact_id in allowed]
        details, unsupported = _parse_details(item, allowed, index)

        coerced = downgraded = False
        if {"supports", "contradicts"} <= set(stances.values()):
            # Luat bang code, bat ke LLM gan nhan gi: co fact xac nhan VA co fact noi trai -> nguon chua thong nhat
            label = VerdictLabel.CONFLICTING
        elif label == VerdictLabel.CONFLICTING:
            # CONFLICTING chi do code gan; LLM tu gan ma stance khong mau thuan thi coi nhu khong du de ket luan
            label, coerced, reason = VerdictLabel.NOT_FOUND, True, COERCED_PREFIX + reason
        elif label != VerdictLabel.NOT_FOUND and (not fact_ids or len(valid_ids) != len(fact_ids)):
            label, coerced, reason = VerdictLabel.NOT_FOUND, True, COERCED_PREFIX + reason
        elif label == VerdictLabel.SUPPORTED and unsupported:
            label, downgraded, reason = VerdictLabel.NOT_FOUND, True, DOWNGRADED_PREFIX + reason
        results.append(
            ClaimVerification(
                claim=claim,
                label=label,
                fact_ids=valid_ids,
                reason=reason.strip(),
                coerced=coerced,
                details=details,
                unsupported_details=unsupported,
                downgraded=downgraded,
                fact_stances=stances,
                retrieved=list(facts),
            )
        )
    return results


def _verify_settings(settings: Optional[Settings]) -> Settings:
    """Settings cho client verify: rieng gioi han token, khong doi gioi han cua luong cham diem."""
    settings = settings or get_settings()
    return settings.model_copy(update={"llm_max_tokens": settings.rag_verify_max_tokens})


STANCES = ("supports", "contradicts")


def _parse_cited_facts(item: dict, index: int) -> list[tuple[str, str]]:
    """
    (fact_id da chuan hoa, stance) cua cac fact LLM trich. Dinh dang moi: "cited_facts" = [{fact_id, stance}].
    Output cu chi co "fact_ids" thi stance rong (khong bao gio tao CONFLICTING).
    """
    raw = item.get("cited_facts")
    if raw is None:
        raw_ids = item.get("fact_ids", [])
        if not isinstance(raw_ids, list):
            raise EvaluationParseError(f"fact_ids khong hop le o claim {index}")
        return [(str(fact_id).strip().lower(), "") for fact_id in raw_ids]
    if not isinstance(raw, list):
        raise EvaluationParseError(f"cited_facts phai la mang o claim {index}")
    cited = []
    for entry in raw:
        if not isinstance(entry, dict) or not str(entry.get("fact_id", "")).strip():
            raise EvaluationParseError(f"Phan tu cited_facts khong hop le o claim {index}: {entry}")
        stance = str(entry.get("stance", "")).strip().lower()
        if stance not in STANCES:
            raise EvaluationParseError(f"stance khong hop le o claim {index}: {entry.get('stance')}")
        cited.append((str(entry["fact_id"]).strip().lower(), stance))
    # Cung 1 fact vua supports vua contradicts la output mau thuan: thu lai thay vi de dict ghi de lang le
    seen: dict[str, str] = {}
    for fact_id, stance in cited:
        if seen.setdefault(fact_id, stance) != stance:
            raise EvaluationParseError(f"fact {fact_id} co 2 stance khac nhau o claim {index}")
    return cited


def _parse_details(item: dict, allowed: set[str], index: int) -> tuple[list[ClaimDetail], list[str]]:
    """
    Chi tiet + fact chua no, va danh sach chi tiet khong co trong fact. Chi tiet LLM khong chi ra duoc fact_id hop le
    cung tinh la khong co trong fact, du LLM khong ghi no vao unsupported_details.
    """
    raw_details = item.get("details")
    raw_unsupported = item.get("unsupported_details")
    if not isinstance(raw_details, list) or not isinstance(raw_unsupported, list):
        raise EvaluationParseError(f"details/unsupported_details phai la mang o claim {index}")

    details = []
    unsupported = [str(text).strip() for text in raw_unsupported if str(text).strip()]
    for raw in raw_details:
        if not isinstance(raw, dict) or not isinstance(raw.get("detail"), str) or not raw["detail"].strip():
            raise EvaluationParseError(f"Chi tiet khong hop le o claim {index}: {raw}")
        ids = raw.get("fact_ids", [])
        if not isinstance(ids, list):
            raise EvaluationParseError(f"fact_ids cua chi tiet khong hop le o claim {index}")
        valid = [str(fact_id).strip().lower() for fact_id in ids if str(fact_id).strip().lower() in allowed]
        text = raw["detail"].strip()
        details.append(ClaimDetail(detail=text, fact_ids=valid))
        if not valid:
            unsupported.append(text)
    # Bo trung nhung giu thu tu
    return details, list(dict.fromkeys(unsupported))


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
            client = llm_client if llm_client is not None else get_llm_client(_verify_settings(settings))
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
            if stats is not None:
                stats.coerced += result.coerced
                stats.downgraded += result.downgraded
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
