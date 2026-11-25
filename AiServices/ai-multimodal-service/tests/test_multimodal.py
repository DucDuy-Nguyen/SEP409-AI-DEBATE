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


def test_realtime_stt_preset_and_ws_helpers():
    from app.config import Settings
    from app.services.deepgram_live import (
        build_deepgram_ws_url,
        diagnose_deepgram_error,
        resolve_stream_options,
        sanitize_error_text,
    )

    s = Settings(deepgram_api_key="")
    options = resolve_stream_options(s)
    assert options["model"] == "nova-2"
    assert options["language"] == "vi"
    assert options["endpointing"] == 300
    assert options["smart_format"] is False
    assert options["punctuate"] is True
    assert options["encoding"] == "webm"

    url_webm = build_deepgram_ws_url(options)
    assert "model=nova-2" in url_webm
    assert "language=vi" in url_webm
    assert "endpointing=300" in url_webm
    assert "smart_format=false" in url_webm
    assert "encoding=linear16" not in url_webm

    pcm_opts = resolve_stream_options(s, model="nova-3", mode="multi", encoding="linear16", endpointing="500")
    url_pcm = build_deepgram_ws_url(pcm_opts)
    assert "model=nova-3" in url_pcm
    assert "language=multi" in url_pcm
    assert "encoding=linear16" in url_pcm
    assert "sample_rate=16000" in url_pcm

    assert sanitize_error_text("Bearer Token secret123", "secret123") == "Bearer Token [REDACTED]"
    code, _ = diagnose_deepgram_error("HTTP 402 Payment Required")
    assert code == "DEEPGRAM_QUOTA_EXCEEDED"


def test_realtime_stt_config_endpoint_and_missing_key_ws(monkeypatch):
    from app.config import Settings
    from app.routers import multimodal as mm_router

    monkeypatch.setattr(mm_router, "get_settings", lambda: Settings(deepgram_api_key=""))
    client = TestClient(app)

    cfg_resp = client.get("/multimodal/realtime-stt/config")
    assert cfg_resp.status_code == 200
    cfg = cfg_resp.json()
    assert cfg["preset_name"] == "Preset Chuẩn Deepgram Web"
    assert cfg["defaults"]["transport"] == "webm_opus"
    assert cfg["defaults"]["encoding"] == "webm"
    assert cfg["defaults"]["webrtc_filter"] == "raw_voice"
    assert cfg["defaults"]["endpointing"] == 300
    assert cfg["defaults"]["smart_format"] is False
    assert cfg["defaults"]["model"] == "nova-2"
    assert cfg["defaults"]["language"] == "vi"

    with client.websocket_connect("/multimodal/ws/transcribe") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "DEEPGRAM_API_KEY_MISSING"


def test_yunet_threshold_is_applied_and_an_empty_frame_has_no_face():
    import os
    from app.config import get_settings
    from app.services.analyzer import analyze_single_frame

    assert os.environ["yunet_score_threshold"] == str(get_settings().yunet_score_threshold)
    assert analyze_single_frame(np.full((480, 640, 3), 90, np.uint8), detector_backend="yunet").face_detected is False


def test_analyze_frame_detects_a_webcam_sized_face():
    """Mat ~100px giua khung 640x480: voi nguong YuNet mac dinh 0.9 cua DeepFace se bi loai (diem ~0.87).

    Repo khong kem anh mat nguoi that: dat 1 anh chan dung vao bien MULTIMODAL_TEST_FACE de chay test nay.
    """
    import os
    import pytest
    from app.services.analyzer import analyze_single_frame

    path = os.environ.get("MULTIMODAL_TEST_FACE", "")
    face = cv2.imread(path) if path and os.path.exists(path) else None
    if face is None:
        pytest.skip("MULTIMODAL_TEST_FACE chua tro toi anh chan dung")
    small = cv2.resize(face, None, fx=200 / max(face.shape[:2]), fy=200 / max(face.shape[:2]))
    frame = np.full((480, 640, 3), 90, np.uint8)
    h, w = small.shape[:2]
    y0, x0 = (480 - h) // 2, (640 - w) // 2
    frame[y0:y0 + h, x0:x0 + w] = small

    res = analyze_single_frame(frame, detector_backend="yunet")
    assert res.face_detected is True
    assert res.region is not None and res.region.w >= 40


class _FakeWhisper:
    def __init__(self):
        self.calls = []

    def transcribe(self, path, **kwargs):
        self.calls.append(kwargs)

        class _Info:
            duration = 3.0

        class _Seg:
            text = "xin chào ban giám khảo"

        return [_Seg()], _Info()


def test_whisper_uses_the_configured_beam_size(monkeypatch):
    from app.config import get_settings
    from app.services import analyzer

    fake = _FakeWhisper()
    monkeypatch.setattr(analyzer, "_whisper_model", fake)
    monkeypatch.setattr(analyzer, "ensure_models_loaded", lambda load_whisper=True: {})

    text, duration = analyzer.transcribe_audio_bytes(b"not-really-audio", ".webm")

    assert text == "xin chào ban giám khảo" and duration == 3.0
    assert fake.calls[0]["beam_size"] == get_settings().whisper_beam_size == 1


def test_turn_without_audio_uses_the_live_transcript_and_skips_whisper(monkeypatch):
    # Luong nhanh cua FE: da co chu realtime (Deepgram) thi gui analyze-turn KHONG kem audio
    from app.services import analyzer

    def _no_whisper(*args, **kwargs):
        raise AssertionError("Whisper khong duoc goi khi khong co audio")

    monkeypatch.setattr(analyzer, "transcribe_audio_bytes", _no_whisper)
    client = TestClient(app)
    resp = client.post("/multimodal/analyze-turn", json={
        "audio_base64": None,
        "emotion_timeline": [],
        "total_frames_captured": 0,
        "duration_seconds": 15,
        "transcript_override": " ".join(["lập_luận"] * 28 + ["ờ", "ừm"]),
        "include_report_chart": False,
    })

    assert resp.status_code == 200
    voice = resp.json()["voice"]
    assert voice["word_count"] == 30
    assert voice["wpm"] == 120.0
    assert voice["filler_count"] == 2
