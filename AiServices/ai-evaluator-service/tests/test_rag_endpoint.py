"""Router /rag/* chi ton tai khi RAG_ENABLED=true; ca hai truong hop deu khong nap torch/psycopg."""
import os
import subprocess
import sys

from fastapi.testclient import TestClient

from app.main import app

_CHECK_ROUTES = (
    "import sys; from app.main import app; "
    "print(any(p.startswith('/rag') for p in app.openapi()['paths']), "
    "sorted(m for m in ('torch', 'sentence_transformers', 'psycopg') if m in sys.modules))"
)


def _run_with_rag_enabled(value: str) -> str:
    env = {**os.environ, "RAG_ENABLED": value, "EVAL_AUDIT_LOG_PATH": ""}
    return subprocess.run(
        [sys.executable, "-c", _CHECK_ROUTES], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


def test_rag_route_is_absent_by_default():
    assert not any(path.startswith("/rag") for path in app.openapi()["paths"])
    response = TestClient(app).post(
        "/rag/check-evidence", json={"argument_text": "a", "motion": "b", "topic": "education"}
    )
    assert response.status_code == 404


def test_rag_route_is_absent_when_disabled_explicitly():
    assert _run_with_rag_enabled("false") == "False []"


def test_rag_route_exists_when_enabled_without_loading_heavy_modules():
    assert _run_with_rag_enabled("true") == "True []"
