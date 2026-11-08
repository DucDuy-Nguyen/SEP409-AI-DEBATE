"""Sinh so bia cua scripts/rag/build_evidence_pairs.py: ham thuan, khong can DB."""
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "rag"))

from build_evidence_pairs import (  # noqa: E402
    fake_number,
    format_vn_number,
    make_fake,
    parse_vn_number,
    unlisted_numbers,
)


def _value(token: str) -> float:
    return parse_vn_number(token)[0]


def test_parse_and_format_vietnamese_numbers():
    assert parse_vn_number("29.383") == (29383.0, 0, 0)
    assert parse_vn_number("12.000") == (12000.0, 0, 3)
    assert parse_vn_number("5,2") == (5.2, 1, 0)
    assert format_vn_number(12812, 0) == "12.812"
    assert format_vn_number(2.5, 1) == "2,5"
    assert format_vn_number(700, 0) == "700"


@pytest.mark.parametrize("token", ["84", "14.695", "230.000", "1.000", "5,2", "1,6", "6", "2"])
def test_fake_number_changes_value_by_30_to_60_percent(token):
    rng = random.Random(0)
    for _ in range(30):
        ratio = abs(_value(fake_number(token, rng, is_year=False)) - _value(token)) / _value(token)
        assert 0.3 <= ratio <= 0.6 + 1e-9


def test_rounding_keeps_precision_of_the_original():
    rng = random.Random(1)
    assert all(fake_number("230.000", rng, False).endswith(".000") for _ in range(20))
    assert all("," in fake_number("1,6", rng, False) for _ in range(20))


def test_percent_never_exceeds_100():
    rng = random.Random(2)
    assert all(_value(fake_number("88", rng, False, is_percent=True)) <= 100 for _ in range(50))


def test_year_is_shifted_by_2_to_5():
    rng = random.Random(3)
    for _ in range(20):
        assert 2 <= abs(int(fake_number("1879", rng, is_year=True)) - 1879) <= 5


def test_make_fake_replaces_only_listed_numbers_and_detects_years():
    argument = "Einstein sinh năm 1879, cách đây hơn 100 năm, và 10.000 tin nhắn."
    fake, changes = make_fake(argument, ["1879", "100"], random.Random(4))
    assert [c["old"] for c in changes] == ["1879", "100"]
    assert fake.replace(changes[0]["new"], "Y").replace(changes[1]["new"], "N") == (
        "Einstein sinh năm Y, cách đây hơn N năm, và 10.000 tin nhắn."
    )
    assert 2 <= abs(int(changes[0]["new"]) - 1879) <= 5


def test_make_fake_requires_each_number_exactly_once():
    with pytest.raises(ValueError):
        make_fake("30 người và 30 người", ["30"], random.Random(0))
    with pytest.raises(ValueError):
        make_fake("không có số", ["30"], random.Random(0))


def test_unlisted_numbers_reports_numbers_not_marked():
    assert unlisted_numbers("COP27 có 90 nguyên thủ năm 2022", ["90"], ["27"]) == ["2022"]


def test_constraint_evaluation_on_vietnamese_numbers():
    from build_evidence_pairs import evaluate_constraint

    assert evaluate_constraint("{16} >= {10}", {"16": "16", "10": "10"})
    assert not evaluate_constraint("{16} >= {10}", {"16": "9", "10": "14"})
    assert evaluate_constraint("20000 <= {110} * 1000000 / {5.000} <= 26000", {"110": "110", "5.000": "5.000"})
    with pytest.raises(ValueError):
        evaluate_constraint("{16} >= {99}", {"16": "16"})
    with pytest.raises(ValueError):
        evaluate_constraint("__import__('os') or {16}", {"16": "16"})


def test_violations_flag_future_years_and_reordered_years():
    from build_evidence_pairs import violations

    year = lambda old, new: {"old": old, "new": new, "kind": "year"}
    assert violations([year("2021", "2026")], []) == ["nam 2026 > 2025"]
    assert violations([year("2017", "2020"), year("2018", "2015")], []) == ["thu tu nam 2017/2018 thanh 2020/2015"]
    assert violations([year("2011", "2006"), year("2021", "2025")], []) == []


def test_generate_fake_retries_seeds_until_constraints_hold_and_is_deterministic():
    from build_evidence_pairs import generate_fake, violations

    argument = "Có 16 diễn giả từ 10 quốc gia."
    first = generate_fake("p", argument, ["16", "10"], ["{16} >= {10}"])
    assert first == generate_fake("p", argument, ["16", "10"], ["{16} >= {10}"])
    fake, changes, attempt = first
    assert not violations(changes, ["{16} >= {10}"])
    with pytest.raises(ValueError):
        generate_fake("p", argument, ["16", "10"], ["{16} < {10}"])  # Sai ngay tren ban dung


def test_power_operator_is_rejected():
    from build_evidence_pairs import evaluate_constraint

    with pytest.raises(ValueError):
        evaluate_constraint("{9} ** {9} > 1", {"9": "9"})
