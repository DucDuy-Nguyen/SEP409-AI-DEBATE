"""
Tinh diem tong (overall_score cua Argument, round_score cua Round) tu diem cac tieu chi,
THEO TRONG SO TRONG RUBRIC (app/prompts/evaluator_prompt.py).

Quyet dinh thiet ke (docs/AI_DEVELOPMENT_LOG.md muc 3.13-3.14, phuong an B): diem tong chi tinh tu
Logic, Evidence, Relevance, Structure (moi tieu chi 25%). Persuasiveness van duoc cham va tra ve
trong `criteria` nhu mot nhan dinh tong the, nhung co trong so 0 nen KHONG cong vao diem tong.

    diem tong = 2 x Sum(w_i x diem tieu chi i)    # thang 0-10, san 2.0
"""
from app.prompts.evaluator_prompt import RUBRIC
from app.schemas import SCORING_VERSION_CURRENT, SCORING_VERSION_LEGACY, CriterionScore
from app.services.json_utils import EvaluationParseError

__all__ = ["SCORING_VERSION_CURRENT", "SCORING_VERSION_LEGACY", "compute_weighted_score"]

MAX_CRITERION_SCORE = 5
SCALE_MAX = 10


def compute_weighted_score(criteria: list[CriterionScore]) -> float:
    """Tinh diem tong 0-10 theo trong so RUBRIC. Nem EvaluationParseError (de call_llm_with_retry
    tu thu lai) neu ten tieu chi LLM tra ve khong khop RUBRIC hoac bi trung."""
    by_name = {c.name: c.score for c in criteria}
    rubric_names = [r["name"] for r in RUBRIC]
    if len(by_name) != len(criteria) or set(by_name) != set(rubric_names):
        raise EvaluationParseError(
            f"Ten tieu chi LLM tra ve {[c.name for c in criteria]} khong khop rubric {rubric_names}"
        )
    weighted = sum(r["weight"] * by_name[r["name"]] for r in RUBRIC)
    return round(weighted / MAX_CRITERION_SCORE * SCALE_MAX, 2)
