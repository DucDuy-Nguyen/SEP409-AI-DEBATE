import base64
import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.services.analyzer import compute_voice_metrics_from_text, count_filler_words


def _make_dummy_jpeg_base64() -> str:
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("utf-8")


def test_filler_word_counting_respects_word_boundaries():
    # "là", "và", "nhà" khong duoc tinh nham la tu dem "à"
    text = "Kính thưa ban giám khảo, đây là vấn đề nhà trường và xã hội, ờ tôi nghĩ kiểu à đúng vậy ừm."
    count, breakdown = count_filler_words(text)
    assert count == 4
    assert breakdown == {"ờ": 1, "kiểu": 1, "à": 1, "ừm": 1}


def test_voice_metrics_computation():
    # 30 tu trong 15 giay = 120 WPM -> Chuan tranh bien (110-170 WPM), pace_score = 100
    words = " ".join(["lập_luận"] * 28 + ["ờ", "ừm"])
    metrics = compute_voice_metrics_from_text(words, duration_seconds=15.0)
    assert metrics.word_count == 30
    assert metrics.wpm == 120.0
    assert metrics.pace_score == 100.0
    assert metrics.filler_count == 2
    assert metrics.fluency_score == 70.0


def test_analyze_frame_and_turn_endpoints():
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    frame_b64 = _make_dummy_jpeg_base64()
    frame_resp = client.post("/multimodal/analyze-frame", json={"image_base64": frame_b64, "timestamp": 1.0})
    assert frame_resp.status_code == 200
    frame_data = frame_resp.json()
    assert "face_detected" in frame_data
    assert "emotion_scores" in frame_data

    turn_resp = client.post(
        "/multimodal/analyze-turn",
        json={
            "emotion_timeline": [
                {"time": 1.0, "dominant": "neutral", "scores": {"neutral": 80.0, "happy": 10.0}, "face_detected": True},
                {"time": 2.0, "dominant": "happy", "scores": {"happy": 70.0, "neutral": 20.0}, "face_detected": True},
            ],
            "total_frames_captured": 2,
            "duration_seconds": 10.0,
            "transcript_override": "Mạng xã hội gây ảnh hưởng lớn đến khả năng tập trung của học sinh sinh viên hiện nay.",
            "include_report_chart": True,
        },
    )
    assert turn_resp.status_code == 200
    turn_data = turn_resp.json()
    assert turn_data["facial"]["composure_score"] == 100.0
    assert turn_data["facial"]["eye_contact_rate"] == 100.0
    assert turn_data["voice"]["word_count"] > 10
    assert turn_data["overall_demeanor_score"] > 0
    assert turn_data["report_chart_base64"].startswith("data:image/png;base64,")


def test_evaluate_speech_and_demo_sample_endpoints(monkeypatch):
    import httpx
    from app.routers import multimodal as mm_router

    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "overall_score": 8.0,
                "overall_reasoning": "Lập luận chặt chẽ.",
                "criteria": [
                    {"name": "Logic", "score": 4, "reasoning": "Tốt"},
                    {"name": "Evidence", "score": 4, "reasoning": "Tốt"},
                    {"name": "Relevance", "score": 4, "reasoning": "Tốt"},
                    {"name": "Structure", "score": 4, "reasoning": "Tốt"},
                    {"name": "Persuasiveness", "score": 4, "reasoning": "Tốt"},
                ],
                "strengths": ["Rõ ràng"],
                "weaknesses": [],
                "suggestions": [],
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json=None):
            return FakeResp()

    monkeypatch.setattr(mm_router.httpx, "Client", FakeClient)
    client = TestClient(app)

    sample_resp = client.post("/multimodal/demo-sample-audio")
    assert sample_resp.status_code == 200
    sample_data = sample_resp.json()
    assert sample_data["overall_demeanor_score"] > 0
    assert sample_data["voice"]["word_count"] > 0

    eval_resp = client.post(
        "/multimodal/evaluate-speech",
        json={
            "motion": "THBT mạng xã hội gây hại nhiều hơn lợi",
            "side": "pro",
            "stage": "rebuttal",
            "opponent_argument_text": None,
            "turn_data": {
                "emotion_timeline": [
                    {"time": 1.0, "dominant": "neutral", "scores": {"neutral": 85.0}, "face_detected": True}
                ],
                "total_frames_captured": 1,
                "duration_seconds": 12.0,
                "transcript_override": "Mạng xã hội làm suy giảm tương tác trực tiếp bởi vì giới trẻ dành quá nhiều thời gian trước màn hình.",
                "include_report_chart": True,
            },
        },
    )
    assert eval_resp.status_code == 200
    eval_data = eval_resp.json()
    assert eval_data["evaluation_error"] is None
    assert eval_data["content_evaluation"] is not None
    assert len(eval_data["content_evaluation"]["criteria"]) == 5
    assert eval_data["content_evaluation"]["overall_score"] == 8.0
    assert eval_data["content_evaluation"]["delivery_analytics"]["composure_score"] == 100.0
