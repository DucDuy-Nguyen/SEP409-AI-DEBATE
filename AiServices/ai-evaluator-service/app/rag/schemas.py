"""Model du lieu cua RAG: fact card luu trong kho va ket qua retrieval."""
from datetime import date
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class FactCard(BaseModel):
    """1 doan fact can luu vao bang fact_card."""

    content: str = Field(..., min_length=1)
    topic: str
    citation: Optional[str] = None
    published_date: Optional[date] = None
    status: str = "approved"
    embedding: Optional[list[float]] = None


class RetrievedFact(BaseModel):
    """
    1 fact tra ve tu retrieval. score tuy mode: cosine similarity (vector), ts_rank (keyword),
    diem RRF (hybrid). Rank tinh tu 1; None nghia la fact khong co mat o nhanh do.
    """

    fact_id: UUID
    content: str
    citation: Optional[str] = None
    score: float
    vector_rank: Optional[int] = None
    keyword_rank: Optional[int] = None


# ============================================================================
# Buoc 2: tach claim + verify bang LLM (docs/RAG_STEP2_SPEC.md)
# ============================================================================


class ClaimType(str, Enum):
    STATISTIC = "statistic"
    EVENT = "event"
    STUDY = "study"
    OTHER_FACTUAL = "other_factual"


class ExtractedClaim(BaseModel):
    """1 claim thuc chung tach tu luot lap luan, da viet lai thanh cau doc lap va chuan hoa so."""

    text: str = Field(..., min_length=1)
    claim_type: ClaimType


class VerdictLabel(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    # Kho fact khong du de ket luan; KHONG co nghia la claim sai
    NOT_FOUND = "NOT_FOUND"


class ClaimVerification(BaseModel):
    claim: str
    label: VerdictLabel
    fact_ids: list[str] = Field(default_factory=list)
    reason: str
    # True khi LLM tra SUPPORTED/CONTRADICTED nhung fact_ids rong hoac co id khong duoc dua vao prompt
    coerced: bool = False
    retrieved: list[RetrievedFact] = Field(default_factory=list)


class EvidenceCheckResult(BaseModel):
    claims: list[ClaimVerification] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    skipped_reason: Optional[str] = None
