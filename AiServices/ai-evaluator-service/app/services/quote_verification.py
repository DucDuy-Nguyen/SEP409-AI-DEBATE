"""
Xac minh trich dan cua nhan xet tieu cuc (docs/AI_DEVELOPMENT_LOG.md muc 3.16, fix C).

Viet luat "phai trich nguyen van" trong prompt la KHONG DU: do thu, model van dua nhan xet khong trich dan. Vi vay
code kiem tra: moi diem yeu phai kem `quote` co that trong transcript cua round, khong thi loai diem yeu do.

GIOI HAN: quote co that chi chung minh cau do da duoc noi, KHONG chung minh nhan xet dung. Bat duoc nhan xet bia ra
tu noi dung khong ton tai, khong bat duoc nhan xet dien giai sai mot cau co that.
"""
import logging
import re
import unicodedata
from difflib import SequenceMatcher

from app.schemas import ArgumentTurn, WeaknessEvidence
from app.services.json_utils import EvaluationParseError

logger = logging.getLogger(__name__)

# Quote qua ngan gan nhu cau nao cung khop, khong chung minh duoc gi. Tach theo khoang trang nen tieng Viet dem theo
# am tiet: "co che yeu" da la 3, 5 am tiet moi bat dau la mot menh de.
MIN_QUOTE_WORDS = 5
# Khop gan dung chi de chiu loi chep nho (1 tu ngan), khong de lot cau da dien giai lai: 3 ky tu la de bo "khong "
# (6 ky tu, dao nghia cau) khong lot. Quote dai chi khop chinh xac, vua tranh lot cau khac nghia vua tranh cham.
FUZZY_MIN_RATIO = 0.9
FUZZY_MAX_CHAR_EDITS = 3
FUZZY_MAX_QUOTE_CHARS = 300

_QUOTE_CHARS_RE = re.compile(r"[\"'“”‘’«»`]")
_DASH_CHARS_RE = re.compile(r"[‐‑‒–—―]")
_ELLIPSIS_RE = re.compile(r"\.{3,}|…")
_EDGE_PUNCTUATION = " .,;:!?()[]-"


def normalize_for_match(text: str) -> str:
    """NFC + bo qua hoa/thuong, dau ngoac kep, kieu gach noi, khoang trang. GIU dau tieng Viet: 'chua' khac 'chưa'."""
    text = unicodedata.normalize("NFC", text).casefold()
    text = _QUOTE_CHARS_RE.sub("", text)
    text = _DASH_CHARS_RE.sub("-", text)
    return " ".join(text.split()).strip(_EDGE_PUNCTUATION)


def _is_close_match(fragment: str, transcript_words: list[str]) -> bool:
    if len(fragment) > FUZZY_MAX_QUOTE_CHARS:
        return False
    size = len(fragment.split())
    for window_size in (size, size - 1, size + 1):
        if window_size < 1:
            continue
        for start in range(len(transcript_words) - window_size + 1):
            window = " ".join(transcript_words[start : start + window_size]).strip(_EDGE_PUNCTUATION)
            matcher = SequenceMatcher(None, fragment, window, autojunk=False)
            if matcher.quick_ratio() < FUZZY_MIN_RATIO or matcher.ratio() < FUZZY_MIN_RATIO:
                continue
            matched = sum(block.size for block in matcher.get_matching_blocks())
            if max(len(fragment), len(window)) - matched <= FUZZY_MAX_CHAR_EDITS:
                return True
    return False


def quote_in_transcript(quote: str, transcript: str) -> bool:
    """Quote co "..." (luoc giua cau) thi moi doan phai khop; tong cong phai du MIN_QUOTE_WORDS tu."""
    fragments = [normalize_for_match(part) for part in _ELLIPSIS_RE.split(quote)]
    fragments = [fragment for fragment in fragments if fragment]
    if sum(len(fragment.split()) for fragment in fragments) < MIN_QUOTE_WORDS:
        return False

    normalized_transcript = normalize_for_match(transcript)
    words = normalized_transcript.split()
    return all(fragment in normalized_transcript or _is_close_match(fragment, words) for fragment in fragments)


def verify_weaknesses(raw_weaknesses: object, turns: list[ArgumentTurn]) -> tuple[list[WeaknessEvidence], int]:
    """Tra ve (cac diem yeu da xac minh, so diem yeu bi loai). Loai: khong co text, khong co quote, quote khong co that."""
    if not isinstance(raw_weaknesses, list):
        raise EvaluationParseError("'weaknesses' phai la danh sach")

    kept: list[WeaknessEvidence] = []
    for item in raw_weaknesses:
        if not isinstance(item, dict):
            continue
        text, quote = item.get("text"), item.get("quote")
        if not isinstance(text, str) or not isinstance(quote, str) or not text.strip():
            continue
        # Doi chieu tung luot: quote phai nam gon trong loi cua 1 nguoi, khong noi cuoi luot nay voi dau luot sau.
        if any(quote_in_transcript(quote, turn.text) for turn in turns):
            kept.append(WeaknessEvidence(text=text.strip(), quote=quote.strip()))

    return kept, len(raw_weaknesses) - len(kept)
