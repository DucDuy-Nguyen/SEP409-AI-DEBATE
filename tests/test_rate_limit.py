"""
Xu ly 429: doc thoi gian cho tu header / message, cho dung + jitter, khong tinh vao so lan thu; token thuc te.
"""
import json
from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.core.config import Settings
from app.llm.client import GroqClient, rate_limit_wait_seconds
from app.opponent import service
from app.opponent.models import DebateSide, OpponentDifficulty
from app.opponent.service import FailureKind, generate_case_file
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, RateLimited, make_case_file

GROQ_MESSAGE = (
    "Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` in organization "
    "`org_x` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 5291, Requested 4032. Please try "
    "again in 9.9225s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing', "
    "'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
)


def _openai_429(message: str = GROQ_MESSAGE, headers: dict | None = None) -> openai.RateLimitError:
    """Loi 429 THAT cua SDK openai (Groq dung SDK nay)."""
    request = httpx2.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx2.Response(429, headers=headers or {}, request=request)
    return openai.RateLimitError(message, response=response, body=None)


# ---------------- doc thoi gian cho ----------------


def test_wait_from_retry_after_header_takes_priority():
    assert rate_limit_wait_seconds(_openai_429(headers={"retry-after": "12"})) == 12.0


def test_wait_from_retry_after_ms_header():
    assert rate_limit_wait_seconds(_openai_429(headers={"retry-after-ms": "2500"})) == 2.5


def test_wait_from_message_when_no_header():
    assert rate_limit_wait_seconds(_openai_429()) == pytest.approx(9.9225)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Please try again in 20.25s.", 20.25),
        ("Please try again in 1m2.5s.", 62.5),
        ("Please try again in 540ms.", 0.54),
        ("Please try again in 7m.", 420.0),
    ],
)
def test_wait_message_formats(text, expected):
    assert rate_limit_wait_seconds(_openai_429(message=text)) == pytest.approx(expected)


def test_wait_unknown_returns_none():
    assert rate_limit_wait_seconds(_openai_429(message="rate limited, no hint")) is None
    assert rate_limit_wait_seconds(_openai_429(message="x", headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})) is None


# ---------------- service: cho dung thoi gian + jitter, khong tinh vao so lan thu ----------------


@pytest.fixture
def slept(monkeypatch) -> list[float]:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(service, "_sleep", fake_sleep)
    return waits


async def _run(responses, **settings):
    fake = FakeLLMClient(list(responses))
    outcome = await generate_case_file(
        "M", DebateSide.CON, DebateSide.PRO, OpponentDifficulty.MEDIUM, fake, Settings(_env_file=None, **settings)
    )
    return outcome, fake


async def test_waits_requested_time_plus_jitter(monkeypatch, slept):
    monkeypatch.setattr(service, "_jitter", lambda: 1.5)

    outcome, _ = await _run([_openai_429(), json.dumps(VALID_CASE_FILE)])

    assert slept == [pytest.approx(9.9225 + 1.5)]
    waited = outcome.attempts[0]
    assert waited.failure_kind == FailureKind.RATE_LIMITED and waited.rate_limit_wait_ms == int((9.9225 + 1.5) * 1000)
    assert outcome.case_file is not None


def test_jitter_is_between_1_and_2_seconds():
    assert service.RATE_LIMIT_JITTER_SECONDS == (1.0, 2.0)


async def test_fallback_wait_when_provider_gives_no_hint(slept):
    outcome, _ = await _run([RateLimited("429"), json.dumps(VALID_CASE_FILE)], case_plan_rate_limit_wait_seconds=4)
    assert slept == [4.0]  # jitter = 0 trong test (fixture autouse)
    assert outcome.attempts[0].rate_limit_wait_ms == 4000


async def test_rate_limit_waits_do_not_count_as_case_plan_attempts(slept):
    # max_attempts=2: 3 lan 429 + 1 output sai + 1 dung -> van thanh cong (429 khong ton luot thu)
    outcome, fake = await _run(
        [_openai_429(), _openai_429(), json.dumps(make_case_file(2)), _openai_429(), json.dumps(VALID_CASE_FILE)],
        case_plan_max_attempts=2,
    )

    assert outcome.case_file is not None and len(fake.calls) == 5
    kinds = [a.failure_kind for a in outcome.attempts]
    assert kinds == ["rate_limited", "rate_limited", "argument_count", "rate_limited", None]
    assert len(slept) == 3
    # lan thu sau 429 van mang phan hoi cua lan output sai (khong bi 429 lam mat)
    assert fake.calls[4]["user"].endswith(outcome.attempts[2].retry_feedback)


async def test_last_429_without_retries_left_is_not_waited(slept):
    outcome, _ = await _run([_openai_429()] * 3, case_plan_rate_limit_retries=2)
    assert len(slept) == 2
    assert [a.rate_limit_wait_ms is not None for a in outcome.attempts] == [True, True, False]
    assert outcome.llm_error is not None


# ---------------- token thuc te ----------------


def test_groq_client_records_usage_from_response():
    client = GroqClient(Settings(_env_file=None, groq_api_key="test-key-not-real"))
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1234, completion_tokens=2345),
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"), finish_reason="stop")],
    )
    sent: list[dict] = []
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: sent.append(kw) or response)))

    assert client.generate("s", "u") == "{}"
    assert client.last_usage == {"tokens_in": 1234, "tokens_out": 2345, "reasoning_tokens": None}
    assert client.last_finish_reason == "stop"
    assert "reasoning_effort" not in sent[-1]  # khong cau hinh -> KHONG gui (giu mac dinh Groq)

    # usage.completion_tokens_details.reasoning_tokens (gpt-oss) + finish_reason "length" + reasoning_effort
    response.usage.completion_tokens_details = SimpleNamespace(reasoning_tokens=1800)
    response.choices[0].finish_reason = "length"
    assert client.generate("s", "u", reasoning_effort="low") == "{}"
    assert client.last_usage["reasoning_tokens"] == 1800 and client.last_finish_reason == "length"
    assert sent[-1]["reasoning_effort"] == "low"
    assert client.generate_chat("s", [{"role": "user", "content": "u"}], reasoning_effort="high") == "{}"
    assert sent[-1]["reasoning_effort"] == "high" and "response_format" not in sent[-1]


async def test_tokens_are_recorded_per_attempt():
    fake = FakeLLMClient([json.dumps(make_case_file(2)), json.dumps(VALID_CASE_FILE)])
    fake.usages = [{"tokens_in": 900, "tokens_out": 3100}, {"tokens_in": 1000, "tokens_out": 3300}]
    outcome = await generate_case_file(
        "M", DebateSide.CON, DebateSide.PRO, OpponentDifficulty.MEDIUM, fake, Settings(_env_file=None)
    )
    assert [(a.tokens_in, a.tokens_out) for a in outcome.attempts] == [(900, 3100), (1000, 3300)]
