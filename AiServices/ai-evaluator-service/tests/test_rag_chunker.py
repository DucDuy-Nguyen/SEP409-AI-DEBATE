"""Test chunker: ham thuan, khong can DB va khong load model."""
import pytest

from app.rag.chunker import chunk_text, split_sentences


def test_splits_on_terminators_and_newlines():
    assert split_sentences("Mot. Hai! Ba?\nBon") == ["Mot.", "Hai!", "Ba?", "Bon"]


def test_ignores_blank_input_and_blank_lines():
    assert split_sentences("  \n \n ") == []
    assert split_sentences("Mot.\n\n\nHai.") == ["Mot.", "Hai."]


@pytest.mark.parametrize(
    "text",
    [
        "Tang truong dat 3,5 phan tram trong nam nay.",
        "Tang truong dat 3.5 phan tram trong nam nay.",
        "Dan so khoang 1.000.000 nguoi vao nam ngoai.",
    ],
)
def test_numbers_do_not_split_a_sentence(text):
    assert split_sentences(text) == [text]


@pytest.mark.parametrize(
    "text",
    [
        "Hoi nghi o TP. Hồ Chí Minh da ket thuc.",
        "Theo PGS. Nguyễn Văn A thi dieu nay dung.",
        "Ong Nguyen V. A phat bieu tai hoi nghi.",
        "Gom sach, vo, but, v.v. Tat ca deu mien phi.",
    ],
)
def test_abbreviations_do_not_split_a_sentence(text):
    assert split_sentences(text) == [text]


def test_capital_letter_after_lowercase_word_ends_a_sentence():
    assert split_sentences("Giai thuoc thuoc ve nhom A. Tiep theo la nhom B.") == [
        "Giai thuoc thuoc ve nhom A.",
        "Tiep theo la nhom B.",
    ]


def test_period_before_lowercase_does_not_split():
    assert split_sentences("Hang ABC Corp. da cong bo bao cao.") == ["Hang ABC Corp. da cong bo bao cao."]


def test_closing_quote_stays_with_its_sentence():
    assert split_sentences('Ong noi "dung vay." Sau do ra ve.') == ['Ong noi "dung vay."', "Sau do ra ve."]


def test_chunks_overlap_by_one_sentence():
    text = "A1 mot. B2 hai. C3 ba. D4 bon. E5 nam."
    assert chunk_text(text, sentences_per_chunk=3, overlap=1) == [
        "A1 mot. B2 hai. C3 ba.",
        "C3 ba. D4 bon. E5 nam.",
    ]


def test_no_chunk_is_only_the_overlap():
    # 4 cau: doan 2 phu het cau cuoi, khong sinh them doan chi co cau lap
    assert chunk_text("A1 mot. B2 hai. C3 ba. D4 bon.", sentences_per_chunk=3, overlap=1) == [
        "A1 mot. B2 hai. C3 ba.",
        "C3 ba. D4 bon.",
    ]


def test_short_text_is_one_chunk_and_empty_text_is_none():
    assert chunk_text("Chi mot cau.") == ["Chi mot cau."]
    assert chunk_text("   ") == []


@pytest.mark.parametrize("size,overlap", [(0, 0), (3, 3), (3, -1)])
def test_invalid_window_is_rejected(size, overlap):
    with pytest.raises(ValueError):
        chunk_text("Mot cau.", sentences_per_chunk=size, overlap=overlap)
