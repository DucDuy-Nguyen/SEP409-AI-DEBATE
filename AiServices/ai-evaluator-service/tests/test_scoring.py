"""
Test cong thuc diem tong theo trong so (app/services/scoring.py): 4 tieu chi x 25%, Persuasiveness 0%.
KHONG goi API. Chay bang: pytest tests/
"""
import pytest

from app.prompts.evaluator_prompt import RUBRIC
from app.schemas import CriterionScore
from app.services.json_utils import EvaluationParseError
from app.services.scoring import compute_weighted_score

NAMES = ["Logic", "Evidence", "Relevance", "Structure", "Persuasiveness"]


def _criteria(scores: list[int], names: list[str] | None = None) -> list[CriterionScore]:
    return [CriterionScore(name=n, score=s, reasoning="x") for n, s in zip(names or NAMES, scores)]


def test_rubric_weights_sum_to_one_and_persuasiveness_is_zero():
    weights = {c["name"]: c["weight"] for c in RUBRIC}

    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert weights["Persuasiveness"] == 0.0
    assert all(weights[n] == 0.25 for n in NAMES[:4])


def test_bounds_floor_and_ceiling():
    assert compute_weighted_score(_criteria([1, 1, 1, 1, 1])) == 2.0
    assert compute_weighted_score(_criteria([5, 5, 5, 5, 5])) == 10.0


def test_each_counted_criterion_adds_half_a_point_per_score_step():
    base = compute_weighted_score(_criteria([2, 2, 2, 2, 2]))
    for i in range(4):
        scores = [2, 2, 2, 2, 2]
        scores[i] = 3
        assert compute_weighted_score(_criteria(scores)) == pytest.approx(base + 0.5)


def test_persuasiveness_never_changes_the_score():
    low = compute_weighted_score(_criteria([4, 3, 5, 4, 1]))
    high = compute_weighted_score(_criteria([4, 3, 5, 4, 5]))

    assert low == high == 8.0


def test_order_of_criteria_does_not_matter():
    shuffled = ["Structure", "Persuasiveness", "Logic", "Relevance", "Evidence"]
    scores_by_name = {"Logic": 4, "Evidence": 3, "Relevance": 5, "Structure": 4, "Persuasiveness": 2}

    assert compute_weighted_score(_criteria([scores_by_name[n] for n in shuffled], shuffled)) == 8.0


def test_unknown_missing_or_duplicate_names_raise_parse_error():
    with pytest.raises(EvaluationParseError):
        compute_weighted_score(_criteria([3, 3, 3, 3, 3], ["Logic", "Evidence", "Relevance", "Structure", "Persuasion"]))
    with pytest.raises(EvaluationParseError):
        compute_weighted_score(_criteria([3, 3, 3, 3, 3], ["Logic", "Logic", "Relevance", "Structure", "Persuasiveness"]))
    with pytest.raises(EvaluationParseError):
        compute_weighted_score(_criteria([3, 3, 3, 3], NAMES[:4]))
