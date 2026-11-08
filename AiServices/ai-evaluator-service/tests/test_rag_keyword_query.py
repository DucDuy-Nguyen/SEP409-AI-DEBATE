"""Test ghep chuoi to_tsquery: ham thuan, khong can DB."""
import unicodedata

from app.rag.keyword_query import VIETNAMESE_STOPWORDS, build_or_tsquery


def test_joins_tokens_with_or_and_drops_stopwords():
    assert build_or_tsquery("Ô nhiễm của rừng và biển") == "'ô' | 'nhiễm' | 'rừng' | 'biển'"


def test_keeps_numbers_as_tokens():
    assert build_or_tsquery("tăng 20% trong năm 2023") == "'tăng' | '20%' | '2023'"
    assert build_or_tsquery("đạt 3,5 và 1.000.000") == "'đạt' | '3,5' | '1.000.000'"


def test_keeps_hyphenated_token_whole():
    assert build_or_tsquery("COVID-19 lây lan") == "'covid-19' | 'lây' | 'lan'"


def test_keeps_ai_as_a_token():
    assert build_or_tsquery("AI thay đổi") == "'ai' | 'thay' | 'đổi'"


def test_only_stopwords_or_punctuation_gives_none():
    assert build_or_tsquery("của và là") is None
    assert build_or_tsquery(" ... !? ") is None
    assert build_or_tsquery("") is None


def test_tsquery_operators_in_input_do_not_reach_the_query():
    query = build_or_tsquery("rừng & biển | (núi) ! a:* <-> sông'; DROP")
    assert query == "'rừng' | 'biển' | 'núi' | 'a' | 'sông' | 'drop'"


def test_lowercases_and_removes_duplicates():
    assert build_or_tsquery("Rừng RỪNG rừng") == "'rừng'"


def test_normalizes_to_nfc_so_stopwords_still_match():
    assert build_or_tsquery(unicodedata.normalize("NFD", "rừng của biển")) == "'rừng' | 'biển'"


def test_stopword_list_is_in_nfc_and_has_no_digits():
    assert 50 <= len(VIETNAMESE_STOPWORDS) <= 100
    assert all(word == unicodedata.normalize("NFC", word) for word in VIETNAMESE_STOPWORDS)
    assert not any(character.isdigit() for word in VIETNAMESE_STOPWORDS for character in word)
