"""
Service Coaching (Argument-level va Round-level): goi y SAU KHI da cham —
phuong phap cai thien cho cac tieu chi yeu + huong phat trien chinh y cua learner.

Nhan lai ket qua /evaluate hoac /evaluate/round da co (khong cham lai) -> 1 lan
goi LLM. Viec CHON tieu chi nao can goi y va CON SO current_score deu do code
quyet dinh, LLM chi viet phan giai thich — cung nguyen tac voi overall_score/
round_score (xem docs/AI_DEVELOPMENT_LOG.md muc 3.8).
"""
import logging

from app.config import Settings, get_settings
from app.prompts.coaching_prompt import build_coaching_prompt, build_round_coaching_prompt
from app.prompts.evaluator_prompt import RUBRIC
from app.schemas import (
    ArgumentCoachingRequest,
    CoachingResult,
    CriterionCoaching,
    CriterionScore,
    IdeaDevelopment,
    RoundCoachingRequest,
)
from app.services.json_utils import EvaluationParseError, call_llm_with_retry
from app.services.llm_client import LLMClient, get_llm_client

logger = logging.getLogger(__name__)

__all__ = ["EvaluationParseError", "coach_argument", "coach_round"]

WEAK_SCORE_THRESHOLD = 3
MAX_FOCUS_CRITERIA = 3


def _select_focus_criteria(criteria: list[CriterionScore]) -> list[CriterionScore]:
    """
    Tieu chi co score <= 3, sap tang dan theo diem (hoa diem thi theo thu tu
    RUBRIC), toi da 3. Neu bai da tot (moi tieu chi >= 4) thi van lay 1 tieu chi
    thap nhat de learner co huong nang cao. CHI xet cac tieu chi co trong so > 0 trong RUBRIC
    (tu 2026-10 Persuasiveness chi la nhan dinh tong the, khong tinh diem, nen khong lam focus —
    loi khuyen cho no se lap lai Evidence/Logic).
    """
    rubric_order = {c["name"]: i for i, c in enumerate(RUBRIC)}
    counted = {c["name"] for c in RUBRIC if c["weight"] > 0}
    criteria = [c for c in criteria if c.name in counted]
    ranked = sorted(criteria, key=lambda c: (c.score, rubric_order.get(c.name, len(RUBRIC))))
    weak = [c for c in ranked if c.score <= WEAK_SCORE_THRESHOLD]
    return weak[:MAX_FOCUS_CRITERIA] if weak else ranked[:1]


def _build_coaching_result(parsed: dict, raw_text: str, focus: list[CriterionScore]) -> CoachingResult:
    focus_scores = {c.name: c.score for c in focus}
    returned = parsed.get("focus_criteria", [])
    returned_names = [item.get("name") if isinstance(item, dict) else None for item in returned]

    if returned_names != [c.name for c in focus]:
        raise EvaluationParseError(
            f"LLM tra ve tieu chi {returned_names}, ky vong dung {[c.name for c in focus]}"
        )

    # current_score LUON lay tu ket qua cham da co, bo qua moi con so LLM tu dua ra.
    focus_criteria = [
        CriterionCoaching(**{**item, "current_score": focus_scores[item["name"]]}) for item in returned
    ]

    idea = IdeaDevelopment(**(parsed.get("idea_development") or {}))
    if not idea.core_claim.strip() or not idea.directions:
        raise EvaluationParseError("LLM khong tra ve du 'idea_development' (core_claim + directions)")

    return CoachingResult(
        focus_criteria=focus_criteria,
        idea_development=idea,
        raw_model_output=raw_text,
    )


def _run_coaching(system_prompt: str, user_prompt: str, focus: list[CriterionScore], client: LLMClient) -> CoachingResult:
    return call_llm_with_retry(
        generate_fn=lambda up: client.generate(system_prompt, up),
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        build_result_fn=lambda parsed, raw: _build_coaching_result(parsed, raw, focus),
    )


def coach_argument(
    req: ArgumentCoachingRequest,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> CoachingResult:
    settings = settings or get_settings()
    client = llm_client or get_llm_client(settings)

    focus = _select_focus_criteria(req.evaluation.criteria)
    system_prompt, user_prompt = build_coaching_prompt(req, [c.name for c in focus])
    return _run_coaching(system_prompt, user_prompt, focus, client)


def coach_round(
    req: RoundCoachingRequest,
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
) -> CoachingResult:
    settings = settings or get_settings()
    client = llm_client or get_llm_client(settings)

    focus = _select_focus_criteria(req.evaluation.criteria)
    system_prompt, user_prompt = build_round_coaching_prompt(req, [c.name for c in focus])
    return _run_coaching(system_prompt, user_prompt, focus, client)
