"""POST /multimodal/tts + GET /multimodal/tts/config — Azure gia lap bang httpx.MockTransport (khong goi mang)."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.routers import multimodal
from app.services import azure_tts

SETTINGS = Settings(_env_file=None, azure_speech_key="k-test", azure_speech_region="japaneast", prewarm_models=False)


@pytest.fixture
def azure(monkeypatch):
    """Ghi lai request gui toi Azure; `reply` dat status / body tra ve."""
    seen: list[httpx.Request] = []
    reply = {"status": 200, "body": b"ID3fake-mp3"}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(reply["status"], content=reply["body"])

    monkeypatch.setattr(multimodal, "get_settings", lambda: SETTINGS)
    monkeypatch.setattr(azure_tts, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen, reply


def test_tts_streams_mp3_and_sends_escaped_ssml_with_an_allowed_voice(azure):
    seen, _ = azure
    client = TestClient(app)

    r = client.post("/multimodal/tts", json={"text": "Giả sử 30% <học sinh> & \"phụ huynh\"", "voice": "vi-VN-HoaiMyNeural"})

    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3fake-mp3"
    req = seen[0]
    assert str(req.url) == "https://japaneast.tts.speech.microsoft.com/cognitiveservices/v1"
    assert req.headers["Ocp-Apim-Subscription-Key"] == "k-test"
    ssml = req.content.decode("utf-8")
    assert '<voice name="vi-VN-HoaiMyNeural">' in ssml
    assert "Giả sử 30% &lt;học sinh&gt; &amp; \"phụ huynh\"" in ssml  # khong chen duoc the SSML


def test_a_voice_outside_the_list_falls_back_to_the_default(azure):
    seen, _ = azure
    TestClient(app).post("/multimodal/tts", json={"text": "Xin chào", "voice": "en-US-JennyNeural"})
    assert '<voice name="vi-VN-NamMinhNeural">' in seen[0].content.decode("utf-8")


@pytest.mark.parametrize("azure_status, expected", [(401, 502), (429, 429), (500, 502)])
def test_azure_errors_become_clear_http_errors(azure, azure_status, expected):
    _, reply = azure
    reply["status"], reply["body"] = azure_status, b"nope"
    r = TestClient(app).post("/multimodal/tts", json={"text": "Xin chào"})
    assert r.status_code == expected and "Azure Speech" in r.json()["detail"]


def test_without_a_key_tts_is_503_and_config_says_not_configured(monkeypatch):
    monkeypatch.setattr(multimodal, "get_settings", lambda: Settings(_env_file=None, prewarm_models=False))
    client = TestClient(app)
    assert client.post("/multimodal/tts", json={"text": "Xin chào"}).status_code == 503
    assert client.get("/multimodal/tts/config").json()["configured"] is False


def test_text_too_long_or_blank_is_rejected(azure):
    client = TestClient(app)
    assert client.post("/multimodal/tts", json={"text": "x" * (azure_tts.MAX_TEXT_CHARS + 1)}).status_code == 422
    assert client.post("/multimodal/tts", json={"text": "   "}).status_code == 422
    assert azure[0] == []  # khong goi Azure


def test_config_lists_the_six_vietnamese_voices_with_labels(monkeypatch):
    monkeypatch.setattr(multimodal, "get_settings", lambda: SETTINGS)
    cfg = TestClient(app).get("/multimodal/tts/config").json()
    assert cfg["configured"] is True and cfg["voice"] == "vi-VN-NamMinhNeural"
    assert [v["id"] for v in cfg["voices"]] == list(azure_tts.VOICE_CATALOG)
    assert cfg["voices"][1] == {"id": "vi-VN-HoaiMyNeural", "label": "Hoài My", "gender": "female", "tier": "neural"}


def test_each_listed_voice_can_be_chosen(azure):
    seen, _ = azure
    client = TestClient(app)
    for voice in azure_tts.VOICE_CATALOG:
        assert client.post("/multimodal/tts", json={"text": "Xin chào", "voice": voice}).status_code == 200
    assert [r.content.decode("utf-8").split('<voice name="')[1].split('"')[0] for r in seen] == list(azure_tts.VOICE_CATALOG)

