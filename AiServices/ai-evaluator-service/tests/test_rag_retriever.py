"""Test RRF va luong retrieve bang store/embedder gia: khong can DB va khong load model."""
import subprocess
import sys
from uuid import UUID

import pytest

from app.rag.retriever import HYBRID_CANDIDATES, reciprocal_rank_fusion, retrieve
from app.rag.schemas import RetrievedFact


def _fact_id(n: int) -> UUID:
    return UUID(int=n)


def _hit(n: int) -> RetrievedFact:
    return RetrievedFact(fact_id=_fact_id(n), content=f"fact {n}", score=0.5)


def test_rrf_scores_and_order():
    result = reciprocal_rank_fusion([_hit(1), _hit(2)], [_hit(2), _hit(3)], k=10)

    assert [fact.fact_id for fact in result] == [_fact_id(2), _fact_id(1), _fact_id(3)]
    assert result[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert result[1].score == pytest.approx(1 / 61)
    assert result[2].score == pytest.approx(1 / 62)


def test_rrf_records_ranks_and_handles_fact_on_one_side():
    by_id = {f.fact_id: f for f in reciprocal_rank_fusion([_hit(1), _hit(2)], [_hit(2), _hit(3)], k=10)}

    assert (by_id[_fact_id(1)].vector_rank, by_id[_fact_id(1)].keyword_rank) == (1, None)
    assert (by_id[_fact_id(2)].vector_rank, by_id[_fact_id(2)].keyword_rank) == (2, 1)
    assert (by_id[_fact_id(3)].vector_rank, by_id[_fact_id(3)].keyword_rank) == (None, 2)


def test_rrf_cuts_to_k_and_accepts_empty_side():
    assert len(reciprocal_rank_fusion([_hit(1), _hit(2), _hit(3)], [], k=2)) == 2
    assert reciprocal_rank_fusion([], [], k=5) == []


def test_rrf_tie_is_deterministic():
    first = reciprocal_rank_fusion([_hit(2)], [_hit(1)], k=2)
    second = reciprocal_rank_fusion([_hit(2)], [_hit(1)], k=2)
    assert [f.fact_id for f in first] == [f.fact_id for f in second] == [_fact_id(1), _fact_id(2)]


class _FakeStore:
    def __init__(self):
        self.calls = []

    def vector_search(self, embedding, topic, k):
        self.calls.append(("vector", topic, k))
        return [_hit(1), _hit(2)]

    def keyword_search(self, query, topic, k):
        self.calls.append(("keyword", topic, k))
        return [_hit(2), _hit(3)]


class _FakeEmbedder:
    def encode(self, texts):
        return [[0.0] for _ in texts]


def test_retrieve_vector_and_keyword_use_one_branch_with_k():
    store = _FakeStore()
    retrieve("q", "education", 5, "vector", store, _FakeEmbedder())
    retrieve("q", "education", 5, "keyword", store)
    assert store.calls == [("vector", "education", 5), ("keyword", "education", 5)]


def test_retrieve_hybrid_takes_candidates_from_both_then_cuts_to_k():
    store = _FakeStore()
    result = retrieve("q", "technology", 2, "hybrid", store, _FakeEmbedder())
    assert store.calls == [("vector", "technology", HYBRID_CANDIDATES), ("keyword", "technology", HYBRID_CANDIDATES)]
    assert [fact.fact_id for fact in result] == [_fact_id(2), _fact_id(1)]


def test_retrieve_rejects_unknown_mode():
    with pytest.raises(ValueError):
        retrieve("q", "education", 5, "semantic", _FakeStore(), _FakeEmbedder())


def test_service_does_not_import_heavy_rag_dependencies():
    # Tien trinh rieng: test khac trong cung tien trinh co the da import cac module nay
    code = (
        "import sys; import app.main; import app.rag.retriever; "
        "print(sorted(m for m in ('torch', 'sentence_transformers', 'psycopg') if m in sys.modules))"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert output.strip() == "[]"
