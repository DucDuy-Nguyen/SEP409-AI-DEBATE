"""Truy cap kho fact tren Postgres + pgvector (psycopg 3). Search chi lay fact status='approved'."""
from typing import Optional, Sequence
from uuid import UUID

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from app.config import get_settings
from app.rag.keyword_query import build_or_tsquery
from app.rag.schemas import FactCard, RetrievedFact

_VECTOR_SEARCH_SQL = """
    SELECT id, content, citation, 1 - (embedding <=> %(embedding)s) AS score
    FROM fact_card
    WHERE topic = %(topic)s AND status = 'approved' AND embedding IS NOT NULL
    ORDER BY embedding <=> %(embedding)s
    LIMIT %(k)s
"""

_KEYWORD_SEARCH_SQL = """
    SELECT id, content, citation, ts_rank_cd(content_tsv, query) AS score
    FROM fact_card, to_tsquery('simple', %(tsquery)s) AS query
    WHERE topic = %(topic)s AND status = 'approved' AND content_tsv @@ query
    ORDER BY score DESC, id
    LIMIT %(k)s
"""


class FactStore:
    """Dung voi `with FactStore() as store:`; thoat binh thuong thi commit, co loi thi rollback."""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or get_settings().rag_database_url
        self._conn: Optional[psycopg.Connection] = None

    def __enter__(self) -> "FactStore":
        self._conn = psycopg.connect(self.database_url)
        register_vector(self._conn)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._conn.__exit__(exc_type, exc, tb)

    def commit(self) -> None:
        self._conn.commit()

    def delete_source_by_dataset_ref(self, dataset_ref: str) -> int:
        """Xoa source cu (fact_card xoa theo ON DELETE CASCADE) de ingest chay lai khong bi trung."""
        return self._conn.execute("DELETE FROM knowledge_source WHERE dataset_ref = %s", (dataset_ref,)).rowcount

    def dataset_refs_with_prefix(self, prefix: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT dataset_ref FROM knowledge_source WHERE starts_with(dataset_ref, %s)", (prefix,)
        ).fetchall()
        return {row[0] for row in rows}

    def count_facts_by_topic(self) -> dict[str, int]:
        rows = self._conn.execute("SELECT topic, count(*) FROM fact_card GROUP BY topic ORDER BY topic").fetchall()
        return {row[0]: row[1] for row in rows}

    def insert_source(
        self,
        topic: str,
        source_type: str,
        title: Optional[str] = None,
        url: Optional[str] = None,
        dataset_ref: Optional[str] = None,
    ) -> UUID:
        row = self._conn.execute(
            """
            INSERT INTO knowledge_source (topic, source_type, title, url, dataset_ref)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            """,
            (topic, source_type, title, url, dataset_ref),
        ).fetchone()
        return row[0]

    def insert_facts(self, source_id: UUID, facts: Sequence[FactCard]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO fact_card (source_id, topic, content, citation, published_date, status, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        source_id,
                        fact.topic,
                        fact.content,
                        fact.citation,
                        fact.published_date,
                        fact.status,
                        np.array(fact.embedding) if fact.embedding is not None else None,
                    )
                    for fact in facts
                ],
            )

    def vector_search(self, embedding: Sequence[float], topic: str, k: int) -> list[RetrievedFact]:
        params = {"embedding": np.array(embedding), "topic": topic, "k": k}
        # HNSW loc topic SAU khi quet index, nen neu khong quet lap (can pgvector >= 0.8) mot topic nho
        # co the tra ve it hon k dong. Dang trong transaction ngam thi day chi la savepoint: SET LOCAL
        # con hieu luc toi het transaction ngoai, khong anh huong keyword_search.
        with self._conn.transaction():
            self._conn.execute("SET LOCAL hnsw.iterative_scan = strict_order")
            rows = self._conn.execute(_VECTOR_SEARCH_SQL, params).fetchall()
        return [
            RetrievedFact(fact_id=row[0], content=row[1], citation=row[2], score=float(row[3]), vector_rank=rank)
            for rank, row in enumerate(rows, start=1)
        ]

    def keyword_search(self, query: str, topic: str, k: int) -> list[RetrievedFact]:
        tsquery = build_or_tsquery(query)
        if tsquery is None:
            return []
        rows = self._conn.execute(_KEYWORD_SEARCH_SQL, {"tsquery": tsquery, "topic": topic, "k": k}).fetchall()
        return [
            RetrievedFact(fact_id=row[0], content=row[1], citation=row[2], score=float(row[3]), keyword_rank=rank)
            for rank, row in enumerate(rows, start=1)
        ]

    def dataset_refs_for_facts(self, fact_ids: Sequence[UUID]) -> dict[UUID, Optional[str]]:
        """Fact thuoc source nao, de script danh gia biet fact co dung article khong."""
        rows = self._conn.execute(
            """
            SELECT f.id, s.dataset_ref FROM fact_card f
            JOIN knowledge_source s ON s.id = f.source_id
            WHERE f.id = ANY(%s)
            """,
            (list(fact_ids),),
        ).fetchall()
        return {row[0]: row[1] for row in rows}
