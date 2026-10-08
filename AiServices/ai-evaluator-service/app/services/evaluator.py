"""
Service cham diem 1 luot lap luan (Argument-level): nhan 1 lap luan -> goi LLM
cham diem -> parse + validate -> tra ve ket qua.

Day la cap do THAP NHAT trong 3 cap do cham diem cua ADPP:
  Argument (file nay) -> Round (round_evaluator.py) -> Session (session_evaluator.py)
"""
import logging

from app.config import Settings, get_settings
from app.prompts.evaluator_prompt import RUBRIC, build_evaluation_prompt
from app.schemas import ArgumentEvaluationRequest, ArgumentEvaluationResult, CriterionScore
from app.services.json_utils import EvaluationParseError, call_llm_with_retry
from app.services.llm_client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)

__all__ = ["EvaluationParseError", "evaluate_argument"]


def _build_result(parsed: dict, raw_text: str) -> ArgumentEvaluationResult:
    criteria = [CriterionScore(**c) for c in parsed.get("criteria", [])]

    if len(criteria) != len(RUBRIC):
        raise EvaluationParseError(
            f"LLM tra ve {len(criteria)} tieu chi, ky vong {len(RUBRIC)} tieu chi theo rubric"
        )

    # overall_score LUON duoc TINH BANG CONG THUC tu 5 diem tieu chi con —
    # KHONG bao gio doc tu JSON LLM tra ve, ke ca neu LLM co lo tra them field
    # "overall_score" (gia tri do bi BO QUA hoan toan). Dam bao tinh tat dinh
    # (deterministic): cung 5 diem tieu chi luon cho ra cung 1 overall_score.
    # Xem ly do dao nguoc tu holistic ve cong thuc trong
    # app/prompts/evaluator_prompt.py va docs/AI_DEVELOPMENT_LOG.md.
    overall_score = round(sum(c.score for c in criteria) / (len(criteria) * 5) * 10, 2)

    overall_reasoning = parsed.get("overall_reasoning")
    if not overall_reasoning:
        # overall_reasoning gio la nhan xet TONG HOP ve 5 tieu chi (khong con
        # giai thich cho 1 overall_score AI tu cham) — nhung van la truong BAT
        # BUOC de giu nguyen tac Chain-of-Thought. Thieu/rong bi coi la loi
        # dinh dang, de call_llm_with_retry tu dong retry.
        raise EvaluationParseError(
            "LLM khong tra ve 'overall_reasoning' — day la field bat buoc (nhan xet "
            "tong hop ve chat luong lap luan, khong duoc de trong)"
        )

    return ArgumentEvaluationResult(
        overall_score=overall_score,
        overall_reasoning=overall_reasoning,
        criteria=criteria,
        strengths=parsed.get("strengths", []),
        weaknesses=parsed.get("weaknesses", []),
        suggestions=parsed.get("suggestions", []),
        raw_model_output=raw_text,
    )


def evaluate_argument(
    req: ArgumentEvaluationRequest,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> ArgumentEvaluationResult:
    settings = settings or get_settings()
    client = llm_client or get_llm_client(settings)

    system_prompt, user_prompt = build_evaluation_prompt(req)

    return call_llm_with_retry(
        generate_fn=lambda up: client.generate(system_prompt, up),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        build_result_fn=_build_result,
    )
