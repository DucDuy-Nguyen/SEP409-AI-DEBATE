"""
Bo do "bang chung mo ho" (thay VAGUE_EVIDENCE_PHRASES + BANNED_EVIDENCE_PATTERNS cu).

Ly do lam lai (docs/AI_DEVELOPMENT_LOG.md muc 2.4j): nhan tay 28 hit cua bo do cu tren batch v3/v4 cho precision
2/28 — gan het la bat nham: "%" trong vi du gia dinh (16/16 nham), "nghiên cứu" nghia thuong ("trung tâm nghiên
cứu", "dự án nghiên cứu"), "chứng minh" nghia thuong ("cơ hội chứng minh", "thí điểm có thể chứng minh").

Quy tac duoc THIET KE chi tren nhan batch v3 (experiments/case_plan/20260927-092737_case_plan_v3.jsonl); nhan batch
v4 (20260927-094713) dung de KIEM TRA (scripts/eval_vague_detector.py) — khong dieu chinh quy tac theo ket qua v4.

Hai muc:
- HIGH: loi vien dan bang chung mo ho that su (nguon khong ro + dong tu ket luan). Trong khang dinh cua AI ->
  validator REJECT (retry co phan hoi). Trong learner_claim -> ha xuong LOW (du doan loi learner la hop le).
- LOW: dang ngo nhung hay bat nham -> CHI LOG (opponent_llm_calls.vague_evidence).
Khong quet so va "%" trong example / definitions (vi du gia dinh duoc phep dung so).
"""
import re
import unicodedata
from dataclasses import dataclass

HIGH = "high"
LOW = "low"

# Truong la khang dinh cua AI (motion_interpretation: ten cu truoc migration 0007, van nhan de doc du lieu cu).
_AI_FIELD_RE = re.compile(
    r"^(motion_reading|motion_interpretation"
    r"|definitions\[\d+\]\.(term|meaning)"
    r"|arguments\[\d+\]\.(title|claim|reasoning|example|impact)"
    r"|anticipated_opponent_arguments\[\d+\]\.planned_response"
    r"|weighing)$"
)
_LEARNER_CLAIM_RE = re.compile(r"^anticipated_opponent_arguments\[\d+\]\.learner_claim$")
_NO_NUMBER_SCAN_RE = re.compile(r"^(arguments\[\d+\]\.example|definitions\[\d+\]\.(term|meaning))$")

# Khoang cach giua 2 tu (khong vuot qua dau ket cau . ! ? ;)
_GAP = r"[^\w.!?;]+"


def _within(n: int) -> str:
    """Toi da n tu chen giua (khong qua ranh gioi cau)."""
    return rf"(?:{_GAP}\w+){{0,{n}}}?{_GAP}"


@dataclass(frozen=True)
class Rule:
    id: str
    level: str
    label: str  # nhan ngan (cot "phrase" trong log / bang so sanh)
    reason: str  # giai thich cho phan hoi retry
    pattern: re.Pattern
    exclude_subject: re.Pattern | None = None  # chu the dung truoc (<= 6 tu) khien khong tinh


_SELF_SUBJECT = re.compile(r"(chúng tôi|chúng ta|phe|đội)(?:[^\w.!?;]+\w+){0,6}[^\w.!?;]*$")

RULES: tuple[Rule, ...] = (
    Rule(
        "nhieu_chu_the_da", HIGH, "nhiều/một số/các … đã (được) chứng minh / áp dụng thành công / cho thấy",
        "khẳng định điều đã xảy ra với chủ thể chung chung, không kiểm chứng được",
        re.compile(
            # danh tu tieng Viet 1-4 am tiet ("giải pháp thay thế" = 4)
            r"\b(?:nhiều|một số|các)(?:\s+\w+){1,4}?\s+đã\s+(?:được\s+)?"
            r"(?:chứng minh|áp dụng thành công|cho thấy)"
        ),
    ),
    Rule(
        # Giu tu validator cu: output THAT cua v3 "nhiều quốc gia đã áp dụng mô hình này mà vẫn..." (mau 2 chay lai,
        # muc 2.4d) — mau "nhieu_chu_the_da" chi bat "áp dụng thành công" nen se lot cau nay.
        "nhieu_noi_da_ap_dung", HIGH, "nhiều quốc gia/nước/nơi … đã áp dụng",
        "viện dẫn việc nơi khác đã áp dụng thay cho lập luận bằng cơ chế",
        re.compile(r"\b(?:nhiều|một số|các)\s+(?:quốc gia|nước|nơi)(?:\s+\w+){0,2}?\s+đã\s+(?:được\s+)?áp dụng"),
    ),
    Rule(
        "nghien_cuu_ket_luan", HIGH, "nghiên cứu … cho thấy / chỉ ra / khẳng định / phát hiện / chứng minh",
        "viện dẫn nghiên cứu không nêu nguồn",
        re.compile(r"nghiên cứu" + _within(5) + r"(?:cho thấy|chỉ ra|khẳng định|phát hiện|chứng minh)"),
    ),
    Rule(
        "da_chung_minh", HIGH, "đã (được) chứng minh",
        "khẳng định điều gì đó 'đã được chứng minh' mà không có cơ chế",
        re.compile(r"đã\s+(?:được\s+)?chứng minh"),
        exclude_subject=_SELF_SUBJECT,
    ),
    Rule(
        "chuyen_gia_nhan_dinh", HIGH, "chuyên gia … cho rằng / khuyến cáo / nhận định / đánh giá",
        "viện dẫn chuyên gia chung chung",
        re.compile(r"chuyên gia" + _within(3) + r"(?:cho rằng|khuyến cáo|nhận định|đánh giá)"),
    ),
    # --- LOW: chi log ---
    Rule("nghien_cuu", LOW, "nghiên cứu", "nhắc tới nghiên cứu", re.compile(r"nghiên cứu")),
    Rule("chuyen_gia", LOW, "chuyên gia", "nhắc tới chuyên gia", re.compile(r"chuyên gia")),
    Rule("thong_ke", LOW, "thống kê / theo báo cáo", "nhắc tới số liệu thống kê", re.compile(r"thống kê|theo báo cáo")),
    Rule("nhieu_quoc_gia", LOW, "nhiều quốc gia / nhiều nước", "nhắc tới nơi khác", re.compile(r"nhiều quốc gia|nhiều nước")),
    Rule("phan_tram", LOW, "%", "tỷ lệ phần trăm", re.compile(r"\d+(?:[.,]\d+)?\s?%")),
)


@dataclass(frozen=True)
class Hit:
    field: str
    rule: str
    level: str
    label: str
    match: str
    reason: str

    def to_log(self) -> dict:
        """Dang luu vao opponent_llm_calls.vague_evidence / JSONL. 'phrase' = nhan quy tac (de gom nhom)."""
        return {"phrase": self.label, "field": self.field, "level": self.level, "rule": self.rule, "match": self.match}


def field_scope(field: str) -> str:
    if _AI_FIELD_RE.match(field):
        return "ai"
    if _LEARNER_CLAIM_RE.match(field):
        return "learner_claim"
    return "other"


def _iter_text_fields(value: object, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_text_fields(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _iter_text_fields(v, f"{path}[{i}]")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _detect_field(field: str, raw: str, scope: str, scan_numbers: bool = True) -> list[Hit]:
    """1 doan text. Moi vung khop chi 1 hit: HIGH uu tien, LOW trong vung da co HIGH bi bo. scope != "ai" -> HIGH ha LOW."""
    hits: list[Hit] = []
    text = _norm(raw)
    taken: list[tuple[int, int]] = []
    for rule in RULES:  # HIGH truoc LOW
        if rule.id == "phan_tram" and not scan_numbers:
            continue
        for m in rule.pattern.finditer(text):
            start, end = m.span()
            if any(s <= start < e or s < end <= e or (start <= s and end >= e) for s, e in taken):
                continue
            if rule.exclude_subject is not None and rule.exclude_subject.search(text[:start]):
                continue
            level = rule.level if (rule.level == LOW or scope == "ai") else LOW
            taken.append((start, end))
            hits.append(Hit(field, rule.id, level, rule.label, raw[start:end] if len(raw) == len(text) else m.group(0), rule.reason))
    return hits


def detect(case_json: dict) -> list[Hit]:
    """
    Quet MOI truong text cua case file (dict). Moi doan text chi ghi 1 hit cho moi vung khop: quy tac HIGH duoc
    uu tien, hit LOW nam trong vung da co hit HIGH bi bo. Hit HIGH trong learner_claim / truong khac -> ha xuong LOW.
    """
    hits: list[Hit] = []
    for field, raw in _iter_text_fields(case_json):
        if field.endswith(".id") or field == "id":
            continue
        hits += _detect_field(field, raw, field_scope(field), scan_numbers=not _NO_NUMBER_SCAN_RE.match(field))
    return hits


def detect_speech(text: str, field: str = "speech_text") -> list[Hit]:
    """Bai noi cua AI trong tran (Giai doan 3b): la khang dinh cua AI -> HIGH giu nguyen muc (validator reject)."""
    return _detect_field(field, text, "ai")


def high_confidence(case_json: dict) -> list[Hit]:
    """Hit HIGH trong khang dinh cua AI — validator reject."""
    return [h for h in detect(case_json) if h.level == HIGH]
