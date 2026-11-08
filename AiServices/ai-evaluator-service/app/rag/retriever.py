"""
Retrieval theo 3 mode: vector, keyword, hybrid (gop 2 nhanh bang Reciprocal Rank Fusion).

Chi import store/embedder khi can, de phan RRF test duoc ma khong can psycopg, torch hay DB.
"""
from typing import TYPE_CHECKING, Literal, Optional, Sequence

from app.rag.schemas import RetrievedFact

if TYPE_CHECKING:
    from app.rag.embedder import Embedder
    from app.rag.store import FactStore

RetrievalMode = Literal["vector", "keyword", "hybrid"]

HYBRID_CANDIDATES = 20  # So ung vien lay tu moi nhanh truoc khi gop
RRF_K = 60


def reciprocal_rank_fusion(
    vector_hits: Sequence[RetrievedFact],
    keyword_hits: Sequence[RetrievedFact],
    k: int,
    k_rrf: int = RRF_K,
) -> list[RetrievedFact]:
    """Gop 2 danh sach da xep hang: score = tong 1 / (k_rrf + rank). Rank tinh theo vi tri trong danh sach."""
    merged: dict = {}
    for hits, rank_field in ((vector_hits, "vector_rank"), (keyword_hits, "keyword_rank")):
        for rank, hit in enumerate(hits, start=1):
            entry = merged.setdefault(
                hit.fact_id,
                RetrievedFact(fact_id=hit.fact_id, content=hit.content, citation=hit.citation, score=0.0),
            )
            entry.score += 1 / (k_rrf + rank)
            setattr(entry, rank_field, rank)
    # Bang diem thi xep theo fact_id de ket qua khong doi giua cac lan chay
    return sorted(merged.values(), key=lambda fact: (-fact.score, str(fact.fact_id)))[:k]


def retrieve(
    query: str,
    topic: str,
    k: int,
    mode: RetrievalMode = "hybrid",
    store: "Optional[FactStore]" = None,
    embedder: "Optional[Embedder]" = None,
) -> list[RetrievedFact]:
    """Lay top k fact. Khong truyen store/embedder thi tu mo ket noi va load model (ton kem, chi hop goi le)."""
    if mode not in ("vector", "keyword", "hybrid"):
        raise ValueError(f"mode khong hop le: {mode}")

    if store is None:
        from app.rag.store import FactStore

        with FactStore() as own_store:
            return retrieve(query, topic, k, mode, own_store, embedder)
    if embedder is None and mode != "keyword":
        from app.rag.embedder import Embedder

        embedder = Embedder()

    if mode == "keyword":
        return store.keyword_search(query, topic, k)

    query_embedding = embedder.encode([query])[0]
    if mode == "vector":
        return store.vector_search(query_embedding, topic, k)

    return reciprocal_rank_fusion(
        store.vector_search(query_embedding, topic, HYBRID_CANDIDATES),
        store.keyword_search(query, topic, HYBRID_CANDIDATES),
        k,
    )
