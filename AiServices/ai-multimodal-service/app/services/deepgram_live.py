"""Deepgram Live Streaming STT WebSocket proxy for real-time debate transcripts."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import urlencode

from fastapi import WebSocket, WebSocketDisconnect
import websockets

from app.config import Settings

logger = logging.getLogger(__name__)

DEEPGRAM_LISTEN_WS_URL = "wss://api.deepgram.com/v1/listen"
MAX_PENDING_AUDIO_CHUNKS = 100
SUPPORTED_MODELS = {"nova-2", "nova-3"}
SUPPORTED_LANGUAGES = {"vi", "multi"}
SUPPORTED_ENCODINGS = {"webm", "linear16"}


def is_api_key_configured(api_key: str | None) -> bool:
    """Return True if a non-placeholder Deepgram API key is configured."""
    if not api_key:
        return False
    trimmed = api_key.strip()
    if not trimmed:
        return False
    placeholders = {"your_deepgram_api_key_here", "REPLACE_ME", "YOUR_KEY"}
    return trimmed not in placeholders and "your_deepgram" not in trimmed.lower()


def sanitize_error_text(raw: Any, api_key: str = "") -> str:
    """Strip any accidental API key exposure from error messages."""
    text = str(raw or "Unknown Deepgram error")
    if api_key and api_key.strip():
        text = text.replace(api_key.strip(), "[REDACTED]")
    text = re.sub(r"Token\s+[A-Za-z0-9._-]+", "Token [REDACTED]", text, flags=re.IGNORECASE)
    return text


def diagnose_deepgram_error(err: Any, api_key: str = "") -> tuple[str, str]:
    """Map Deepgram / WebSocket failures to clear diagnostic codes and Vietnamese messages."""
    raw = sanitize_error_text(err, api_key)
    lower = raw.lower()

    if "401" in lower or "403" in lower or "unauthorized" in lower or "invalid credentials" in lower:
        return (
            "DEEPGRAM_AUTH_ERROR",
            "Deepgram API Key không hợp lệ hoặc đã hết hạn (401/403). Vui lòng kiểm tra DEEPGRAM_API_KEY.",
        )
    if "402" in lower or "insufficient" in lower or "payment required" in lower or "credit" in lower:
        return (
            "DEEPGRAM_QUOTA_EXCEEDED",
            "Tài khoản Deepgram đã hết credit/quota (402). Vui lòng nạp thêm credit hoặc đổi key.",
        )
    if "429" in lower or "too many requests" in lower or "rate limit" in lower:
        return (
            "DEEPGRAM_RATE_LIMIT",
            "Vượt quá giới hạn kết nối đồng thời của Deepgram (429). Vui lòng thử lại sau vài giây.",
        )
    if "400" in lower or "bad request" in lower or "unsupported" in lower:
        return (
            "DEEPGRAM_BAD_PARAMS",
            f"Tham số cấu hình Deepgram không hợp lệ (400): {raw}",
        )
    if "enotfound" in lower or "getaddrinfo" in lower or "timed out" in lower or "timeout" in lower:
        return (
            "DEEPGRAM_NETWORK_ERROR",
            f"Không thể kết nối tới Deepgram API (lỗi mạng/DNS/timeout): {raw}",
        )
    return ("DEEPGRAM_ERROR", f"Lỗi Deepgram streaming: {raw}")


def _parse_bool(val: str | None, default: bool) -> bool:
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(val: str | None, default: int, min_val: int, max_val: int) -> int:
    if val is None:
        return default
    try:
        parsed = int(val)
    except ValueError:
        return default
    return max(min_val, min(max_val, parsed))


def resolve_stream_options(
    settings: Settings,
    *,
    model: str | None = None,
    mode: str | None = None,
    endpointing: str | None = None,
    smart_format: str | None = None,
    punctuate: str | None = None,
    encoding: str | None = None,
    sample_rate: str | None = None,
) -> dict[str, Any]:
    """Resolve query overrides against the configured Deepgram preset defaults."""
    resolved_model = model if model in SUPPORTED_MODELS else settings.deepgram_default_model
    resolved_lang = mode if mode in SUPPORTED_LANGUAGES else settings.deepgram_default_language
    resolved_encoding = (
        encoding if encoding in SUPPORTED_ENCODINGS else settings.deepgram_default_encoding
    )
    resolved_endpointing = _parse_int(
        endpointing, settings.deepgram_default_endpointing_ms, 10, 5000
    )
    resolved_smart_format = _parse_bool(smart_format, settings.deepgram_default_smart_format)
    resolved_punctuate = _parse_bool(punctuate, settings.deepgram_default_punctuate)
    resolved_sample_rate = _parse_int(
        sample_rate, settings.deepgram_default_sample_rate, 8000, 48000
    )

    return {
        "model": resolved_model,
        "language": resolved_lang,
        "endpointing": resolved_endpointing,
        "smart_format": resolved_smart_format,
        "punctuate": resolved_punctuate,
        "encoding": resolved_encoding,
        "sample_rate": resolved_sample_rate,
        "utterance_end_ms": settings.deepgram_utterance_end_ms,
    }


def build_deepgram_ws_url(options: dict[str, Any]) -> str:
    """Build the Deepgram /v1/listen WebSocket URL from resolved stream options."""
    params: dict[str, Any] = {
        "model": options["model"],
        "language": options["language"],
        "interim_results": "true",
        "punctuate": "true" if options["punctuate"] else "false",
        "smart_format": "true" if options["smart_format"] else "false",
        "endpointing": str(options["endpointing"]),
        "vad_events": "true",
        "utterance_end_ms": str(options["utterance_end_ms"]),
    }

    if options["encoding"] == "linear16":
        params["encoding"] = "linear16"
        params["sample_rate"] = str(options["sample_rate"])
        params["channels"] = "1"

    return f"{DEEPGRAM_LISTEN_WS_URL}?{urlencode(params)}"


def get_realtime_stt_preset(settings: Settings) -> dict[str, Any]:
    """Return the active default preset metadata (matches Preset Chuan Deepgram Web)."""
    return {
        "configured": is_api_key_configured(settings.deepgram_api_key),
        "preset_name": "Preset Chuẩn Deepgram Web",
        "defaults": {
            "transport": "webm_opus"
            if settings.deepgram_default_encoding == "webm"
            else "pcm_linear16",
            "encoding": settings.deepgram_default_encoding,
            "webrtc_filter": "raw_voice",
            "endpointing": settings.deepgram_default_endpointing_ms,
            "smart_format": settings.deepgram_default_smart_format,
            "punctuate": settings.deepgram_default_punctuate,
            "model": settings.deepgram_default_model,
            "language": settings.deepgram_default_language,
            "sample_rate": settings.deepgram_default_sample_rate,
            "utterance_end_ms": settings.deepgram_utterance_end_ms,
        },
        "supported": {
            "models": sorted(SUPPORTED_MODELS),
            "languages": sorted(SUPPORTED_LANGUAGES),
            "encodings": sorted(SUPPORTED_ENCODINGS),
            "endpointing_ms": [300, 500, 800],
        },
    }


def _translate_deepgram_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Translate a Deepgram JSON event into the client WebSocket contract."""
    event_type = payload.get("type")

    if event_type == "Results":
        channel = payload.get("channel") or {}
        alternatives = channel.get("alternatives") or []
        alt0 = alternatives[0] if alternatives else {}
        transcript = (alt0.get("transcript") or "").strip()
        is_final = bool(payload.get("is_final"))
        speech_final = bool(payload.get("speech_final"))
        from_finalize = bool(payload.get("from_finalize"))

        # Skip empty interim noise unless finalizing or marking speech_final
        if not transcript and not is_final and not speech_final and not from_finalize:
            return None

        return {
            "type": "transcript",
            "transcript": alt0.get("transcript") or "",
            "is_final": is_final,
            "speech_final": speech_final,
            "from_finalize": from_finalize,
            "confidence": alt0.get("confidence"),
            "start": payload.get("start", 0),
            "duration": payload.get("duration", 0),
            "languages": alt0.get("languages") or channel.get("languages") or [],
        }

    if event_type == "SpeechStarted":
        return {"type": "speech_started", "timestamp": payload.get("timestamp")}

    if event_type == "UtteranceEnd":
        return {"type": "utterance_end", "last_word_end": payload.get("last_word_end")}

    if event_type == "Metadata":
        return {
            "type": "metadata",
            "request_id": payload.get("request_id"),
            "model_info": payload.get("model_info"),
        }

    if event_type == "Error":
        code, message = diagnose_deepgram_error(payload.get("description") or payload)
        return {"type": "error", "code": code, "message": message}

    return None


async def _send_json_safe(ws: WebSocket, data: dict[str, Any]) -> None:
    try:
        await ws.send_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


async def proxy_deepgram_live(client_ws: WebSocket, settings: Settings) -> None:
    """Accept a client WebSocket and proxy audio/transcripts to Deepgram Live STT."""
    await client_ws.accept()

    api_key = (settings.deepgram_api_key or "").strip()
    if not is_api_key_configured(api_key):
        await _send_json_safe(
            client_ws,
            {
                "type": "error",
                "code": "DEEPGRAM_API_KEY_MISSING",
                "message": "Backend chưa cấu hình DEEPGRAM_API_KEY hợp lệ trong ai-multimodal-service.",
            },
        )
        await client_ws.close(code=1008, reason="DEEPGRAM_API_KEY_MISSING")
        return

    qp = client_ws.query_params
    options = resolve_stream_options(
        settings,
        model=qp.get("model"),
        mode=qp.get("mode") or qp.get("language"),
        endpointing=qp.get("endpointing"),
        smart_format=qp.get("smart_format"),
        punctuate=qp.get("punctuate"),
        encoding=qp.get("encoding"),
        sample_rate=qp.get("sampleRate") or qp.get("sample_rate"),
    )
    dg_url = build_deepgram_ws_url(options)

    await _send_json_safe(client_ws, {"type": "dg_status", "status": "connecting"})

    is_stopping = False
    pending_chunks: list[bytes] = []

    try:
        async with websockets.connect(
            dg_url,
            additional_headers={"Authorization": f"Token {api_key}"},
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
        ) as dg_ws:
            await _send_json_safe(client_ws, {"type": "dg_status", "status": "connected"})

            for chunk in pending_chunks:
                await dg_ws.send(chunk)
            pending_chunks.clear()

            async def keepalive_loop() -> None:
                try:
                    while not is_stopping:
                        await asyncio.sleep(settings.deepgram_keepalive_interval_s)
                        if is_stopping:
                            break
                        await dg_ws.send(json.dumps({"type": "KeepAlive"}))
                except (websockets.ConnectionClosed, asyncio.CancelledError):
                    pass

            async def forward_client_to_dg() -> None:
                nonlocal is_stopping
                chunk_count = 0
                try:
                    while True:
                        message = await client_ws.receive()
                        msg_type = message.get("type")
                        if msg_type == "websocket.disconnect":
                            break

                        raw_bytes = message.get("bytes")
                        if raw_bytes is not None:
                            if not is_stopping:
                                chunk_count += 1
                                if chunk_count == 1:
                                    logger.info(
                                        "Deepgram WS first audio chunk forwarded (%d bytes, encoding=%s)",
                                        len(raw_bytes),
                                        options["encoding"],
                                    )
                                await dg_ws.send(raw_bytes)
                            continue

                        raw_text = message.get("text")
                        if raw_text is not None:
                            try:
                                ctrl = json.loads(raw_text)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(ctrl, dict) and ctrl.get("type") == "stop":
                                is_stopping = True
                                await dg_ws.send(json.dumps({"type": "Finalize"}))
                                await dg_ws.send(json.dumps({"type": "CloseStream"}))
                                break
                except (WebSocketDisconnect, websockets.ConnectionClosed, asyncio.CancelledError):
                    is_stopping = True

            async def forward_dg_to_client() -> None:
                try:
                    async for raw_msg in dg_ws:
                        if isinstance(raw_msg, bytes):
                            continue
                        try:
                            payload = json.loads(raw_msg)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(payload, dict):
                            continue
                        translated = _translate_deepgram_event(payload)
                        if translated is not None:
                            await _send_json_safe(client_ws, translated)
                except websockets.ConnectionClosed:
                    pass

            keepalive_task = asyncio.create_task(keepalive_loop())
            client_task = asyncio.create_task(forward_client_to_dg())
            dg_task = asyncio.create_task(forward_dg_to_client())

            done, pending = await asyncio.wait(
                {client_task, dg_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Give Deepgram up to 2s to flush Finalize transcripts after client stops
            if client_task in done and dg_task in pending and is_stopping:
                try:
                    await asyncio.wait_for(dg_task, timeout=2.0)
                except asyncio.TimeoutError:
                    dg_task.cancel()

            keepalive_task.cancel()
            for task in pending:
                if not task.done():
                    task.cancel()

            await _send_json_safe(client_ws, {"type": "dg_status", "status": "closed"})
            try:
                await client_ws.close(code=1000, reason="DEEPGRAM_CLOSED")
            except Exception:
                pass

    except WebSocketDisconnect:
        logger.info("Client disconnected from Deepgram live STT proxy")
    except Exception as exc:
        code, message = diagnose_deepgram_error(exc, api_key)
        logger.warning("Deepgram live STT proxy error (%s): %s", code, message)
        await _send_json_safe(
            client_ws, {"type": "error", "code": code, "message": message}
        )
        try:
            await client_ws.close(code=1011, reason=code)
        except Exception:
            pass

