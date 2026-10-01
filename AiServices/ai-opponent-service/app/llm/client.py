"""
Lop truu tuong goi LLM API.

BAN SAO CO CHU DICH tu adpp-ai-service/app/services/llm_client.py (AI Evaluation
service). KHONG import cheo giua 2 service — moi service deploy doc lap, khong
phu thuoc code cua nhau. Neu sua bug o 1 ben, can can nhac sua ben kia.
Xem docs/AI_DEVELOPMENT_LOG.md muc 2.1.

Khac ban goc (thay doi toi thieu):
- generate() nhan them `temperature` / `max_tokens` tuy chon, de moi tac vu sinh
  (Case Planning, ...) dung tham so rieng ma khong phai tao client moi.
  Khong truyen -> dung LLM_TEMPERATURE / LLM_MAX_TOKENS nhu ban goc.
- Them thuoc tinh `provider` / `model` de ghi log vao bang opponent_llm_calls.
- Them GroqClient default model openai/gpt-oss-120b (xem config.py).
- TAT RETRY NGAM cua SDK: OpenAI / Anthropic / Groq khoi tao voi max_retries=0 (SDK mac dinh
  tu retry 2 lan, khong ai thay, khong duoc log); Gemini dat ro retry attempts=1 va them timeout
  (ban goc khong co timeout cho Gemini). Moi generate() = DUNG 1 HTTP request.
- BO vong retry rate-limit trong GroqClient: chuyen len opponent/service.py de moi lan thu
  deu duoc ghi vao opponent_llm_calls va nam trong CASE_PLAN_TOTAL_BUDGET_SECONDS.
  generate() gio nem thang loi 429 (RateLimitError) cho service xu ly.
- Moi client ghi `last_usage` = {"tokens_in", "tokens_out"} cua lan generate() gan nhat (None neu loi /
  provider khong tra usage) de log token thuc te. KHONG an toan neu 1 instance duoc goi DONG THOI — service tao
  client moi cho moi request, batch chay tuan tu.
- generate() nhan them `json_schema` tuy chon (structured output, strict). Hien CHI GroqClient dung
  (da kiem chung voi openai/gpt-oss-120b); provider khac bo qua va giu JSON mode cu.
- THEM generate_chat(): hoi thoai nhieu tin (role user / assistant), output VAN BAN THUAN (khong JSON mode) —
  cho bai noi trong tran (Giai doan 3). Ban goc khong co vi Evaluation chi cham 1 lan, tra JSON.
- generate() / generate_chat() nhan them `reasoning_effort` ("low" / "medium" / "high"; None = khong gui, provider
  dung mac dinh). CHI GroqClient gui (gpt-oss tren Groq, mac dinh "medium" — dev log muc 2.10); provider khac bo qua.
- Moi client ghi them `last_finish_reason` ("stop" / "length" / ...; Anthropic "max_tokens" va Gemini "MAX_TOKENS"
  quy ve "length") va `last_usage["reasoning_tokens"]` (OpenAI / Groq: usage.completion_tokens_details.reasoning_tokens;
  Gemini: thoughts_token_count; None neu provider khong tra).

Interface van la SYNC (giong ban goc); service async goi qua asyncio.to_thread.
"""
import re
from abc import ABC, abstractmethod

from app.core.config import Settings

# Khong de SDK tu retry: moi retry phai do code cua service thuc hien va ghi log.
SDK_MAX_RETRIES = 0


class LLMClient(ABC):
    provider: str = "unknown"
    model: str = "unknown"
    last_usage: dict | None = None  # {"tokens_in", "tokens_out", "reasoning_tokens"} cua lan goi gan nhat
    last_finish_reason: str | None = None  # "stop" / "length" (het max_tokens) / ... cua lan goi gan nhat

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        """
        Goi LLM, tra ve text output (raw). Nem exception neu goi that bai.
        json_schema: neu provider ho tro structured output thi ep output theo schema; khong thi bo qua.
        """
        raise NotImplementedError

    def generate_chat(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        """
        Hoi thoai: messages = [{"role": "user" | "assistant", "content": str}, ...], tin cuoi nen la "user".
        Tra ve van ban thuan (KHONG ep JSON). Nem exception neu goi that bai / noi dung rong.
        """
        raise NotImplementedError(f"{type(self).__name__} chua ho tro generate_chat")


def _chat_messages(system_prompt: str, messages: list[dict]) -> list[dict]:
    """Dinh dang chat.completions (OpenAI / Groq)."""
    return [{"role": "system", "content": system_prompt}] + [{"role": m["role"], "content": m["content"]} for m in messages]


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(self, settings: Settings):
        from openai import OpenAI  # import cuc bo de khong bat buoc cai dat neu khong dung provider nay

        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY chua duoc set trong .env")

        self._client = OpenAI(
            api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds, max_retries=SDK_MAX_RETRIES
        )
        self.model = settings.openai_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    def generate(
        self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None, reasoning_effort=None
    ) -> str:
        self.last_usage, self.last_finish_reason = None, None
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=max_tokens or self._max_tokens,
            response_format={"type": "json_object"},  # bat che do JSON mode cua OpenAI cho chac chan
        )
        self.last_usage = _openai_usage(response)
        self.last_finish_reason = response.choices[0].finish_reason
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI tra ve noi dung rong")
        return content

    def generate_chat(self, system_prompt, messages, temperature=None, max_tokens=None, reasoning_effort=None) -> str:
        self.last_usage, self.last_finish_reason = None, None
        response = self._client.chat.completions.create(
            model=self.model,
            messages=_chat_messages(system_prompt, messages),
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=max_tokens or self._max_tokens,
        )
        self.last_usage = _openai_usage(response)
        self.last_finish_reason = response.choices[0].finish_reason
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI tra ve noi dung rong")
        return content


class AnthropicClient(LLMClient):
    provider = "anthropic"

    def __init__(self, settings: Settings):
        from anthropic import Anthropic  # import cuc bo

        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY chua duoc set trong .env")

        self._client = Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds, max_retries=SDK_MAX_RETRIES
        )
        self.model = settings.anthropic_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    def generate(
        self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None, reasoning_effort=None
    ) -> str:
        self.last_usage, self.last_finish_reason = None, None
        response = self._client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=max_tokens or self._max_tokens,
        )
        # Anthropic tra ve list cac content block; ghep phan text lai
        usage = getattr(response, "usage", None)
        self.last_usage = (
            {"tokens_in": usage.input_tokens, "tokens_out": usage.output_tokens} if usage is not None else None
        )
        self.last_finish_reason = "length" if response.stop_reason == "max_tokens" else response.stop_reason
        text_parts = [block.text for block in response.content if block.type == "text"]
        content = "".join(text_parts)
        if not content:
            raise RuntimeError("Anthropic tra ve noi dung rong")
        return content

    def generate_chat(self, system_prompt, messages, temperature=None, max_tokens=None, reasoning_effort=None) -> str:
        self.last_usage, self.last_finish_reason = None, None
        response = self._client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=max_tokens or self._max_tokens,
        )
        usage = getattr(response, "usage", None)
        self.last_usage = (
            {"tokens_in": usage.input_tokens, "tokens_out": usage.output_tokens} if usage is not None else None
        )
        self.last_finish_reason = "length" if response.stop_reason == "max_tokens" else response.stop_reason
        content = "".join(block.text for block in response.content if block.type == "text")
        if not content:
            raise RuntimeError("Anthropic tra ve noi dung rong")
        return content


class GeminiClient(LLMClient):
    """
    Dung SDK moi `google-genai` (khong dung `google-generativeai` — SDK cu dang bi
    Google khai tu dan). Free tier: chi can API key tu aistudio.google.com/apikey.
    """

    provider = "gemini"

    def __init__(self, settings: Settings):
        from google import genai
        from google.genai import types

        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY chua duoc set trong .env")

        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=settings.llm_timeout_seconds * 1000,  # Gemini tinh bang ms
                retry_options=types.HttpRetryOptions(attempts=1),  # chi 1 lan goi, khong retry ngam
            ),
        )
        self._types = types
        self.model = settings.gemini_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    def generate(
        self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None, reasoning_effort=None
    ) -> str:
        self.last_usage, self.last_finish_reason = None, None
        response = self._client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=self._types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=self._temperature if temperature is None else temperature,
                max_output_tokens=max_tokens or self._max_tokens,
                response_mime_type="application/json",  # bat che do tra JSON, giong OpenAI json mode
            ),
        )
        self.last_usage = _gemini_usage(response)
        self.last_finish_reason = _gemini_finish_reason(response)
        content = response.text
        if not content:
            raise RuntimeError("Gemini tra ve noi dung rong")
        return content

    def generate_chat(self, system_prompt, messages, temperature=None, max_tokens=None, reasoning_effort=None) -> str:
        self.last_usage, self.last_finish_reason = None, None
        types = self._types
        response = self._client.models.generate_content(
            model=self.model,
            # Gemini goi vai tro assistant la "model"
            contents=[
                types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["content"])])
                for m in messages
            ],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=self._temperature if temperature is None else temperature,
                max_output_tokens=max_tokens or self._max_tokens,
            ),
        )
        self.last_usage = _gemini_usage(response)
        self.last_finish_reason = _gemini_finish_reason(response)
        content = response.text
        if not content:
            raise RuntimeError("Gemini tra ve noi dung rong")
        return content


def _gemini_usage(response) -> dict | None:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    # thoughts_token_count: token suy luan, cung tinh vao output
    thoughts = getattr(meta, "thoughts_token_count", None)
    return {
        "tokens_in": meta.prompt_token_count,
        "tokens_out": (meta.candidates_token_count or 0) + (thoughts or 0),
        "reasoning_tokens": thoughts,
    }


def _gemini_finish_reason(response) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    reason = getattr(candidates[0], "finish_reason", None) if candidates else None
    name = getattr(reason, "name", None) or (str(reason) if reason is not None else None)
    return "length" if name == "MAX_TOKENS" else (name.lower() if name else None)


class GroqClient(LLMClient):
    """
    Groq tuong thich chuan OpenAI, nen tai dung SDK `openai`, chi doi base_url.
    LUU Y: danh sach model free tier cua Groq thay doi thuong xuyen — neu GROQ_MODEL
    bi loi "model not found", vao console.groq.com xem model nao dang free.
    """

    provider = "groq"

    def __init__(self, settings: Settings):
        from openai import OpenAI  # tai dung SDK openai, khong can them thu vien rieng

        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY chua duoc set trong .env")

        self._client = OpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=settings.llm_timeout_seconds,
            max_retries=SDK_MAX_RETRIES,
        )
        self.model = settings.groq_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    def generate(
        self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None, reasoning_effort=None
    ) -> str:
        self.last_usage, self.last_finish_reason = None, None
        # Ban goc co vong retry RateLimitError (5 lan, cach 3s) o day — da chuyen len service.
        if json_schema is not None:
            # Structured output strict: Groq ep output khop schema (so phan tu, pattern...).
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json_schema, "strict": True},
            }
        else:
            response_format = {"type": "json_object"}
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=max_tokens or self._max_tokens,
            response_format=response_format,
            **_effort(reasoning_effort),
        )
        self.last_usage = _openai_usage(response)  # completion_tokens da gom token suy luan cua gpt-oss
        self.last_finish_reason = response.choices[0].finish_reason
        content = response.choices[0].message.content
        if content is None:  # "" van tra ve (nguoi goi xu ly) — giu nguyen hanh vi Case Planning / baseline
            raise RuntimeError(f"Groq tra ve noi dung rong (finish_reason={self.last_finish_reason})")
        return content

    def generate_chat(self, system_prompt, messages, temperature=None, max_tokens=None, reasoning_effort=None) -> str:
        self.last_usage, self.last_finish_reason = None, None
        # Van ban thuan: KHONG response_format. Loi 429 nem thang cho service (nhu generate()).
        response = self._client.chat.completions.create(
            model=self.model,
            messages=_chat_messages(system_prompt, messages),
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=max_tokens or self._max_tokens,
            **_effort(reasoning_effort),
        )
        self.last_usage = _openai_usage(response)
        self.last_finish_reason = response.choices[0].finish_reason
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError(f"Groq tra ve noi dung rong (finish_reason={self.last_finish_reason})")
        return content


def schema_rejected_output(e: Exception) -> str | None:
    """
    Groq structured output (strict) KHONG ep luc sinh: model sinh xong, Groq moi kiem tra schema, sai thi
    tra 400 code "json_validate_failed" kem output bi tu choi trong "failed_generation" (da kiem chung
    voi openai/gpt-oss-120b, 2026-09-26). Day la OUTPUT KHONG HOP LE, khong phai loi provider.
    Tra ve output bi tu choi ("" neu khong co), hoac None neu e khong phai loi nay.
    """
    if getattr(e, "status_code", None) != 400 or getattr(e, "code", None) != "json_validate_failed":
        return None
    body = getattr(e, "body", None)
    return (body.get("failed_generation") if isinstance(body, dict) else None) or ""


def _openai_usage(response) -> dict | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "completion_tokens_details", None)
    return {
        "tokens_in": usage.prompt_tokens,
        "tokens_out": usage.completion_tokens,  # gpt-oss: DA GOM token suy luan
        "reasoning_tokens": getattr(details, "reasoning_tokens", None) if details is not None else None,
    }


def _effort(reasoning_effort: str | None) -> dict:
    """Chi gui reasoning_effort khi duoc cau hinh — None = giu mac dinh cua provider (gpt-oss tren Groq: "medium")."""
    return {"reasoning_effort": reasoning_effort} if reasoning_effort else {}


# Groq: "Please try again in 9.9225s" / "1m2.5s" / "540ms"
_TRY_AGAIN_RE = re.compile(r"try again in\s+((?:\d+(?:\.\d+)?(?:ms|h|m|s))+)", re.IGNORECASE)
_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_UNIT_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def rate_limit_wait_seconds(e: Exception) -> float | None:
    """
    Thoi gian provider yeu cau cho sau loi 429, theo thu tu uu tien:
    1. header `retry-after-ms` / `retry-after` (giay) cua response,
    2. cau "Please try again in Xs" (Groq; ho tro dang 1m2.5s, 540ms) trong message.
    None neu khong tim thay (service dung CASE_PLAN_RATE_LIMIT_WAIT_SECONDS).
    """
    response = getattr(e, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
            value = headers.get(name)
            if value is not None:
                try:
                    return max(0.0, float(value) * scale)
                except ValueError:
                    pass  # vd dang ngay HTTP — bo qua, thu message
    m = _TRY_AGAIN_RE.search(str(e))
    if m:
        return sum(float(num) * _UNIT_SECONDS[unit] for num, unit in _DURATION_PART_RE.findall(m.group(1)))
    return None


# Loi mang / server THOANG QUA (dev log muc 2.12: tran 17:34 Case Planning chet vi 1 lan APIConnectionError).
# Nhan dien theo TEN lop (openai / anthropic / httpx dung cung ten) de khong phai import SDK; 5xx theo status_code / code.
_TRANSIENT_CLASS_NAMES = {
    "APIConnectionError", "APITimeoutError", "ConnectError", "ConnectTimeout", "ReadTimeout", "ReadError",
    "WriteTimeout", "PoolTimeout", "RemoteProtocolError", "TimeoutException",
}
_TRANSIENT_STATUS = {500, 502, 503, 504}


def is_transient_error(e: Exception) -> bool:
    """Loi mang / timeout / 5xx cua provider — thu lai co the qua. KHONG gom 429 (co luong cho rieng) va 4xx khac."""
    if any(cls.__name__ in _TRANSIENT_CLASS_NAMES for cls in type(e).__mro__):
        return True
    return getattr(e, "status_code", None) in _TRANSIENT_STATUS or getattr(e, "code", None) in _TRANSIENT_STATUS


def is_rate_limit_error(e: Exception) -> bool:
    """Nhan dien loi 429 cua moi provider (openai/groq/anthropic: status_code; gemini: code)."""
    return getattr(e, "status_code", None) == 429 or getattr(e, "code", None) == 429


_CLIENTS: dict[str, type[LLMClient]] = {
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
    "gemini": GeminiClient,
    "groq": GroqClient,
}


def get_llm_client(settings: Settings, provider: str | None = None, model: str | None = None) -> LLMClient:
    """
    provider / model: ghi de LLM_PROVIDER / <PROVIDER>_MODEL — dung cho tac vu can model rieng
    (vd Stance Reviewer dung model nho). Khong truyen -> hanh vi nhu ban goc.
    """
    name = (provider or settings.llm_provider).lower()
    cls = _CLIENTS.get(name)
    if cls is None:
        raise ValueError(
            f"LLM provider khong hop le: '{name}' (chi ho tro 'openai', 'anthropic', 'gemini', hoac 'groq')"
        )
    client = cls(settings)
    if model:
        client.model = model  # moi client doc self.model khi goi API
    return client
