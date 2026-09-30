"""
Bo sinh bai noi cua AI trong tran (Giai doan 3).

Interface: TurnGenerator.generate(mode, context) -> TurnResult. Chon bang TURN_GENERATOR_VERSION (get_turn_generator):
turn_baseline_v1 (file nay) | turn_full_v1 / turn_full_v2 (turn_full.py, Giai doan 3b).
Bo sinh TU goi LLM qua LLMCaller (xu ly 429 + ghi moi lan goi thanh TurnCall = 1 dong opponent_llm_calls), nen bo
sinh day du o 3b (nhieu buoc: trich luan diem learner, chon premise, reviewer...) cam vao ben canh ma khong doi service.

turn_baseline_v1 — CO Y NGAY THO, lam moc so sanh: mo phong chatbot thong thuong kieu DEBO.
- System: vai + phe + motion, 1-2 cau chi dan theo mode, do dai muc tieu, "tieng Viet, van noi, khong markdown".
- Lich su: toan bo bai noi truoc do dang hoi thoai (learner = user, AI = assistant) — AI noi voi learner o ngoi thu hai.
- KHONG case file, KHONG ledger, KHONG nhac lai rang buoc o cuoi, KHONG reviewer; output van ban thuan.
- Tin cuoi khong phai cua learner (AI noi dau o luot 1; AI con noi tong ket ngay sau phan bac cua chinh minh o luot 5)
  -> them 1 tin user "Mời bạn trình bày phần <mo man / tong ket>." (chatbot can 1 tin user de tra loi; mot so
  provider coi tin assistant cuoi la "prefill" va viet tiep no). Tin moi luot 1 duoc giu lai trong lich su cac luot
  sau cua AI pro (no la mot phan cuoc hoi thoai da dien ra).
- Validator toi thieu: khong rong (rong -> thu lai, toi da TURN_MAX_ATTEMPTS). Do dai chi ghi lai, khong reject.
"""
import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import Settings
from app.llm.client import (
    LLMClient,
    is_rate_limit_error,
    is_transient_error,
    rate_limit_wait_seconds,
    schema_rejected_output,
)
from app.opponent.match_format import RoundType, Speaker, TurnMode, word_count
from app.opponent.models import DebateSide, LLMCallPurpose, OpponentDifficulty, ReviewerVerdict

logger = logging.getLogger(__name__)

BASELINE_V1 = "turn_baseline_v1"
FULL_V1 = "turn_full_v1"
FULL_V2 = "turn_full_v2"
FULL_V3 = "turn_full_v3"
# Baseline GIU NGUYEN hanh vi 3a de so sanh: khong doc TURN_MAX_TOKENS / TURN_MAX_ATTEMPTS (3b doi mac dinh 2 bien nay
# cho turn_full_v1 len 4000 / 3).
BASELINE_MAX_TOKENS = 3000
BASELINE_MAX_ATTEMPTS = 2

SIDE_LABEL = {DebateSide.PRO: "Đề xuất", DebateSide.CON: "Phản đối"}  # cung nhan voi prompt Case Planning v3+
ROUND_LABEL = {RoundType.OPENING: "mở màn", RoundType.REBUTTAL: "phản bác", RoundType.CLOSING: "tổng kết"}


class TurnFailure:
    """Gia tri failure_kind cho loi goi / ket qua sinh bai noi."""

    PROVIDER_ERROR = "provider_error"
    RATE_LIMITED = "rate_limited"
    TRANSIENT_ERROR = "transient_error"  # loi mang / timeout / 5xx — thu lai (muc 2.12)
    EMPTY_OUTPUT = "empty_output"
    BUDGET_EXCEEDED = "budget_exceeded"
    # turn_full_v1 (cung ten voi Case Planning de so sanh):
    SCHEMA_REJECTED = "schema_rejected"  # Groq 400 json_validate_failed (khong tu sua duoc ten truong)
    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION = "schema_validation"
    WORD_COUNT = "word_count"  # speech_text ngoai khoang chap nhan [0.7, 1.25] x muc tieu (loi MEM)
    # Output rong / bi cat vi het max_tokens (finish_reason "length", noi dung rong, hoac Groq 400 json_validate_failed
    # voi failed_generation RONG — token suy luan dung het gioi han). KHONG gop vao schema_rejected (muc 2.10).
    TRUNCATED = "truncated_max_tokens"
    BANNED_PHRASE = "banned_phrase"  # bang chung mo ho muc HIGH trong speech_text
    SIDE_FLIP = "side_flip"  # Stance Reviewer bao lat phe (muc 2.11) -> retry TRUNG TINH
    REVIEWER_ERROR = "reviewer_error"  # output reviewer khong parse duoc


@dataclass(frozen=True)
class SpeechItem:
    turn_index: int
    round_type: RoundType
    speaker: Speaker
    text: str


@dataclass
class Ledger:
    """
    Nhung gi da xay ra o cac luot AI TRUOC (dung lai tu opponent_turns moi luot, khong luu bang rieng). Luot baseline
    khong co cac truong nay -> bo qua.
    """

    learner_claims: list[str] = field(default_factory=list)
    ai_points: list[str] = field(default_factory=list)  # "nhung dieu ban DA khang dinh"
    attacked_premises: list[str] = field(default_factory=list)


@dataclass
class TurnContext:
    motion: str
    ai_side: DebateSide
    learner_side: DebateSide
    difficulty: OpponentDifficulty
    turn_index: int
    round_type: RoundType
    target_words: int
    history: list[SpeechItem]  # MOI bai noi truoc turn_index, theo thu tu luot
    case_file: dict | None = None  # baseline khong dung; turn_full_v1 bat buoc
    ledger: Ledger = field(default_factory=Ledger)  # baseline khong dung


@dataclass
class TurnCall:
    """1 lan goi LLM = 1 dong opponent_llm_calls (purpose=turn)."""

    attempt: int
    prompt_version: str
    llm_provider: str
    llm_model: str
    temperature: float
    system_prompt: str
    user_prompt: str  # baseline: JSON danh sach messages (hoi thoai); full: user prompt (van ban)
    raw_output: str | None
    success: bool
    error: str | None
    latency_ms: int
    failure_kind: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    rate_limit_wait_ms: int | None = None
    schema_rejected: bool = False
    retry_feedback: str | None = None  # phan hoi DA GUI cho lan thu ke tiep (turn_full_v1)
    key_repairs: dict | None = None
    vague_evidence: list[dict] | None = None  # hit bo do tren speech_text (None = khong quet)
    speech_checks: dict | None = None  # kiem tra chi log (so ngoai "Giả sử", xung "em", length_soft_accept)
    reasoning_tokens: int | None = None  # token suy luan rieng (da nam trong tokens_out), neu provider tra ve
    finish_reason: str | None = None
    reasoning_effort: str | None = None  # DA GUI (None = khong gui)
    truncated: bool = False  # output rong / bi cat vi het max_tokens
    purpose: LLMCallPurpose = LLMCallPurpose.TURN  # STANCE_REVIEW: loi goi reviewer cho luot noi
    reviewer_verdict: ReviewerVerdict | None = None
    reviewer_detail: dict | None = None


@dataclass
class TurnResult:
    text: str | None  # None = that bai
    mode: TurnMode
    generator_version: str
    llm_provider: str
    llm_model: str
    temperature: float
    calls: list[TurnCall] = field(default_factory=list)
    error: str | None = None
    failure_kind: str | None = None  # provider_error / empty_output (budget do service danh dau)
    # turn_full_v1 dien; baseline de None.
    learner_claims: list | dict | None = None
    premises: list | dict | None = None
    target_premise: str | None = None
    ai_points: list | None = None

    @property
    def word_count(self) -> int:
        return word_count(self.text or "")

    @property
    def rate_limit_wait_ms(self) -> int:
        """Tong thoi gian DA CHO 429 trong luot (moi loi goi, ke ca reviewer)."""
        return sum(c.rate_limit_wait_ms or 0 for c in self.calls)


class TurnLLMError(Exception):
    """Loi provider (khong phai 429 con luot cho) — dung luot, khong thu lai."""


# Cho 429 = thoi gian provider yeu cau + jitter (giong Case Planning; test tat jitter qua monkeypatch).
RATE_LIMIT_JITTER_SECONDS = (1.0, 2.0)


def _jitter() -> float:
    return random.uniform(*RATE_LIMIT_JITTER_SECONDS)


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


class LLMCaller:
    """
    Moi lan goi = DUNG 1 HTTP request; 429 -> cho theo provider (+ jitter) roi thu lai, KHONG gioi han so vong: chi
    TURN_TOTAL_BUDGET_SECONDS (asyncio.wait_for o turn_service) chan (muc 2.12). Loi mang / timeout / 5xx thoang qua ->
    thu lai toi da LLM_TRANSIENT_RETRIES lan (cho tang dan). MOI lan goi (ke ca loi, 429, lan bi huy vi het budget) them 1
    TurnCall vao self.calls — danh sach nay doc duoc ca khi service huy giua chung.
    chat(): hoi thoai, van ban thuan (baseline). complete(): system + user, JSON schema (turn_full_v*) — Groq tu choi
    schema (400 json_validate_failed) la OUTPUT KHONG HOP LE: tra ve call (success=False, schema_rejected=True,
    raw_output = output bi tu choi), khong nem loi. failed_generation RONG -> truncated (khong phai schema_rejected);
    complete() con danh dau truncated khi finish_reason "length" hoac noi dung rong. chat() giu nguyen hanh vi 3a.
    TURN_REASONING_EFFORT (neu dat) duoc gui o ca hai.
    """

    def __init__(
        self, client: LLMClient, settings: Settings, calls: list[TurnCall] | None = None, send_effort: bool = True
    ):
        """calls: dung chung danh sach voi caller khac (reviewer ghi chung, danh so attempt lien tuc).
        send_effort=False: khong gui TURN_REASONING_EFFORT (Stance Reviewer)."""
        self.client, self.settings = client, settings
        self.calls: list[TurnCall] = [] if calls is None else calls
        self._rate_limit_waits = 0
        self._transient_retries = 0
        self._send_effort = send_effort

    async def chat(
        self, system_prompt: str, messages: list[dict], *, temperature: float, max_tokens: int, prompt_version: str
    ) -> TurnCall:
        effort = self._effort()
        return await self._call(
            system_prompt, json.dumps(messages, ensure_ascii=False), prompt_version, temperature, LLMCallPurpose.TURN,
            lambda: self.client.generate_chat(
                system_prompt, messages, temperature=temperature, max_tokens=max_tokens, **effort
            ),
        )

    def _effort(self) -> dict:
        effort = self.settings.turn_reasoning_effort if self._send_effort else None
        return {"reasoning_effort": effort} if effort else {}

    async def complete(
        self, system_prompt: str, user_prompt: str, *, temperature: float, max_tokens: int, prompt_version: str,
        json_schema: dict | None, purpose: LLMCallPurpose = LLMCallPurpose.TURN,
    ) -> TurnCall:
        effort = self._effort()
        call = await self._call(
            system_prompt, user_prompt, prompt_version, temperature, purpose,
            lambda: self.client.generate(
                system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens, json_schema=json_schema,
                **effort,
            ),
        )
        if call.success and (call.finish_reason == "length" or not (call.raw_output or "").strip()):
            call.success, call.truncated, call.failure_kind = False, True, TurnFailure.TRUNCATED
            call.error = (
                f"{TurnFailure.TRUNCATED}: output {'rong' if not (call.raw_output or '').strip() else 'bi cat'} "
                f"(finish_reason={call.finish_reason}, tokens_out={call.tokens_out}/{max_tokens})"
            )
        return call

    async def _call(
        self, system_prompt: str, user_prompt: str, prompt_version: str, temperature: float, purpose: LLMCallPurpose, send
    ) -> TurnCall:
        while True:
            call = TurnCall(
                attempt=len(self.calls) + 1, prompt_version=prompt_version, llm_provider=self.client.provider,
                llm_model=self.client.model, temperature=temperature, system_prompt=system_prompt,
                user_prompt=user_prompt, raw_output=None, success=False, error=None, latency_ms=0,
                reasoning_effort=self._effort().get("reasoning_effort"), purpose=purpose,
            )
            started = time.perf_counter()
            self.client.last_usage, self.client.last_finish_reason = None, None
            try:
                # LLMClient la sync -> chay trong thread de khong chan event loop.
                call.raw_output = await asyncio.to_thread(send)
                call.success = True
            except Exception as e:  # noqa: BLE001 — moi loi provider deu phai duoc log
                call.error = f"{type(e).__name__}: {e}"[:4000]
                rejected = schema_rejected_output(e)
                if rejected == "":  # Groq tu choi vi output RONG: het max_tokens truoc khi viet (tran 15:11 luot 5)
                    call.truncated, call.failure_kind = True, TurnFailure.TRUNCATED
                    call.error = f"{TurnFailure.TRUNCATED}: failed_generation rong — {call.error}"[:4000]
                elif rejected is not None:
                    call.schema_rejected, call.raw_output = True, rejected
                    call.failure_kind = TurnFailure.SCHEMA_REJECTED
                elif is_rate_limit_error(e):
                    call.failure_kind = TurnFailure.RATE_LIMITED
                elif is_transient_error(e):
                    call.failure_kind = TurnFailure.TRANSIENT_ERROR
                else:
                    call.failure_kind = TurnFailure.PROVIDER_ERROR
                error = e
            finally:  # chay ca khi bi huy (het budget): lan goi dang cho van duoc ghi, success=False, error=None
                call.latency_ms = int((time.perf_counter() - started) * 1000)
                usage = getattr(self.client, "last_usage", None) or {}
                call.tokens_in, call.tokens_out = usage.get("tokens_in"), usage.get("tokens_out")
                call.reasoning_tokens = usage.get("reasoning_tokens")
                call.finish_reason = getattr(self.client, "last_finish_reason", None)
                self.calls.append(call)
            if call.success or call.schema_rejected or call.truncated:
                return call
            if call.failure_kind == TurnFailure.RATE_LIMITED:
                self._rate_limit_waits += 1
                requested = rate_limit_wait_seconds(error)
                wait = (requested if requested is not None else self.settings.case_plan_rate_limit_wait_seconds) + _jitter()
                call.rate_limit_wait_ms = int(wait * 1000)
                logger.warning("turn bi rate-limit (lan cho %d, lan goi %d) -> cho %.1fs", self._rate_limit_waits,
                               call.attempt, wait)
                await _sleep(wait)
                continue
            if call.failure_kind == TurnFailure.TRANSIENT_ERROR and self._transient_retries < self.settings.llm_transient_retries:
                self._transient_retries += 1
                wait = self.settings.llm_transient_retry_wait_seconds * 2 ** (self._transient_retries - 1) + _jitter()
                logger.warning("turn loi mang thoang qua (lan %d, lan goi %d): %s -> cho %.1fs", self._transient_retries,
                               call.attempt, call.error, wait)
                await _sleep(wait)
                continue
            raise TurnLLMError(call.error) from error


class TurnGenerator(Protocol):
    version: str
    temperature: float
    caller: LLMCaller

    async def generate(self, mode: TurnMode, context: TurnContext) -> TurnResult: ...


# ---------------- turn_baseline_v1 ----------------

MODE_INSTRUCTION = {
    TurnMode.OPENING_FIRST: "Đây là phần mở màn của bạn: hãy nêu lập trường và trình bày các luận điểm chính.",
    TurnMode.OPENING_REPLY: (
        "Đây là phần mở màn của bạn, sau phần mở màn của người dùng: hãy nêu lập trường và trình bày các luận điểm chính."
    ),
    TurnMode.REBUTTAL: "Đây là phần phản bác: hãy phản bác lập luận của người dùng và bảo vệ lập luận của bạn.",
    TurnMode.CLOSING: "Đây là phần tổng kết: hãy tóm lại cuộc tranh luận và giải thích vì sao phe của bạn thắng.",
}


def baseline_kickoff(round_type: RoundType) -> str:
    return f"Mời bạn trình bày phần {ROUND_LABEL[round_type]}."


def build_baseline_prompt(mode: TurnMode, context: TurnContext) -> tuple[str, list[dict]]:
    """THUAN: (system prompt, messages). Khong dung context.case_file."""
    system = (
        f"Bạn là một người tranh luận thuộc phe {SIDE_LABEL[context.ai_side]} về kiến nghị '{context.motion}'. "
        f"Hãy tranh luận với người dùng. {MODE_INSTRUCTION[mode]} "
        f"Độ dài khoảng {context.target_words} từ. "
        "Viết bằng tiếng Việt, văn nói, không dùng markdown hay gạch đầu dòng."
    )
    messages: list[dict] = []
    if context.ai_side == DebateSide.PRO:
        # AI noi dau: cuoc hoi thoai bat dau bang loi moi mo man (luot 1), giu lai o cac luot sau.
        messages.append({"role": "user", "content": baseline_kickoff(RoundType.OPENING)})
    for s in sorted(context.history, key=lambda s: s.turn_index):
        messages.append({"role": "user" if s.speaker == Speaker.LEARNER else "assistant", "content": s.text})
    if not messages or messages[-1]["role"] == "assistant":
        messages.append({"role": "user", "content": baseline_kickoff(context.round_type)})
    return system, messages


class BaselineTurnGenerator:
    """GIU NGUYEN hanh vi 3a (moc so sanh) — khong sua khi lam bo sinh moi."""

    version = BASELINE_V1

    def __init__(self, client: LLMClient, settings: Settings):
        self.settings = settings
        self.temperature = settings.turn_temperature
        self.caller = LLMCaller(client, settings)

    async def generate(self, mode: TurnMode, context: TurnContext) -> TurnResult:
        client = self.caller.client
        result = TurnResult(
            text=None, mode=mode, generator_version=self.version, llm_provider=client.provider,
            llm_model=client.model, temperature=self.temperature, calls=self.caller.calls,
        )
        system, messages = build_baseline_prompt(mode, context)
        for _ in range(BASELINE_MAX_ATTEMPTS):
            try:
                call = await self.caller.chat(
                    system, messages, temperature=self.temperature, max_tokens=BASELINE_MAX_TOKENS,
                    prompt_version=self.version,
                )
            except TurnLLMError as e:
                result.error, result.failure_kind = str(e), TurnFailure.PROVIDER_ERROR
                return result
            text = (call.raw_output or "").strip()
            if text:
                result.text = text
                return result
            call.success, call.error, call.failure_kind = False, "bai noi rong", TurnFailure.EMPTY_OUTPUT
            logger.warning("Bai noi luot %d rong (lan goi %d), thu lai", context.turn_index, call.attempt)
        result.error, result.failure_kind = "bai noi rong sau moi lan thu", TurnFailure.EMPTY_OUTPUT
        return result


def generators() -> dict[str, type]:
    from app.opponent.turn_full import FullTurnGenerator, FullTurnGeneratorV2, FullTurnGeneratorV3  # import muon

    return {
        BASELINE_V1: BaselineTurnGenerator, FULL_V1: FullTurnGenerator, FULL_V2: FullTurnGeneratorV2,
        FULL_V3: FullTurnGeneratorV3,
    }


def get_turn_generator(settings: Settings, client: LLMClient, reviewer_client: LLMClient | None = None) -> TurnGenerator:
    """reviewer_client: Stance Reviewer cho turn_full_v* (None = khong review). Baseline bo qua."""
    cls = generators()[settings.turn_generator_version]
    if cls is BaselineTurnGenerator:
        return cls(client, settings)
    return cls(client, settings, reviewer_client)
