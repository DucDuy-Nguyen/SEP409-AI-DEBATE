"""
Logic nghiep vu module AI Opponent. Router chi goi vao day, khong chua logic.

Case Planning: truoc tran, AI doi thu goi LLM sinh "case file" (luan diem, du doan luan
diem cua learner + huong phan bien), validate bang schemas.CaseFile + so luan diem theo
do kho, roi luu JSONB. Moi lan goi LLM (ke ca lan loi) deu duoc log vao opponent_llm_calls.

Tach 2 tang:
- generate_case_file(): THUAN, khong dung DB — dung duoc tu script thu LLM that.
- create_session_and_plan(): tao session (idempotent theo external_session_id) + chay
  Case Planning DONG BO trong cung request + quan ly trang thai + ghi DB.
"""
import asyncio
import copy
import logging
import random
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.llm.client import (
    LLMClient,
    is_rate_limit_error,
    is_transient_error,
    rate_limit_wait_seconds,
    schema_rejected_output,
)
from app.llm.json_utils import LLMOutputParseError, extract_json
from app.opponent.models import (
    DebateSide,
    LLMCallPurpose,
    OpponentCaseFile,
    OpponentDifficulty,
    OpponentLLMCall,
    OpponentSession,
    ReviewerVerdict,
    SessionStatus,
)
from app.opponent import stance_reviewer, vague_detector
from app.opponent.json_repair import repair_split_array
from app.opponent.prompts import case_plan_v3, case_plan_v4, case_plan_v5
from app.opponent.schemas import AnticipatedArgument, CaseArgument, CaseFile, CreateSessionRequest, Definition

logger = logging.getLogger(__name__)

PROMPT_MODULES = {m.PROMPT_VERSION: m for m in (case_plan_v3, case_plan_v4, case_plan_v5)}

class InvalidSidesError(ValueError):
    """learner_side trung ai_side."""


class SessionNotFoundError(Exception):
    pass


class CasePlanningInProgressError(Exception):
    """Session dang co 1 lan Case Planning khac chay."""


class SessionDataMismatchError(Exception):
    """external_session_id da ton tai nhung du lieu request khac phien cu."""

    def __init__(self, external_session_id: str, fields: list[str]):
        self.fields = fields
        super().__init__(
            f"external_session_id '{external_session_id}' da ton tai voi du lieu khac: {', '.join(fields)}"
        )


class CasePlanningError(Exception):
    """LLM goi duoc nhung output khong hop le sau khi da het so lan thu."""


class CasePlanningBudgetExceededError(Exception):
    """Toan bo Case Planning vuot CASE_PLAN_TOTAL_BUDGET_SECONDS."""


class LLMCallError(Exception):
    """Goi LLM that bai (mang, auth, model khong ton tai...). Retry parse khong giup duoc."""


class LLMNotConfiguredError(Exception):
    """Thieu API key / sai LLM_PROVIDER."""


BUDGET_EXCEEDED = "budget_exceeded"


def detect_vague_evidence(case: CaseFile | dict) -> list[dict]:
    """
    Moi hit cua vague_detector (HIGH + LOW, moi truong ke ca learner_claim) o dang log:
    [{"phrase": nhan quy tac, "field", "level", "rule", "match": doan khop}]. Hit HIGH trong khang dinh cua AI
    bi validator reject (xem _validate_case_data), nen case file duoc chap nhan chi con hit LOW.
    """
    data = case.model_dump(mode="json") if isinstance(case, CaseFile) else case
    return [h.to_log() for h in vague_detector.detect(data)]


class FailureKind:
    """Gia tri cot opponent_llm_calls.failure_kind (NULL = thanh cong)."""

    PROVIDER_ERROR = "provider_error"  # loi provider khac -> dung ngay, khong retry
    RATE_LIMITED = "rate_limited"  # 429 -> cho roi thu lai (khong tinh vao CASE_PLAN_MAX_ATTEMPTS)
    TRANSIENT_ERROR = "transient_error"  # loi mang / timeout / 5xx -> thu lai toi da LLM_TRANSIENT_RETRIES (muc 2.12)
    SCHEMA_REJECTED = "schema_rejected"  # Groq 400 json_validate_failed (va khong tu sua duoc ten truong)
    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION = "schema_validation"  # CaseFile (Pydantic) tu choi: thieu truong, "Giả sử", ...
    ARGUMENT_COUNT = "argument_count"
    # Bang chung mo ho muc HIGH (vague_detector) trong khang dinh cua AI. Giu gia tri "banned_phrase" de so
    # sanh lien tuc voi cac batch truoc (truoc 2026-09-29 la validator 4 cum cam).
    BANNED_PHRASE = "banned_phrase"
    SIDE_FLIP = "side_flip"
    BUDGET_EXCEEDED = "budget_exceeded"
    REVIEWER_ERROR = "reviewer_error"  # output cua Stance Reviewer khong parse duoc


# Phan hoi gui kem lan thu ke tiep (thay cho cau nhac chung chung truoc day): noi RO truong nao, sai gi.
_FEEDBACK_HEADER = "[PHẢN HỒI LẦN THỬ TRƯỚC] Output trước của bạn KHÔNG hợp lệ vì:"
_FEEDBACK_FOOTER = (
    "Sửa ĐÚNG các điểm trên, giữ nguyên mọi yêu cầu khác, và trả lại TOÀN BỘ JSON "
    "(chỉ JSON, không thêm text nào khác)."
)


def build_retry_feedback(issues: list[str]) -> str:
    return "\n\n" + _FEEDBACK_HEADER + "\n" + "\n".join(f"- {i}" for i in issues) + "\n" + _FEEDBACK_FOOTER


class _InvalidOutput(Exception):
    """Output LLM goi duoc nhung khong hop le. error: ghi log; issues: phan hoi cho LLM (tieng Viet)."""

    def __init__(self, kind: str, error: str, issues: list[str]):
        super().__init__(error)
        self.kind, self.error, self.issues = kind, error, issues


_PYDANTIC_MESSAGES = {
    "missing": "thiếu trường bắt buộc",
    "string_too_short": "không được để trống",
    "string_type": "phải là chuỗi (string)",
    "list_type": "phải là mảng (array)",
    "model_type": "phải là object",
    "dict_type": "phải là object",
    "model_attributes_type": "phải là object",
}
_NESTED_MODELS = {
    "definitions": Definition,
    "arguments": CaseArgument,
    "anticipated_opponent_arguments": AnticipatedArgument,
}


def _format_loc(loc: tuple) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


# ---------------------------------------------------------------------------
# Ten truong: key THIEU / key LA + tu sua loi go (gpt-oss-120b lap lai "motion_interinterpretation" — muc 2.4j)
# ---------------------------------------------------------------------------
KEY_REPAIR_MAX_DISTANCE = 3  # khoang cach chinh sua (Levenshtein) toi da de coi key la la go sai cua key bat buoc


def edit_distance(a: str, b: str) -> int:
    """Levenshtein (chen / xoa / thay 1 ky tu = 1)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _objects_with_models(data: dict):
    """(prefix, object, model) cho case file va moi object long nhau (definitions / arguments / anticipated)."""
    yield "", data, CaseFile
    for field_name, model in _NESTED_MODELS.items():
        items = data.get(field_name)
        if isinstance(items, list):
            for i, item in enumerate(items):
                if isinstance(item, dict):
                    yield f"{field_name}[{i}].", item, model


def _match_renames(missing: list[str], unknown: list[str]) -> dict[str, str]:
    """{key la: key thieu} — moi key thieu ghep voi key la gan nhat (<= KEY_REPAIR_MAX_DISTANCE), khong trung, khong mo ho."""
    renames: dict[str, str] = {}
    for target in missing:
        scored = sorted((edit_distance(k, target), k) for k in unknown if k not in renames)
        if not scored or scored[0][0] > KEY_REPAIR_MAX_DISTANCE:
            continue
        if len(scored) > 1 and scored[1][0] == scored[0][0]:
            continue  # 2 key la cach deu -> mo ho, khong doan
        renames[scored[0][1]] = target
    return renames


def key_diffs(data: dict) -> list[dict]:
    """Moi object co van de ve ten truong: {"prefix", "missing", "unknown", "renames": {la: dung}}."""
    diffs = []
    for prefix, obj, model in _objects_with_models(data):
        fields = model.model_fields
        required = [name for name, info in fields.items() if info.is_required()]
        missing = [k for k in required if k not in obj]
        unknown = [k for k in obj if k not in fields]
        if missing or unknown:
            diffs.append(
                {"prefix": prefix, "missing": missing, "unknown": unknown, "renames": _match_renames(missing, unknown)}
            )
    return diffs


def key_issues(data: dict) -> list[str]:
    """Phan hoi ve ten truong: neu CA key thieu lan key la ("bạn đã viết 'X', tên đúng là 'Y'")."""
    issues = []
    for d in key_diffs(data):
        p = d["prefix"]
        for wrong, right in d["renames"].items():
            issues.append(f"`{p}{wrong}`: bạn đã viết '{wrong}', tên đúng là '{right}'")
        for key in d["unknown"]:
            if key not in d["renames"]:
                issues.append(f"`{p}{key}`: trường lạ, không có trong cấu trúc mẫu — bỏ đi")
        for key in d["missing"]:
            if key not in d["renames"].values():
                issues.append(f"`{p}{key}`: thiếu trường bắt buộc")
    return issues


def repair_keys(data: dict) -> tuple[dict, list[dict]]:
    """
    Doi ten key la -> key bat buoc dang thieu khi khoang cach chinh sua <= 3. Tra (ban da sua, danh sach doi ten).
    Chi doi ten, KHONG them / xoa noi dung. Ban goc khong bi sua.
    """
    fixed = copy.deepcopy(data)
    renames = []
    for d in key_diffs(fixed):
        if not d["renames"]:
            continue
        obj = next(o for prefix, o, _ in _objects_with_models(fixed) if prefix == d["prefix"])
        for wrong, right in d["renames"].items():
            obj[right] = obj.pop(wrong)
            renames.append({"path": d["prefix"] + right, "from": wrong, "to": right})
    return fixed, renames


def _validation_issues(e: ValidationError, data: object) -> list[str]:
    # Loi "missing" bo qua o day: key_issues() neu lai kem goi y ten dung neu la go sai.
    issues = []
    for err in e.errors():
        kind = err["type"]
        if kind == "missing" and isinstance(data, dict):
            continue
        where = _format_loc(err["loc"]) or "(toàn bộ case file)"
        if kind == "value_error":
            msg = err["msg"].removeprefix("Value error, ")
        elif kind == "too_short":
            msg = f"cần ít nhất {err.get('ctx', {}).get('min_length')} phần tử"
        elif kind == "too_long":
            msg = f"chỉ được tối đa {err.get('ctx', {}).get('max_length')} phần tử"
        else:
            msg = _PYDANTIC_MESSAGES.get(kind, err["msg"])
        issues.append(f"`{where}`: {msg}")
    if isinstance(data, dict):
        issues += key_issues(data)
    return issues


_JSONSCHEMA_DETAIL = re.compile(r"jsonschema: (.+?)[\"'], 'type'")


def _schema_rejected_issues(error: str, failed_generation: str | None) -> list[str]:
    """
    Groq chi bao LOI DAU TIEN cua jsonschema (vd chi "missing 'motion_interpretation'", khong noi key la). Neu
    failed_generation doc duoc -> tu doi chieu va neu CA key thieu lan key la.
    """
    m = _JSONSCHEMA_DETAIL.search(error)
    detail = f" ({m.group(1)})" if m else ""
    issues = [
        f"Output bị nhà cung cấp từ chối vì không khớp JSON schema{detail}. Kiểm tra lại đúng cấu trúc mẫu: "
        "đủ trường, đúng kiểu (object / mảng / chuỗi), không thêm trường lạ."
    ]
    try:
        data = extract_json(failed_generation or "")
    except LLMOutputParseError:
        return issues
    return issues + key_issues(data)


def _validate_case_data(data: object, difficulty: OpponentDifficulty, prompt) -> CaseFile:
    """Nem _InvalidOutput (kem phan hoi) neu du lieu khong hop le o bat ky lop nao."""
    try:
        case_file = CaseFile.model_validate(data)
    except ValidationError as e:
        raise _InvalidOutput(FailureKind.SCHEMA_VALIDATION, str(e), _validation_issues(e, data)) from e

    kind, errors, issues = None, [], []
    expected = prompt.ARGUMENT_COUNT_BY_DIFFICULTY[difficulty]
    if len(case_file.arguments) != expected:
        kind = FailureKind.ARGUMENT_COUNT
        errors.append(f"Do kho '{difficulty.value}' can dung {expected} luan diem, LLM tra ve {len(case_file.arguments)}")
        issues.append(f"`arguments`: độ khó này cần ĐÚNG {expected} luận điểm, bạn trả về {len(case_file.arguments)}.")
    high = vague_detector.high_confidence(case_file.model_dump(mode="json"))
    if high:
        # Uu tien ghi banned_phrase (chi so so sanh prompt); loi so luan diem (neu co) van nam trong error.
        kind = FailureKind.BANNED_PHRASE
        errors.append("banned_phrase: " + "; ".join(f"{h.field}: '{h.match}' ({h.rule})" for h in high))
        issues += [
            f"`{h.field}` có lời viện dẫn bằng chứng mơ hồ \"{h.match}\" ({h.reason}) — bỏ đi, thay bằng lập luận "
            "dựa trên cơ chế hoạt động."
            for h in high
        ]
    if kind is not None:
        raise _InvalidOutput(kind, " | ".join(errors), issues)
    return case_file


def _parse_case_file(raw_output: str, difficulty: OpponentDifficulty, prompt) -> CaseFile:
    """Nem _InvalidOutput (kem phan hoi) neu output khong hop le o bat ky lop nao."""
    try:
        data = extract_json(raw_output)
    except LLMOutputParseError as e:
        raise _InvalidOutput(
            FailureKind.INVALID_JSON,
            str(e),
            ["Output không phải một JSON object hợp lệ (có thể bị cắt ngắn, hoặc có text / markdown thừa ngoài JSON)."],
        ) from e
    return _validate_case_data(data, difficulty, prompt)


def _try_key_repair(
    failed_generation: str | None, difficulty: OpponentDifficulty, prompt
) -> tuple[CaseFile | None, list[dict], list[str]]:
    """
    Groq tu choi schema nhung failed_generation doc duoc: doi ten key go sai (<= 3 ky tu) roi validate CUC BO.
    Qua -> (case_file, renames, []) va KHONG goi lai LLM. Khong sua duoc / van khong hop le -> (None, renames, issues).
    """
    try:
        data = extract_json(failed_generation or "")
    except LLMOutputParseError:
        return None, [], []
    fixed, renames = repair_keys(data)
    if not renames:
        return None, [], []
    if key_diffs(fixed):  # con key thieu / la khac -> khong chap nhan (strict schema cung se tu choi)
        return None, renames, []
    try:
        return _validate_case_data(fixed, difficulty, prompt), renames, []
    except _InvalidOutput as e:
        return None, renames, e.issues


def _try_array_repair(
    failed_generation: str | None, difficulty: OpponentDifficulty, prompt
) -> tuple[CaseFile | None, dict | None, list[str]]:
    """
    Groq tu choi vi output la "MANG TACH" (json_repair, muc 2.12): dung lai object (+ sua ten key go sai) roi validate
    CUC BO. Qua -> (case_file, thong tin log array_repaired, []). Khong phai dang nay -> (None, None, []). Dung lai
    duoc nhung khong hop le -> (None, None, issues) — xu ly nhu schema_rejected.
    """
    repaired = repair_split_array(failed_generation, CaseFile.model_fields)
    if repaired is None:
        return None, None, []
    data, info = repaired
    fixed, renames = repair_keys(data)
    if key_diffs(fixed):
        return None, None, key_issues(fixed)
    try:
        case_file = _validate_case_data(fixed, difficulty, prompt)
    except _InvalidOutput as e:
        return None, None, e.issues
    return case_file, {**info, "renames": renames}, []


_PENDING_REVIEW = "cho stance review"


@dataclass
class AttemptRecord:
    """1 lan goi LLM = 1 dong opponent_llm_calls."""

    attempt: int
    user_prompt: str
    raw_output: str | None
    success: bool
    error: str | None
    latency_ms: int
    vague_evidence: list[dict] | None = None  # [{phrase, field}]; None = khong quet (output khong hop le / loi)
    purpose: LLMCallPurpose = LLMCallPurpose.CASE_PLAN
    # Metadata rieng cho loi goi KHONG phai planner (vd stance review dung prompt/model/temperature khac).
    # None = lay tu CasePlanOutcome.
    system_prompt: str | None = None
    prompt_version: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    temperature: float | None = None
    schema_rejected: bool = False  # provider tu choi output vi sai JSON schema (Groq 400 json_validate_failed)
    reviewer_verdict: ReviewerVerdict | None = None
    reviewer_detail: dict | None = None
    failure_kind: str | None = None  # FailureKind.*; None = thanh cong
    retry_feedback: str | None = None  # phan hoi DA GUI cho lan thu ke tiep vi dong nay khong hop le
    tokens_in: int | None = None  # usage thuc te tu provider (None neu loi / khong co)
    tokens_out: int | None = None
    rate_limit_wait_ms: int | None = None  # dong 429: thoi gian DA CHO truoc khi goi lai
    # Groq tu choi schema nhung ten truong go sai da duoc TU SUA (khong goi lai LLM):
    # {"event": "key_repaired", "renames": [{"path", "from", "to"}], "provider_error": ...}
    key_repairs: dict | None = None
    reasoning_tokens: int | None = None  # token suy luan rieng (neu provider tra), da nam trong tokens_out
    finish_reason: str | None = None
    reasoning_effort: str | None = None  # DA GUI (None = khong gui)


@dataclass
class CasePlanOutcome:
    case_file: CaseFile | None
    system_prompt: str
    prompt_version: str
    temperature: float
    llm_provider: str
    llm_model: str
    reviewer_model: str | None = None  # None = khong chay Stance Reviewer
    attempts: list[AttemptRecord] = field(default_factory=list)
    llm_error: str | None = None  # set neu dung vi loi provider (khong phai loi parse)
    budget_exceeded: bool = False


@dataclass
class _Progress:
    """Trang thai vong thu, doc duoc tu ngoai khi asyncio.wait_for huy giua chung."""

    user_prompt: str
    next_attempt: int = 1
    # (attempt, user_prompt, started, overrides) cua lan goi LLM dang cho tra loi
    in_flight: tuple[int, str, float, dict] | None = None
    # (user_prompt, overrides) cua lan goi dang CHO retry rate-limit (chua goi)
    waiting: tuple[str, dict] | None = None


@dataclass
class _Ctx:
    outcome: CasePlanOutcome
    progress: _Progress
    settings: Settings
    rate_limit_retries: int = 0  # dung chung cho moi loi goi (planner + reviewer)
    transient_retries: int = 0  # loi mang thoang qua, dung chung moi loi goi


class _CallFailed(Exception):
    """Lan goi LLM that bai (da ghi AttemptRecord)."""

    def __init__(self, record: AttemptRecord):
        super().__init__(record.error)
        self.record = record


# Cho 429 = thoi gian provider yeu cau + jitter (tranh nhieu request cung goi lai dung 1 thoi diem).
RATE_LIMIT_JITTER_SECONDS = (1.0, 2.0)


def _jitter() -> float:
    return random.uniform(*RATE_LIMIT_JITTER_SECONDS)


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _usage_fields(client: LLMClient) -> dict:
    usage = getattr(client, "last_usage", None) or {}
    return {
        "tokens_in": usage.get("tokens_in"), "tokens_out": usage.get("tokens_out"),
        "reasoning_tokens": usage.get("reasoning_tokens"), "finish_reason": getattr(client, "last_finish_reason", None),
    }


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def _call_llm(
    ctx: _Ctx,
    client: LLMClient,
    system_prompt: str,
    user_prompt: str,
    *,
    purpose: LLMCallPurpose,
    temperature: float,
    max_tokens: int,
    json_schema: dict | None,
    prompt_version: str | None = None,
) -> tuple[int, str, int, dict]:
    """
    Goi LLM DUNG 1 HTTP request (SDK da tat retry ngam); 429 -> cho DUNG thoi gian provider yeu cau (retry-after
    / "try again in Xs", fallback CASE_PLAN_RATE_LIMIT_WAIT_SECONDS) + jitter 1-2s roi thu lai. Moi lan la 1 dong
    log; lan cho 429 KHONG tinh vao so lan thu Case Planning; tong thoi gian van bi chan boi budget (wait_for).
    That bai -> ghi AttemptRecord roi nem _CallFailed. Thanh cong -> tra (attempt, raw, latency_ms, meta) voi
    meta = overrides + token thuc te; NGUOI GOI tu ghi AttemptRecord thanh cong (vi con phai parse / review).
    """
    overrides: dict = {}
    if purpose != LLMCallPurpose.CASE_PLAN:
        overrides = dict(
            purpose=purpose,
            system_prompt=system_prompt,
            prompt_version=prompt_version,
            llm_provider=client.provider,
            llm_model=client.model,
            temperature=temperature,
        )
    progress, settings = ctx.progress, ctx.settings
    # Chi planner gui reasoning_effort (CASE_PLAN_REASONING_EFFORT); None = khong gui -> hanh vi nhu truoc.
    effort = settings.case_plan_reasoning_effort if purpose == LLMCallPurpose.CASE_PLAN else None
    effort_kwargs = {"reasoning_effort": effort} if effort else {}
    overrides = {**overrides, "reasoning_effort": effort} if effort else overrides
    while True:
        attempt = progress.next_attempt
        progress.next_attempt += 1
        started = time.perf_counter()
        progress.in_flight, progress.waiting = (attempt, user_prompt, started, overrides), None
        try:
            # LLMClient la sync (ban sao tu Evaluation service) -> chay trong thread de khong chan event loop.
            raw_output = await asyncio.to_thread(
                client.generate,
                system_prompt,
                user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                json_schema=json_schema,
                **effort_kwargs,
            )
        except Exception as e:  # noqa: BLE001 — moi loi provider deu phai duoc log vao DB
            progress.in_flight = None
            error = f"{type(e).__name__}: {e}"
            rejected = schema_rejected_output(e)
            rate_limited = rejected is None and is_rate_limit_error(e)
            transient = rejected is None and not rate_limited and is_transient_error(e)
            if rejected is not None:
                kind = FailureKind.SCHEMA_REJECTED
            elif rate_limited:
                kind = FailureKind.RATE_LIMITED
            elif transient:
                kind = FailureKind.TRANSIENT_ERROR
            else:
                kind = FailureKind.PROVIDER_ERROR
            record = AttemptRecord(
                attempt,
                user_prompt,
                rejected or None,
                False,
                error[:4000],
                _elapsed_ms(started),
                schema_rejected=rejected is not None,
                failure_kind=kind,
                **overrides,
                **_usage_fields(client),
            )
            ctx.outcome.attempts.append(record)
            if rate_limited and ctx.rate_limit_retries < settings.case_plan_rate_limit_retries:
                ctx.rate_limit_retries += 1
                requested = rate_limit_wait_seconds(e)
                base = requested if requested is not None else settings.case_plan_rate_limit_wait_seconds
                wait = base + _jitter()
                record.rate_limit_wait_ms = int(wait * 1000)
                logger.warning(
                    "%s bi rate-limit (lan %d), provider yeu cau cho %s -> cho %.1fs",
                    purpose.value, attempt, f"{requested:.1f}s" if requested is not None else "?", wait,
                )
                progress.waiting = (user_prompt, overrides)
                await _sleep(wait)
                continue
            if transient and ctx.transient_retries < settings.llm_transient_retries:
                ctx.transient_retries += 1
                wait = settings.llm_transient_retry_wait_seconds * 2 ** (ctx.transient_retries - 1) + _jitter()
                logger.warning("%s loi mang thoang qua (lan %d): %s -> cho %.1fs", purpose.value, ctx.transient_retries,
                               error[:200], wait)
                progress.waiting = (user_prompt, overrides)
                await _sleep(wait)
                continue
            raise _CallFailed(record) from e
        progress.in_flight = None
        return attempt, raw_output, _elapsed_ms(started), {**overrides, **_usage_fields(client)}


async def _review_stance(
    ctx: _Ctx, reviewer_client: LLMClient, motion: str, case_file: CaseFile, ai_side: DebateSide
) -> tuple[ReviewerVerdict, dict]:
    """
    Stance Reviewer cho case file: CHI dua motion + claim cua tung argument + weighing (khong dua phe).
    Reviewer loi (goi that bai / output sai) -> THU LAI 1 LAN (khong tinh vao so lan thu Case Planning);
    van loi -> unclear, KHONG chan Case Planning. Moi lan goi deu la 1 dong log.
    """
    review_version = ctx.settings.stance_review_prompt_version
    spec = stance_reviewer.REVIEW_VERSIONS[review_version]  # prompt + schema + parse cua phien ban
    # v2 / v3 doc them reasoning (v1 bo qua truong nay) — van KHONG dua phe.
    statements = [stance_reviewer.Statement(a.id, a.claim, a.reasoning) for a in case_file.arguments]
    ids = [st.id for st in statements]
    system_prompt, user_prompt = spec.build_prompt(motion, statements, case_file.weighing)
    schema = spec.build_schema(ids, has_summary=True) if ctx.settings.case_plan_use_json_schema else None

    for call_no in range(1, stance_reviewer.MAX_CALLS + 1):
        try:
            attempt, raw_output, latency_ms, meta = await _call_llm(
                ctx,
                reviewer_client,
                system_prompt,
                user_prompt,
                purpose=LLMCallPurpose.STANCE_REVIEW,
                temperature=stance_reviewer.TEMPERATURE,
                max_tokens=ctx.settings.stance_review_max_tokens,
                json_schema=schema,
                prompt_version=review_version,
            )
        except _CallFailed as f:
            failed = f.record
        else:
            record = AttemptRecord(attempt, user_prompt, raw_output, True, None, latency_ms, **meta)
            ctx.outcome.attempts.append(record)
            try:
                review, extra = spec.parse(raw_output, ids, has_summary=True)
            except (LLMOutputParseError, ValidationError, ValueError) as e:
                record.success, record.error, record.failure_kind = False, str(e)[:4000], FailureKind.REVIEWER_ERROR
                failed = record
            else:
                verdict, detail = stance_reviewer.judge(review, ai_side, review_version, extra)
                detail["reviewer_calls"] = call_no
                record.reviewer_verdict, record.reviewer_detail = verdict, detail
                return verdict, detail

        if call_no < stance_reviewer.MAX_CALLS:
            logger.warning("Stance review loi (lan goi %d), thu lai: %s", call_no, failed.error)
            continue
        verdict, detail = stance_reviewer.reviewer_failure(failed.error or "", review_version)
        detail["reviewer_calls"] = call_no
        failed.reviewer_verdict, failed.reviewer_detail = verdict, detail
        logger.warning("Stance review loi %d lan, coi nhu unclear: %s", call_no, failed.error)
        return verdict, detail
    raise AssertionError("unreachable")  # pragma: no cover


# Retry khi reviewer bao side_flip: sinh lai tu prompt GOC, KHONG phan hoi (muc 2.4m). Batch v5: 3/3 bao side_flip cua
# reviewer v3 la bao sai; phan hoi "ban dang bao ve phe nguoi hoc" co the ep generator doi phe that.
SIDE_FLIP_NEUTRAL_RETRY = "side_flip_neutral_retry"


async def _attempt_loop(
    ctx: _Ctx,
    prompt,
    motion: str,
    ai_side: DebateSide,
    difficulty: OpponentDifficulty,
    client: LLMClient,
    reviewer_client: LLMClient | None,
) -> None:
    """
    Output KHONG HOP LE -> retry CO PHAN HOI (neu ro truong nao, vi pham gi), toi da case_plan_max_attempts
    lan (dem chung): sai JSON / schema / so luan diem / "Giả sử" / cum bi cam, Groq tu choi schema.
    Stance Reviewer bao side_flip -> retry TRUNG TINH: prompt goc, khong phan hoi (van tinh vao so lan thu).
    Loi provider khac -> dung ngay. "unclear" -> chi canh bao.
    Phan hoi luon gan vao prompt GOC (khong cong don qua cac lan) va duoc luu vao retry_feedback.
    """
    outcome, progress, settings = ctx.outcome, ctx.progress, ctx.settings
    base_user_prompt = progress.user_prompt
    invalid_outputs = 0
    response_schema = prompt.build_response_schema(difficulty) if settings.case_plan_use_json_schema else None

    def out_of_attempts() -> bool:
        nonlocal invalid_outputs
        invalid_outputs += 1
        return invalid_outputs >= settings.case_plan_max_attempts

    def retry_with_feedback(record: AttemptRecord, issues: list[str]) -> bool:
        """True = het luot thu (dung lai)."""
        if out_of_attempts():
            return True
        feedback = build_retry_feedback(issues)
        record.retry_feedback = feedback.strip()
        progress.user_prompt = base_user_prompt + feedback
        logger.info("Case plan lan thu %d khong hop le (%s), retry kem phan hoi: %s", record.attempt, record.failure_kind, issues)
        return False

    def retry_neutral(record: AttemptRecord) -> bool:
        """side_flip: sinh lai tu prompt goc, khong noi generator 'da lat phe'. True = het luot thu."""
        if out_of_attempts():
            return True
        record.reviewer_detail = {**(record.reviewer_detail or {}), "retry": SIDE_FLIP_NEUTRAL_RETRY}
        progress.user_prompt = base_user_prompt
        logger.info("Case plan lan thu %d: %s (khong gui phan hoi)", record.attempt, SIDE_FLIP_NEUTRAL_RETRY)
        return False

    while True:
        user_prompt = progress.user_prompt
        try:
            attempt, raw_output, latency_ms, meta = await _call_llm(
                ctx,
                client,
                outcome.system_prompt,
                user_prompt,
                purpose=LLMCallPurpose.CASE_PLAN,
                temperature=settings.case_plan_temperature,
                max_tokens=settings.case_plan_max_tokens,
                json_schema=response_schema,
            )
        except _CallFailed as f:
            if f.record.failure_kind != FailureKind.SCHEMA_REJECTED:
                logger.error("Goi LLM that bai (case plan, lan %d): %s", f.record.attempt, f.record.error)
                outcome.llm_error = f.record.error
                return
            # Provider tu choi output vi sai JSON schema. Thu sua TAT DINH: "mang tach" (muc 2.12), roi ten key go sai
            # (<= 3 ky tu), validate cuc bo: qua -> chap nhan, KHONG goi lai LLM. Khong duoc -> retry co phan hoi.
            case_file, array_info, extra_issues = _try_array_repair(f.record.raw_output, difficulty, prompt)
            repair_log = None
            if case_file is not None:
                repair_log = array_info
            else:
                case_file, renames, key_extra = _try_key_repair(f.record.raw_output, difficulty, prompt)
                extra_issues += key_extra
                if case_file is not None:
                    repair_log = {"event": "key_repaired", "renames": renames}
            if case_file is None:
                issues = _schema_rejected_issues(f.record.error or "", f.record.raw_output) + extra_issues
                if retry_with_feedback(f.record, issues):
                    return
                continue
            record = f.record
            record.key_repairs = {**repair_log, "provider_error": (record.error or "")[:1000]}
            record.success, record.error, record.failure_kind = True, None, None
            logger.info("Case plan lan thu %d: %s, khong goi lai LLM: %s", record.attempt, repair_log["event"], repair_log)
        else:
            try:
                case_file = _parse_case_file(raw_output, difficulty, prompt)
            except _InvalidOutput as e:
                logger.warning("Case plan lan thu %d khong hop le (%s): %s", attempt, e.kind, e.error)
                record = AttemptRecord(
                    attempt, user_prompt, raw_output, False, e.error[:4000], latency_ms, failure_kind=e.kind, **meta
                )
                outcome.attempts.append(record)
                if retry_with_feedback(record, e.issues):
                    return
                continue
            record = AttemptRecord(attempt, user_prompt, raw_output, True, None, latency_ms, **meta)
            outcome.attempts.append(record)

        record.vague_evidence = detect_vague_evidence(case_file)
        if record.vague_evidence:
            logger.info("Case plan co dau hieu bang chung mo ho (chi log): %s", record.vague_evidence)

        if reviewer_client is not None:
            record.success, record.error = False, _PENDING_REVIEW
            verdict, detail = await _review_stance(ctx, reviewer_client, motion, case_file, ai_side)
            record.reviewer_verdict, record.reviewer_detail = verdict, detail
            if verdict == ReviewerVerdict.SIDE_FLIP:
                record.error = (
                    f"side_flip: trong tai danh gia {detail['flipped_ids']} nguoc phe {ai_side.value} "
                    f"(ky vong {detail['expected_position']})"
                )
                record.failure_kind = FailureKind.SIDE_FLIP
                logger.warning("Case plan lan thu %d lat phe: %s", record.attempt, detail["flipped_ids"])
                if retry_neutral(record):
                    return
                continue
            if verdict == ReviewerVerdict.UNCLEAR:
                logger.warning("Stance review khong ro (lan %d): %s", record.attempt, detail)
            record.success, record.error = True, None

        outcome.case_file = case_file
        return


def prompt_module(settings: Settings):
    """Module prompt theo CASE_PLAN_PROMPT_VERSION (v3 / v4 / v5 dung chung CaseFile + validator)."""
    return PROMPT_MODULES[settings.case_plan_prompt_version]


async def generate_case_file(
    motion: str,
    ai_side: DebateSide,
    learner_side: DebateSide,
    difficulty: OpponentDifficulty,
    client: LLMClient,
    settings: Settings,
    reviewer_client: LLMClient | None = None,
) -> CasePlanOutcome:
    """
    Goi LLM sinh case file (+ Stance Reviewer neu co reviewer_client) trong gioi han
    CASE_PLAN_TOTAL_BUDGET_SECONDS — bao MOI lan goi (planner + reviewer) va moi lan cho rate-limit.
    Prompt theo CASE_PLAN_PROMPT_VERSION. KHONG nem exception — ket qua nam trong outcome.
    """
    prompt = prompt_module(settings)
    system_prompt, user_prompt = prompt.build_case_plan_prompt(motion, ai_side, learner_side, difficulty)
    outcome = CasePlanOutcome(
        case_file=None,
        system_prompt=system_prompt,
        prompt_version=prompt.PROMPT_VERSION,
        temperature=settings.case_plan_temperature,
        llm_provider=client.provider,
        llm_model=client.model,
        reviewer_model=reviewer_client.model if reviewer_client is not None else None,
    )
    progress = _Progress(user_prompt=user_prompt)
    ctx = _Ctx(outcome=outcome, progress=progress, settings=settings)
    budget = settings.case_plan_total_budget_seconds

    try:
        await asyncio.wait_for(
            _attempt_loop(ctx, prompt, motion, ai_side, difficulty, client, reviewer_client),
            timeout=budget,
        )
    except TimeoutError:
        # LUU Y: thread dang goi LLM (neu co) KHONG bi huy — no chay tiep toi khi HTTP xong/timeout,
        # ket qua bi bo qua. Chi co tran thoi gian cua request la duoc dam bao.
        outcome.budget_exceeded = True
        for a in outcome.attempts:
            if a.error == _PENDING_REVIEW:
                a.error = f"{BUDGET_EXCEEDED}: het budget truoc khi stance review xong"
                a.failure_kind = FailureKind.BUDGET_EXCEEDED
        if progress.in_flight is not None:
            attempt, up, started, overrides = progress.in_flight
            detail, latency_ms = "dang cho LLM tra loi", _elapsed_ms(started)
        else:
            attempt = progress.next_attempt
            up, overrides = progress.waiting or (progress.user_prompt, {})
            detail, latency_ms = "dang cho retry rate-limit, chua goi LLM", 0
        purpose = overrides.get("purpose", LLMCallPurpose.CASE_PLAN)
        error = f"{BUDGET_EXCEEDED}: het {budget}s cho toan bo Case Planning ({detail}, {purpose.value})"
        logger.error("Case plan %s", error)
        outcome.attempts.append(
            AttemptRecord(attempt, up, None, False, error, latency_ms, failure_kind=FailureKind.BUDGET_EXCEEDED, **overrides)
        )

    return outcome


async def get_session_by_external_id(db: AsyncSession, external_session_id: str) -> OpponentSession:
    session = await db.scalar(
        select(OpponentSession).where(OpponentSession.external_session_id == external_session_id)
    )
    if session is None:
        raise SessionNotFoundError(external_session_id)
    return session


async def get_case_file(db: AsyncSession, session_id: uuid.UUID) -> OpponentCaseFile | None:
    return await db.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == session_id))


# Cac truong phai trung khop khi goi lai cung external_session_id.
_IDENTITY_FIELDS = ("motion", "learner_side", "ai_side", "difficulty")


def _ensure_same_data(session: OpponentSession, req: CreateSessionRequest) -> None:
    mismatched = [f for f in _IDENTITY_FIELDS if getattr(session, f) != getattr(req, f)]
    if mismatched:
        raise SessionDataMismatchError(req.external_session_id, mismatched)


def _is_stale(session: OpponentSession, settings: Settings) -> bool:
    age = datetime.now(timezone.utc) - session.updated_at
    return age >= timedelta(seconds=settings.case_plan_stale_after_seconds)


async def create_session_and_plan(
    db: AsyncSession,
    req: CreateSessionRequest,
    client_factory: Callable[[], LLMClient],
    settings: Settings,
    reviewer_factory: Callable[[], LLMClient | None] | None = None,
) -> tuple[OpponentSession, bool]:
    """
    Tao session + chay Case Planning dong bo. Tra ve (session, created).

    Idempotent theo external_session_id:
    - Chua co            -> tao (status PLANNING ngay trong INSERT), goi LLM, created=True.
    - Da co, du lieu khac (motion/learner_side/ai_side/difficulty) -> 409, neu ro truong nao khac.
    - Da co, READY       -> tra ve session cu, KHONG goi LLM, created=False.
    - Da co, PLANNING    -> 409 (request khac dang xu ly), tru khi qua CASE_PLAN_STALE_AFTER_SECONDS.
    - Da co, FAILED/ket  -> chay lai Case Planning (chua co case file nao nen khong vi pham
                            "1 case file / session"), created=False.
    """
    if req.learner_side == req.ai_side:
        raise InvalidSidesError("learner_side va ai_side phai khac nhau")

    existing = await db.scalar(
        select(OpponentSession).where(OpponentSession.external_session_id == req.external_session_id)
    )
    if existing is not None:
        _ensure_same_data(existing, req)
        if existing.status == SessionStatus.READY:
            return existing, False

    # Lay LLM client TRUOC khi ghi gi vao DB: thieu key -> 503 ma khong de lai session ket o PLANNING.
    client = client_factory()
    reviewer_client = reviewer_factory() if reviewer_factory is not None else None

    # INSERT ... ON CONFLICT DO NOTHING: 2 request dong thoi cung external_session_id chi 1 ben
    # tao duoc row (va "so huu" lan planning dau tien), ben kia roi vao nhanh "da co".
    inserted_id = await db.scalar(
        pg_insert(OpponentSession)
        .values(
            external_session_id=req.external_session_id,
            motion=req.motion,
            ai_side=req.ai_side,
            learner_side=req.learner_side,
            difficulty=req.difficulty,
            language=req.language,
            status=SessionStatus.PLANNING,
        )
        .on_conflict_do_nothing(index_elements=[OpponentSession.external_session_id])
        .returning(OpponentSession.id)
    )

    if inserted_id is not None:
        await db.commit()
        session = await db.get(OpponentSession, inserted_id, populate_existing=True)
        created = True
    else:
        # populate_existing: lay trang thai moi nhat tu DB, khong dung ban cu trong identity map.
        session = await db.scalar(
            select(OpponentSession)
            .where(OpponentSession.external_session_id == req.external_session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        created = False
        try:
            _ensure_same_data(session, req)
        except SessionDataMismatchError:
            await db.rollback()
            raise
        if session.status == SessionStatus.READY:
            await db.commit()
            return session, False
        if session.status == SessionStatus.PLANNING:
            if not _is_stale(session, settings):
                await db.rollback()
                raise CasePlanningInProgressError(req.external_session_id)
            logger.warning("Session %s ket o PLANNING qua lau, cho phep chay lai", req.external_session_id)
        session.status = SessionStatus.PLANNING
        await db.commit()  # nha lock, khong giu transaction trong luc cho LLM

    session, lost_race = await _run_case_planning(db, session, client, settings, reviewer_client)
    return session, created and not lost_race


def _llm_call_rows(session_id: uuid.UUID, outcome: CasePlanOutcome) -> list[OpponentLLMCall]:
    return [
        OpponentLLMCall(
            session_id=session_id,
            purpose=a.purpose,
            attempt=a.attempt,
            prompt_version=a.prompt_version or outcome.prompt_version,
            llm_provider=a.llm_provider or outcome.llm_provider,
            llm_model=a.llm_model or outcome.llm_model,
            temperature=outcome.temperature if a.temperature is None else a.temperature,
            system_prompt=a.system_prompt or outcome.system_prompt,
            user_prompt=a.user_prompt,
            raw_output=a.raw_output,
            success=a.success,
            error=a.error,
            latency_ms=a.latency_ms,
            vague_evidence=a.vague_evidence,
            reviewer_verdict=a.reviewer_verdict,
            reviewer_detail=a.reviewer_detail,
            failure_kind=a.failure_kind,
            retry_feedback=a.retry_feedback,
            tokens_in=a.tokens_in,
            tokens_out=a.tokens_out,
            rate_limit_wait_ms=a.rate_limit_wait_ms,
            key_repairs=a.key_repairs,
            reasoning_tokens=a.reasoning_tokens,
            finish_reason=a.finish_reason,
            reasoning_effort=a.reasoning_effort,
        )
        for a in outcome.attempts
    ]


async def _run_case_planning(
    db: AsyncSession,
    session: OpponentSession,
    client: LLMClient,
    settings: Settings,
    reviewer_client: LLMClient | None = None,
) -> tuple[OpponentSession, bool]:
    """Tra ve (session, lost_race). lost_race=True: request khac da ghi case file truoc."""
    session_id = session.id
    outcome = await generate_case_file(
        session.motion, session.ai_side, session.learner_side, session.difficulty, client, settings, reviewer_client
    )

    db.add_all(_llm_call_rows(session_id, outcome))
    if outcome.case_file is not None:
        db.add(
            OpponentCaseFile(
                session_id=session_id,
                content=outcome.case_file.model_dump(mode="json"),
                prompt_version=outcome.prompt_version,
                llm_provider=outcome.llm_provider,
                llm_model=outcome.llm_model,
                temperature=outcome.temperature,
            )
        )
        session.status = SessionStatus.READY
    else:
        session.status = SessionStatus.FAILED

    # Commit ca khi that bai: log LLM call la bang chung de debug prompt.
    try:
        await db.commit()
    except IntegrityError as e:
        if "uq_opponent_case_files_session_id" not in str(e.orig):
            raise
        # Request khac (vd chay lai 1 phien bi coi la ket) da ghi case file truoc -> case file cua
        # ta bi loai, dung ban da co. Log LLM call van giu lai (bi rollback cung case file nen ghi lai).
        logger.warning("Session %s da co case file tu request khac, bo case file vua sinh", session_id)
        await db.rollback()
        db.add_all(_llm_call_rows(session_id, outcome))
        await db.commit()
        existing = await db.get(OpponentSession, session_id, populate_existing=True)
        return existing, True

    if outcome.budget_exceeded:
        raise CasePlanningBudgetExceededError(outcome.attempts[-1].error)
    if outcome.llm_error is not None:
        raise LLMCallError(outcome.llm_error)
    if outcome.case_file is None:
        raise CasePlanningError(
            f"LLM tra ve case file khong hop le sau {len(outcome.attempts)} lan thu. "
            f"Loi cuoi: {outcome.attempts[-1].error if outcome.attempts else 'khong ro'}"
        )
    return session, False
