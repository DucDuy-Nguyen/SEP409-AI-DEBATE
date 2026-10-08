import logging

from fastapi import APIRouter, HTTPException

from app.schemas import (
    ArgumentEvaluationRequest,
    ArgumentEvaluationResult,
    RoundEvaluationRequest,
    RoundEvaluationResult,
    SessionEvaluationRequest,
    SessionEvaluationResult,
)
from app.services.evaluator import EvaluationParseError, evaluate_argument
from app.services.round_evaluator import evaluate_round
from app.services.session_evaluator import evaluate_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evaluate", tags=["evaluate"])


@router.post("", response_model=ArgumentEvaluationResult)
def evaluate(req: ArgumentEvaluationRequest) -> ArgumentEvaluationResult:
    """
    Cham diem 1 luot lap luan tranh bien theo rubric 5 tieu chi (cap do Argument).
    """
    try:
        return evaluate_argument(req)
    except EvaluationParseError as e:
        logger.error("Parse loi tu LLM (argument): %s", e)
        raise HTTPException(status_code=502, detail="AI evaluator tra ve ket qua khong hop le, vui long thu lai.")
    except RuntimeError as e:
        logger.error("Loi khi goi LLM (argument): %s", e)
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/round", response_model=RoundEvaluationResult)
def evaluate_round_endpoint(req: RoundEvaluationRequest) -> RoundEvaluationResult:
    """
    Cham diem toan bo 1 round (giai doan), gom nhieu luot noi qua lai giua
    learner va doi phuong (AI hoac nguoi thuc — dung chung cho Practice va
    Competition).
    """
    try:
        return evaluate_round(req)
    except EvaluationParseError as e:
        logger.error("Parse loi tu LLM (round): %s", e)
        raise HTTPException(status_code=502, detail="AI evaluator tra ve ket qua khong hop le, vui long thu lai.")
    except RuntimeError as e:
        logger.error("Loi khi goi LLM (round): %s", e)
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/session", response_model=SessionEvaluationResult)
def evaluate_session_endpoint(req: SessionEvaluationRequest) -> SessionEvaluationResult:
    """
    Tong hop bao cao cuoi cho ca phien tranh bien, tu cac RoundEvaluationResult
    da cham san. Diem tong tinh toan hoc (minh bach, kiem chung duoc); LLM chi
    tong hop phan nhan xet dinh tinh (progress_trend, strengths/weaknesses chung).
    """
    try:
        return evaluate_session(req)
    except EvaluationParseError as e:
        logger.error("Parse loi tu LLM (session): %s", e)
        raise HTTPException(status_code=502, detail="AI evaluator tra ve ket qua khong hop le, vui long thu lai.")
    except RuntimeError as e:
        logger.error("Loi khi goi LLM (session): %s", e)
        raise HTTPException(status_code=502, detail=str(e))
