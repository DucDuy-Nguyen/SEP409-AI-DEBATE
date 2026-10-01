"""
Service tong hop bao cao Session (ca phien tranh bien), cap do CAO NHAT trong
3 cap do cham diem cua ADPP: Argument -> Round -> Session (file nay).

overall_score va stage_breakdown duoc TINH TOAN HOC (trung binh round_score
da co san) — khong goi LLM cham lai, de dam bao minh bach + kiem chung duoc
(auditable) va khong ton chi phi API cho phan da co du lieu. LLM chi tong hop
phan nhan xet dinh tinh (progress_trend, overall_strengths/weaknesses/suggestions).
"""
import logging

from app.config import Settings, get_settings
from app.prompts.session_prompt import build_session_evaluation_prompt
from app.schemas import SessionEvaluationRequest, SessionEvaluationResult
from app.services.json_utils import EvaluationParseError, call_llm_with_retry
from app.services.llm_client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)

__all__ = ["EvaluationParseError", "evaluate_session"]


def _compute_stage_breakdown(req: SessionEvaluationRequest) -> dict[str, float]:
    """Neu co nhieu round cung stage (vi du 2 luot Rebuttal), lay trung binh cho stage do."""
    scores_by_stage: dict[str, list[float]] = {}
    for r in req.rounds:
        scores_by_stage.setdefault(r.stage.value, []).append(r.round_score)
    return {stage: round(sum(scores) / len(scores), 2) for stage, scores in scores_by_stage.items()}


def _compute_overall_score(req: SessionEvaluationRequest) -> float:
    scores = [r.round_score for r in req.rounds]
    return round(sum(scores) / len(scores), 2)


def _build_session_result(
    parsed: dict, raw_text: str, overall_score: float, stage_breakdown: dict[str, float]
) -> SessionEvaluationResult:
    progress_trend = parsed.get("progress_trend")
    if not progress_trend:
        raise EvaluationParseError("LLM khong tra ve 'progress_trend' — day la field bat buoc cho Session")

    return SessionEvaluationResult(
        overall_score=overall_score,
        stage_breakdown=stage_breakdown,
        progress_trend=progress_trend,
        overall_strengths=parsed.get("overall_strengths", []),
        overall_weaknesses=parsed.get("overall_weaknesses", []),
        overall_suggestions=parsed.get("overall_suggestions", []),
        raw_model_output=raw_text,
    )


def evaluate_session(
    req: SessionEvaluationRequest,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> SessionEvaluationResult:
    settings = settings or get_settings()
    client = llm_client or get_llm_client(settings)

    overall_score = _compute_overall_score(req)
    stage_breakdown = _compute_stage_breakdown(req)

    system_prompt, user_prompt = build_session_evaluation_prompt(req)

    return call_llm_with_retry(
        generate_fn=lambda up: client.generate(system_prompt, up),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        build_result_fn=lambda parsed, raw: _build_session_result(
            parsed, raw, overall_score, stage_breakdown
        ),
    )
