"""
Lop truu tuong goi LLM API.

Ly do can lop nay: nhom chua chot OpenAI / Anthropic / Gemini / Groq (xem README).
Phan con lai cua code (evaluator.py) chi biet toi interface generate(),
khong quan tam dang sau la provider nao — doi provider chi can doi
LLM_PROVIDER trong .env, khong phai sua logic nghiep vu.
"""
from abc import ABC, abstractmethod

from app.config import Settings
import time
from openai import RateLimitError


class LLMClient(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Goi LLM, tra ve text output (raw). Nem exception neu goi that bai."""
        raise NotImplementedError


class OpenAIClient(LLMClient):
    def __init__(self, settings: Settings):
        from openai import OpenAI  # import cuc bo de khong bat buoc cai dat neu khong dung provider nay

        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY chua duoc set trong .env")

        self._client = OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds)
        self._model = settings.openai_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},  # bat che do JSON mode cua OpenAI cho chac chan
        )
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI tra ve noi dung rong")
        return content


class AnthropicClient(LLMClient):
    def __init__(self, settings: Settings):
        from anthropic import Anthropic  # import cuc bo

        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY chua duoc set trong .env")

        self._client = Anthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds)
        self._model = settings.anthropic_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        # Anthropic tra ve list cac content block; ghep phan text lai
        text_parts = [block.text for block in response.content if block.type == "text"]
        content = "".join(text_parts)
        if not content:
            raise RuntimeError("Anthropic tra ve noi dung rong")
        return content


class GeminiClient(LLMClient):
    """
    Dung SDK moi `google-genai` (khong dung `google-generativeai` — SDK cu dang bi
    Google khai tu dan). Cai bang: pip install google-genai

    Free tier: khong can nap tien truoc, chi can API key tu aistudio.google.com/apikey.
    LUU Y: Google doi model/free-tier kha thuong xuyen — neu GEMINI_MODEL trong .env
    bi loi "model not found", vao aistudio.google.com kiem tra ten model rang buoc
    free tier hien tai va cap nhat lai .env, khong sua code.
    """

    def __init__(self, settings: Settings):
        from google import genai
        from google.genai import types

        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY chua duoc set trong .env")

        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._types = types
        self._model = settings.gemini_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=self._types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=self._temperature,
                max_output_tokens=self._max_tokens,
                response_mime_type="application/json",  # bat che do tra JSON, giong OpenAI json mode
            ),
        )
        content = response.text
        if not content:
            raise RuntimeError("Gemini tra ve noi dung rong")
        return content


class GroqClient(LLMClient):
    """
    Groq co API tuong thich hoan toan voi chuan OpenAI (cung format request/response),
    nen tai dung thang SDK `openai`, chi doi base_url tro ve Groq — khong can them
    dependency moi.

    Free tier: khong can the, dang ky tai console.groq.com. Toc do rat nhanh (LPU rieng).
    LUU Y: danh sach model free tier cua Groq thay doi thuong xuyen — neu GROQ_MODEL
    trong .env bi loi "model not found", vao console.groq.com xem model nao dang free.
    """

    def __init__(self, settings: Settings):
        from openai import OpenAI  # tai dung SDK openai, khong can them thu vien rieng

        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY chua duoc set trong .env")

        self._client = OpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=settings.llm_timeout_seconds,
        )
        self._model = settings.groq_model
        self._temperature = settings.llm_temperature
        self._max_tokens = settings.llm_max_tokens

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        max_attempts = 5
        wait_seconds = 3

        for attempt in range(max_attempts):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                if content is None:
                    raise RuntimeError("Groq tra ve noi dung rong")
                return content
            except RateLimitError as e:
                is_last_attempt = attempt == max_attempts - 1
                if is_last_attempt:
                    raise
                time.sleep(wait_seconds)

        raise RuntimeError("Groq: het so lan thu cho phep vi rate limit")


def get_llm_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower()
    if provider == "openai":
        return OpenAIClient(settings)
    if provider == "anthropic":
        return AnthropicClient(settings)
    if provider == "gemini":
        return GeminiClient(settings)
    if provider == "groq":
        return GroqClient(settings)
    raise ValueError(
        f"LLM_PROVIDER khong hop le: '{settings.llm_provider}' "
        "(chi ho tro 'openai', 'anthropic', 'gemini', hoac 'groq')"
    )
