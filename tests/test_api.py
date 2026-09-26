"""
Test cap API (endpoint), dung FastAPI TestClient. Chi test validation/routing —
KHONG goi LLM that, vi FastAPI validate Pydantic body TRUOC khi request toi
evaluate_argument(), nen cac case loi input se tra ve 422 ma khong can API key.
"""
import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-placeholder-not-real")

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "llm_provider" in body


def test_evaluate_missing_required_field_returns_422():
    # Thieu field bat buoc "motion" -> FastAPI/Pydantic tu choi truoc khi cham LLM
    payload = {
        "side": "pro",
        "argument_text": "Some argument text.",
    }
    response = client.post("/evaluate", json=payload)
    assert response.status_code == 422


def test_evaluate_blank_argument_text_returns_422():
    payload = {
        "motion": "THBT social media does more harm than good",
        "side": "pro",
        "argument_text": "   ",
    }
    response = client.post("/evaluate", json=payload)
    assert response.status_code == 422


def test_evaluate_invalid_side_value_returns_422():
    # "side" chi chap nhan "pro" hoac "con" (DebateSide enum)
    payload = {
        "motion": "THBT social media does more harm than good",
        "side": "team_a",
        "argument_text": "Some argument text.",
    }
    response = client.post("/evaluate", json=payload)
    assert response.status_code == 422
