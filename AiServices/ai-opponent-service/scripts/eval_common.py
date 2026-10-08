"""
Ham dung chung cho cac script danh gia (compare_case_plan_batches, label_stance, label_vague_evidence).
Chi DOC file JSONL cua batch — khong goi LLM, khong dung DB.
"""
import json
import re
import unicodedata
from pathlib import Path

Key = tuple[str, str, str]  # (motion, ai_side, difficulty)

# Nhom truong cho vague_evidence
AI_FIELDS = "ai_fields"  # khang dinh cua AI
LEARNER_CLAIM = "learner_claim"  # du doan loi learner — viện dẫn o day la hop le
UNKNOWN = "unknown"  # dang vague_evidence cu (list chuoi, khong co ten truong) hoac truong khac
FIELD_GROUPS = (AI_FIELDS, LEARNER_CLAIM, UNKNOWN)

_AI_FIELD_RE = re.compile(
    r"^(motion_reading|motion_interpretation"  # motion_interpretation: ten truoc migration 0007
    r"|definitions\[\d+\]\.(term|meaning)"
    r"|arguments\[\d+\]\.(title|claim|reasoning|example|impact)"
    r"|anticipated_opponent_arguments\[\d+\]\.planned_response"
    r"|weighing)$"
)
_LEARNER_CLAIM_RE = re.compile(r"^anticipated_opponent_arguments\[\d+\]\.learner_claim$")


def load_jsonl(path: Path) -> list[dict]:
    """Doc 1 file JSONL; moi record gan them `_source` (ten file) va `_source_path`."""
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            record["_source"] = Path(path).name
            record["_source_path"] = str(path)
            records.append(record)
    return records


def run_key(record: dict) -> Key:
    return (record["motion"], record["ai_side"], record["difficulty"])


def field_group(field: str | None) -> str:
    if field is None:
        return UNKNOWN
    if _AI_FIELD_RE.match(field):
        return AI_FIELDS
    if _LEARNER_CLAIM_RE.match(field):
        return LEARNER_CLAIM
    return UNKNOWN


def normalize_vague(entries: list | None) -> list[dict]:
    """
    vague_evidence -> [{"phrase", "field", "group"}]. Chap nhan ca dang moi ({"phrase","field"}) lan dang cu
    (list chuoi — khong biet truong -> nhom "unknown").
    """
    out = []
    for e in entries or []:
        if isinstance(e, dict):
            out.append({"phrase": e["phrase"], "field": e.get("field"), "group": field_group(e.get("field"))})
        else:
            out.append({"phrase": str(e), "field": None, "group": UNKNOWN})
    return out


def parse_case_json(raw_output: str | None) -> dict | None:
    """Case file (dict) tu raw_output cua 1 lan thu case_plan; None neu khong parse duoc."""
    if not raw_output:
        return None
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


_PATH_PART_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def resolve_field(data: dict, path: str) -> str | None:
    """Lay text theo duong dan kieu 'arguments[0].impact'; None neu khong co."""
    node: object = data
    for name, index in _PATH_PART_RE.findall(path):
        try:
            node = node[int(index)] if index else node[name]  # type: ignore[index]
        except (KeyError, IndexError, TypeError):
            return None
    return node if isinstance(node, str) else None


def iter_text_fields(value: object, path: str = ""):
    """(duong dan, text) cho moi chuoi trong JSON — cung quy uoc duong dan voi service._iter_fields."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from iter_text_fields(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from iter_text_fields(v, f"{path}[{i}]")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")


def sentence_with(text: str, phrase: str) -> str:
    """Cau (tach theo . ! ? ;) chua cum `phrase`; khong tim thay -> ca doan text."""
    target = _norm(phrase)
    for sentence in _SENTENCE_SPLIT_RE.split(text.strip()):
        if target in _norm(sentence):
            return sentence.strip()
    return text.strip()


def find_phrase_field(data: dict, phrase: str) -> tuple[str | None, str | None]:
    """(truong, text) dau tien chua `phrase` — dung cho vague_evidence dang cu khong co ten truong."""
    target = _norm(phrase)
    for path, text in iter_text_fields(data):
        if target in _norm(text):
            return path, text
    return None, None


def parse_source_spec(spec: str) -> tuple[str, str, str, str]:
    """'<file>:<motion_id>:<ai_side>:<difficulty>' -> 4 phan (file co the chua ':' nhu C:\\...)."""
    parts = spec.rsplit(":", 3)
    if len(parts) != 4 or not all(parts):
        raise ValueError(f"Dinh dang sai: '{spec}' (can <file>:<motion_id>:<ai_side>:<difficulty>)")
    return parts[0], parts[1], parts[2], parts[3]


def read_csv(path: Path) -> list[dict]:
    import csv

    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def append_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Ghi NOI vao CSV (tao header neu file moi) — goi sau MOI mau de dung giua chung khong mat du lieu."""
    import csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)
