"""
Service cham diem toan bo 1 Round (giai doan tranh bien), cap do giua Argument
va Session trong 3 cap do cham diem cua ADPP.

round_score (2026-09): LUON tinh bang cong thuc tu 5 tieu chi con, KHONG doc
gia tri "round_score" (neu co) tu JSON LLM tra ve — ap dung dung nguyen tac
da chot cho overall_score o Argument-level (app/services/evaluator.py). Ly
do: AI tung tra round_score=14.0 (vuot thang 0-10) gay ValidationError phai
retry — cung ban chat voi hien tuong da phat hien o Argument-level (AI "tu
cam nhan" diem tong doc lap, khong nhat quan voi 5 tieu chi con). Xem day du
ly do va bang chung trong docs/AI_DEVELOPMENT_LOG.md muc 3.8.
"""
import logging

from app.config import Settings, get_settings
from app.prompts.evaluator_prompt import RUBRIC
from app.prompts.round_prompt import build_round_evaluation_prompt
from app.schemas import CriterionScore, RoundEvaluationRequest, RoundEvaluationResult
from app.services.json_utils import EvaluationParseError, call_llm_with_retry
from app.services.llm_client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)

__all__ = ["EvaluationParseError", "evaluate_round"]


def _build_round_result(parsed: dict, raw_text: str, stage) -> RoundEvaluationResult:
    criteria = [CriterionScore(**c) for c in parsed.get("criteria", [])]

    if len(criteria) != len(RUBRIC):
        raise EvaluationParseError(
            f"LLM tra ve {len(criteria)} tieu chi, ky vong {len(RUBRIC)} tieu chi theo rubric"
        )

    # round_score LUON duoc TINH BANG CONG THUC tu 5 diem tieu chi con — KHONG
    # bao gio doc tu JSON LLM tra ve, ke ca neu LLM co lo tra them field
    # "round_score" (gia tri do bi BO QUA hoan toan). Dam bao tinh tat dinh
    # (deterministic) va tranh loi thuc te da gap (AI tra ve 14.0, vuot thang
    # 0-10). Xem app/prompts/round_prompt.py va docs/AI_DEVELOPMENT_LOG.md muc 3.8.
    round_score = round(sum(c.score for c in criteria) / (len(criteria) * 5) * 10, 2)

    consistency_note = parsed.get("consistency_note")
    if not consistency_note:
        raise EvaluationParseError("LLM khong tra ve 'consistency_note' — day la field bat buoc cho Round")

    return RoundEvaluationResult(
        stage=stage,
        round_score=round_score,
        criteria=criteria,
        consistency_note=consistency_note,
        strengths=parsed.get("strengths", []),
        weaknesses=parsed.get("weaknesses", []),
        suggestions=parsed.get("suggestions", []),
        raw_model_output=raw_text,
    )


def evaluate_round(
    req: RoundEvaluationRequest,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> RoundEvaluationResult:
    settings = settings or get_settings()
    client = llm_client or get_llm_client(settings)

    system_prompt, user_prompt = build_round_evaluation_prompt(req)

    return call_llm_with_retry(
        generate_fn=lambda up: client.generate(system_prompt, up),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        build_result_fn=lambda parsed, raw: _build_round_result(parsed, raw, req.stage),
    )
