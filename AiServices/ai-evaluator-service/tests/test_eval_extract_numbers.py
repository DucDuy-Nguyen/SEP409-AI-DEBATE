"""Thuoc do so cua scripts/rag/eval_extract.py: doc so theo dinh dang tieng Viet, bat dau phay hang nghin kieu tieng Anh."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "rag"))

from eval_extract import english_thousands, vn_number_values  # noqa: E402


def test_vietnamese_format_values():
    assert vn_number_values("29.383 mét vuông, 8.000 học sinh, 8000 bạn, 3,5%, ngày 22/3") == {"29383", "8000", "3.5", "22/3"}


def test_english_thousands_comma_does_not_count_as_the_same_number():
    expected = vn_number_values("USAID đã bàn giao 29.383 mét vuông")
    assert expected & vn_number_values("USAID đã bàn giao 29,383 mét vuông") == set()
    assert expected & vn_number_values("USAID đã bàn giao 29.383 mét vuông") == {"29383"}


def test_english_thousands_are_reported():
    assert english_thousands("29,383 mét vuông và 12,000 tỷ, nhưng 3,5% và 1.000.000") == ["29,383", "12,000"]
    assert english_thousands("3,5% và 12.000 tỷ") == []
