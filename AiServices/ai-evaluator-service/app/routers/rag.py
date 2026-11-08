"""
Endpoint debug cua RAG Evidence. Chi dang ky khi RAG_ENABLED=true (app/main.py). Can DB va requirements-rag.txt.
Chua noi vao diem Evidence cua /evaluate* (buoc 3).
"""
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.rag.pipeline import check_evidence
from app.rag.schemas import EvidenceCheckResult
from app.services.json_utils import EvaluationParseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


class CheckEvidenceRequest(BaseModel):
    argument_text: str = Field(..., min_length=1)
    motion: str
    topic: Literal["education", "environment", "technology"]


@router.post("/check-evidence", response_model=EvidenceCheckResult)
def check_evidence_endpoint(req: CheckEvidenceRequest) -> EvidenceCheckResult:
    try:
        return check_evidence(req.argument_text, req.motion, req.topic)
    except EvaluationParseError as e:
        logger.error("Parse loi tu LLM (rag): %s", e)
        raise HTTPException(status_code=502, detail="AI evaluator tra ve ket qua khong hop le, vui long thu lai.")
    except RuntimeError as e:
        logger.error("Loi khi goi LLM (rag): %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        # Loi ket noi kho fact: psycopg chi nap khi dung toi, nen nhan dien theo module thay vi import o day
        if type(e).__module__.startswith("psycopg"):
            logger.error("Khong truy cap duoc kho fact (rag): %s", e)
            raise HTTPException(status_code=503, detail="Kho fact RAG chua san sang (kiem tra Postgres va RAG_DATABASE_URL).")
        raise
