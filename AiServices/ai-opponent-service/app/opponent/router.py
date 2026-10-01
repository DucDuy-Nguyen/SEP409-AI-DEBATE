import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.llm.client import LLMClient, get_llm_client
from app.opponent import service, turn_service
from app.opponent.schemas import (
    CaseFileResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    CreateTurnRequest,
    SessionResponse,
    TurnResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/opponent", tags=["opponent"])


def get_llm_client_factory(settings: Settings = Depends(get_settings)) -> Callable[[], LLMClient]:
    """
    Tra ve FACTORY thay vi client: request idempotent (session da READY) khong can LLM,
    nen khong duoc fail 503 chi vi thieu key. Tach thanh dependency de test override.
    """

    def factory() -> LLMClient:
        try:
            return get_llm_client(settings)
        except (RuntimeError, ValueError) as e:
            raise service.LLMNotConfiguredError(str(e)) from e

    return factory


def get_stance_reviewer_factory(settings: Settings = Depends(get_settings)) -> Callable[[], LLMClient | None]:
    """
    Client cho Stance Reviewer (provider/model rieng: STANCE_REVIEW_PROVIDER / STANCE_REVIEW_MODEL).
    Factory tra None neu STANCE_REVIEW_ENABLED=false. Cung ly do lazy nhu get_llm_client_factory.
    """

    def factory() -> LLMClient | None:
        if not settings.stance_review_enabled:
            return None
        try:
            return get_llm_client(
                settings, provider=settings.stance_review_provider, model=settings.stance_review_model
            )
        except (RuntimeError, ValueError) as e:
            raise service.LLMNotConfiguredError(f"Stance reviewer: {e}") from e

    return factory


def _not_found(external_session_id: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Khong tim thay session {external_session_id}")


@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": CreateSessionResponse, "description": "external_session_id da ton tai (idempotent)"}},
)
async def create_session(
    req: CreateSessionRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    llm_client_factory: Callable[[], LLMClient] = Depends(get_llm_client_factory),
    reviewer_factory: Callable[[], LLMClient | None] = Depends(get_stance_reviewer_factory),
    settings: Settings = Depends(get_settings),
) -> CreateSessionResponse:
    """
    Tao phien + chay Case Planning dong bo. Idempotent theo external_session_id:
    201 khi tao moi, 200 khi da ton tai voi DUNG du lieu cu (khong goi lai LLM neu da co case file),
    409 neu motion/learner_side/ai_side/difficulty khac phien cu.
    Khong tra case file ve (xem bang GET .../case-plan de debug).
    """
    try:
        session, created = await service.create_session_and_plan(
            db, req, llm_client_factory, settings, reviewer_factory
        )
    except service.InvalidSidesError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except service.LLMNotConfiguredError as e:
        logger.error("Khong khoi tao duoc LLM client: %s", e)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except service.SessionDataMismatchError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except service.CasePlanningInProgressError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session dang chuan bi case, vui long doi.")
    except service.CasePlanningBudgetExceededError as e:
        logger.error("Case plan vuot budget: %s", e)
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e))
    except service.CasePlanningError as e:
        logger.error("Case plan khong hop le: %s", e)
        raise HTTPException(status_code=502, detail="AI tra ve case file khong hop le, vui long thu lai.")
    except service.LLMCallError as e:
        logger.error("Loi khi goi LLM (case plan): %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    if not created:
        response.status_code = status.HTTP_200_OK
    return CreateSessionResponse(opponent_session_id=session.id, status=session.status)


@router.get("/sessions/{external_session_id}", response_model=SessionResponse)
async def get_session(external_session_id: str, db: AsyncSession = Depends(get_db)) -> SessionResponse:
    """Debug: xem session + case file."""
    try:
        session = await service.get_session_by_external_id(db, external_session_id)
    except service.SessionNotFoundError:
        raise _not_found(external_session_id)
    case_file = await service.get_case_file(db, session.id)
    # Khong dung model_validate(session): se cham relationship session.case_file (lazy-load, cam voi async).
    return SessionResponse(
        **{k: getattr(session, k) for k in SessionResponse.model_fields if k != "case_file"},
        case_file=CaseFileResponse.model_validate(case_file) if case_file else None,
    )


@router.get("/sessions/{external_session_id}/case-plan", response_model=CaseFileResponse)
async def get_case_plan(external_session_id: str, db: AsyncSession = Depends(get_db)) -> CaseFileResponse:
    """Debug: lay case file cua session."""
    try:
        session = await service.get_session_by_external_id(db, external_session_id)
    except service.SessionNotFoundError:
        raise _not_found(external_session_id)
    case_file = await service.get_case_file(db, session.id)
    if case_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session chua co case file")
    return CaseFileResponse.model_validate(case_file)


@router.post(
    "/sessions/{external_session_id}/turns",
    response_model=TurnResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": TurnResponse, "description": "Luot AI da duoc sinh truoc do (idempotent)"}},
)
async def create_turn(
    external_session_id: str,
    req: CreateTurnRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    llm_client_factory: Callable[[], LLMClient] = Depends(get_llm_client_factory),
    reviewer_factory: Callable[[], LLMClient | None] = Depends(get_stance_reviewer_factory),
    settings: Settings = Depends(get_settings),
) -> TurnResponse:
    """
    Sinh bai noi cua AI cho luot turn_index (format 6 luot: match_format.py). new_learner_speeches = moi bai noi
    cua learner ke tu luot AI truoc (co the rong). 201 khi sinh moi; 200 khi luot da co va bai learner khop snapshot
    (khong goi LLM). 400 sai format / sai nguoi noi; 409 session chua READY, thieu luot truoc, khac snapshot.
    502 ca khi het luot thu ma Stance Reviewer van bao lat phe (turn_full_v*: khong bao gio tra bai noi lat phe).
    """
    try:
        outcome, created = await turn_service.generate_turn(
            db, external_session_id, req, llm_client_factory, settings, reviewer_factory
        )
    except service.SessionNotFoundError:
        raise _not_found(external_session_id)
    except turn_service.TurnRequestError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except turn_service.TurnConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except service.LLMNotConfiguredError as e:
        logger.error("Khong khoi tao duoc LLM client: %s", e)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except turn_service.TurnBudgetExceededError as e:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(e))
    except turn_service.TurnGenerationError as e:
        raise HTTPException(status_code=502, detail=f"AI tra ve bai noi khong hop le: {e}")
    except service.LLMCallError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not created:
        response.status_code = status.HTTP_200_OK
    return TurnResponse(
        turn_index=outcome.turn_index, round_type=outcome.round_type, mode=outcome.mode, speech_text=outcome.speech_text
    )

