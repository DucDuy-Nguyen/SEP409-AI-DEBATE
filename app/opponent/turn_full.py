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
tra bai noi bi bao lat phe. "khong_ro" (phan doan that) -> chi log; reviewer LOI 2 lan -> reviewer_unavailable, retry
trung tinh nhu side_flip (fail-closed, muc 2.14).

turn_full_v7 (muc 3.2): xem FullTurnGeneratorV7. v1..v6 GIU NGUYEN (TurnOutput cu, TARGET_RULE cu).

Gon token (muc 2.11): khong co bai learner moi -> prompt ghi ro, learner_claims / premises BI EP rong; closing khong
phan tich tien de -> premises rong, target_premise null (log neu model tra khong rong).
"""
import difflib
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
from app.opponent.models import LLMCallPurpose, OpponentDifficulty, ReviewerVerdict
from app.opponent.service import _JSONSCHEMA_DETAIL, _match_renames, build_retry_feedback
from app.opponent.turn_generators import (
    FULL_V1,
    FULL_V2,
    FULL_V3,
    FULL_V4,
    FULL_V4_NOBURDEN,
    FULL_V5,
    FULL_V5_NOBURDEN,
    FULL_V6,
    FULL_V6_NOBURDEN,
    FULL_V7,
    FULL_V7_NODIFFICULTY,
    FULL_V7_NODIFFICULTY_NOBURDEN,
    FULL_V7_NOBURDEN,
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
NO_NEW_SPEECH = "Không có bài nói mới của người học kể từ lượt trước của bạn."
# v2: tran 15:11 — bai noi doc ra nhan phan tich ("tiền đề ngầm"...) vi JSON co truong premises / target_premise.
NATURAL_SPEECH_RULE = (
    "- Nói tự nhiên như một người tranh luận; KHÔNG đọc ra các thuật ngữ phân tích như 'tiền đề', 'tiền đề ngầm' "
    "hay trích nguyên văn nhãn phân tích."
)
# v3: tran 17:38 luot 1 noi "Đây là một quy định cố định, không mở rộng hay thu hẹp hơn." — doc lai khoi rang buoc.
# turn_full_v5 (muc 2.18) — 3 rang buoc moi, nguyen van spec.
V5_RULES = (
    "- Mọi trường trong JSON, kể cả ai_points, viết bằng tiếng Việt.",
    "- ai_points là các khẳng định ngắn, không mở đầu bằng 'Mình sẽ…', 'Mình nhấn mạnh rằng…'. Bài nói diễn đạt các ý "
    "đó bằng lời nói tự nhiên, không chép nguyên văn dàn ý.",
    "- Không lặp lại cùng một câu hay cùng một ý hai lần.",
)
FIELD_ORDER_V5 = ("premises", "target_premise", "ai_points", "speech_text")  # v5: KHONG con learner_claims
# v5: do dai CHI retry khi ngoai [0,5x; 1,5x] muc tieu; trong khoang nay ma ngoai [0,7x; 1,25x] -> chap nhan ngay (log)
RETRY_MIN_RATIO, RETRY_MAX_RATIO = 0.5, 1.5


def is_v7_difficulty(version: str) -> bool:
    """v7 KHI BAT do kho. Cac nhan _nodifficulty: prompt + schema + validator = v6."""
    return version in (FULL_V7, FULL_V7_NOBURDEN)


def is_v6(version: str) -> bool:
    """v6 TRO LEN (v7 giu moi thay doi cua v6)."""
    return version in (FULL_V6, FULL_V6_NOBURDEN, FULL_V7, FULL_V7_NOBURDEN, FULL_V7_NODIFFICULTY,
                       FULL_V7_NODIFFICULTY_NOBURDEN)


def is_v5(version: str) -> bool:
    """v5 TRO LEN (v6 giu moi thay doi cua v5)."""
    return version in (FULL_V5, FULL_V5_NOBURDEN) or is_v6(version)


# v6 (muc 2.19) — nguyen van spec
V6_LEDGER_TITLE = "Những ý người học đã nêu ở các lượt TRƯỚC (chỉ để tham khảo, đừng chép lại):"
V6_EXTRACTION_RULE = (
    "premises chỉ được trích từ (các) bài nói MỚI của đội {learner} ở mục trên, không lấy từ các lượt trước."
)
PREMISES_REUSED_ISSUE = "premises phải trích từ bài nói mới, hiện đang chép từ các lượt trước"
PREMISES_REUSED_RATIO = 0.7


def is_v4_plus(version: str) -> bool:
    """v4 / v5: co v3 (natural + no echo) + ganh nang (khi co burden)."""
    return version in (FULL_V4, FULL_V4_NOBURDEN) or is_v5(version)


def uses_burden(version: str) -> bool:
    return version in (FULL_V4, FULL_V5, FULL_V6, FULL_V7, FULL_V7_NODIFFICULTY)


def retry_range(target_words: int) -> tuple[int, int]:
    """v5: ngoai khoang nay MOI thu lai vi do dai."""
    return round(RETRY_MIN_RATIO * target_words), round(RETRY_MAX_RATIO * target_words)


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


class TurnOutputV7(TurnOutput):
    """Lop rieng de v1..v6 van coi points_addressed la truong la (sua key / bao loi khong doi)."""

    points_addressed: list[str]


FIELD_ORDER_V7 = ("premises", "target_premise", "points_addressed", "ai_points", "speech_text")


def needs_target(mode: TurnMode) -> bool:
    """Chi opening_reply / rebuttal chon tien de de tan cong; opening_first va closing: target_premise = null."""
    return mode in (TurnMode.OPENING_REPLY, TurnMode.REBUTTAL)


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


def build_response_schema(mode: TurnMode, has_new_speech: bool = True, version: str = FULL_V1) -> dict:
    """
    JSON schema strict (Groq), viet tay de GIU THU TU truong (model sinh theo thu tu properties). Theo mode:
    target_premise la string (opening_reply / rebuttal) hoac null. Khong co bai learner moi -> learner_claims /
    premises rong; closing -> premises rong (maxItems 0: bot token sinh phan tich thua, muc 2.11).
    v5 (muc 2.18): KHONG co learner_claims. v7 bat do kho (muc 3.2): them points_addressed sau target_premise.
    """
    if is_v7_difficulty(version):
        schema = build_response_schema(mode, has_new_speech, FULL_V6)
        strings = {"type": "array", "items": {"type": "string"}}
        points = strings if analyzes_premises(mode, has_new_speech) else {**strings, "maxItems": 0}
        properties = {**schema["properties"], "points_addressed": points}
        schema["properties"] = {k: properties[k] for k in FIELD_ORDER_V7}
        schema["required"] = list(FIELD_ORDER_V7)
        return schema
    if is_v5(version):
        schema = build_response_schema(mode, has_new_speech)
        del schema["properties"]["learner_claims"]
        schema["required"] = list(FIELD_ORDER_V5)
        return schema
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
            "target_premise": {"type": "string"} if needs_target(mode) else {"type": "null"},
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


# turn_full_v7 (muc 3.2) — nguyen van spec
DIFFICULTY_LABEL = {
    OpponentDifficulty.EASY: "DỄ",
    OpponentDifficulty.MEDIUM: "TRUNG BÌNH",
    OpponentDifficulty.HARD: "KHÓ",
}
V7_DIFFICULTY_LINE = (
    "Độ khó của trận: {label}. Độ khó chỉ quyết định cách bạn chọn điểm tấn công và mức độ bạn đáp lại; nó KHÔNG làm "
    "thay đổi lập trường: bạn vẫn bảo vệ phe của mình đến hết trận ở mọi độ khó."
)
V7_TARGET_BLOCK = {
    OpponentDifficulty.EASY: (
        "target_premise: một tiền đề TƯỜNG MINH trong bài của đội {learner}. Chỉ phản bác ĐÚNG MỘT ý chính, không cần "
        "đáp các ý còn lại. Dùng câu ngắn, từ ngữ đơn giản, một ví dụ dễ hình dung. Có thể ghi nhận ngắn một ý đúng của "
        "đối phương rồi nêu rõ vì sao phe bạn vẫn đúng."
    ),
    OpponentDifficulty.MEDIUM: (
        "target_premise: một tiền đề TƯỜNG MINH vừa nền tảng (gần gốc lập luận) vừa được chứng minh chưa đầy đủ. Phản "
        "bác ý chính đó và, nếu còn chỗ, thêm một ý liên quan. Lập luận chặt chẽ ở mức khá, có cơ chế rõ ràng."
    ),
    OpponentDifficulty.HARD: (
        "target_premise: có thể là tiền đề NGẦM; chọn tiền đề nền tảng mà nếu sai thì lập luận của đối phương đổ theo. "
        "Đáp ÍT NHẤT hai ý chính của đội {learner} và chỉ ra ít nhất một ý họ chưa chứng minh hoặc bỏ ngỏ. Chủ động chặn "
        "trước phản biện sắp tới của họ bằng mục 'Những phản biện bạn đã dự đoán'. So sánh mức độ tác động của hai bên "
        "(quy mô, ai bị ảnh hưởng, thời gian)."
    ),
}
V7_OPENING_FIRST_EXTRA = {
    OpponentDifficulty.EASY: "Giọng đơn giản, câu ngắn, mỗi luận điểm một ví dụ dễ hình dung.",
    OpponentDifficulty.MEDIUM: None,
    OpponentDifficulty.HARD: (
        "Chặn trước một đến hai phản biện phổ biến dựa trên mục 'Những phản biện bạn đã dự đoán', và kết bằng một câu so "
        "sánh mức độ tác động."
    ),
}
V7_CLOSING_POINTS = {
    OpponentDifficulty.EASY: "Nêu 2 điểm tranh chấp chính.",
    OpponentDifficulty.MEDIUM: "Nêu 2 đến 3 điểm tranh chấp chính.",
    OpponentDifficulty.HARD: (
        "Nêu 3 điểm tranh chấp chính; với mỗi điểm so sánh quy mô, xác suất và thời gian tác động; đáp lại điểm mạnh nhất "
        "của đội {learner} và chỉ ra điều họ chưa chứng minh được."
    ),
}
# Phan con lai cua MODE_TASK[CLOSING]. KHO: khoi tren da gom so sanh + dap lai nen khong lap lai.
V7_CLOSING_COMPARE = "Với mỗi điểm so sánh vì sao phe bạn thắng; đáp lại điểm mạnh nhất của đội {learner}."
V7_CLOSING_TAIL = "KHÔNG đưa lập luận mới, KHÔNG liệt kê lại toàn bộ luận điểm."
V7_ANTICIPATED_TITLE = "Những phản biện bạn đã dự đoán từ phía đội {learner} (đã chuẩn bị sẵn cách đáp):"
V7_ANTICIPATED_MODES = (TurnMode.OPENING_FIRST, TurnMode.OPENING_REPLY, TurnMode.REBUTTAL)
V7_POINTS_RULE = (
    "points_addressed chỉ lấy từ premises.explicit của (các) bài nói MỚI, đúng nguyên văn mục đã trích; rỗng nếu không "
    "có bài mới."
)
V7_NO_ATTACK_AGAIN = "Không tấn công lại tiền đề đã tấn công, trừ khi người học chưa đáp lại nó."


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items)


def v7_task(mode: TurnMode, difficulty: OpponentDifficulty, learner: str) -> str:
    """Khoi nhiem vu v7 (truoc mo ta JSON): chi dan theo mode + dong do kho chung + khoi theo cap."""
    level = OpponentDifficulty(difficulty)
    if mode == TurnMode.CLOSING:
        points = V7_CLOSING_POINTS[level].format(learner=learner)
        compare = "" if level == OpponentDifficulty.HARD else " " + V7_CLOSING_COMPARE.format(learner=learner)
        head = f"Tổng kết trận. {points}{compare} {V7_CLOSING_TAIL}"
    else:
        head = MODE_TASK[mode].format(learner=learner)
    if mode == TurnMode.OPENING_FIRST and V7_OPENING_FIRST_EXTRA[level]:
        head += " " + V7_OPENING_FIRST_EXTRA[level]
    task = f"Nhiệm vụ lượt này: {head}\n{V7_DIFFICULTY_LINE.format(label=DIFFICULTY_LABEL[level])}"
    if needs_target(mode):
        task += f"\n{V7_TARGET_BLOCK[level].format(learner=learner)}\n{V7_NO_ATTACK_AGAIN}"
    return task


def anticipated_section(case: dict, learner: str) -> str | None:
    """Muc 'phan bien da du doan' (v7, chi hard + V7_ANTICIPATED_MODES). Case file cu khong co -> None."""
    items = [a for a in case.get("anticipated_opponent_arguments", []) if isinstance(a, dict)]
    if not items:
        return None
    lines = [f"- {a.get('learner_claim', '')} Cách đáp: {a.get('planned_response', '')}" for a in items]
    return V7_ANTICIPATED_TITLE.format(learner=learner) + "\n" + "\n".join(lines)


def new_learner_speeches(context: TurnContext):
    """Bai learner KE TU luot AI gan nhat (moi luot AI truoc do da 'doc' cac bai cu -> nam trong ledger)."""
    ai_turns = [s.turn_index for s in context.history if s.speaker == Speaker.AI]
    last_ai = max(ai_turns, default=0)
    return [s for s in sorted(context.history, key=lambda s: s.turn_index)
            if s.speaker == Speaker.LEARNER and s.turn_index > last_ai]


def burden_sentence(context: TurnContext) -> str:
    """turn_full_v4 (muc 2.17): cau ganh nang cua phe AI — dua vao system prompt VA nhac lai trong khoi rang buoc."""
    return f"BẠN là phe {SIDE_LABEL[context.ai_side]}. Mọi điều bạn nói phải chứng minh: {context.ai_burden}"


def constraints_block(context: TurnContext, version: str = FULL_V1) -> str:
    ai, learner = SIDE_LABEL[context.ai_side], SIDE_LABEL[context.learner_side]
    lo, hi = word_range(context.target_words)
    v4 = is_v4_plus(version)
    natural = "\n" + NATURAL_SPEECH_RULE if version in (FULL_V2, FULL_V3) or v4 else ""
    if version == FULL_V3 or v4:
        natural += "\n" + NO_RULE_ECHO_RULE
    if is_v5(version):
        natural += "\n" + "\n".join(V5_RULES)
    burden_line = f"\n- {burden_sentence(context)}" if uses_burden(version) and context.ai_burden else ""
    reading_ref = "cách hiểu ở trên" if is_v6(version) else "cách hiểu cố định ở trên"  # v6: bo "cố định" (muc 2.19)
    return f"""Ràng buộc bắt buộc:
- Bạn thuộc phe {ai} và phải bảo vệ phe này đến hết trận.{burden_line}
- KHÔNG thu hẹp, mở rộng hay định nghĩa lại kiến nghị so với {reading_ref}.
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
    system, before, new, after, constraints = _prompt_sections(mode, context, feedback, version)
    learner = SIDE_LABEL[context.learner_side]
    speeches = [f"Đội {learner} vừa phát biểu ({ROUND_LABEL[s.round_type]}):\n«{s.text}»" for s in new] or [NO_NEW_SPEECH]
    return system, "\n\n".join(before + speeches + after + [constraints])


def build_variant_prompt(
    mode: TurnMode, context: TurnContext, feedback: str | None = None, version: str = FULL_V1, *,
    second_person: bool = False, final_constraints: bool = True,
) -> tuple[str, list[dict]]:
    """
    CHI cho thi nghiem do do vung lap truong (Giai doan 3d) — san pham KHONG dung. Tra (system, messages), noi dung GIONG
    build_full_prompt, chi khac:
    - second_person (nhanh C): moi bai learner MOI la 1 tin role=user rieng, NGUYEN VAN (bo nhan "Đội X vừa phát biểu
      («…»)"); messages = [user: case + ledger] + [user: bai learner]... + [user: nhiem vu (+ phan hoi) (+ rang buoc)].
    - final_constraints=False (nhanh E): KHONG dat khoi rang buoc o cuoi tin user; khoi rang buoc (nguyen van) chuyen len
      CUOI system prompt (v6 khong co rang buoc o system -> neu bo han thi nhanh E mat luon rang buoc, xem dev log 3.1).
    """
    system, before, new, after, constraints = _prompt_sections(mode, context, feedback, version)
    tail = [constraints] if final_constraints else []
    if not final_constraints:
        system += "\n\n" + constraints
    if second_person and new:
        messages = [{"role": "user", "content": "\n\n".join(before)}]
        messages += [{"role": "user", "content": s.text} for s in new]
        messages.append({"role": "user", "content": "\n\n".join(after + tail)})
        return system, messages
    learner = SIDE_LABEL[context.learner_side]
    speeches = [f"Đội {learner} vừa phát biểu ({ROUND_LABEL[s.round_type]}):\n«{s.text}»" for s in new] or [NO_NEW_SPEECH]
    return system, [{"role": "user", "content": "\n\n".join(before + speeches + after + tail)}]


def _prompt_sections(
    mode: TurnMode, context: TurnContext, feedback: str | None, version: str
) -> tuple[str, list[str], list, list[str], str]:
    """(system, [case + ledger], [bai learner MOI], [nhiem vu (+ phan hoi)], khoi rang buoc)."""
    case = context.case_file or {}
    ai, learner = SIDE_LABEL[context.ai_side], SIDE_LABEL[context.learner_side]
    # v5 (muc 2.18): bo chu "CỐ ĐỊNH" (tran 18:03 luot 1: "Đề xuất cố định yêu cầu…")
    reading_line = (
        f"Cách hiểu kiến nghị trong trận này: '{case.get('motion_reading', '')}'." if is_v5(version)
        else f"Cách hiểu kiến nghị của trận này là CỐ ĐỊNH: '{case.get('motion_reading', '')}'."
    )
    system = (
        f"Bạn là một debater đang thi đấu, thuộc phe {ai} về kiến nghị: '{context.motion}'.\n"
        f"{reading_line}\n"
        f"Người học thuộc phe {learner}. Phe của bạn không bao giờ thay đổi."
    )
    if uses_burden(version) and context.ai_burden:
        system += "\n" + burden_sentence(context)

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
    learner_items = ledger.learner_premises if is_v5(version) else ledger.learner_claims  # v5: tu premises.explicit
    if learner_items:
        # v6: tieu de KHONG trung ten truong output ("tien de" / premises) — v5 bi model chep lai (muc 2.19)
        title = V6_LEDGER_TITLE if is_v6(version) else "Các luận điểm người học đã nêu trước đó:"
        parts.append(title + "\n" + _bullets(learner_items))
    if ledger.attacked_premises:
        parts.append("Các tiền đề bạn đã tấn công:\n" + _bullets(ledger.attacked_premises))
    new = new_learner_speeches(context)

    v7 = is_v7_difficulty(version)
    task = "Nhiệm vụ lượt này: " + MODE_TASK[mode].format(learner=learner)
    if v7:
        task = v7_task(mode, context.difficulty, learner)
    elif needs_target(mode):
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
        "tiền đề bạn chọn để tấn công (một câu, lấy từ premises)" if needs_target(mode)
        else "null (lượt này không chọn tiền đề để tấn công)"
    )
    points_line = ""
    if v7:
        points_line = (
            ("\n- points_addressed: danh sách các mục premises.explicit của bài MỚI mà bài nói thực sự đáp lại. "
             + V7_POINTS_RULE) if analyzes_premises(mode, bool(new))
            else "\n- points_addressed: để mảng rỗng (lượt này không phân tích tiền đề)."
        )
    if is_v6(version) and analyzes_premises(mode, bool(new)):
        task += "\n\n" + V6_EXTRACTION_RULE.format(learner=learner)  # dat NGAY TRUOC mo ta JSON (muc 2.19)
    task += (
        "\n\nTrả về JSON, ĐÚNG thứ tự trường sau (phân tích trước, lập dàn ý, rồi mới viết bài):"
        + ("" if is_v5(version) else f"\n- learner_claims: {claims_rule}.")
        + f"\n- premises: {{\"explicit\": [...], \"implicit\": [...]}} — {premises_rule}."
        f"\n- target_premise: {target_rule}."
        + points_line
        + "\n- ai_points: dàn ý 2–4 ý bạn sẽ nói trong lượt này, mỗi ý một câu."
        "\n- speech_text: bài nói hoàn chỉnh, viết theo dàn ý ai_points."
    )
    after = [task] + ([feedback.strip()] if feedback else [])
    if v7 and OpponentDifficulty(context.difficulty) == OpponentDifficulty.HARD and mode in V7_ANTICIPATED_MODES:
        anticipated = anticipated_section(case, learner)
        if anticipated:
            after.insert(0, anticipated)  # ngay truoc khoi nhiem vu
    return system, parts, new, after, constraints_block(context, version)


# ---------------- validator ----------------


class _Invalid(Exception):
    def __init__(self, kind: str, error: str, issues: list[str], speech: str | None = None, data: object = None):
        """data: output da parse (neu co) — v7 log target_premise / points_addressed ca lan thu bi loai."""
        super().__init__(error)
        self.kind, self.error, self.issues, self.speech, self.data = kind, error, issues, speech, data


def _output_model(version: str) -> type[TurnOutput]:
    return TurnOutputV7 if is_v7_difficulty(version) else TurnOutput


def _key_diffs(data: dict, version: str = FULL_V1) -> list[dict]:
    diffs = []
    for prefix, model in (("", _output_model(version)), ("premises.", Premises)):
        obj = data if not prefix else data.get("premises")
        if not isinstance(obj, dict):
            continue
        missing = [k for k in model.model_fields if k not in obj]
        unknown = [k for k in obj if k not in model.model_fields]
        if missing or unknown:
            diffs.append({"prefix": prefix, "obj": obj, "missing": missing, "unknown": unknown,
                          "renames": _match_renames(missing, unknown)})
    return diffs


def _key_issues(data: dict, version: str = FULL_V1) -> list[str]:
    issues = []
    for d in _key_diffs(data, version):
        p = d["prefix"]
        issues += [f"`{p}{w}`: bạn đã viết '{w}', tên đúng là '{r}'" for w, r in d["renames"].items()]
        issues += [f"`{p}{k}`: trường lạ — bỏ đi" for k in d["unknown"] if k not in d["renames"]]
        issues += [f"`{p}{k}`: thiếu trường bắt buộc" for k in d["missing"] if k not in d["renames"].values()]
    return issues


def repair_keys(data: dict, version: str = FULL_V1) -> list[dict]:
    """Doi ten key go sai (<= 3 ky tu) TRUC TIEP tren data. Tra danh sach doi ten."""
    renames = []
    for d in _key_diffs(data, version):
        for wrong, right in d["renames"].items():
            d["obj"][right] = d["obj"].pop(wrong)
            renames.append({"path": d["prefix"] + right, "from": wrong, "to": right})
    return renames


def _validation_issues(e: ValidationError, data: object, version: str = FULL_V1) -> list[str]:
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
    return issues + (_key_issues(data, version) if isinstance(data, dict) else [])


def _without_claims(data: object, version: str) -> object:
    """v5: model KHONG sinh learner_claims -> dien [] (va bo neu model van tra) truoc khi dung chung TurnOutput."""
    if is_v5(version) and isinstance(data, dict):
        return {**data, "learner_claims": []}
    return data


def validate_turn_data(data: object, mode: TurnMode, target_words: int, version: str = FULL_V1) -> TurnOutput:
    """Nem _Invalid (kem phan hoi tieng Viet) neu khong hop le."""
    data = _without_claims(data, version)
    try:
        out = _output_model(version).model_validate(data)
    except ValidationError as e:
        speech = data.get("speech_text") if isinstance(data, dict) and isinstance(data.get("speech_text"), str) else None
        raise _Invalid(TurnFailure.SCHEMA_VALIDATION, str(e)[:4000], _validation_issues(e, data, version), speech, data) from e
    if mode == TurnMode.OPENING_FIRST:  # chua co bai learner: bo moi phan tich (schema Groq da ep rong)
        out.learner_claims, out.premises = [], Premises(explicit=[], implicit=[])
    if not needs_target(mode):
        out.target_premise = None
    elif not (out.target_premise or "").strip():
        raise _Invalid(
            TurnFailure.SCHEMA_VALIDATION, "target_premise rong o luot can tan cong",
            ["`target_premise`: lượt này phải chọn đúng một tiền đề để tấn công (không được null / rỗng)."],
            out.speech_text, data,
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
            issues, out.speech_text, data,
        )
    return out


def parse_turn_output(raw: str | None, mode: TurnMode, target_words: int, version: str = FULL_V1) -> TurnOutput:
    try:
        data = extract_json(raw or "")
    except LLMOutputParseError as e:
        raise _Invalid(
            TurnFailure.INVALID_JSON, str(e),
            ["Output không phải một JSON object hợp lệ (có thể bị cắt ngắn, hoặc có text / markdown thừa ngoài JSON)."],
        ) from e
    return validate_turn_data(data, mode, target_words, version)


def _repair_rejected(call, mode: TurnMode, target_words: int, version: str = FULL_V1) -> TurnOutput:
    """
    Groq tu choi schema -> sua TAT DINH roi validate CUC BO (khong goi lai LLM). Khong duoc -> _Invalid schema_rejected.
    1. "Mang tach" (json_repair, muc 2.12): dung lai object; khong qua schema cuc bo -> xu ly nhu schema_rejected; qua
       schema nhung sai noi dung (bang chung HIGH) -> retry nhu thuong.
    2. Ten truong go sai <= 3 ky tu (muc 2.4j).
    """
    m = _JSONSCHEMA_DETAIL.search(call.error or "")
    issues = [
        f"Output bị nhà cung cấp từ chối vì không khớp JSON schema{f' ({m.group(1)})' if m else ''}. Kiểm tra lại "
        f"đúng {4 if is_v5(version) and not is_v7_difficulty(version) else 5} trường theo thứ tự, đúng kiểu, không thêm trường lạ. Trả về MỘT object "
        "JSON (không phải mảng)."
    ]
    known_keys = FIELD_ORDER_V7 if is_v7_difficulty(version) else FIELD_ORDER_V5 if is_v5(version) else FIELD_ORDER
    repaired = repair_split_array(call.raw_output, known_keys)
    if repaired is not None:
        data, info = repaired
        data = _without_claims(data, version)
        renames = repair_keys(data, version)
        if _key_diffs(data, version):
            raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues + _key_issues(data, version), data=data)
        try:
            out = validate_turn_data(data, mode, target_words, version)
        except _Invalid as e:
            if e.kind == TurnFailure.SCHEMA_VALIDATION:
                raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues + e.issues, e.speech, e.data) from None
            raise
        call.key_repairs = {**info, "renames": renames, "provider_error": (call.error or "")[:1000]}
        return out
    try:
        data = extract_json(call.raw_output or "")
    except LLMOutputParseError:
        raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues) from None
    if not isinstance(data, dict):
        raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues)
    data = _without_claims(data, version)
    renames = repair_keys(data, version)
    if not renames or _key_diffs(data, version):
        raise _Invalid(TurnFailure.SCHEMA_REJECTED, call.error or "", issues + _key_issues(data, version), data=data)
    out = validate_turn_data(data, mode, target_words, version)  # co the nem _Invalid khac (HIGH...) -> retry nhu thuong
    call.key_repairs = {"event": "key_repaired", "renames": renames, "provider_error": (call.error or "")[:1000]}
    return out


# ---------------- kiem tra chi log ----------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_DIGIT_OR_PERCENT = re.compile(r"\d|%")
# Dai tu "em" (AI tu xung hoac goi learner). Chap nhan bat nham (vd "trẻ em", "anh em").
_EM_PRONOUN = re.compile(r"\bem\b", re.IGNORECASE)


# v6 (muc 2.19): so KHONG phai so lieu — bo qua khi kiem tra "so ngoai Giả sử" (tran 001136: "thế kỷ 21" bi log nham)
_NON_STAT_NUMBER = re.compile(
    r"\bthế\s+kỷ\s+(?:\d+|[ivxlc]+)\b|\b(?:thứ|lớp|khối|số|phần|lượt|năm\s+thứ)\s+\d+\b", re.IGNORECASE
)


def speech_checks(text: str, ignore_non_stat_numbers: bool = False) -> dict:
    sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    nfc = [unicodedata.normalize("NFC", s) for s in sentences]

    def has_number(s: str) -> bool:
        return bool(_DIGIT_OR_PERCENT.search(_NON_STAT_NUMBER.sub(" ", s) if ignore_non_stat_numbers else s))

    return {
        "numbers_without_gia_su": [s for s in nfc if has_number(s) and "giả sử" not in s.casefold()],
        "em_pronoun": [s for s in nfc if _EM_PRONOUN.search(s)],
    }


# --- v5 (muc 2.18): them kiem tra CHI LOG ---
_TOI_PRONOUN = re.compile(r"\btôi\b", re.IGNORECASE)  # AI phai xung "mình" (tran 17:35 luot 4: "Tôi đồng ý…")
_WORD = re.compile(r"[^\W\d_]+")
_ASCII_WORD = re.compile(r"[A-Za-z]+")
ENGLISH_RATIO = 0.5  # ai_point co >= 50% tu la tu ASCII (khong dau) -> nghi la tieng Anh
ENGLISH_MIN_WORDS = 3


def english_ratio(text: str) -> float:
    words = _WORD.findall(text)
    if not words:
        return 0.0
    return sum(1 for w in words if _ASCII_WORD.fullmatch(w)) / len(words)


def _sentence_key(sentence: str) -> str:
    return " ".join(_WORD.findall(unicodedata.normalize("NFC", sentence).casefold()))


def speech_checks_v5(text: str, ai_points: list[str], ignore_non_stat_numbers: bool = False) -> dict:
    """speech_checks + "toi_pronoun" (cau co "tôi"), "ai_points_english" (y dan y nghi tieng Anh), "repeated_sentences"
    (cau xuat hien >= 2 lan, so sanh bo dau / hoa thuong). CHI LOG, khong reject."""
    checks = speech_checks(text, ignore_non_stat_numbers)
    sentences = [unicodedata.normalize("NFC", s) for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    seen: dict[str, int] = {}
    for s in sentences:
        key = _sentence_key(s)
        if key:
            seen[key] = seen.get(key, 0) + 1
    repeated, listed = [], set()
    for s in sentences:
        key = _sentence_key(s)
        if seen.get(key, 0) >= 2 and key not in listed:
            repeated.append(s)
            listed.add(key)
    checks.update(
        toi_pronoun=[s for s in sentences if _TOI_PRONOUN.search(s)],
        ai_points_english=[p for p in ai_points
                           if len(_WORD.findall(p)) >= ENGLISH_MIN_WORDS and english_ratio(p) >= ENGLISH_RATIO],
        repeated_sentences=repeated,
    )
    return checks


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
    if isinstance(out, TurnOutputV7) and not analyzes_premises(mode, has_new_speech) and out.points_addressed:
        dropped["points_addressed"] = len(out.points_addressed)
        out.points_addressed = []
    if not needs_target(mode):
        out.target_premise = None  # validate_turn_data da ep; giu o day cho ro
    return dropped


def _log_speech(call, speech: str | None, version: str = FULL_V1, ai_points: list[str] | None = None) -> None:
    if speech:
        call.vague_evidence = [h.to_log() for h in vague_detector.detect_speech(speech)]
        call.speech_checks = (
            speech_checks_v5(speech, ai_points or [], ignore_non_stat_numbers=is_v6(version)) if is_v5(version)
            else speech_checks(speech)
        )


# ---------------- v6: chep tien de + chuan hoa xung ho ----------------


def _norm_item(text: str) -> str:
    return " ".join(_WORD.findall(unicodedata.normalize("NFC", text).casefold()))


def premises_reuse_ratio(explicit: list[str], previous: list[str]) -> float:
    """Ti le muc premises.explicit TRUNG (sau chuan hoa: NFC, hoa thuong, bo dau cau) voi y nguoi hoc o ledger."""
    if not explicit or not previous:
        return 0.0
    seen = {_norm_item(p) for p in previous}
    return sum(1 for e in explicit if _norm_item(e) in seen) / len(explicit)


# "tôi" la dai tu ngoi 1 -> "mình". KHONG thay: trong ngoac kep / « » (trich dan), tu ghep "tôi luyện", "tôi tớ".
_QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”")
_TOI = re.compile(r"\b([Tt])ôi\b(?!\s+(?:luyện|tớ)\b)")


def normalize_first_person(text: str) -> tuple[str, int]:
    """Thay "Tôi"/"tôi" (dai tu) -> "Mình"/"mình" ngoai trich dan. Tra (van ban moi, so lan thay)."""
    text = unicodedata.normalize("NFC", text)
    count = 0

    def fix(segment: str) -> str:
        nonlocal count

        def sub(m: re.Match) -> str:
            nonlocal count
            count += 1
            return "Mình" if m.group(1) == "T" else "mình"

        return _TOI.sub(sub, segment)

    out, last = [], 0
    for q in _QUOTED.finditer(text):
        out.append(fix(text[last:q.start()]))
        out.append(q.group(0))  # trich dan: giu nguyen
        last = q.end()
    out.append(fix(text[last:]))
    return "".join(out), count


# ---------------- v7: target_premise + points_addressed ----------------

PREMISE_MATCH_RATIO = 0.85
_TOKEN = re.compile(r"[^\W_]+")  # giu chu so ("lớp 10" khac "lớp 12"), khac _WORD
TARGET_NOT_IN_PREMISES_ISSUE = (
    "`target_premise` phải là một mục đã có trong `premises.explicit` hoặc `premises.implicit` — chép đúng mục đó, không "
    "viết một tiền đề khác."
)
TARGET_EXPLICIT_ONLY_ISSUE = (
    "`target_premise` phải là một mục trong `premises.explicit` — chép đúng mục đó, không viết một tiền đề khác."
)
TARGET_LEVEL_MISMATCH_ISSUE = (
    "`target_premise` đang là một tiền đề ngầm (`premises.implicit`); ở độ khó này phải chọn một mục trong "
    "`premises.explicit`."
)
POINTS_MIN_SHARED_WORDS = 2
# Tu chuc nang pho bien (moi am tiet la 1 tu) — chi dung cho kiem tra CHI LOG points_unsupported.
VI_STOPWORDS = frozenset("""
    và là của có không các những một để trong cho với được khi thì mà này đó ở về từ như nên vì hay hoặc nhưng đã đang sẽ
    bị rằng do tại trên dưới ra vào lên xuống rất cũng còn lại đều chỉ nếu tuy dù bởi nào gì ai mọi mỗi cả sau trước
    bạn mình họ em tôi ta chúng người đội phe việc điều cái sự ý
""".split())
# So muc points_addressed (da khop) mong doi — CHI LOG. medium: khong co ky vong.
_POINTS_EXPECTED = {OpponentDifficulty.EASY: lambda n: n == 1, OpponentDifficulty.HARD: lambda n: n >= 2}


def _norm_premise(text: str) -> str:
    return " ".join(_TOKEN.findall(unicodedata.normalize("NFC", text).casefold()))


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def premise_kind(target: str, premises: Premises) -> str | None:
    """'explicit' / 'implicit' (muc giong nhat, hoa -> explicit) hoac None neu khong muc nao dat PREMISE_MATCH_RATIO."""
    norm = _norm_premise(target)
    explicit = max((_ratio(norm, _norm_premise(p)) for p in premises.explicit), default=0.0)
    implicit = max((_ratio(norm, _norm_premise(p)) for p in premises.implicit), default=0.0)
    if max(explicit, implicit) < PREMISE_MATCH_RATIO:
        return None
    return "explicit" if explicit >= implicit else "implicit"


def target_issue(out: TurnOutputV7, difficulty: OpponentDifficulty) -> tuple[str, str] | None:
    """(failure_kind, phan hoi) neu target_premise khong khop premises hoac sai cap; None = hop le."""
    level = OpponentDifficulty(difficulty)
    kind = premise_kind(out.target_premise or "", out.premises)
    if kind is None:
        issue = TARGET_NOT_IN_PREMISES_ISSUE if level == OpponentDifficulty.HARD else TARGET_EXPLICIT_ONLY_ISSUE
        return TurnFailure.TARGET_NOT_IN_PREMISES, issue
    if kind == "implicit" and level != OpponentDifficulty.HARD:
        return TurnFailure.TARGET_LEVEL_MISMATCH, TARGET_LEVEL_MISMATCH_ISSUE
    return None


def points_checks(points: list[str], explicit: list[str], difficulty: OpponentDifficulty) -> dict:
    """CHI LOG: so muc premises.explicit (moi muc tinh 1 lan) co trong points_addressed; co lech ky vong theo cap khong."""
    norm = [_norm_premise(p) for p in points]
    count = sum(1 for e in explicit if any(_ratio(_norm_premise(e), p) >= PREMISE_MATCH_RATIO for p in norm))
    expected = _POINTS_EXPECTED.get(OpponentDifficulty(difficulty))
    return {"points_addressed_count": count, "points_below_expected": expected is not None and not expected(count)}


def points_unsupported(points: list[str], speech: str) -> list[str]:
    """
    CHI LOG: cac muc points_addressed co < POINTS_MIN_SHARED_WORDS tu noi dung (khac nhau, bo stopword) trong bai noi.
    Kiem tra YEU: moi am tiet la 1 tu, nen "điện thoại" (chu de kien nghi) da du 2 tu — chi bat muc khong lien quan han.
    """
    spoken = set(_norm_premise(speech).split())
    return [p for p in points if len((set(_norm_premise(p).split()) - VI_STOPWORDS) & spoken) < POINTS_MIN_SHARED_WORDS]


def _strings(value: object) -> list[str]:
    return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def attempt_checks(data: object, difficulty: OpponentDifficulty) -> dict:
    """
    CHI LOG, MOI lan thu co output parse duoc (ke ca lan bi loai) — bao cao "lan thu dau" (muc 3.2) khong can parse lai
    raw_output (dang mang tach khong doc thang duoc). Doc than trong: output sai schema van lay duoc phan con dung.
    """
    if not isinstance(data, dict):
        return {}
    raw = data.get("premises")
    raw = raw if isinstance(raw, dict) else {}
    premises = Premises(explicit=_strings(raw.get("explicit")), implicit=_strings(raw.get("implicit")))
    target = data.get("target_premise") if isinstance(data.get("target_premise"), str) else None
    points = _strings(data.get("points_addressed"))
    speech = data.get("speech_text") if isinstance(data.get("speech_text"), str) else ""
    kind = premise_kind(target or "", premises)
    return {
        "target_premise": target,
        "points_addressed": points,
        "target_kind": kind,
        "target_level_ok": kind == "explicit" or (kind == "implicit" and OpponentDifficulty(difficulty) == OpponentDifficulty.HARD),
        "points_unsupported": points_unsupported(points, speech),
        **points_checks(points, premises.explicit, difficulty),
    }


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

    def __init__(
        self, client: LLMClient, settings: Settings, reviewer_client: LLMClient | None = None, *,
        second_person: bool = False, final_constraints: bool = True,
    ):
        """second_person / final_constraints: CHI harness Giai doan 3d truyen (nhanh C / E, build_variant_prompt); san
        pham dung mac dinh = build_full_prompt."""
        self.second_person, self.final_constraints = second_person, final_constraints
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
        schema = build_response_schema(mode, has_new, self.version) if settings.case_plan_use_json_schema else None
        feedback = None
        length_retries = 0
        # v7 (muc 3.2). Khong co bai moi -> khong co premises de doi chieu (format 6 luot khong gap, luon co bai moi).
        log_attempt = is_v7_difficulty(self.version) and needs_target(mode) and has_new
        candidates: list[tuple[int, int, TurnOutput, object]] = []  # (khoang cach, thu tu, output, call) — sai do dai
        for attempt_no in range(1, settings.turn_max_attempts + 1):
            last = attempt_no == settings.turn_max_attempts
            messages = None
            if self.second_person or not self.final_constraints:
                system, messages = build_variant_prompt(
                    mode, context, feedback, self.version,
                    second_person=self.second_person, final_constraints=self.final_constraints,
                )
                user = None
            else:
                system, user = build_full_prompt(mode, context, feedback, self.version)
            try:
                call = await self.caller.complete(
                    system, user, temperature=self.temperature, max_tokens=settings.turn_max_tokens,
                    prompt_version=self.version, json_schema=schema, messages=messages,
                )
            except TurnLLMError as e:
                result.error, result.failure_kind = str(e), TurnFailure.PROVIDER_ERROR
                return result
            try:
                if call.truncated:
                    raise _Invalid(TurnFailure.TRUNCATED, call.error or TurnFailure.TRUNCATED, [TRUNCATED_ISSUE])
                if call.schema_rejected:
                    out = _repair_rejected(call, mode, context.target_words, self.version)
                    call.success, call.error, call.failure_kind = True, None, None
                    logger.info("Luot %d: %s, khong goi lai LLM: %s", context.turn_index,
                                call.key_repairs.get("event"), call.key_repairs)
                else:
                    out = parse_turn_output(call.raw_output, mode, context.target_words, self.version)
            except _Invalid as e:
                call.success, call.error, call.failure_kind = False, e.error[:4000], e.kind
                _log_speech(call, e.speech, self.version)
                if log_attempt:
                    call.speech_checks = {**(call.speech_checks or {}), "content_attempt": attempt_no,
                                          **attempt_checks(e.data, context.difficulty)}
                logger.warning("Luot %d lan thu %d khong hop le (%s): %s", context.turn_index, attempt_no, e.kind, e.error)
                if last:
                    return self._give_up(result, candidates, context, e.error, e.kind)
                feedback = build_retry_feedback(e.issues)
                call.retry_feedback = feedback.strip()
                continue

            _log_speech(call, out.speech_text, self.version, out.ai_points)
            if log_attempt:  # TRUOC moi kiem tra co the loai lan thu nay
                call.speech_checks = {**(call.speech_checks or {}), "content_attempt": attempt_no,
                                      **attempt_checks(out.model_dump(), context.difficulty)}
            if is_v6(self.version) and analyzes_premises(mode, has_new):
                # v6 (muc 2.19): premises phai trich tu bai MOI (chi luot co bai learner moi va phan tich tien de). >= 70% trung y o ledger -> reject, retry co phan hoi.
                ratio = premises_reuse_ratio(out.premises.explicit, context.ledger.learner_premises)
                if ratio >= PREMISES_REUSED_RATIO:
                    call.success, call.failure_kind = False, TurnFailure.PREMISES_REUSED
                    call.error = f"{TurnFailure.PREMISES_REUSED}: {ratio:.0%} premises.explicit trung y cac luot truoc"
                    logger.warning("Luot %d lan thu %d: %s", context.turn_index, attempt_no, call.error)
                    if last:
                        return self._give_up(result, candidates, context, call.error, TurnFailure.PREMISES_REUSED)
                    feedback = build_retry_feedback([PREMISES_REUSED_ISSUE])
                    call.retry_feedback = feedback.strip()
                    continue
            if log_attempt:
                problem = target_issue(out, context.difficulty)
                if problem is not None:
                    kind, issue = problem
                    call.success, call.failure_kind = False, kind
                    call.error = f"{kind}: target_premise={out.target_premise!r}"[:4000]
                    logger.warning("Luot %d lan thu %d: %s", context.turn_index, attempt_no, call.error)
                    if last:
                        return self._give_up(result, candidates, context, call.error, kind)
                    feedback = build_retry_feedback([issue])
                    call.retry_feedback = feedback.strip()
                    continue
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
                if stance_reviewer.is_reviewer_failure(detail):
                    # FAIL-CLOSED (muc 2.14): reviewer khong tra duoc verdict -> KHONG chap nhan, retry trung tinh.
                    call.success, call.failure_kind = False, TurnFailure.REVIEWER_UNAVAILABLE
                    call.error = f"{TurnFailure.REVIEWER_UNAVAILABLE}: {detail['reviewer_error'][:500]}"
                    logger.warning("Luot %d lan thu %d: reviewer khong tra duoc verdict", context.turn_index, attempt_no)
                    if last:
                        return self._give_up(result, candidates, context, call.error, TurnFailure.REVIEWER_UNAVAILABLE)
                    feedback = None
                    call.reviewer_detail = {**detail, "retry": "reviewer_unavailable_neutral_retry"}
                    continue
                if verdict == ReviewerVerdict.UNCLEAR:
                    logger.warning("Luot %d: stance review khong ro: %s", context.turn_index, detail)

            n = word_count(out.speech_text)
            distance = length_distance(n, context.target_words)
            if distance == 0:
                call.success, call.error, call.failure_kind = True, None, None
                return self._accept(result, out, call)
            if is_v5(self.version):
                r_lo, r_hi = retry_range(context.target_words)
                if r_lo <= n <= r_hi:
                    # v5 (muc 2.18): lech nhung trong [0,5x; 1,5x] -> CHAP NHAN NGAY, KHONG goi lai LLM (tran 18:10 luot 6:
                    # 363 tu, retry vi do dai roi van dung ban cu)
                    return self._soft_accept(result, [(distance, attempt_no, out, call)], context)
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
                        return verdict, detail
                else:
                    error = call.error or ""
            if call_no < sr.MAX_CALLS:
                logger.warning("Stance review luot %d loi (lan goi %d), thu lai: %s", context.turn_index, call_no, error)
        verdict, detail = sr.reviewer_failure(error, TURN_REVIEW_VERSION)
        detail["reviewer_calls"] = sr.MAX_CALLS
        return verdict, detail

    def _give_up(self, result: TurnResult, candidates: list, context: TurnContext, error: str, kind: str) -> TurnResult:
        """Het luot thu. Con ban hop le chi sai do dai (da qua reviewer) -> chap nhan; khong -> that bai."""
        if candidates:
            return self._soft_accept(result, candidates, context)
        result.error, result.failure_kind = error, kind
        return result

    def _accept(self, result: TurnResult, out: TurnOutput, call=None) -> TurnResult:
        if is_v6(self.version):
            # v6 (muc 2.19): chuan hoa xung ho SAU khi chap nhan; ghi so lan thay
            out.speech_text, replaced = normalize_first_person(out.speech_text)
            if call is not None:
                call.speech_checks = {**(call.speech_checks or {}), "toi_replaced": replaced}
        result.text = out.speech_text
        result.learner_claims = None if is_v5(self.version) else out.learner_claims  # v5: cot DB de null
        result.premises = out.premises.model_dump()
        result.target_premise = out.target_premise
        result.points_addressed = out.points_addressed if isinstance(out, TurnOutputV7) else None
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
        return self._accept(result, out, call)


class FullTurnGeneratorV2(FullTurnGenerator):
    """v1 + rang buoc NATURAL_SPEECH_RULE trong khoi rang buoc (muc 2.10). Moi thu khac giong v1."""

    version = FULL_V2


class FullTurnGeneratorV3(FullTurnGenerator):
    """v2 + rang buoc NO_RULE_ECHO_RULE (muc 2.12). Moi thu khac giong v1 / v2."""

    version = FULL_V3


class FullTurnGeneratorV4(FullTurnGenerator):
    """
    v3 + ganh nang chung minh cua phe AI (muc 2.17): khi context.ai_burden co -> them "BẠN là phe {X}. Mọi điều bạn nói
    phải chứng minh: {burden}" vao system prompt VA khoi rang buoc (ngay sau dong "Bạn thuộc phe…"). Khong co burden
    (session cu / TURN_BURDEN_ENABLED=false) -> prompt = v3, version ghi "turn_full_v4_noburden" (phan biet khi ablation).
    """

    version = FULL_V4

    async def generate(self, mode: TurnMode, context: TurnContext) -> TurnResult:
        self.version = FULL_V4 if context.ai_burden else FULL_V4_NOBURDEN
        return await super().generate(mode, context)


class FullTurnGeneratorV5(FullTurnGenerator):
    """
    v4 + sua loi tu 4 tran thu 30/09 (muc 2.18):
    1. system: "Cách hiểu kiến nghị trong trận này: '…'." (bo chu "CỐ ĐỊNH"); rang buoc khong dinh nghia lai giu o cuoi;
    2. KHONG con learner_claims trong output (schema + prompt); ledger "luan diem nguoi hoc" tu premises.explicit;
       cot DB learner_claims = NULL;
    3. 3 rang buoc moi (V5_RULES): JSON tieng Viet ke ca ai_points; ai_points ngan, bai noi khong chep dan y; khong lap;
    4. CHI LOG: "tôi", ai_points tieng Anh, cau lap nguyen van (speech_checks_v5);
    5. do dai: CHI retry ngoai [0,5x; 1,5x]; trong do ma ngoai [0,7x; 1,25x] -> chap nhan ngay (length_soft_accept);
    6. ganh nang nhu v4; khong burden -> "turn_full_v5_noburden".
    """

    version = FULL_V5

    async def generate(self, mode: TurnMode, context: TurnContext) -> TurnResult:
        self.version = FULL_V5 if context.ai_burden else FULL_V5_NOBURDEN
        return await super().generate(mode, context)


class FullTurnGeneratorV6(FullTurnGenerator):
    """
    v5 + sua loi chep tien de (muc 2.19; tran 20261002 luot 4 chep nguyen premises.explicit cua luot 2):
    1. ledger y nguoi hoc: tieu de V6_LEDGER_TITLE (khong goi la "tien de", "dung chep lai");
    2. V6_EXTRACTION_RULE ngay truoc mo ta JSON (khi co bai learner moi va luot phan tich tien de);
    3. >= 70% premises.explicit trung ledger -> reject "premises_reused", retry co phan hoi (khong ap dung khi khong co
       bai moi);
    4. "tôi" -> "mình" sau khi chap nhan (ngoai trich dan), ghi speech_checks.toi_replaced;
    5. rang buoc cuoi: "…so với cách hiểu ở trên";
    6. kiem tra so ngoai "Giả sử" bo qua "thế kỷ 21/XXI", so thu tu (thứ 2, lớp 12…) — chi log.
    """

    version = FULL_V6

    async def generate(self, mode: TurnMode, context: TurnContext) -> TurnResult:
        self.version = FULL_V6 if context.ai_burden else FULL_V6_NOBURDEN
        return await super().generate(mode, context)


class FullTurnGeneratorV7(FullTurnGenerator):
    """
    v6 + 3 cap do doi thu (muc 3.2). Do kho CHI doi cach chon diem tan cong va muc dap lai — KHONG doi lap truong,
    temperature, reasoning_effort, do dai, max_tokens (test xac nhan). Case Planning khong doi.
    1. Khoi nhiem vu theo mode + cap (v7_task); dong do kho chung o moi mode;
    2. hard + opening_first / opening_reply / rebuttal: muc 'phan bien da du doan' truoc khoi nhiem vu;
    3. output them points_addressed (ep rong khi khong phan tich tien de), luu cot opponent_turns.points_addressed;
    4. opening_reply / rebuttal: target_premise phai khop premises (difflib >= 0.85) -> target_not_in_premises; de /
       trung binh chon implicit -> target_level_mismatch; retry co phan hoi, tinh vao TURN_MAX_ATTEMPTS;
    5. CHI LOG, MOI lan thu (ca lan bi loai) o opening_reply / rebuttal, trong speech_checks: content_attempt (lan thu noi
       dung 1, 2, 3; khac cot attempt vi cot do dem ca 429 va reviewer), target_premise, points_addressed, target_kind,
       target_level_ok, points_addressed_count, points_below_expected, points_unsupported.
    TURN_DIFFICULTY_ENABLED=false: prompt + schema + validator = v6, nhan turn_full_v7_nodifficulty[_noburden].
    """

    version = FULL_V7

    async def generate(self, mode: TurnMode, context: TurnContext) -> TurnResult:
        if self.settings.turn_difficulty_enabled:
            self.version = FULL_V7 if context.ai_burden else FULL_V7_NOBURDEN
        else:
            self.version = FULL_V7_NODIFFICULTY if context.ai_burden else FULL_V7_NODIFFICULTY_NOBURDEN
        return await super().generate(mode, context)
