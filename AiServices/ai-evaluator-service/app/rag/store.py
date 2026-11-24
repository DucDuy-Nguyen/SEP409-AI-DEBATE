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

    def count_approved(self, topic: str) -> int:
        """So fact approved cua topic: 0 thi khong co kho du kien de kiem chung (status no_fact_base)."""
        row = self._conn.execute(
            "SELECT count(*) FROM fact_card WHERE topic = %s AND status = 'approved'", (topic,)
        ).fetchone()
        return int(row[0])

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

    def list_sources(
        self,
        topic: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        where_sql = "WHERE s.topic = %s" if topic else ""
        params: list = [topic] if topic else []

        total_row = self._conn.execute(
            f"SELECT count(*) FROM knowledge_source s {where_sql}",
            params,
        ).fetchone()
        total = int(total_row[0]) if total_row else 0

        rows = self._conn.execute(
            f"""
            SELECT
                s.id,
                s.topic,
                s.source_type,
                s.title,
                s.url,
                s.dataset_ref,
                s.created_at,
                count(f.id) AS total_facts,
                count(f.id) FILTER (WHERE f.status = 'approved') AS approved_facts,
                count(f.id) FILTER (WHERE f.status = 'pending') AS pending_facts,
                count(f.id) FILTER (WHERE f.status = 'rejected') AS rejected_facts
            FROM knowledge_source s
            LEFT JOIN fact_card f ON f.source_id = s.id
            {where_sql}
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        ).fetchall()

        items = [
            {
                "id": str(r[0]),
                "topic": r[1],
                "source_type": r[2],
                "title": r[3],
                "url": r[4],
                "dataset_ref": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "total_facts": int(r[7]),
                "approved_facts": int(r[8]),
                "pending_facts": int(r[9]),
                "rejected_facts": int(r[10]),
            }
            for r in rows
        ]
        return items, total

    def delete_source(self, source_id: UUID) -> bool:
        row = self._conn.execute(
            "DELETE FROM knowledge_source WHERE id = %s RETURNING id",
            (source_id,),
        ).fetchone()
        return row is not None

    def list_facts(
        self,
        topic: Optional[str] = None,
        status: Optional[str] = None,
        source_id: Optional[UUID] = None,
        query: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        clauses: list[str] = []
        params: list = []
        if topic:
            clauses.append("f.topic = %s")
            params.append(topic)
        if status:
            clauses.append("f.status = %s")
            params.append(status)
        if source_id:
            clauses.append("f.source_id = %s")
            params.append(source_id)
        if query and query.strip():
            clauses.append("(f.content ILIKE %s OR COALESCE(f.citation, '') ILIKE %s)")
            like = f"%{query.strip()}%"
            params.extend([like, like])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        total_row = self._conn.execute(
            f"SELECT count(*) FROM fact_card f {where_sql}",
            params,
        ).fetchone()
        total = int(total_row[0]) if total_row else 0

        rows = self._conn.execute(
            f"""
            SELECT
                f.id,
                f.source_id,
                f.topic,
                f.content,
                f.citation,
                f.published_date,
                f.status,
                (f.embedding IS NOT NULL) AS has_embedding,
                f.created_at,
                s.title AS source_title
            FROM fact_card f
            LEFT JOIN knowledge_source s ON s.id = f.source_id
            {where_sql}
            ORDER BY f.created_at DESC, f.id
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        ).fetchall()

        items = [
            {
                "id": str(r[0]),
                "source_id": str(r[1]) if r[1] else None,
                "topic": r[2],
                "content": r[3],
                "citation": r[4],
                "published_date": r[5].isoformat() if r[5] else None,
                "status": r[6],
                "has_embedding": bool(r[7]),
                "created_at": r[8].isoformat() if r[8] else None,
                "source_title": r[9],
            }
            for r in rows
        ]
        return items, total

    def get_fact(self, fact_id: UUID) -> Optional[dict]:
        row = self._conn.execute(
            """
            SELECT id, source_id, topic, content, citation, published_date, status, (embedding IS NOT NULL), created_at
            FROM fact_card WHERE id = %s
            """,
            (fact_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "source_id": str(row[1]) if row[1] else None,
            "topic": row[2],
            "content": row[3],
            "citation": row[4],
            "published_date": row[5].isoformat() if row[5] else None,
            "status": row[6],
            "has_embedding": bool(row[7]),
            "created_at": row[8].isoformat() if row[8] else None,
        }

    def update_fact(
        self,
        fact_id: UUID,
        *,
        content: Optional[str] = None,
        citation: Optional[str] = None,
        published_date=None,
        embedding: Optional[Sequence[float]] = None,
    ) -> Optional[dict]:
        sets: list[str] = []
        params: list = []
        if content is not None:
            sets.append("content = %s")
            params.append(content)
        if citation is not None:
            sets.append("citation = %s")
            params.append(citation)
        if published_date is not None:
            sets.append("published_date = %s")
            params.append(published_date)
        if embedding is not None:
            sets.append("embedding = %s")
            params.append(np.array(embedding))
        if not sets:
            return self.get_fact(fact_id)

        params.append(fact_id)
        row = self._conn.execute(
            f"""
            UPDATE fact_card
            SET {', '.join(sets)}
            WHERE id = %s
            RETURNING id
            """,
            params,
        ).fetchone()
        return self.get_fact(fact_id) if row else None

    def update_fact_status(self, fact_id: UUID, status: str) -> Optional[dict]:
        row = self._conn.execute(
            "UPDATE fact_card SET status = %s WHERE id = %s RETURNING id",
            (status, fact_id),
        ).fetchone()
        return self.get_fact(fact_id) if row else None

    def batch_update_fact_status(self, fact_ids: Sequence[UUID], status: str) -> int:
        if not fact_ids:
            return 0
        return self._conn.execute(
            "UPDATE fact_card SET status = %s WHERE id = ANY(%s)",
            (status, list(fact_ids)),
        ).rowcount

    def delete_fact(self, fact_id: UUID) -> bool:
        row = self._conn.execute(
            "DELETE FROM fact_card WHERE id = %s RETURNING id",
            (fact_id,),
        ).fetchone()
        return row is not None

    def get_stats(self) -> dict:
        rows = self._conn.execute(
            """
            SELECT topic, status, count(*)
            FROM fact_card
            GROUP BY topic, status
            ORDER BY topic, status
            """
        ).fetchall()
        by_topic: dict[str, dict[str, int]] = {}
        totals = {"approved": 0, "pending": 0, "rejected": 0, "total": 0}
        for topic, status, cnt in rows:
            c = int(cnt)
            bucket = by_topic.setdefault(topic, {"approved": 0, "pending": 0, "rejected": 0, "total": 0})
            if status in bucket:
                bucket[status] += c
            bucket["total"] += c
            if status in totals:
                totals[status] += c
            totals["total"] += c
        source_row = self._conn.execute("SELECT count(*) FROM knowledge_source").fetchone()
        return {
            "total_sources": int(source_row[0]) if source_row else 0,
            "totals": totals,
            "by_topic": by_topic,
        }
