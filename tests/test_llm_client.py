"""
Test xu ly loi cua GroqClient — gia lap response loi tu Groq, KHONG goi API that.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

from app.config import Settings
from app.schemas import ArgumentEvaluationRequest, DebateSide
from app.services.evaluator import evaluate_argument
from app.services.json_utils import EvaluationParseError
from app.services.llm_client import GroqClient


def _bad_request(code: str) -> BadRequestError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    body = {"message": "Failed to generate JSON", "type": "invalid_request_error", "code": code}
    response = httpx.Response(400, request=request, json={"error": body})
    return BadRequestError("Failed to generate JSON", response=response, body=body)


def _ok_response(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _groq_client(create_fn) -> GroqClient:
    client = GroqClient(Settings(llm_provider="groq", groq_api_key="test-not-real"))
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_fn)))
    return client


def test_json_validate_failed_becomes_parse_error():
    """Groq tu choi JSON hong (400 json_validate_failed) -> EvaluationParseError,
    de call_llm_with_retry thu lai thay vi lot ra thanh loi 500."""
    def create(**kwargs):
        raise _bad_request("json_validate_failed")

    with pytest.raises(EvaluationParseError):
        _groq_client(create).generate("system", "user")


def test_other_bad_request_is_not_swallowed():
    """Loi 400 khac (vi du model sai) KHONG duoc doi thanh loi dinh dang de retry vo ich."""
    def create(**kwargs):
        raise _bad_request("model_not_found")

    with pytest.raises(BadRequestError):
        _groq_client(create).generate("system", "user")


def test_evaluation_retries_after_json_validate_failed():
    """Ca luong cham diem: lan 1 Groq tu choi JSON, lan 2 tra ve hop le -> thanh cong."""
    valid = {
        "criteria": [
            {"name": n, "score": 3, "reasoning": "ok"}
            for n in ["Logic", "Evidence", "Relevance", "Structure", "Persuasiveness"]
        ],
        "overall_reasoning": "Trung binh.",
    }
    calls = {"n": 0}

    def create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _bad_request("json_validate_failed")
        return _ok_response(json.dumps(valid))

    req = ArgumentEvaluationRequest(motion="THBT test", side=DebateSide.PRO, argument_text="Lap luan.")
    result = evaluate_argument(req, llm_client=_groq_client(create))

    assert result.overall_score == 6.0
    assert calls["n"] == 2
