"""
Azure AI Speech text-to-speech for the AI opponent's speech, read sentence by sentence by the FE.

Why Azure (2026-11-20): Free F0 tier = 0.5M neural characters / month (~80 debates of ~6,000 characters), Vietnamese
neural voices (vi-VN-HoaiMyNeural, vi-VN-NamMinhNeural), the key stays on the server. Measured from Vietnam to
japaneast with a kept-alive connection: first audio of one sentence after ~0.8 s (median of 4).

The FE sends one sentence per request; the next one is fetched while the previous plays. One shared httpx client keeps
the TLS connection to Azure open: a new connection per sentence measured 1.2-1.6 s instead.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from xml.sax.saxutils import escape

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 1000  # one sentence (or a short group); a whole speech must be split by the caller
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
MEDIA_TYPE = "audio/mpeg"

_client: httpx.AsyncClient | None = None


class TtsNotConfigured(Exception):
    """AZURE_SPEECH_KEY / AZURE_SPEECH_REGION missing."""


class TtsUpstreamError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def is_configured(settings: Settings) -> bool:
    return bool(settings.azure_speech_key.strip() and settings.azure_speech_region.strip())


# Ten hien thi cho FE. Do 2026-11-20 (japaneast, 1 cau, ket noi giu san): Neural / MAI Flash ~0.8-1.0 s toi am thanh
# dau tien, MAI HD 1.25-1.4 s.
VOICE_CATALOG: dict[str, dict] = {
    "vi-VN-NamMinhNeural": {"label": "Nam Minh", "gender": "male", "tier": "neural"},
    "vi-VN-HoaiMyNeural": {"label": "Hoài My", "gender": "female", "tier": "neural"},
    "vi-VN-Grant:MAI-Voice-2.1-Flash": {"label": "Grant", "gender": "male", "tier": "flash"},
    "vi-VN-Harper:MAI-Voice-2.1-Flash": {"label": "Harper", "gender": "female", "tier": "flash"},
    "vi-VN-Grant:MAI-Voice-2.1": {"label": "Grant HD", "gender": "male", "tier": "hd"},
    "vi-VN-Harper:MAI-Voice-2.1": {"label": "Harper HD", "gender": "female", "tier": "hd"},
}


def allowed_voices(settings: Settings) -> list[str]:
    return [v.strip() for v in settings.azure_tts_voices.split(",") if v.strip()]


def voice_options(settings: Settings) -> list[dict]:
    """[{id, label, gender, tier}] theo thu tu AZURE_TTS_VOICES; giong ngoai catalog: label = id."""
    return [
        {"id": v, **VOICE_CATALOG.get(v, {"label": v, "gender": "unknown", "tier": "other"})}
        for v in allowed_voices(settings)
    ]


def resolve_voice(settings: Settings, voice: str | None) -> str:
    """Only the configured Vietnamese voices: the endpoint is not a general proxy to the Speech key."""
    voices = allowed_voices(settings)
    if voice and voice in voices:
        return voice
    return settings.azure_tts_voice if settings.azure_tts_voice in voices or not voices else voices[0]


def build_ssml(text: str, voice: str, rate: str) -> str:
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="vi-VN">'
        f'<voice name="{escape(voice, {chr(34): "&quot;"})}"><prosody rate="{escape(rate, {chr(34): "&quot;"})}">'
        f"{escape(text)}</prosody></voice></speak>"
    )


def _http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _upstream_message(status: int) -> str:
    if status in (401, 403):
        return "Azure Speech từ chối key (401/403): kiểm tra AZURE_SPEECH_KEY / AZURE_SPEECH_REGION."
    if status == 429:
        return "Azure Speech đang giới hạn số yêu cầu hoặc đã hết hạn mức gói Free (429)."
    return f"Azure Speech trả lỗi HTTP {status}."


async def synthesize_stream(settings: Settings, text: str, voice: str | None = None) -> AsyncIterator[bytes]:
    """
    Opens the Azure request and checks its status BEFORE returning, so the caller can answer with a proper HTTP error;
    then yields the MP3 bytes as they arrive.
    """
    if not is_configured(settings):
        raise TtsNotConfigured()
    clean = " ".join(text.split())
    url = f"https://{settings.azure_speech_region.strip()}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": settings.azure_speech_key.strip(),
        "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
        "Content-Type": "application/ssml+xml; charset=utf-8",
        "User-Agent": "adpp-ai-multimodal-service",
    }
    ssml = build_ssml(clean, resolve_voice(settings, voice), settings.azure_tts_rate).encode("utf-8")
    client = _http_client()
    try:
        response = await client.send(client.build_request("POST", url, headers=headers, content=ssml), stream=True)
    except httpx.HTTPError as exc:
        raise TtsUpstreamError(502, f"Không kết nối được tới Azure Speech: {type(exc).__name__}") from exc
    if response.status_code != 200:
        await response.aclose()
        logger.warning("Azure TTS HTTP %s for %d chars", response.status_code, len(clean))
        raise TtsUpstreamError(429 if response.status_code == 429 else 502, _upstream_message(response.status_code))

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()

    return body()
