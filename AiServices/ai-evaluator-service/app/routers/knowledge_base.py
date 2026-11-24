"""WF-05 Knowledge Base & Evidence Management API for Organizer/Admin."""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.rag.chunker import chunk_text
from app.rag.schemas import FactCard
from app.schemas import EvidenceTopic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag/knowledge-base", tags=["knowledge-base"])

FactStatus = Literal["pending", "approved", "rejected"]
SourceType = Literal["manual", "document", "url", "dataset"]


class CreateKnowledgeSourceRequest(BaseModel):
    topic: EvidenceTopic
    source_type: SourceType = "manual"
    title: Optional[str] = Field(default=None, max_length=300)
    url: Optional[str] = Field(default=None, max_length=1000)
    citation: Optional[str] = Field(default=None, max_length=500)
    published_date: Optional[date] = None
    raw_text: Optional[str] = None
    facts: list[str] = Field(default_factory=list)
    auto_approve: bool = False
    chunk_sentences: int = Field(default=3, ge=1, le=10)
    chunk_overlap: int = Field(default=1, ge=0, le=5)


class UpdateFactRequest(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1)
    citation: Optional[str] = Field(default=None, max_length=500)
    published_date: Optional[date] = None


class UpdateFactStatusRequest(BaseModel):
    status: FactStatus


class BatchUpdateFactStatusRequest(BaseModel):
    fact_ids: list[UUID] = Field(..., min_length=1, max_length=200)
    status: FactStatus


def _get_store():
    from app.rag.store import FactStore

    return FactStore()


def _encode_texts(texts: list[str]) -> list[list[float]]:
    from app.rag.embedder import get_default_embedder

    return get_default_embedder().encode(texts)


def _handle_pg_error(exc: Exception) -> None:
    if type(exc).__module__.startswith("psycopg"):
        logger.error("Postgres RAG store unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Kho fact RAG chua san sang (kiem tra Postgres va RAG_DATABASE_URL).",
        ) from exc
    raise exc


@router.get("/stats")
def get_knowledge_base_stats() -> dict:
    try:
        with _get_store() as store:
            return store.get_stats()
    except HTTPException:
        raise
    except Exception as exc:
        _handle_pg_error(exc)


@router.get("/sources")
def list_knowledge_sources(
    topic: Optional[EvidenceTopic] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    try:
        offset = (page - 1) * page_size
        with _get_store() as store:
            items, total = store.list_sources(topic=topic, limit=page_size, offset=offset)
            return {"items": items, "total": total, "page": page, "page_size": page_size}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_pg_error(exc)


@router.post("/sources", status_code=201)
def create_knowledge_source(req: CreateKnowledgeSourceRequest) -> dict:
    if req.chunk_overlap >= req.chunk_sentences:
        raise HTTPException(status_code=400, detail="chunk_overlap phai nho hon chunk_sentences")

    segments = [s.strip() for s in req.facts if s and s.strip()]
    if req.raw_text and req.raw_text.strip():
        segments.extend(
            chunk_text(
                req.raw_text.strip(),
                sentences_per_chunk=req.chunk_sentences,
                overlap=req.chunk_overlap,
            )
        )

    if not segments:
        raise HTTPException(status_code=400, detail="Can cung cap raw_text hoac it nhat 1 fact.")

    citation = req.citation or (f"{req.title} ({req.url})" if req.title and req.url else req.title or req.url)
    status: FactStatus = "approved" if req.auto_approve else "pending"

    try:
        embeddings = _encode_texts(segments)
        cards = [
            FactCard(
                content=text,
                topic=req.topic,
                citation=citation,
                published_date=req.published_date,
                status=status,
                embedding=emb,
            )
            for text, emb in zip(segments, embeddings)
        ]
        with _get_store() as store:
            source_id = store.insert_source(
                topic=req.topic,
                source_type=req.source_type,
                title=req.title,
                url=req.url,
            )
            store.insert_facts(source_id, cards)
            store.commit()
        return {
            "source_id": str(source_id),
            "topic": req.topic,
            "status": status,
            "created_facts": len(cards),
        }
    except HTTPException:
        raise
    except Exception as exc:
        _handle_pg_error(exc)


@router.delete("/sources/{source_id}")
def delete_knowledge_source(source_id: UUID) -> dict:
    try:
        with _get_store() as store:
            deleted = store.delete_source(source_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Khong tim thay knowledge source.")
            store.commit()
        return {"deleted": True, "source_id": str(source_id)}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_pg_error(exc)


@router.get("/facts")
def list_facts(
    topic: Optional[EvidenceTopic] = Query(default=None),
    status: Optional[FactStatus] = Query(default=None),
    source_id: Optional[UUID] = Query(default=None),
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    try:
        offset = (page - 1) * page_size
        with _get_store() as store:
            items, total = store.list_facts(
                topic=topic,
                status=status,
                source_id=source_id,
                query=q,
                limit=page_size,
                offset=offset,
            )
            return {"items": items, "total": total, "page": page, "page_size": page_size}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_pg_error(exc)


@router.patch("/facts/{fact_id}")
def update_fact(fact_id: UUID, req: UpdateFactRequest) -> dict:
    try:
        embedding = _encode_texts([req.content])[0] if req.content is not None else None
        with _get_store() as store:
            updated = store.update_fact(
                fact_id,
                content=req.content,
                citation=req.citation,
                published_date=req.published_date,
                embedding=embedding,
            )
            if updated is None:
                raise HTTPException(status_code=404, detail="Khong tim thay fact card.")
            store.commit()
            return updated
    except HTTPException:
        raise
    except Exception as exc:
        _handle_pg_error(exc)


@router.patch("/facts/{fact_id}/status")
def update_fact_status(fact_id: UUID, req: UpdateFactStatusRequest) -> dict:
    try:
        with _get_store() as store:
            updated = store.update_fact_status(fact_id, req.status)
            if updated is None:
                raise HTTPException(status_code=404, detail="Khong tim thay fact card.")
            store.commit()
            return updated
    except HTTPException:
        raise
    except Exception as exc:
        _handle_pg_error(exc)


@router.post("/facts/batch-status")
def batch_update_fact_status(req: BatchUpdateFactStatusRequest) -> dict:
    try:
        with _get_store() as store:
            updated_count = store.batch_update_fact_status(req.fact_ids, req.status)
            store.commit()
            return {"updated_count": updated_count, "status": req.status}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_pg_error(exc)


@router.delete("/facts/{fact_id}")
def delete_fact(fact_id: UUID) -> dict:
    try:
        with _get_store() as store:
            deleted = store.delete_fact(fact_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Khong tim thay fact card.")
            store.commit()
            return {"deleted": True, "fact_id": str(fact_id)}
    except HTTPException:
        raise
    except Exception as exc:
        _handle_pg_error(exc)

