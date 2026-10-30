"""
Goi y phan bac cho learner (WF-02, prompt hint_v1) — phan THUAN (khong DB). Luong DB: hint_service.py.

Learner bam "Goi y phan bac" truoc luot cua minh -> 2-3 CHIEN LUOC nham vao bai AI vua noi (luot target). Chi chi
huong, KHONG viet san bai noi.

QUY TAC QUAN TRONG NHAT (spec muc 4): KHONG doc case plan. Case file / ledger / ai_points / premises cua AI la du lieu
lap ke hoach NOI BO; dua vao hint la mach nuoc cho learner va AI khong con la doi thu that. build_hint_prompt KHONG nhan
tham so nao chua du lieu do — chi motion, phe learner, round_type cua luot learner, bai noi CONG KHAI (opponent_speeches)
va ban nhap cua learner. File nay khong import case file / ledger (test kiem tra).

Validator (loi -> thu lai co phan hoi, toi da HINT_MAX_ATTEMPTS; KHONG tu va JSON / ten truong, theo spec):
- JSON / schema: 2-3 chien luoc, attack_type trong enum, du truong;
- direction <= 60 tu (huong di, khong phai doan van mau);
- direction + evidence_to_look_for: cam chu so / %, URL, vien dan nghien cuu muc HIGH (vague_detector) — evidence chi
  LOAI dan chung;
- 2 chien luoc khong duoc trung CA attack_type LAN target_claim (so sau chuan hoa).
Stance Reviewer v1 (neu bat): moi chien luoc la 1 muc, phai bao ve phe LEARNER. Lat phe -> thu lai trung tinh; reviewer
loi -> fail-closed, thu lai trung tinh (giong luot noi, dev log muc 2.14). Het luot -> that bai (502).
Chi LOG: do trung tu giua target_claim va bai target (nham dung noi dung AI da noi khong kiem tra duoc chac chan bang code).
"""
import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.llm.client import LLMClient
from app.llm.json_utils import LLMOutputParseError, extract_json
from app.opponent import stance_reviewer, vague_detector
from app.opponent.match_format import RoundType, Speaker, word_count
from app.opponent.models import DebateSide, LLMCallPurpose, ReviewerVerdict
from app.opponent.schemas import AttackType, HintStrategy
from app.opponent.service import build_retry_feedback
from app.opponent.turn_generators import ROUND_LABEL, SIDE_LABEL, LLMCaller, TurnCall, TurnFailure, TurnLLMError

logger = logging.getLogger(__name__)

HINT_PROMPT_VERSION = "hint_v1"
HINT_REVIEW_VERSION = stance_reviewer.PROMPT_VERSION  # v1, giong luot noi
MIN_STRATEGIES, MAX_STRATEGIES = 2, 3
MAX_DIRECTION_WORDS = 60
HISTORY_WORDS = 150  # moi luot TRUOC luot target cat con ~150 tu dau (spec muc 6)
FIELD_ORDER = ("title", "target_claim", "attack_type", "direction", "evidence_to_look_for")


class HintFailure:
    """failure_kind rieng cua hint (cac loai chung dung TurnFailure: invalid_json, schema_validation, side_flip...)."""

    DIRECTION_TOO_LONG = "direction_too_long"
    FABRICATED_EVIDENCE = "fabricated_evidence"
    DUPLICATE_STRATEGY = "duplicate_strategy"


@dataclass(frozen=True)
class PublicSpeech:
    """1 bai noi DA NOI CONG KHAI trong tran (tu opponent_speeches)."""

    turn_index: int
    round_type: RoundType
    speaker: Speaker
    text: str


@dataclass
class HintContext:
    motion: str
    learner_side: DebateSide
    learner_turn_index: int
    learner_round_type: RoundType
    target: PublicSpeech  # luot AI gan nhat truoc luot learner — NGUYEN VAN
    history: list[PublicSpeech]  # MOI luot khac da noi truoc luot learner (ca hai ben, ke ca sau target) — rut gon
    learner_draft: str | None = None


@dataclass
class HintResult:
    strategies: list[dict] | None  # None = that bai
    prompt_version: str
    llm_provider: str
    llm_model: str
    temperature: float
    calls: list[TurnCall] = field(default_factory=list)
    error: str | None = None
    failure_kind: str | None = None

    @property
    def latency_ms(self) -> int:
        return sum(c.latency_ms for c in self.calls)

    def tokens(self, attr: str) -> int | None:
        known = [getattr(c, attr) for c in self.calls if getattr(c, attr) is not None]
        return sum(known) if known else None


# ---------------- output ----------------


class HintOutput(BaseModel):
    strategies: list[HintStrategy] = Field(..., min_length=MIN_STRATEGIES, max_length=MAX_STRATEGIES)


def build_hint_schema() -> dict:
    """JSON schema strict (Groq), viet tay de giu thu tu truong."""
    text = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "strategies": {
                "type": "array",
                "minItems": MIN_STRATEGIES,
                "maxItems": MAX_STRATEGIES,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": text,
                        "target_claim": text,
                        "attack_type": {"type": "string", "enum": [a.value for a in AttackType]},
                        "direction": text,
                        "evidence_to_look_for": {"type": ["string", "null"]},
                    },
                    "required": list(FIELD_ORDER),
                    "additionalProperties": False,
                },
            }
        },
        "required": ["strategies"],
        "additionalProperties": False,
    }


# ---------------- prompt ----------------


def truncate_words(text: str, limit: int = HISTORY_WORDS) -> str:
    words = text.split()
    return text if len(words) <= limit else " ".join(words[:limit]) + " …"


ATTACK_TYPE_GUIDE = (
    "counterexample (phản ví dụ), hidden_premise (tiền đề ngầm chưa được chứng minh), weak_evidence (dẫn chứng / "
    "lý do yếu), logical_gap (bước suy luận bị thiếu), impact_comparison (so sánh mức độ tác động), "
    "turn_the_argument (biến lập luận của đối thủ thành lợi thế cho phe mình)"
)

SYSTEM_PROMPT = """Bạn là huấn luyện viên tranh biện, giúp một học sinh Việt Nam chuẩn bị phản bác. \
Bạn chỉ GỢI Ý HƯỚNG phản bác, KHÔNG viết sẵn bài nói cho học sinh. Mọi nội dung viết bằng tiếng Việt. \
Chỉ trả về JSON hợp lệ."""


def build_hint_prompt(context: HintContext, feedback: str | None = None) -> tuple[str, str]:
    """
    THUAN: (system, user). Chi chua: motion, phe learner, round_type luot learner, bai target NGUYEN VAN, cac luot
    truoc (rut gon), ban nhap. KHONG co tham so case file / ledger — co y (spec muc 4).
    """
    learner, ai = SIDE_LABEL[context.learner_side], SIDE_LABEL[
        DebateSide.CON if context.learner_side == DebateSide.PRO else DebateSide.PRO
    ]
    who = {Speaker.LEARNER: f"Học sinh (phe {learner})", Speaker.AI: f"Đối thủ (phe {ai})"}
    parts = [
        f"Kiến nghị: '{context.motion}'.\nHọc sinh thuộc phe {learner}; đối thủ thuộc phe {ai}.\n"
        f"Lượt sắp tới của học sinh: phần {ROUND_LABEL[context.learner_round_type]} (lượt {context.learner_turn_index})."
    ]
    if context.history:
        parts.append(
            "Các lượt khác đã nói trong trận (rút gọn):\n"
            + "\n".join(f"- Lượt {s.turn_index} – {who[s.speaker]}: «{truncate_words(s.text)}»" for s in context.history)
        )
    parts.append(
        f"Bài nói của đối thủ cần phản bác (lượt {context.target.turn_index}, nguyên văn):\n«{context.target.text}»"
    )
    if context.learner_draft:
        parts.append(f"Bản nháp học sinh đang định nói (chỉ để tham khảo, đừng viết lại):\n«{context.learner_draft}»")
    parts.append(
        f"Nhiệm vụ: đưa ra {MIN_STRATEGIES}–{MAX_STRATEGIES} chiến lược phản bác khác nhau nhắm vào bài nói của đối thủ "
        f"ở lượt {context.target.turn_index}. Trả về JSON {{\"strategies\": [...]}}, mỗi chiến lược gồm ĐÚNG các trường:\n"
        "- title: tên chiến lược, ngắn.\n"
        "- target_claim: tóm tắt ngắn luận điểm CỤ THỂ mà đối thủ đã nói trong bài trên (không bịa điều đối thủ không nói).\n"
        f"- attack_type: một trong {ATTACK_TYPE_GUIDE}.\n"
        f"- direction: hướng phản bác trong 1–2 câu, tối đa {MAX_DIRECTION_WORDS} từ.\n"
        "- evidence_to_look_for: LOẠI dẫn chứng học sinh nên tìm, hoặc null."
    )
    if feedback:
        parts.append(feedback.strip())
    parts.append(
        "Ràng buộc bắt buộc:\n"
        f"- Mọi chiến lược phải giúp phe {learner} (phe của học sinh), không được bênh phe {ai}.\n"
        "- Chỉ nhắm vào những gì đối thủ THỰC SỰ đã nói ở bài cần phản bác.\n"
        "- direction là hướng đi, KHÔNG phải đoạn văn mẫu để đọc; không viết hộ bài nói.\n"
        "- evidence_to_look_for chỉ mô tả LOẠI dẫn chứng (vd 'tình huống thực tế ở trường', 'quy định hiện hành'); "
        "KHÔNG ghi con số, phần trăm, tên nghiên cứu, tổ chức hay đường link.\n"
        "- Hai chiến lược không được cùng attack_type và cùng target_claim.\n"
        "- Viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ."
    )
    return SYSTEM_PROMPT, "\n\n".join(parts)


# ---------------- validator ----------------


class InvalidHint(Exception):
    def __init__(self, kind: str, error: str, issues: list[str]):
        super().__init__(error)
        self.kind, self.error, self.issues = kind, error, issues


_DIGIT_OR_PERCENT = re.compile(r"\d|%")
_URL = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|org|net|vn|edu|gov)\b", re.IGNORECASE)
_WORD = re.compile(r"[^\W_]+")


def _norm(text: str) -> str:
    return " ".join(_WORD.findall(unicodedata.normalize("NFC", text).casefold()))


def parse_hint_output(raw: str | None) -> list[HintStrategy]:
    """Nem InvalidHint (kem phan hoi tieng Viet) neu khong hop le. KHONG tu va."""
    try:
        data = extract_json(raw or "")
    except LLMOutputParseError as e:
        raise InvalidHint(TurnFailure.INVALID_JSON, str(e)[:4000],
                          ["Output không phải một JSON object hợp lệ (có thể bị cắt, hoặc có chữ thừa ngoài JSON)."]) from e
    try:
        out = HintOutput.model_validate(data)
    except ValidationError as e:
        issues = []
        for err in e.errors():
            where = ".".join(str(p) for p in err["loc"]) or "(toàn bộ JSON)"
            if err["type"] in ("too_short", "too_long") and where == "strategies":
                msg = f"phải có từ {MIN_STRATEGIES} đến {MAX_STRATEGIES} chiến lược"
            elif err["type"] == "enum":
                msg = f"attack_type phải là một trong: {', '.join(a.value for a in AttackType)}"
            else:
                msg = err["msg"]
            issues.append(f"`{where}`: {msg}")
        raise InvalidHint(TurnFailure.SCHEMA_VALIDATION, str(e)[:4000], issues) from e
    return validate_strategies(out.strategies)


def validate_strategies(strategies: list[HintStrategy]) -> list[HintStrategy]:
    """Kiem tra noi dung (sau schema). Loi dau tien theo thu tu: do dai -> bang chung -> trung lap."""
    long = [(i, word_count(s.direction)) for i, s in enumerate(strategies) if word_count(s.direction) > MAX_DIRECTION_WORDS]
    if long:
        raise InvalidHint(
            HintFailure.DIRECTION_TOO_LONG, f"direction qua {MAX_DIRECTION_WORDS} tu: {long}",
            [f"`strategies.{i}.direction` dài {n} từ — tối đa {MAX_DIRECTION_WORDS} từ; chỉ nêu hướng, không viết đoạn văn."
             for i, n in long],
        )
    # direction cung kiem tra: chay that 2026-10-31 co "vi nghien cuu cho thay..." lot qua o direction (dev log muc 4.2).
    bad = []
    for i, s in enumerate(strategies):
        for name, text in (("direction", s.direction), ("evidence_to_look_for", s.evidence_to_look_for or "")):
            reasons = []
            if _DIGIT_OR_PERCENT.search(text):
                reasons.append("có con số / phần trăm")
            if _URL.search(text):
                reasons.append("có đường link / tên miền")
            high = [h.match for h in vague_detector.detect_speech(text, name) if h.level == vague_detector.HIGH]
            if high:
                reasons.append(f"viện dẫn nguồn mơ hồ \"{high[0]}\"")
            if reasons:
                bad.append((i, name, reasons))
    if bad:
        raise InvalidHint(
            HintFailure.FABRICATED_EVIDENCE, f"direction / evidence_to_look_for khong hop le: {bad}",
            [f"`strategies.{i}.{name}` {', '.join(r)} — không đưa số liệu / nguồn cụ thể (kể cả \"nghiên cứu cho thấy\"); "
             "chỉ nêu hướng lập luận và LOẠI dẫn chứng cần tìm." for i, name, r in bad],
        )
    seen: dict[tuple, int] = {}
    for i, s in enumerate(strategies):
        key = (s.attack_type, _norm(s.target_claim))
        if key in seen:
            raise InvalidHint(
                HintFailure.DUPLICATE_STRATEGY, f"chien luoc {seen[key]} va {i} trung attack_type + target_claim",
                [f"Chiến lược {seen[key] + 1} và {i + 1} trùng cả attack_type lẫn target_claim — mỗi chiến lược phải khác nhau."],
            )
        seen[key] = i
    return strategies


def target_overlap(strategies: list[HintStrategy], target_text: str) -> list[float]:
    """CHI LOG: ti le tu cua target_claim co trong bai target (thap -> nghi bia noi dung AI khong noi)."""
    target_words = set(_norm(target_text).split())
    out = []
    for s in strategies:
        words = _norm(s.target_claim).split()
        out.append(round(sum(w in target_words for w in words) / len(words), 2) if words else 0.0)
    return out


# ---------------- bo sinh ----------------


class HintGenerator:
    def __init__(self, client: LLMClient, settings: Settings, reviewer_client: LLMClient | None = None):
        self.settings = settings
        self.temperature = settings.llm_temperature
        # LLMCaller gui settings.turn_reasoning_effort -> thay bang HINT_REASONING_EFFORT cho loi goi hint.
        self.caller = LLMCaller(client, settings.model_copy(update={"turn_reasoning_effort": settings.hint_reasoning_effort}))
        self.reviewer = (
            LLMCaller(reviewer_client, settings, calls=self.caller.calls, send_effort=False)
            if reviewer_client is not None else None
        )

    async def generate(self, context: HintContext) -> HintResult:
        client, settings = self.caller.client, self.settings
        result = HintResult(
            strategies=None, prompt_version=HINT_PROMPT_VERSION, llm_provider=client.provider, llm_model=client.model,
            temperature=self.temperature, calls=self.caller.calls,
        )
        schema = build_hint_schema() if settings.case_plan_use_json_schema else None
        feedback = None
        for attempt_no in range(1, settings.hint_max_attempts + 1):
            last = attempt_no == settings.hint_max_attempts
            system, user = build_hint_prompt(context, feedback)
            try:
                call = await self.caller.complete(
                    system, user, temperature=self.temperature, max_tokens=settings.hint_max_tokens,
                    prompt_version=HINT_PROMPT_VERSION, json_schema=schema, purpose=LLMCallPurpose.HINT,
                )
            except TurnLLMError as e:
                result.error, result.failure_kind = str(e), TurnFailure.PROVIDER_ERROR
                return result
            try:
                if call.truncated:
                    raise InvalidHint(TurnFailure.TRUNCATED, call.error or TurnFailure.TRUNCATED,
                                      ["Output lần trước bị cắt vì hết giới hạn token. Suy nghĩ ngắn gọn hơn, trả về đủ JSON."])
                if call.schema_rejected:
                    raise InvalidHint(TurnFailure.SCHEMA_REJECTED, call.error or TurnFailure.SCHEMA_REJECTED,
                                      ["Output không khớp JSON schema: kiểm tra đủ 5 trường mỗi chiến lược, đúng kiểu, "
                                       "attack_type đúng enum, 2–3 chiến lược."])
                strategies = parse_hint_output(call.raw_output)
            except InvalidHint as e:
                call.success, call.error, call.failure_kind = False, e.error[:4000], e.kind
                logger.warning("Hint lan thu %d khong hop le (%s): %s", attempt_no, e.kind, e.error)
                if last:
                    result.error, result.failure_kind = e.error, e.kind
                    return result
                feedback = build_retry_feedback(e.issues)
                call.retry_feedback = feedback.strip()
                continue
            call.speech_checks = {"target_overlap": target_overlap(strategies, context.target.text)}

            if self.reviewer is not None:
                verdict, detail = await self._review(strategies, context)
                call.reviewer_verdict, call.reviewer_detail = verdict, detail
                if verdict == ReviewerVerdict.SIDE_FLIP or stance_reviewer.is_reviewer_failure(detail):
                    kind = (TurnFailure.SIDE_FLIP if verdict == ReviewerVerdict.SIDE_FLIP
                            else TurnFailure.REVIEWER_UNAVAILABLE)
                    call.success, call.failure_kind = False, kind
                    call.error = (f"side_flip: trong tai danh gia {detail.get('flipped_ids')} nguoc phe learner "
                                  f"{context.learner_side.value}" if kind == TurnFailure.SIDE_FLIP
                                  else f"{kind}: {detail.get('reviewer_error', '')[:500]}")
                    logger.warning("Hint lan thu %d: %s", attempt_no, call.error)
                    if last:
                        result.error, result.failure_kind = call.error, kind
                        return result
                    feedback = None  # retry TRUNG TINH (giong luot noi, muc 2.4m)
                    continue
            result.strategies = [s.model_dump(mode="json") for s in strategies]
            return result
        raise AssertionError("unreachable")  # pragma: no cover

    async def _review(self, strategies: list[HintStrategy], context: HintContext) -> tuple[ReviewerVerdict, dict]:
        """
        Reviewer v1: motion + moi chien luoc (target_claim -> direction) la 1 muc; KHONG cho biet phe. Code so voi phe
        LEARNER. Loi -> goi lai (toi da MAX_CALLS) roi reviewer_failure (fail-closed o generate).
        """
        sr, settings = stance_reviewer, self.settings
        spec = sr.REVIEW_VERSIONS[HINT_REVIEW_VERSION]
        statements = [sr.Statement(f"H{i}", f"Phản bác ý '{s.target_claim}': {s.direction}")
                      for i, s in enumerate(strategies, start=1)]
        ids = [st.id for st in statements]
        system, user = spec.build_prompt(context.motion, statements, None)
        schema = spec.build_schema(ids, has_summary=False) if settings.case_plan_use_json_schema else None
        error = ""
        for call_no in range(1, sr.MAX_CALLS + 1):
            try:
                call = await self.reviewer.complete(
                    system, user, temperature=sr.TEMPERATURE, max_tokens=settings.stance_review_max_tokens,
                    prompt_version=HINT_REVIEW_VERSION, json_schema=schema, purpose=LLMCallPurpose.STANCE_REVIEW,
                )
            except TurnLLMError as e:
                error = str(e)
                continue
            if not call.success:
                error = call.error or ""
                continue
            try:
                review, extra = spec.parse(call.raw_output, ids, has_summary=False)
            except (LLMOutputParseError, ValidationError, ValueError) as e:
                call.success, call.error, call.failure_kind = False, str(e)[:4000], TurnFailure.REVIEWER_ERROR
                error = call.error
                continue
            verdict, detail = sr.judge(review, context.learner_side, HINT_REVIEW_VERSION, extra)
            detail["reviewer_calls"] = call_no
            call.reviewer_verdict, call.reviewer_detail = verdict, detail
            return verdict, detail
        verdict, detail = sr.reviewer_failure(error, HINT_REVIEW_VERSION)
        detail["reviewer_calls"] = sr.MAX_CALLS
        return verdict, detail


async def run_hint(
    context: HintContext, client: LLMClient, settings: Settings, reviewer_client: LLMClient | None = None
) -> HintResult:
    """Chay trong HINT_TOTAL_BUDGET_SECONDS. Het budget -> HintResult that bai (budget_exceeded)."""
    generator = HintGenerator(client, settings, reviewer_client)
    try:
        return await asyncio.wait_for(generator.generate(context), timeout=settings.hint_total_budget_seconds)
    except TimeoutError:
        error = f"{TurnFailure.BUDGET_EXCEEDED}: het {settings.hint_total_budget_seconds}s cho goi y"
        for call in generator.caller.calls:
            if not call.success and call.error is None:
                call.error, call.failure_kind = error, TurnFailure.BUDGET_EXCEEDED
        return HintResult(
            strategies=None, prompt_version=HINT_PROMPT_VERSION, llm_provider=client.provider, llm_model=client.model,
            temperature=generator.temperature, calls=generator.caller.calls, error=error,
            failure_kind=TurnFailure.BUDGET_EXCEEDED,
        )
