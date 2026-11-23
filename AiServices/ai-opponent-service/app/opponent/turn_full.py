"""
turn_full_v1 / turn_full_v2 — bo sinh bai noi DAY DU (Giai doan 3b, dev log muc 2.9, 2.10). Cung interface voi
turn_baseline_v1. v2 = v1 + 1 dong rang buoc "noi tu nhien, KHONG doc thuat ngu phan tich" (muc 2.10).

1 loi goi LLM, output JSON (structured output nhu Case Planning), thu tu truong BAT BUOC:
    learner_claims -> premises -> target_premise -> ai_points -> speech_text
= phan tich -> lap dan y -> MOI viet (bai hoc reviewer v3: dien dat lai truoc khi ket luan, muc 2.4l).

Prompt: case file (motion_reading CO DINH, arguments, weighing) + ledger (cac luot AI truoc: ai_points,
learner_claims, tien de da tan cong) + bai learner MOI o ngoi thu ba + nhiem vu theo mode (chon target_premise theo
do kho) + KHOI RANG BUOC dat CUOI CUNG (hieu ung gan nhat: rang buoc la dieu cuoi model doc truoc khi viet).

Validator (phan hoi chen TRUOC khoi rang buoc de khoi nay van o cuoi):
- Loi CUNG (retry co phan hoi, toi da TURN_MAX_ATTEMPTS): JSON / schema (ke ca tu sua ten truong go sai khi Groq tu
  choi schema), output rong / bi cat vi het max_tokens (truncated_max_tokens), bang chung mo ho muc HIGH.
- Loi MEM (muc 2.10): speech_text ngoai [0.7, 1.25] x muc tieu (prompt yeu cau [0.8, 1.2]) -> thu lai TOI DA 1 lan;
  van ngoai -> CHAP NHAN ban gan khoang nhat trong cac lan thu hop le, log "length_soft_accept". Khong bao gio lam
  luot that bai chi vi do dai.
Chi LOG: bo do muc LOW, cau co chu so / "%" ngoai "Giả sử", xung "em".

Stance Reviewer cho luot noi (Giai doan 3c, muc 2.11): reviewer v1 (stance_reviewer.py, model rieng) nhan motion +
ai_points (P1..Pn) + speech_text o vi tri "ket luan tong the" — KHONG nhan ai_side; code so voi ai_side.
side_flip -> retry TRUNG TINH (khong phan hoi, tinh vao TURN_MAX_ATTEMPTS); het luot -> luot THAT BAI, KHONG BAO GIO
tra bai noi bi bao lat phe. "khong_ro" / reviewer loi 2 lan -> unclear, chi log.

Gon token (muc 2.11): khong co bai learner moi -> prompt ghi ro, learner_claims / premises BI EP rong; closing khong
phan tich tien de -> premises rong, target_premise null (log neu model tra khong rong).
"""
import logging
import re
import unicodedata

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.llm.client import LLMClient
from app.llm.json_utils import LLMOutputParseError, extract_json
from app.opponent import stance_reviewer, vague_detector
from app.opponent.json_repair import ARRAY_REPAIRED, repair_split_array
from app.opponent.match_format import Speaker, TurnMode, word_count
from app.opponent.schemas import is_skipped_speech
from app.opponent.models import LLMCallPurpose, OpponentDifficulty, ReviewerVerdict
from app.opponent.service import _JSONSCHEMA_DETAIL, _match_renames, build_retry_feedback
from app.opponent.turn_generators import (
    FULL_V1,
    FULL_V2,
    FULL_V3,
    FULL_V4_STREAM,
    ROUND_LABEL,
    SIDE_LABEL,
    LLMCaller,
    TurnContext,
    TurnFailure,
    TurnLLMError,
    TurnResult,
)

logger = logging.getLogger(__name__)

MISSING_CASE_FILE = "missing_case_file"
MIN_WORDS_RATIO, MAX_WORDS_RATIO = 0.8, 1.2  # khoang YEU CAU trong prompt
ACCEPT_MIN_RATIO, ACCEPT_MAX_RATIO = 0.7, 1.25  # khoang CHAP NHAN (validator) — rong hon, do dai la loi mem
MAX_LENGTH_RETRIES = 1
LENGTH_SOFT_ACCEPT = "length_soft_accept"
ANALYSIS_COERCED = "analysis_coerced"  # speech_checks: model tra phan tich khong rong o cho bi ep rong
# Reviewer cho luot noi: CO DINH v1 (chi doc tung y — ai_points khong co "reasoning" rieng cho v2 / v3), muc 2.11.
TURN_REVIEW_VERSION = stance_reviewer.PROMPT_VERSION
# reviewer_detail: ket qua side check khi reviewer bao MOI muc nguoc phe; override khi side check xac nhan dung phe
SIDE_CHECK = "side_check"
REVIEWER_INVERTED_SUSPECT = "reviewer_inverted_suspect"
NO_NEW_SPEECH = "Không có bài nói mới của người học kể từ lượt trước của bạn."
# Learner bo luot (het gio / bam bo luot): khong co gi de phan bac, KHONG duoc gan cho ho loi chua noi
SKIPPED_SPEECH_NOTE = "Đội {learner} đã bỏ lượt {round} (không phát biểu)."
SKIPPED_TASK = (
    "Đội {learner} không phát biểu ở lượt vừa rồi. Nói ngắn gọn (một câu) rằng đối phương đã không phản biện, rồi "
    "củng cố và bảo vệ các luận điểm trong case của bạn. KHÔNG gán cho đội {learner} bất kỳ lập luận nào ở lượt này, "
    "KHÔNG phản bác lại như thể họ vừa nói."
)
# v2: tran 15:11 — bai noi doc ra nhan phan tich ("tiền đề ngầm"...) vi JSON co truong premises / target_premise.
NATURAL_SPEECH_RULE = (
    "- Nói tự nhiên như một người tranh luận; KHÔNG đọc ra các thuật ngữ phân tích như 'tiền đề', 'tiền đề ngầm' "
    "hay trích nguyên văn nhãn phân tích."
)
# v3: tran 17:38 luot 1 noi "Đây là một quy định cố định, không mở rộng hay thu hẹp hơn." — doc lai khoi rang buoc.
NO_RULE_ECHO_RULE = (
    "- KHÔNG nhắc lại, trích dẫn hay diễn giải các quy tắc và chỉ dẫn này trong bài nói (vd không nói 'cách hiểu cố "
    "định', 'không thu hẹp', 'tiền đề')."
)


# ---------------- output ----------------


class Premises(BaseModel):
    explicit: list[str]
    implicit: list[str]


class TurnOutput(BaseModel):
    learner_claims: list[str]
    premises: Premises
    target_premise: str | None
    ai_points: list[str] = Field(..., min_length=2, max_length=4)
    speech_text: str = Field(..., min_length=1)


FIELD_ORDER = ("learner_claims", "premises", "target_premise", "ai_points", "speech_text")
assert tuple(TurnOutput.model_fields) == FIELD_ORDER  # thu tu khai bao = thu tu trong schema / prompt


def needs_target(mode: TurnMode) -> bool:
    """Chi opening_reply / rebuttal chon tien de de tan cong; opening_first va closing: target_premise = null."""
    return mode in (TurnMode.OPENING_REPLY, TurnMode.REBUTTAL)


def attacks_premise(mode: TurnMode, has_new_speech: bool = True) -> bool:
    """Chon target_premise: mode can VA co bai learner moi that (learner bo luot -> khong co gi de tan cong)."""
    return needs_target(mode) and has_new_speech


def word_range(target_words: int) -> tuple[int, int]:
    """Khoang YEU CAU (ghi trong prompt va phan hoi)."""
    return round(MIN_WORDS_RATIO * target_words), round(MAX_WORDS_RATIO * target_words)


def accept_range(target_words: int) -> tuple[int, int]:
    """Khoang CHAP NHAN khong can thu lai."""
    return round(ACCEPT_MIN_RATIO * target_words), round(ACCEPT_MAX_RATIO * target_words)


def length_distance(n: int, target_words: int) -> int:
    """So tu nam ngoai khoang chap nhan (0 = trong khoang)."""
    lo, hi = accept_range(target_words)
    return max(lo - n, n - hi, 0)


def length_issue(n: int, target_words: int) -> str:
    lo, hi = word_range(target_words)
    return f"`speech_text` hiện dài {n} từ, yêu cầu từ {lo} đến {hi} từ — " + ("viết ngắn lại." if n > hi else "viết dài thêm.")


def analyzes_claims(mode: TurnMode, has_new_speech: bool) -> bool:
    """Co bai learner MOI de trich learner_claims (opening_first luon khong co)."""
    return has_new_speech and mode != TurnMode.OPENING_FIRST


def analyzes_premises(mode: TurnMode, has_new_speech: bool) -> bool:
    """Phan tich tien de: can bai learner moi VA khong phai closing (tong ket khong tan cong tien de)."""
    return analyzes_claims(mode, has_new_speech) and mode != TurnMode.CLOSING


def build_response_schema(mode: TurnMode, has_new_speech: bool = True) -> dict:
    """
    JSON schema strict (Groq), viet tay de GIU THU TU truong (model sinh theo thu tu properties). Theo mode:
    target_premise la string (opening_reply / rebuttal) hoac null. Khong co bai learner moi -> learner_claims /
    premises rong; closing -> premises rong (maxItems 0: bot token sinh phan tich thua, muc 2.11).
    """
    strings = {"type": "array", "items": {"type": "string"}}
    empty = {"type": "array", "items": {"type": "string"}, "maxItems": 0}
    claims = strings if analyzes_claims(mode, has_new_speech) else empty
    premises = strings if analyzes_premises(mode, has_new_speech) else empty
    return {
        "type": "object",
        "properties": {
            "learner_claims": claims,
            "premises": {
                "type": "object",
                "properties": {"explicit": premises, "implicit": premises},
                "required": ["explicit", "implicit"],
                "additionalProperties": False,
            },
            "target_premise": {"type": "string"} if attacks_premise(mode, has_new_speech) else {"type": "null"},
            "ai_points": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
            "speech_text": {"type": "string"},
        },
        "required": list(FIELD_ORDER),
        "additionalProperties": False,
    }


# ---------------- prompt ----------------

MODE_TASK = {
    TurnMode.OPENING_FIRST: (
        "Trình bày phần mở màn: giới thiệu cách hiểu kiến nghị và các luận điểm trong case của bạn. "
        "Chưa có gì để phản bác."
    ),
    TurnMode.OPENING_REPLY: (
        "Trình bày các luận điểm trong case của bạn, sau đó phản bác sơ bộ bài mở màn của đội {learner}."
    ),
    TurnMode.REBUTTAL: "Phản bác bài nói của đội {learner} và bảo vệ các luận điểm của bạn đã bị tấn công.",
    TurnMode.CLOSING: (
        "Tổng kết trận: nêu 2–3 điểm tranh chấp chính, với mỗi điểm so sánh vì sao phe bạn thắng; đáp lại điểm mạnh "
        "nhất của đội {learner}. KHÔNG đưa lập luận mới, KHÔNG liệt kê lại toàn bộ luận điểm."
    ),
}

TARGET_RULE = {
    OpponentDifficulty.EASY: "chọn một tiền đề TƯỜNG MINH bất kỳ.",
    OpponentDifficulty.MEDIUM: "chọn tiền đề TƯỜNG MINH vừa nền tảng (gần gốc lập luận) vừa được chứng minh chưa đầy đủ.",
    OpponentDifficulty.HARD: (
        "xét cả tiền đề NGẦM; chọn tiền đề nền tảng và chưa được chứng minh đầy đủ; có so sánh mức độ tác động."
    ),
}


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items)


def _since_last_ai(context: TurnContext):
    ai_turns = [s.turn_index for s in context.history if s.speaker == Speaker.AI]
    last_ai = max(ai_turns, default=0)
    return [s for s in sorted(context.history, key=lambda s: s.turn_index)
            if s.speaker == Speaker.LEARNER and s.turn_index > last_ai]


def new_learner_speeches(context: TurnContext):
    """Bai learner KE TU luot AI gan nhat (moi luot AI truoc do da 'doc' cac bai cu -> nam trong ledger). Luot learner
    BO (is_skipped_speech) khong phai bai noi: xem skipped_learner_turns."""
    return [s for s in _since_last_ai(context) if not is_skipped_speech(s.text)]


def skipped_learner_turns(context: TurnContext):
    """Luot learner bo (het gio / bo luot) ke tu luot AI gan nhat."""
    return [s for s in _since_last_ai(context) if is_skipped_speech(s.text)]


def constraints_block(context: TurnContext, version: str = FULL_V1) -> str:
    ai, learner = SIDE_LABEL[context.ai_side], SIDE_LABEL[context.learner_side]
    lo, hi = word_range(context.target_words)
    natural = "\n" + NATURAL_SPEECH_RULE if version in (FULL_V2, FULL_V3) else ""
    if version == FULL_V3:
        natural += "\n" + NO_RULE_ECHO_RULE
    return f"""Ràng buộc bắt buộc:
- Bạn thuộc phe {ai} và phải bảo vệ phe này đến hết trận.
- KHÔNG thu hẹp, mở rộng hay định nghĩa lại kiến nghị so với cách hiểu cố định ở trên.
- KHÔNG đề xuất như giải pháp của mình một phương án mà đội {learner} đã đưa ra hoặc gần giống với lập trường của họ. \
Có thể thừa nhận ngắn gọn tối đa một ý đúng của đối phương, sau đó phải chỉ ra vì sao phe bạn vẫn đúng.
- KHÔNG mâu thuẫn với những điều bạn đã khẳng định ở các lượt trước.
- Con số chỉ được xuất hiện trong tình huống giả định mở đầu bằng 'Giả sử'. KHÔNG viện dẫn nghiên cứu, thống kê, \
tổ chức, 'nhiều nơi/nhiều nước đã…' hay bất kỳ bằng chứng nào không nêu được nguồn.
- Tránh câu có phủ định lồng nhau; mỗi câu một ý rõ ràng.
- Xưng 'mình', gọi người học là 'bạn'. Giọng tôn trọng, không mỉa mai, không công kích cá nhân.
- Đây là bài NÓI sẽ được đọc thành tiếng: câu ngắn, không markdown, không gạch đầu dòng, không tiêu đề.{natural}
- Độ dài speech_text: từ {lo} đến {hi} từ.
- Chỉ trả về JSON hợp lệ."""


def build_full_prompt(
    mode: TurnMode, context: TurnContext, feedback: str | None = None, version: str = FULL_V1
) -> tuple[str, str]:
    """
    THUAN: (system, user). User theo thu tu (a) case (b) ai_points cu (c) learner_claims cu + tien de da tan cong
    (d) bai learner moi, ngoi thu ba (e) nhiem vu + dinh dang JSON [phan hoi retry] (f) khoi rang buoc — LUON cuoi.
    """
    case = context.case_file or {}
    ai, learner = SIDE_LABEL[context.ai_side], SIDE_LABEL[context.learner_side]
    system = (
        f"Bạn là một debater đang thi đấu, thuộc phe {ai} về kiến nghị: '{context.motion}'.\n"
        f"Cách hiểu kiến nghị của trận này là CỐ ĐỊNH: '{case.get('motion_reading', '')}'.\n"
        f"Người học thuộc phe {learner}. Phe của bạn không bao giờ thay đổi."
    )

    parts = [
        "Case của bạn (đã chuẩn bị trước trận):\n"
        + "\n".join(
            f"- [{a.get('id', '')}] {a.get('title', '')}: {a.get('claim', '')} Lý do: {a.get('reasoning', '')}"
            for a in case.get("arguments", [])
        )
        + f"\nCân nhắc tổng thể (weighing): {case.get('weighing', '')}"
    ]
    ledger = context.ledger
    if ledger.ai_points:
        parts.append("Những điều bạn ĐÃ khẳng định ở các lượt trước (không được mâu thuẫn):\n" + _bullets(ledger.ai_points))
    if ledger.learner_claims:
        parts.append("Các luận điểm người học đã nêu trước đó:\n" + _bullets(ledger.learner_claims))
    if ledger.attacked_premises:
        parts.append("Các tiền đề bạn đã tấn công:\n" + _bullets(ledger.attacked_premises))
    new = new_learner_speeches(context)
    skipped = skipped_learner_turns(context)
    for s in new:
        parts.append(f"Đội {learner} vừa phát biểu ({ROUND_LABEL[s.round_type]}):\n«{s.text}»")
    for s in skipped:
        parts.append(SKIPPED_SPEECH_NOTE.format(learner=learner, round=ROUND_LABEL[s.round_type].lower()))
    if not new and not skipped:
        parts.append(NO_NEW_SPEECH)
    attacks = attacks_premise(mode, bool(new))

    if skipped and not new and needs_target(mode):
        task = "Nhiệm vụ lượt này: " + SKIPPED_TASK.format(learner=learner)
    else:
        task = "Nhiệm vụ lượt này: " + MODE_TASK[mode].format(learner=learner)
        if skipped and not new:
            task += "\n" + SKIPPED_TASK.format(learner=learner)
    if attacks:
        task += (
            f"\nChọn target_premise (tiền đề của đội {learner} để tấn công): {TARGET_RULE[context.difficulty]}"
            "\nKhông tấn công lại tiền đề đã tấn công, trừ khi người học chưa đáp lại nó."
        )
    if mode == TurnMode.OPENING_FIRST:
        premises_rule = "để cả hai mảng rỗng (chưa có bài nói nào của người học)"
    elif not new:
        premises_rule = "để cả hai mảng rỗng (không có bài nói mới để phân tích)"
    elif mode == TurnMode.CLOSING:
        premises_rule = "để cả hai mảng rỗng (lượt tổng kết không phân tích tiền đề)"
    else:
        premises_rule = f"các tiền đề trong lập luận của đội {learner}: tường minh (explicit) và ngầm (implicit)"
    claims_rule = (
        f"các luận điểm chính trong (các) bài nói MỚI của đội {learner} ở trên" if new
        else "[] (không có bài nói mới)"
    )
    target_rule = (
        "tiền đề bạn chọn để tấn công (một câu, lấy từ premises)" if attacks
        else "null (lượt này không chọn tiền đề để tấn công)"
    )
    task += (
        "\n\nTrả về JSON, ĐÚNG thứ tự trường sau (phân tích trước, lập dàn ý, rồi mới viết bài):"
        f"\n- learner_claims: {claims_rule}."
        f"\n- premises: {{\"explicit\": [...], \"implicit\": [...]}} — {premises_rule}."
        f"\n- target_premise: {target_rule}."
        "\n- ai_points: dàn ý 2–4 ý bạn sẽ nói trong lượt này, mỗi ý một câu."
        "\n- speech_text: bài nói hoàn chỉnh, viết theo dàn ý ai_points."
    )
    parts.append(task)
    if feedback:
        parts.append(feedback.strip())
    parts.append(constraints_block(context, version))
    return system, "\n\n".join(parts)


# ---------------- validator ----------------


class _Invalid(Exception):
    def __init__(self, kind: str, error: str, issues: list[str], speech: str | None = None):
        super().__init__(error)
        self.kind, self.error, self.issues, self.speech = kind, error, issues, speech


_OBJECTS = (("", TurnOutput), ("premises.", Premises))


def _key_diffs(data: dict) -> list[dict]:
    diffs = []
    for prefix, model in _OBJECTS:
        obj = data if not prefix else data.get("premises")
        if not isinstance(obj, dict):
            continue
        missing = [k for k in model.model_fields if k not in obj]
        unknown = [k for k in obj if k not in model.model_fields]
        if missing or unknown:
            diffs.append({"prefix": prefix, "obj": obj, "missing": missing, "unknown": unknown,
                          "renames": _match_renames(missing, unknown)})
    return diffs


def _key_issues(data: dict) -> list[str]:
    issues = []
    for d in _key_diffs(data):
        p = d["prefix"]
        issues += [f"`{p}{w}`: bạn đã viết '{w}', tên đúng là '{r}'" for w, r in d["renames"].items()]
        issues += [f"`{p}{k}`: trường lạ — bỏ đi" for k in d["unknown"] if k not in d["renames"]]
        issues += [f"`{p}{k}`: thiếu trường bắt buộc" for k in d["missing"] if k not in d["renames"].values()]
    return issues


def repair_keys(data: dict) -> list[dict]:
    """Doi ten key go sai (<= 3 ky tu) TRUC TIEP tren data. Tra danh sach doi ten."""
    renames = []
    for d in _key_diffs(data):
        for wrong, right in d["renames"].items():
            d["obj"][right] = d["obj"].pop(wrong)
            renames.append({"path": d["prefix"] + right, "from": wrong, "to": right})
    return renames


def _validation_issues(e: ValidationError, data: object) -> list[str]:
    issues = []
    for err in e.errors():
        if err["type"] == "missing" and isinstance(data, dict):
            continue  # _key_issues neu kem goi y ten dung
        where = ".".join(str(p) for p in err["loc"]) or "(toàn bộ JSON)"
        if err["type"] == "too_short":
            msg = f"cần ít nhất {err.get('ctx', {}).get('min_length')} phần tử / ký tự"
        elif err["type"] == "too_long":
            msg = f"chỉ được tối đa {err.get('ctx', {}).get('max_length')} phần tử"
        else:
            msg = err["msg"]
        issues.append(f"`{where}`: {msg}")
    return issues + (_key_issues(data) if isinstance(data, dict) else [])


def validate_turn_data(data: object, mode: TurnMode, target_words: int, has_new_speech: bool = True) -> TurnOutput:
    """Nem _Invalid (kem phan hoi tieng Viet) neu khong hop le. has_new_speech=False (learner bo luot): khong doi
    target_premise."""
    try:
        out = TurnOutput.model_validate(data)
    except ValidationError as e:
        speech = data.get("speech_text") if isinstance(data, dict) and isinstance(data.get("speech_text"), str) else None
        raise _Invalid(TurnFailure.SCHEMA_VALIDATION, str(e)[:4000], _validation_issues(e, data), speech) from e
    if mode == TurnMode.OPENING_FIRST:  # chua co bai learner: bo moi phan tich (schema Groq da ep rong)
        out.learner_claims, out.premises = [], Premises(explicit=[], implicit=[])
    if not attacks_premise(mode, has_new_speech):
        out.target_premise = None
    elif not (out.target_premise or "").strip():
        raise _Invalid(
            TurnFailure.SCHEMA_VALIDATION, "target_premise rong o luot can tan cong",
            ["`target_premise`: lượt này phải chọn đúng một tiền đề để tấn công (không được null / rỗng)."],
            out.speech_text,
        )
    out.speech_text = out.speech_text.strip()

    # Loi CUNG duy nhat o day: bang chung HIGH. Do dai (loi MEM) do generator xu ly — neu ca hai cung sai, phan hoi
    # retry neu kem do dai.
    high = [h for h in vague_detector.detect_speech(out.speech_text) if h.level == vague_detector.HIGH]
    if high:
        issues = [
            f"`speech_text` có lời viện dẫn bằng chứng mơ hồ \"{h.match}\" ({h.reason}) — bỏ đi, thay bằng lập luận "
            "dựa trên cơ chế hoặc tình huống 'Giả sử'."
            for h in high
        ]
        n = word_count(out.speech_text)
        if length_distance(n, target_words):
            issues.append(length_issue(n, target_words))
        raise _Invalid(
            TurnFailure.BANNED_PHRASE, "banned_phrase: " + "; ".join(f"'{h.match}' ({h.rule})" for h in high),
            issues, out.speech_text,
        )
    return out


def parse_turn_output(raw: str | None, mode: TurnMode, target_words: int, has_new_speech: bool = True) -> TurnOutput:
    try:
        data = extract_json(raw or "")
    except LLMOutputParseError as e:
        raise _Invalid(
            TurnFailure.INVALID_JSON, str(e),
            ["Output không phải một JSON object hợp lệ (có thể bị cắt ngắn, hoặc có text / markdown thừa ngoài JSON)."],
        ) from e
    return validate_turn_data(data, mode, target_words, has_new_speech)


def _repair_rejected(call, mode: TurnMode, target_words: int, has_new_speech: bool = True) -> TurnOutput:
    """
    Groq tu choi schema -> sua TAT DINH roi validate CUC BO (khong goi lai LLM). Khong duoc -> _Invalid schema_rejected.
    1. "Mang tach" (json_repair, muc 2.12): dung lai object; khong qua schema cuc bo -> xu ly nhu schema_rejected; qua
       schema nhung sai noi dung (bang chung HIGH) -> retry nhu thuong.
    2. Ten truong go sai <= 3 ky tu (muc 2.4j).
    """
    m = _JSONSCHEMA_DETAIL.search(call.error or "")
    issues = [
        f"Output bị nhà cung cấp từ chối vì không khớp JSON schema{f' ({m.group(1)})' if m else ''}. Kiểm tra lại "
        "đúng 5 trường theo thứ tự, đúng kiểu, không thêm trường lạ. Trả về MỘT object JSON (không phải mảng)."
    ]
    repaired = repair_split_array(call.raw_output, FIELD_ORDER)
    if repaired is not None:
        data, info = repaired
        renames = repair_keys(data)
        if _key_diffs(data):
            raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues + _key_issues(data))
        try:
            out = validate_turn_data(data, mode, target_words, has_new_speech)
        except _Invalid as e:
            if e.kind == TurnFailure.SCHEMA_VALIDATION:
                raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues + e.issues, e.speech) from None
            raise
        call.key_repairs = {**info, "renames": renames, "provider_error": (call.error or "")[:1000]}
        return out
    try:
        data = extract_json(call.raw_output or "")
    except LLMOutputParseError:
        raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues) from None
    if not isinstance(data, dict):
        raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues)
    renames = repair_keys(data)
    if not renames or _key_diffs(data):
        raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues + _key_issues(data))
    out = validate_turn_data(data, mode, target_words, has_new_speech)  # co the nem _Invalid khac -> retry
    call.key_repairs = {"event": "key_repaired", "renames": renames, "provider_error": (call.error or "")[:1000]}
    return out


# ---------------- kiem tra chi log ----------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_DIGIT_OR_PERCENT = re.compile(r"\d|%")
# Dai tu "em" (AI tu xung hoac goi learner). Chap nhan bat nham (vd "trẻ em", "anh em").
_EM_PRONOUN = re.compile(r"\bem\b", re.IGNORECASE)


def speech_checks(text: str) -> dict:
    sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    nfc = [unicodedata.normalize("NFC", s) for s in sentences]
    return {
        "numbers_without_gia_su": [s for s in nfc if _DIGIT_OR_PERCENT.search(s) and "giả sử" not in s.casefold()],
        "em_pronoun": [s for s in nfc if _EM_PRONOUN.search(s)],
    }


TRUNCATED_ISSUE = (
    "Output lần trước RỖNG hoặc bị CẮT giữa chừng vì hết giới hạn token. Suy nghĩ ngắn gọn hơn, trả về ĐỦ 5 trường "
    "JSON; speech_text giữ trong khoảng độ dài yêu cầu."
)


def coerce_analysis(out: TurnOutput, mode: TurnMode, has_new_speech: bool) -> dict:
    """
    Ep rong phan tich o cho KHONG duoc phan tich (khong co bai learner moi; closing: premises). Tra {truong: so muc
    bi bo} (rong = model tuan thu) de log — provider khong ep schema (hoac model lap lai ledger) van khong luu rac.
    """
    dropped = {}
    if not analyzes_claims(mode, has_new_speech) and out.learner_claims:
        dropped["learner_claims"] = len(out.learner_claims)
        out.learner_claims = []
    if not analyzes_premises(mode, has_new_speech) and (out.premises.explicit or out.premises.implicit):
        dropped["premises"] = len(out.premises.explicit) + len(out.premises.implicit)
        out.premises = Premises(explicit=[], implicit=[])
    if not attacks_premise(mode, has_new_speech):
        out.target_premise = None  # validate_turn_data da ep; giu o day cho ro
    return dropped


def _log_speech(call, speech: str | None) -> None:
    if speech:
        call.vague_evidence = [h.to_log() for h in vague_detector.detect_speech(speech)]
        call.speech_checks = speech_checks(speech)


# ---------------- bo sinh ----------------


class FullTurnGenerator:
    """
    Vong thu (moi lan thu = 1 loi goi sinh [+ reviewer]):
    - loi CUNG -> retry co phan hoi (toi da TURN_MAX_ATTEMPTS lan sinh);
    - Stance Reviewer bao side_flip -> retry TRUNG TINH (prompt goc, khong phan hoi), tinh vao TURN_MAX_ATTEMPTS;
    - loi MEM (do dai) -> toi da MAX_LENGTH_RETRIES lan thu lai, sau do chap nhan ban gan khoang nhat.
    Het luot: con ban hop le (da qua reviewer, chi sai do dai) -> chap nhan; khong -> that bai (ke ca vi side_flip).
    """

    version = FULL_V1

    def __init__(self, client: LLMClient, settings: Settings, reviewer_client: LLMClient | None = None):
        # on_event(dict): turn_service gan cho endpoint stream. {"type": "attempt", "attempt", "previous_failure"} o dau
        # moi lan thu (lan thu sau thay bai cua lan truoc); turn_full_v4_stream them {"type": "delta", "text"}.
        self.on_event = None
        self.settings = settings
        self.temperature = settings.turn_temperature
        self.caller = LLMCaller(client, settings)
        # Reviewer ghi CHUNG danh sach loi goi (attempt lien tuc), khong gui TURN_REASONING_EFFORT.
        self.reviewer = (
            LLMCaller(reviewer_client, settings, calls=self.caller.calls, send_effort=False)
            if reviewer_client is not None else None
        )

    async def generate(self, mode: TurnMode, context: TurnContext) -> TurnResult:
        client, settings = self.caller.client, self.settings
        result = TurnResult(
            text=None, mode=mode, generator_version=self.version, llm_provider=client.provider,
            llm_model=client.model, temperature=self.temperature, calls=self.caller.calls,
        )
        if not context.case_file:
            result.error, result.failure_kind = f"{self.version} can case file (session READY)", MISSING_CASE_FILE
            return result
        has_new = bool(new_learner_speeches(context))
        schema = build_response_schema(mode, has_new) if settings.case_plan_use_json_schema else None
        feedback = None
        length_retries = 0
        candidates: list[tuple[int, int, TurnOutput, object]] = []  # (khoang cach, thu tu, output, call) — sai do dai
        previous_failure = None
        for attempt_no in range(1, settings.turn_max_attempts + 1):
            last = attempt_no == settings.turn_max_attempts
            if attempt_no > 1:
                previous_failure = next(  # lan goi SINH gan nhat (reviewer ghi sau no trong cung danh sach)
                    (c.failure_kind for c in reversed(self.caller.calls) if c.purpose == LLMCallPurpose.TURN), None
                )
            self._emit({"type": "attempt", "attempt": attempt_no, "previous_failure": previous_failure})
            system, user = self._prompt(mode, context, feedback)
            try:
                call = await self._complete(system, user, schema)
            except TurnLLMError as e:
                result.error, result.failure_kind = str(e), TurnFailure.PROVIDER_ERROR
                return result
            try:
                if call.truncated:
                    raise _Invalid(TurnFailure.TRUNCATED, call.error or TurnFailure.TRUNCATED, [TRUNCATED_ISSUE])
                if call.schema_rejected:
                    out = _repair_rejected(call, mode, context.target_words, has_new)
                    call.success, call.error, call.failure_kind = True, None, None
                    logger.info("Luot %d: %s, khong goi lai LLM: %s", context.turn_index,
                                call.key_repairs.get("event"), call.key_repairs)
                else:
                    out = self._parse(call.raw_output, mode, context.target_words, has_new)
            except _Invalid as e:
                call.success, call.error, call.failure_kind = False, e.error[:4000], e.kind
                _log_speech(call, e.speech)
                logger.warning("Luot %d lan thu %d khong hop le (%s): %s", context.turn_index, attempt_no, e.kind, e.error)
                if last:
                    return self._give_up(result, candidates, context, e.error, e.kind)
                feedback = build_retry_feedback(e.issues)
                call.retry_feedback = feedback.strip()
                continue

            _log_speech(call, out.speech_text)
            dropped = coerce_analysis(out, mode, has_new)
            if dropped:
                call.speech_checks = {**(call.speech_checks or {}), ANALYSIS_COERCED: dropped}
                logger.info("Luot %d: ep rong phan tich model tra thua %s", context.turn_index, dropped)

            if self.reviewer is not None:
                verdict, detail = await self._review(out, context)
                call.reviewer_verdict, call.reviewer_detail = verdict, detail
                if verdict == ReviewerVerdict.SIDE_FLIP:
                    call.success, call.failure_kind = False, TurnFailure.SIDE_FLIP
                    call.error = f"side_flip: trong tai danh gia {detail['flipped_ids']} nguoc phe {context.ai_side.value}"
                    logger.warning("Luot %d lan thu %d lat phe: %s", context.turn_index, attempt_no, detail["flipped_ids"])
                    if last:
                        return self._give_up(result, candidates, context, call.error, TurnFailure.SIDE_FLIP)
                    feedback = None  # retry TRUNG TINH: prompt goc, khong noi "ban da lat phe" (muc 2.4m)
                    call.reviewer_detail = {**detail, "retry": "side_flip_neutral_retry"}
                    continue
                if verdict == ReviewerVerdict.UNCLEAR:
                    logger.warning("Luot %d: stance review khong ro: %s", context.turn_index, detail)

            n = word_count(out.speech_text)
            distance = length_distance(n, context.target_words)
            if distance == 0:
                call.success, call.error, call.failure_kind = True, None, None
                return self._accept(result, out)
            # Loi MEM: do dai
            lo, hi = accept_range(context.target_words)
            call.success, call.failure_kind = False, TurnFailure.WORD_COUNT
            call.error = f"word_count {n} ngoai khoang chap nhan [{lo}, {hi}]"
            candidates.append((distance, attempt_no, out, call))
            if length_retries >= MAX_LENGTH_RETRIES or last:
                return self._soft_accept(result, candidates, context)
            length_retries += 1
            feedback = build_retry_feedback([length_issue(n, context.target_words)])
            call.retry_feedback = feedback.strip()
            logger.info("Luot %d: do dai %d tu ngoai [%d, %d], thu lai (loi mem)", context.turn_index, n, lo, hi)
        raise AssertionError("unreachable")  # pragma: no cover

    def _emit(self, event: dict) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _prompt(self, mode: TurnMode, context: TurnContext, feedback: str | None) -> tuple[str, str]:
        return build_full_prompt(mode, context, feedback, self.version)

    async def _complete(self, system: str, user: str, schema: dict | None):
        return await self.caller.complete(
            system, user, temperature=self.temperature, max_tokens=self.settings.turn_max_tokens,
            prompt_version=self.version, json_schema=schema,
        )

    def _parse(self, raw: str | None, mode: TurnMode, target_words: int, has_new_speech: bool) -> TurnOutput:
        return parse_turn_output(raw, mode, target_words, has_new_speech)

    async def _review(self, out: TurnOutput, context: TurnContext) -> tuple[ReviewerVerdict, dict]:
        """
        Reviewer v1: motion + ai_points (P1..Pn) + speech_text (vi tri "ket luan tong the"); KHONG ai_side. Loi goi /
        output reviewer loi -> thu lai 1 lan (khong tinh TURN_MAX_ATTEMPTS) roi coi nhu unclear (giong Case Planning).
        """
        sr, settings = stance_reviewer, self.settings
        spec = sr.REVIEW_VERSIONS[TURN_REVIEW_VERSION]
        statements = [sr.Statement(f"P{i}", point) for i, point in enumerate(out.ai_points, start=1)]
        ids = [st.id for st in statements]
        system, user = spec.build_prompt(context.motion, statements, out.speech_text)
        schema = spec.build_schema(ids, has_summary=True) if settings.case_plan_use_json_schema else None
        error = ""
        for call_no in range(1, sr.MAX_CALLS + 1):
            try:
                call = await self.reviewer.complete(
                    system, user, temperature=sr.TEMPERATURE, max_tokens=settings.stance_review_max_tokens,
                    prompt_version=TURN_REVIEW_VERSION, json_schema=schema, purpose=LLMCallPurpose.STANCE_REVIEW,
                )
            except TurnLLMError as e:
                error = str(e)
            else:
                if call.success:
                    try:
                        review, extra = spec.parse(call.raw_output, ids, has_summary=True)
                    except (LLMOutputParseError, ValidationError, ValueError) as e:
                        call.success, call.error = False, str(e)[:4000]
                        call.failure_kind = TurnFailure.REVIEWER_ERROR
                        error = call.error
                    else:
                        verdict, detail = sr.judge(review, context.ai_side, TURN_REVIEW_VERSION, extra)
                        detail["reviewer_calls"] = call_no
                        call.reviewer_verdict, call.reviewer_detail = verdict, detail
                        if verdict == ReviewerVerdict.SIDE_FLIP and sr.is_total_flip(detail):
                            return await self._check_total_flip(out, context, detail)
                        return verdict, detail
                else:
                    error = call.error or ""
            if call_no < sr.MAX_CALLS:
                logger.warning("Stance review luot %d loi (lan goi %d), thu lai: %s", context.turn_index, call_no, error)
        verdict, detail = sr.reviewer_failure(error, TURN_REVIEW_VERSION)
        detail["reviewer_calls"] = sr.MAX_CALLS
        return verdict, detail

    async def _check_total_flip(
        self, out: TurnOutput, context: TurnContext, detail: dict
    ) -> tuple[ReviewerVerdict, dict]:
        """
        Reviewer bao MOI muc nguoc phe: hoi lai 1 lan theo cach khac (side_check_v1: ca bai noi, y dinh nguoi noi, van
        KHONG biet phe). Xac nhan dung phe AI -> reviewer bi nghi doc nguoc: UNCLEAR (chap nhan, log
        reviewer_inverted_suspect). Nguoc phe / khong ro / loi -> giu SIDE_FLIP (khong bao gio tra bai lat phe chua ro).
        """
        sr, settings = stance_reviewer, self.settings
        expected = sr.EXPECTED_POSITION[context.ai_side]
        system, user = sr.build_side_check_prompt(context.motion, out.speech_text)
        schema = sr.build_side_check_schema() if settings.case_plan_use_json_schema else None
        check: dict = {"prompt_version": sr.SIDE_CHECK_VERSION}
        for call_no in range(1, sr.MAX_CALLS + 1):
            check["calls"] = call_no
            try:
                call = await self.reviewer.complete(
                    system, user, temperature=sr.TEMPERATURE, max_tokens=settings.stance_review_max_tokens,
                    prompt_version=sr.SIDE_CHECK_VERSION, json_schema=schema, purpose=LLMCallPurpose.STANCE_REVIEW,
                )
            except TurnLLMError as e:
                check["error"] = str(e)[:2000]
                continue
            if not call.success:
                check["error"] = (call.error or "")[:2000]
                continue
            try:
                parsed = sr.parse_side_check(call.raw_output)
            except (LLMOutputParseError, ValidationError, ValueError) as e:
                call.success, call.error = False, str(e)[:4000]
                call.failure_kind = TurnFailure.REVIEWER_ERROR
                check["error"] = call.error[:2000]
                continue
            check.pop("error", None)
            check.update(position=parsed.position.value, conclusion=parsed.conclusion, reason=parsed.reason)
            call.reviewer_verdict = ReviewerVerdict.PASS if parsed.position == expected else ReviewerVerdict.SIDE_FLIP
            call.reviewer_detail = {**check, "expected_position": expected.value}
            break
        detail = {**detail, SIDE_CHECK: check}
        if check.get("position") == expected.value:
            logger.warning("Luot %d: %s — reviewer bao lat ca %s nhung side check xac nhan dung phe %s",
                           context.turn_index, REVIEWER_INVERTED_SUSPECT, detail["flipped_ids"], context.ai_side.value)
            return ReviewerVerdict.UNCLEAR, {**detail, "override": REVIEWER_INVERTED_SUSPECT}
        return ReviewerVerdict.SIDE_FLIP, detail

    def _give_up(self, result: TurnResult, candidates: list, context: TurnContext, error: str, kind: str) -> TurnResult:
        """Het luot thu. Con ban hop le chi sai do dai (da qua reviewer) -> chap nhan; khong -> that bai."""
        if candidates:
            return self._soft_accept(result, candidates, context)
        result.error, result.failure_kind = error, kind
        return result

    @staticmethod
    def _accept(result: TurnResult, out: TurnOutput) -> TurnResult:
        result.text = out.speech_text
        result.learner_claims = out.learner_claims
        result.premises = out.premises.model_dump()
        result.target_premise = out.target_premise
        result.ai_points = out.ai_points
        return result

    def _soft_accept(self, result: TurnResult, candidates: list, context: TurnContext) -> TurnResult:
        """Chap nhan ban hop le GAN khoang chap nhan nhat (hoa -> ban som hon). Log length_soft_accept."""
        _, _, out, call = min(candidates, key=lambda c: (c[0], c[1]))
        n, (lo, hi) = word_count(out.speech_text), accept_range(context.target_words)
        call.success, call.error, call.failure_kind = True, None, None
        call.speech_checks = {**(call.speech_checks or {}),
                              LENGTH_SOFT_ACCEPT: {"word_count": n, "accept_min": lo, "accept_max": hi}}
        logger.info("Luot %d: %s word_count=%d (chap nhan [%d, %d])", context.turn_index, LENGTH_SOFT_ACCEPT, n, lo, hi)
        return self._accept(result, out)


class FullTurnGeneratorV2(FullTurnGenerator):
    """v1 + rang buoc NATURAL_SPEECH_RULE trong khoi rang buoc (muc 2.10). Moi thu khac giong v1."""

    version = FULL_V2


class FullTurnGeneratorV3(FullTurnGenerator):
    """v2 + rang buoc NO_RULE_ECHO_RULE (muc 2.12). Moi thu khac giong v1 / v2."""

    version = FULL_V3


# ---------------- turn_full_v4_stream ----------------

SPEECH_DELIMITER = "===BÀI NÓI==="
# Dong phan cach (chap nhan khoang trang / so dau "=" khac, khong phan biet hoa thuong; so tren chuoi da NFC)
# Ca dang dung san (À, Ó) lan dang tach dau (A + U+0300, O + U+0301): stream tach tren chu GOC, khong NFC
_DELIMITER_LINE = re.compile(
    "^[ \t]*=+[ \t]*B(?:\u00c0|A\u0300)I N(?:\u00d3|O\u0301)I[ \t]*=+[ \t]*$", re.MULTILINE | re.IGNORECASE
)
MISSING_DELIMITER_ISSUE = (
    f"Output thiếu dòng {SPEECH_DELIMITER}. Viết đúng 3 phần: JSON phân tích, một dòng {SPEECH_DELIMITER}, rồi bài nói."
)
_JSON_TASK_HEAD = "\n\nTrả về JSON, ĐÚNG thứ tự trường sau (phân tích trước, lập dàn ý, rồi mới viết bài):"
_JSON_TASK_SPEECH = "\n- speech_text: bài nói hoàn chỉnh, viết theo dàn ý ai_points."
_JSON_ONLY_RULE = "- Chỉ trả về JSON hợp lệ."
_LENGTH_RULE_FIELD = "- Độ dài speech_text:"


def build_stream_prompt(mode: TurnMode, context: TurnContext, feedback: str | None = None) -> tuple[str, str]:
    """
    Prompt v3, chi doi DINH DANG output: JSON 4 truong phan tich (bo speech_text) -> dong SPEECH_DELIMITER -> bai noi
    van ban thuan. Ly do: Groq khong stream duoc khi ep JSON (client.GroqClient.generate_stream), con bai noi o CUOI
    van giu thu tu "phan tich -> dan y -> moi viet".
    """
    system, user = build_full_prompt(mode, context, feedback, FULL_V3)
    for marker in (_JSON_TASK_HEAD, _JSON_TASK_SPEECH, _JSON_ONLY_RULE, _LENGTH_RULE_FIELD):
        if user.count(marker) != 1:
            raise AssertionError(f"prompt v3 da doi, can sua build_stream_prompt: {marker!r}")
    user = (
        user.replace(
            _JSON_TASK_HEAD,
            "\n\nTrả lời ĐÚNG 3 phần theo thứ tự (phân tích trước, lập dàn ý, rồi mới viết bài):"
            "\n1. Một JSON object gồm đúng 4 trường theo thứ tự:",
        )
        .replace(
            _JSON_TASK_SPEECH,
            f"\n2. Một dòng chỉ gồm {SPEECH_DELIMITER}"
            "\n3. Bài nói hoàn chỉnh (speech_text), viết theo dàn ý ai_points, dạng văn bản thường — không đặt trong "
            "JSON, không ngoặc kép bao quanh.",
        )
        .replace(_JSON_ONLY_RULE, f"- Chỉ trả về JSON, dòng {SPEECH_DELIMITER} và bài nói; không thêm gì khác.")
        .replace(_LENGTH_RULE_FIELD, "- Độ dài bài nói (speech_text):")
    )
    return system, user


def split_stream_output(raw: str) -> tuple[str, str | None]:
    """(phan truoc dong phan cach, bai noi). Khong co dong phan cach -> (raw, None)."""
    text = unicodedata.normalize("NFC", raw or "")
    m = _DELIMITER_LINE.search(text)
    if m is None:
        return text, None
    return text[: m.start()], text[m.end():].strip()


def parse_stream_output(raw: str | None, mode: TurnMode, target_words: int, has_new_speech: bool = True) -> TurnOutput:
    head, speech = split_stream_output(raw or "")
    try:
        data = extract_json(head)
    except LLMOutputParseError as e:
        issue = MISSING_DELIMITER_ISSUE if speech is None else (
            f"Phần trước dòng {SPEECH_DELIMITER} không phải một JSON object hợp lệ."
        )
        raise _Invalid(TurnFailure.INVALID_JSON, str(e), [issue]) from e
    if not isinstance(data, dict):
        raise _Invalid(TurnFailure.INVALID_JSON, "phan phan tich khong phai JSON object", [MISSING_DELIMITER_ISSUE])
    if speech is not None:
        data["speech_text"] = speech
    elif not isinstance(data.get("speech_text"), str):  # model viet kieu v3 (speech_text trong JSON) van nhan
        raise _Invalid(TurnFailure.INVALID_JSON, "thieu dong phan cach bai noi", [MISSING_DELIMITER_ISSUE])
    return validate_turn_data(data, mode, target_words, has_new_speech)


class SpeechStreamExtractor:
    """
    Nhan tung doan output stream, tra phan BAI NOI moi (sau dong phan cach). Dong phan cach co the bi cat giua 2 doan:
    tim tren buffer da gom, va chi chot khi da co ky tu sau dong do. Khoang trang dau bai bi bo (giong strip() khi parse).
    Lam tren chu GOC (khong NFC): NFC tren buffer dang lon co the gop dau vao chu da gui, lam lech vi tri da gui. Ban
    chinh thuc (su kien done) van la ban da NFC + strip cua parse_stream_output.
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.speech_start: int | None = None
        self.emitted = 0

    def feed(self, piece: str) -> str:
        self.buffer += piece
        if self.speech_start is None:
            m = _DELIMITER_LINE.search(self.buffer)
            if m is None or len(self.buffer) <= m.end():
                return ""
            rest = self.buffer[m.end():]
            if not rest.strip():  # chua co chu nao cua bai noi: cho them de bo khoang trang dau bai
                return ""
            self.speech_start = m.end() + (len(rest) - len(rest.lstrip()))
        new = self.buffer[self.speech_start + self.emitted:]
        self.emitted += len(new)
        return new


class FullTurnGeneratorV4Stream(FullTurnGeneratorV3):
    """
    v3 (prompt, validator, Stance Reviewer, retry) nhung output van ban thuan va STREAM bai noi qua on_event
    {"type": "delta", "text"}. Bai noi hien TRUOC khi reviewer xong: lan thu bi loai -> lan sau mo dau bang su kien
    "attempt" va nguoi nghe thay bai. Muc suy luan rieng: TURN_STREAM_REASONING_EFFORT.
    """

    version = FULL_V4_STREAM

    def __init__(self, client: LLMClient, settings: Settings, reviewer_client: LLMClient | None = None):
        super().__init__(
            client, settings.model_copy(update={"turn_reasoning_effort": settings.turn_stream_reasoning_effort}),
            reviewer_client,
        )

    def _prompt(self, mode: TurnMode, context: TurnContext, feedback: str | None) -> tuple[str, str]:
        return build_stream_prompt(mode, context, feedback)

    async def _complete(self, system: str, user: str, schema: dict | None):
        state = {"request_no": None, "extractor": SpeechStreamExtractor()}

        def on_delta(request_no: int, piece: str) -> None:
            if state["request_no"] != request_no:
                # _call thu lai HTTP request (loi mang giua chung): bo phan bai noi da day cua request truoc
                if state["request_no"] is not None and state["extractor"].emitted:
                    self._emit({"type": "attempt", "attempt": None, "previous_failure": TurnFailure.TRANSIENT_ERROR})
                state["request_no"], state["extractor"] = request_no, SpeechStreamExtractor()
            new = state["extractor"].feed(piece)
            if new:
                self._emit({"type": "delta", "text": new})

        return await self.caller.complete_stream(
            system, user, temperature=self.temperature, max_tokens=self.settings.turn_max_tokens,
            prompt_version=self.version, on_delta=on_delta,
        )

    def _parse(self, raw: str | None, mode: TurnMode, target_words: int, has_new_speech: bool) -> TurnOutput:
        return parse_stream_output(raw, mode, target_words, has_new_speech)
