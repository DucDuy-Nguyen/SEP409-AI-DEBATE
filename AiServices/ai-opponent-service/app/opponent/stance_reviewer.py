"""
Stance Reviewer — trong tai trung lap kiem tra "noi dung nay dang bao ve phe nao cua kien nghi".

Ly do (docs/AI_DEVELOPMENT_LOG.md muc 2.4e): da thay AI lat phe (phe Phan doi lap luan UNG HO kien
nghi) va prompt khong chan duoc hoan toan. Kiem tra bang 1 lan goi LLM RIENG, dong vai trong tai:
- KHONG cho reviewer biet phe mong doi -> khong bi dan dat "xac nhan" dieu minh duoc bao.
  build_review_prompt() co tinh KHONG co tham so phe.
- Trinh bay o ngoi thu ba ("Mot doi tranh luan dua ra...") thay vi "ban/doi thu" de reviewer
  khong nhap vai debater.
- LLM chi PHAN LOAI tung muc; KET LUAN (pass / side_flip / unclear) do code so voi phe mong doi (judge()).

Module thuan (khong goi LLM, khong dung DB): service lo viec goi LLM, log, budget. Phase 3 dung lai cho
tung luot noi: dua statements = cac y trong luot noi, summary = phan chot (neu co).
"""
import enum
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.llm.json_utils import extract_json
from app.opponent.models import DebateSide, ReviewerVerdict

PROMPT_VERSION = "stance_review_v1"  # v1 (MAC DINH, STANCE_REVIEW_PROMPT_VERSION — muc 2.4m): chi claim.
PROMPT_VERSION_V2 = "stance_review_v2"  # v2: claim + reasoning.
# v3: claim + reasoning, dien dat lai -> "manh hon / yeu di" (muc 2.4k, 2.4l). Bao sai 3/3 o batch v5 (muc 2.4m).
PROMPT_VERSION_V3 = "stance_review_v3"
TEMPERATURE = 0.0  # phan loai can on dinh — co dinh, khong cau hinh
# Reviewer loi (goi that bai / output sai) -> thu lai 1 lan (KHONG tinh vao so lan thu Case Planning);
# van loi -> unclear. Luu y: temperature 0 + cung prompt nen output SAI co the lap lai y het — lan thu lai
# chu yeu cuu loi tam thoi (mang, 5xx, Groq tu choi schema ngau nhien).
MAX_CALLS = 2
SUMMARY_ID = "weighing"


class Position(str, enum.Enum):
    UNG_HO = "ung_ho_kien_nghi"
    PHAN_DOI = "phan_doi_kien_nghi"
    KHONG_RO = "khong_ro"


EXPECTED_POSITION = {DebateSide.PRO: Position.UNG_HO, DebateSide.CON: Position.PHAN_DOI}


@dataclass(frozen=True)
class Statement:
    """
    1 muc can phan loai phe (Case Planning: claim cua 1 argument; Phase 3: 1 y trong luot noi).
    reasoning: chi prompt v2 / v3 dung (v1 bo qua) — de doc dung huong khi claim co phu dinh / mo ho.
    """

    id: str
    text: str
    reasoning: str | None = None


class StatementPosition(BaseModel):
    id: str
    position: Position
    reason: str = Field(..., min_length=1)


class SummaryPosition(BaseModel):
    position: Position
    reason: str = Field(..., min_length=1)


class StanceReviewOutput(BaseModel):
    """JSON reviewer (LLM) phai tra ve."""

    arguments: list[StatementPosition]
    weighing: SummaryPosition | None = None


SYSTEM_PROMPT = """Bạn là TRỌNG TÀI TRUNG LẬP của một cuộc thi tranh biện, KHÔNG phải người tranh biện. \
Bạn không đứng về phe nào và không đánh giá lập luận hay hay dở, đúng hay sai.

Nhiệm vụ duy nhất: với từng nội dung được đưa ra, xác định nội dung đó đang BẢO VỆ phía nào của kiến nghị:
- "ung_ho_kien_nghi": nội dung này, nếu được chấp nhận, làm cho kiến nghị đáng được thông qua hơn.
- "phan_doi_kien_nghi": nội dung này, nếu được chấp nhận, làm cho kiến nghị ít đáng được thông qua hơn.
- "khong_ro": không xác định được, hoặc nội dung trung lập / nói về cả hai phía như nhau.

Chú ý: đánh giá theo HƯỚNG TÁC ĐỘNG lên kiến nghị, không theo từ ngữ bề mặt. Ví dụ với kiến nghị \
"Nên cấm X", câu "X gây hại cho trẻ em" là ung_ho_kien_nghi dù có từ "hại"; câu "cấm X làm mất lợi \
ích Y" là phan_doi_kien_nghi dù có từ "cấm".

Lý do (reason) viết ngắn gọn bằng tiếng Việt, 1 câu. Chỉ trả về JSON hợp lệ."""


def build_review_prompt(
    motion: str, statements: list[Statement], summary: str | None = None
) -> tuple[str, str]:
    """KHONG co tham so phe — co y: reviewer khong duoc biet phe mong doi."""
    lines = "\n".join(f'- [{s.id}] "{s.text}"' for s in statements)
    user_prompt = f"""Một đội tranh luận đưa ra các luận điểm sau về kiến nghị '{motion}':
{lines}"""
    if summary is not None:
        user_prompt += f"""

Phần kết luận / cân nhắc tổng thể của đội đó:
"{summary}\""""
    ids = ", ".join(s.id for s in statements)
    user_prompt += f"""

Trả về JSON: "arguments" gồm đúng một mục cho mỗi id ({ids}), mỗi mục có "id", "position", "reason"\
{'; "weighing" gồm "position", "reason" cho phần kết luận' if summary is not None else ""}."""
    return SYSTEM_PROMPT, user_prompt


# ---------------------------------------------------------------------------
# v2: doc them reasoning. Ly do (docs/AI_DEVELOPMENT_LOG.md muc 2.4j): nhan tay phat hien reviewer v1 bao lat phe
# SAI o v4 M10 con medium: A3 "Giá tăng do thuế KHÔNG CHẮC CHẮN dẫn đến giảm đáng kể việc tiêu thụ..." bi doc thanh
# ung ho (bo sot phu dinh) -> case file dung phe bi reject, lan chay het luot. Reasoning cua A3 noi ro huong
# ("một số người vẫn sẽ mua ... không chỉ phụ thuộc vào giá cả").
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_V2 = """Bạn là TRỌNG TÀI TRUNG LẬP của một cuộc thi tranh biện, KHÔNG phải người tranh biện. \
Bạn không đứng về phe nào và không đánh giá lập luận hay hay dở, đúng hay sai.

Nhiệm vụ duy nhất: với từng luận điểm được đưa ra, xác định luận điểm đó đang BẢO VỆ phía nào của kiến nghị:
- "ung_ho_kien_nghi": luận điểm này, nếu được chấp nhận, làm cho kiến nghị đáng được thông qua hơn.
- "phan_doi_kien_nghi": luận điểm này, nếu được chấp nhận, làm cho kiến nghị ít đáng được thông qua hơn.
- "khong_ro": không xác định được, hoặc nội dung trung lập / nói về cả hai phía như nhau.

Mỗi luận điểm gồm KHẲNG ĐỊNH và LÝ DO. Xác định hướng dựa trên CẢ HAI: lý do cho biết khẳng định được dùng \
để làm gì. Đặc biệt chú ý phủ định và từ chỉ mức độ chắc chắn ("không", "chưa", "không chắc chắn", "khó có thể") \
— chúng có thể đảo ngược hướng của cả câu.

Chú ý: đánh giá theo HƯỚNG TÁC ĐỘNG lên kiến nghị, không theo từ ngữ bề mặt. Ví dụ với kiến nghị \
"Nên cấm X", câu "X gây hại cho trẻ em" là ung_ho_kien_nghi dù có từ "hại"; câu "cấm X làm mất lợi \
ích Y" là phan_doi_kien_nghi dù có từ "cấm".

Lý do (reason) viết ngắn gọn bằng tiếng Việt, 1 câu. Chỉ trả về JSON hợp lệ."""


def build_review_prompt_v2(
    motion: str, statements: list[Statement], summary: str | None = None
) -> tuple[str, str]:
    """Nhu v1 nhung moi muc kem LY DO (reasoning). VAN KHONG co tham so phe."""
    blocks = []
    for st in statements:
        block = f'- [{st.id}] Khẳng định: "{st.text}"'
        if st.reasoning:
            block += f'\n  Lý do: "{st.reasoning}"'
        blocks.append(block)
    user_prompt = f"""Một đội tranh luận đưa ra các luận điểm sau về kiến nghị '{motion}':
{chr(10).join(blocks)}"""
    if summary is not None:
        user_prompt += f"""

Phần kết luận / cân nhắc tổng thể của đội đó:
"{summary}\""""
    ids = ", ".join(st.id for st in statements)
    user_prompt += f"""

Trả về JSON: "arguments" gồm đúng một mục cho mỗi id ({ids}), mỗi mục có "id", "position", "reason"\
{'; "weighing" gồm "position", "reason" cho phần kết luận' if summary is not None else ""}."""
    return SYSTEM_PROMPT_V2, user_prompt


# ---------------------------------------------------------------------------
# v3: tach "hieu cau" khoi "ket luan phe". Ly do (dev log muc 2.4k): v1 dao nghia phu dinh (M10 A3 "…không chắc
# chắn dẫn đến giảm…"); v2 chi NHAC chu y phu dinh nhung model van ket luan ngay. v3 bat model:
#   a. restatement: dien dat lai luan diem thanh MOT cau don gian, khong phu dinh long (hieu cau TRUOC),
#   b. effect: "Neu luan diem nay dung, kien nghi manh hon hay yeu di?" (cau hoi don, khong can biet phe),
#   c. reason.
# Thu tu truong trong JSON schema la restatement -> effect -> reason de model dien dat lai TRUOC khi ket luan.
# Code anh xa effect -> position (manh_hon -> ung_ho, yeu_di -> phan_doi); judge() / side_flip giu nguyen.
# ---------------------------------------------------------------------------
class Effect(str, enum.Enum):
    MANH_HON = "manh_hon"
    YEU_DI = "yeu_di"
    KHONG_RO = "khong_ro"


EFFECT_TO_POSITION = {
    Effect.MANH_HON: Position.UNG_HO,
    Effect.YEU_DI: Position.PHAN_DOI,
    Effect.KHONG_RO: Position.KHONG_RO,
}


class StatementEffect(BaseModel):
    id: str
    restatement: str = Field(..., min_length=1)
    effect: Effect
    reason: str = Field(..., min_length=1)


class SummaryEffect(BaseModel):
    restatement: str = Field(..., min_length=1)
    effect: Effect
    reason: str = Field(..., min_length=1)


class StanceReviewOutputV3(BaseModel):
    arguments: list[StatementEffect]
    weighing: SummaryEffect | None = None


SYSTEM_PROMPT_V3 = """Bạn là TRỌNG TÀI TRUNG LẬP của một cuộc thi tranh biện, KHÔNG phải người tranh biện. \
Bạn không đứng về phe nào và không đánh giá lập luận hay hay dở, đúng hay sai.

Mỗi luận điểm gồm KHẲNG ĐỊNH và LÝ DO. Với TỪNG luận điểm (và phần kết luận), làm ĐÚNG theo thứ tự:
a. "restatement": diễn đạt lại luận điểm thành MỘT câu đơn giản, không phủ định lồng, giữ nguyên ý (dựa trên cả \
khẳng định và lý do). Nếu câu gốc có phủ định hoặc từ chỉ mức độ chắc chắn ("không", "chưa", "không chắc chắn", \
"khó có thể"), viết lại sao cho nghĩa rõ ràng — ví dụ "Cấm X không chắc chắn làm giảm Y" → "Cấm X có thể không làm \
giảm được Y".
b. "effect": trả lời câu hỏi "Nếu luận điểm này đúng, kiến nghị trở nên mạnh hơn hay yếu đi?"
   - "manh_hon": kiến nghị trở nên đáng được thông qua hơn.
   - "yeu_di": kiến nghị trở nên ít đáng được thông qua hơn.
   - "khong_ro": không xác định được, hoặc trung lập / tác động cả hai chiều như nhau.
c. "reason": lý do ngắn gọn, 1 câu.

Viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ, các trường theo đúng thứ tự restatement → effect → reason."""


def build_review_prompt_v3(
    motion: str, statements: list[Statement], summary: str | None = None
) -> tuple[str, str]:
    """Input nhu v2 (claim + reasoning), VAN KHONG co tham so phe; chi doi cach hoi + dinh dang output."""
    _, user_v2 = build_review_prompt_v2(motion, statements, summary)
    head = user_v2[: user_v2.rindex("\n\nTrả về JSON:")]
    ids = ", ".join(st.id for st in statements)
    user_prompt = head + f"""

Trả về JSON: "arguments" gồm đúng một mục cho mỗi id ({ids}), mỗi mục có "id", "restatement", "effect", "reason" \
(đúng thứ tự này)\
{'; "weighing" gồm "restatement", "effect", "reason" cho phần kết luận' if summary is not None else ""}."""
    return SYSTEM_PROMPT_V3, user_prompt


def build_review_schema_v3(statement_ids: list[str], has_summary: bool) -> dict:
    """Nhu v1 nhung moi muc: id -> restatement -> effect -> reason (thu tu co y — dien dat lai truoc khi ket luan)."""
    effect = {"type": "string", "enum": [e.value for e in Effect]}
    fields = {"restatement": {"type": "string"}, "effect": effect, "reason": {"type": "string"}}
    item = {
        "type": "object",
        "properties": {"id": {"type": "string", "enum": list(statement_ids)}, **fields},
        "required": ["id", *fields],
        "additionalProperties": False,
    }
    properties: dict = {
        "arguments": {"type": "array", "items": item, "minItems": len(statement_ids), "maxItems": len(statement_ids)}
    }
    if has_summary:
        properties[SUMMARY_ID] = {
            "type": "object", "properties": dict(fields), "required": list(fields), "additionalProperties": False,
        }
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def build_review_schema(statement_ids: list[str], has_summary: bool) -> dict:
    """JSON schema strict: dung so muc, id trong danh sach, position la 1 trong 3 gia tri."""
    position = {"type": "string", "enum": [p.value for p in Position]}
    item = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "enum": list(statement_ids)},
            "position": position,
            "reason": {"type": "string"},
        },
        "required": ["id", "position", "reason"],
        "additionalProperties": False,
    }
    properties: dict = {
        "arguments": {
            "type": "array",
            "items": item,
            "minItems": len(statement_ids),
            "maxItems": len(statement_ids),
        }
    }
    if has_summary:
        properties[SUMMARY_ID] = {
            "type": "object",
            "properties": {"position": position, "reason": {"type": "string"}},
            "required": ["position", "reason"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def parse_review(raw_output: str, statement_ids: list[str], has_summary: bool) -> StanceReviewOutput:
    """Parse + kiem tra reviewer tra DU va DUNG cac id (khong thua, khong thieu, khong trung)."""
    review = StanceReviewOutput.model_validate(extract_json(raw_output))
    got = [a.id for a in review.arguments]
    if sorted(got) != sorted(statement_ids):
        raise ValueError(f"Reviewer tra ve id {got}, ky vong {statement_ids}")
    if has_summary and review.weighing is None:
        raise ValueError("Reviewer thieu danh gia 'weighing'")
    return review


def parse_review_v3(
    raw_output: str, statement_ids: list[str], has_summary: bool
) -> tuple[StanceReviewOutput, dict[str, dict]]:
    """
    Parse output v3, anh xa effect -> position (manh_hon -> ung_ho, yeu_di -> phan_doi) ra StanceReviewOutput de
    judge() dung chung. Tra them {id: {"restatement", "effect"}} de ghi log.
    """
    v3 = StanceReviewOutputV3.model_validate(extract_json(raw_output))
    got = [a.id for a in v3.arguments]
    if sorted(got) != sorted(statement_ids):
        raise ValueError(f"Reviewer tra ve id {got}, ky vong {statement_ids}")
    if has_summary and v3.weighing is None:
        raise ValueError("Reviewer thieu danh gia 'weighing'")
    review = StanceReviewOutput(
        arguments=[StatementPosition(id=a.id, position=EFFECT_TO_POSITION[a.effect], reason=a.reason) for a in v3.arguments],
        weighing=(
            SummaryPosition(position=EFFECT_TO_POSITION[v3.weighing.effect], reason=v3.weighing.reason)
            if v3.weighing is not None else None
        ),
    )
    extra = {a.id: {"restatement": a.restatement, "effect": a.effect.value} for a in v3.arguments}
    if v3.weighing is not None:
        extra[SUMMARY_ID] = {"restatement": v3.weighing.restatement, "effect": v3.weighing.effect.value}
    return review, extra


def _parse_review_plain(raw_output: str, statement_ids: list[str], has_summary: bool) -> tuple[StanceReviewOutput, dict]:
    return parse_review(raw_output, statement_ids, has_summary), {}


@dataclass(frozen=True)
class ReviewVersion:
    """Bo 3 ham cua 1 phien ban reviewer. build_prompt KHONG co tham so phe o moi phien ban."""

    build_prompt: object  # (motion, statements, summary) -> (system, user)
    build_schema: object  # (ids, has_summary) -> dict
    parse: object  # (raw, ids, has_summary) -> (StanceReviewOutput, extra {id: {...}})


# Chon theo STANCE_REVIEW_PROMPT_VERSION (service) / --reviewer-version (replay).
REVIEW_VERSIONS = {
    PROMPT_VERSION: ReviewVersion(build_review_prompt, build_review_schema, _parse_review_plain),
    PROMPT_VERSION_V2: ReviewVersion(build_review_prompt_v2, build_review_schema, _parse_review_plain),
    PROMPT_VERSION_V3: ReviewVersion(build_review_prompt_v3, build_review_schema_v3, parse_review_v3),
}
REVIEW_PROMPTS = {version: spec.build_prompt for version, spec in REVIEW_VERSIONS.items()}


def judge(
    review: StanceReviewOutput, ai_side: DebateSide, prompt_version: str = PROMPT_VERSION,
    extra: dict[str, dict] | None = None,
) -> tuple[ReviewerVerdict, dict]:
    """
    CODE (khong phai LLM) so position voi phe cua AI:
    - co bat ky muc nao o phia NGUOC phe AI -> side_flip (output khong hop le, retry)
    - khong nguoc phe nhung co "khong_ro" -> unclear (chi canh bao, KHONG reject)
    - con lai -> pass
    """
    expected = EXPECTED_POSITION[ai_side]
    opposite = EXPECTED_POSITION[DebateSide.CON if ai_side == DebateSide.PRO else DebateSide.PRO]

    entries = [(a.id, a.position, a.reason) for a in review.arguments]
    if review.weighing is not None:
        entries.append((SUMMARY_ID, review.weighing.position, review.weighing.reason))

    flipped = [i for i, pos, _ in entries if pos == opposite]
    unclear = [i for i, pos, _ in entries if pos == Position.KHONG_RO]
    if flipped:
        verdict = ReviewerVerdict.SIDE_FLIP
    elif unclear:
        verdict = ReviewerVerdict.UNCLEAR
    else:
        verdict = ReviewerVerdict.PASS

    detail = {
        "prompt_version": prompt_version,
        "expected_position": expected.value,
        "flipped_ids": flipped,
        "unclear_ids": unclear,
        # v3: kem "restatement" + "effect" cua tung muc (extra) de doc lai model da hieu cau the nao.
        "positions": [
            {"id": i, "position": pos.value, "reason": reason, **(extra or {}).get(i, {})} for i, pos, reason in entries
        ],
    }
    return verdict, detail


def reviewer_failure(error: str, prompt_version: str = PROMPT_VERSION) -> tuple[ReviewerVerdict, dict]:
    """Reviewer loi (goi LLM that bai / output sai): KHONG chan Case Planning — coi nhu unclear + ghi ly do."""
    return ReviewerVerdict.UNCLEAR, {"prompt_version": prompt_version, "reviewer_error": error[:2000]}
