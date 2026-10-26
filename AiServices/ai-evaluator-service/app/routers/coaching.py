import logging

from fastapi import APIRouter, HTTPException

from app.schemas import ArgumentCoachingRequest, CoachingResult, RoundCoachingRequest
from app.services.coaching import EvaluationParseError, coach_argument, coach_round

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coaching", tags=["coaching"])


@router.post("/argument", response_model=CoachingResult)
def coach_argument_endpoint(req: ArgumentCoachingRequest) -> CoachingResult:
    """
    Goi y SAU KHI cham 1 luot lap luan: phuong phap cai thien cho cac tieu chi
    yeu + huong phat trien chinh y cua learner. Truyen lai bai goc (`request`)
    va ket qua /evaluate da co (`evaluation`) — khong cham lai.
    """
    try:
        return coach_argument(req)
    except EvaluationParseError as e:
        logger.error("Parse loi tu LLM (coaching argument): %s", e)
        raise HTTPException(status_code=502, detail="AI coach tra ve ket qua khong hop le, vui long thu lai.")
    except RuntimeError as e:
        logger.error("Loi khi goi LLM (coaching argument): %s", e)
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/round", response_model=CoachingResult)
def coach_round_endpoint(req: RoundCoachingRequest) -> CoachingResult:
    """
    Goi y SAU KHI cham ca 1 round: giong /coaching/argument nhung xet tren tat
    ca luot noi cua learner trong round. Truyen lai round goc (`request`) va ket
    qua /evaluate/round da co (`evaluation`) — khong cham lai.
    """
    try:
        return coach_round(req)
    except EvaluationParseError as e:
        logger.error("Parse loi tu LLM (coaching round): %s", e)
        raise HTTPException(status_code=502, detail="AI coach tra ve ket qua khong hop le, vui long thu lai.")
    except RuntimeError as e:
        logger.error("Loi khi goi LLM (coaching round): %s", e)
        raise HTTPException(status_code=502, detail=str(e))
