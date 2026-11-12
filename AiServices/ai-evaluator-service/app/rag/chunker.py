"""
Tach van ban thanh cac doan ngan de embed. Ham thuan, khong phu thuoc DB hay model.

Dau cau chi tinh la het cau khi theo sau la khoang trang hoac het chuoi, nen so thap phan
kieu 3.5 va 1.000.000 khong bi tach (3,5 khong co dau cham nen cung khong bi tach).
"""
import re

# Viet tat hay gap trong bao tieng Viet, so sanh o dang chu thuong, khong gom dau cham cuoi.
ABBREVIATIONS = frozenset(
    {
        "tp", "tt", "ts", "ths", "pgs", "gs", "bs", "ks", "cn", "nxb", "ubnd", "hđnd", "tr", "q", "p",
        "v.v", "vv", "vd", "dr", "mr", "mrs", "ms", "prof", "st", "no", "vs", "etc", "e.g", "i.e",
    }
)

# Cum dau ket cau, co the kem dau dong ngoac/nhay, va phai dung truoc khoang trang hoac het chuoi
_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s|$)")
_NEWLINES = re.compile(r"\s*\n\s*")


def _is_false_period(line: str, end_match: re.Match) -> bool:
    """Dau cham nay khong phai het cau: sau viet tat, chu cai dau ten, hoac cau con tiep chu thuong."""
    if not end_match.group().startswith(".") or end_match.group().rstrip("\"'”’)]") != ".":
        return False
    words_before = line[: end_match.start()].split()
    last_word = words_before[-1].lstrip("(\"'“‘[") if words_before else ""
    if last_word.lower() in ABBREVIATIONS:
        return True
    # Ten viet tat "Nguyen V. A": tu truoc cung viet hoa. "nhom A. Tiep" van la het cau.
    if len(last_word) == 1 and last_word.isupper() and len(words_before) >= 2 and words_before[-2][0].isupper():
        return True
    rest = line[end_match.end() :].lstrip()
    return bool(rest) and rest[0].islower()


def split_sentences(text: str) -> list[str]:
    """Tach theo . ! ? va xuong dong; bo qua dong trong."""
    sentences: list[str] = []
    for line in _NEWLINES.split(text.strip()):
        start = 0
        for match in _SENTENCE_END.finditer(line):
            if _is_false_period(line, match):
                continue
            sentence = line[start : match.end()].strip()
            if sentence:
                sentences.append(sentence)
            start = match.end()
        tail = line[start:].strip()
        if tail:
            sentences.append(tail)
    return sentences


def chunk_text(text: str, sentences_per_chunk: int = 3, overlap: int = 1) -> list[str]:
    """Gom cau thanh cac doan `sentences_per_chunk` cau, 2 doan lien tiep chung `overlap` cau."""
    if sentences_per_chunk < 1:
        raise ValueError("sentences_per_chunk phai >= 1")
    if not 0 <= overlap < sentences_per_chunk:
        raise ValueError("overlap phai >= 0 va nho hon sentences_per_chunk")

    sentences = split_sentences(text)
    chunks: list[str] = []
    step = sentences_per_chunk - overlap
    for start in range(0, len(sentences), step):
        chunks.append(" ".join(sentences[start : start + sentences_per_chunk]))
        # Da toi cau cuoi: doan tiep theo chi lap lai phan overlap
        if start + sentences_per_chunk >= len(sentences):
            break
    return chunks
