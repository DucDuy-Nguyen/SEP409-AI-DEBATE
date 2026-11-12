"""Warm-up model RAG luc khoi dong va /health/ready (dev log muc 3.22). Khong load model that."""
import os
import subprocess
import sys
import threading

from fastapi.testclient import TestClient

import app.main as main_module
import app.rag.embedder as embedder_module
from app.config import Settings


def test_rag_disabled_does_not_load_model_and_is_ready(monkeypatch):
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(rag_enabled=False))

    def must_not_load():
        raise AssertionError("RAG tat thi khong duoc load model")

    monkeypatch.setattr(embedder_module, "get_default_embedder", must_not_load)
    with TestClient(main_module.app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200 and response.json()["status"] == "ready"
        assert response.json()["rag_warmup_seconds"] is None
        assert client.get("/health").json()["status"] == "ok"


def test_rag_disabled_startup_never_imports_torch():
    code = (
        "import sys; from fastapi.testclient import TestClient; from app.main import app\n"
        "with TestClient(app) as c: status = c.get('/health/ready').status_code\n"
        "print(status, sorted(m for m in ('torch', 'sentence_transformers', 'app.rag.embedder') if m in sys.modules))"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                            env={**os.environ, "RAG_ENABLED": "false", "EVAL_AUDIT_LOG_PATH": ""})
    assert output.stdout.strip() == "200 []"


def test_rag_enabled_reports_503_until_warm_up_finishes(monkeypatch):
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(rag_enabled=True))
    release, encoded = threading.Event(), []

    class SlowEmbedder:
        def encode(self, texts):
            release.wait(timeout=5)
            encoded.append(texts)
            return [[0.0] for _ in texts]

    monkeypatch.setattr(embedder_module, "get_default_embedder", lambda: SlowEmbedder())
    with TestClient(main_module.app) as client:
        assert client.get("/health/ready").status_code == 503
        assert client.get("/health").status_code == 200  # /health giu nguyen
        release.set()
        for _ in range(100):
            response = client.get("/health/ready")
            if response.status_code == 200:
                break
            threading.Event().wait(0.02)
        assert response.status_code == 200
        assert response.json()["rag_warmup_error"] is None and response.json()["rag_warmup_seconds"] is not None
        assert encoded == [["khởi động"]]


def test_failed_warm_up_still_becomes_ready_with_error(monkeypatch):
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(rag_enabled=True))

    def broken():
        raise OSError("model khong tai duoc")

    monkeypatch.setattr(embedder_module, "get_default_embedder", broken)
    with TestClient(main_module.app) as client:
        for _ in range(100):
            response = client.get("/health/ready")
            if response.status_code == 200:
                break
            threading.Event().wait(0.02)
        assert response.status_code == 200
        assert "OSError: model khong tai duoc" in response.json()["rag_warmup_error"]
