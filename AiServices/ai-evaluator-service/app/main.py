import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from app.demo_page import DEMO_HTML
from app.routers import coaching, evaluate

# Logger cua uvicorn: logger rieng cua app o muc INFO bi uvicorn loc mat, ma thoi gian warm-up can hien trong log
logger = logging.getLogger("uvicorn.error")

settings = get_settings()


@dataclass
class WarmupState:
    """Trang thai warm-up model embedding (RAG). /health/ready tra 503 cho toi khi ready."""

    ready: bool = False
    seconds: Optional[float] = None
    error: Optional[str] = None


warmup = WarmupState()


def _warm_up_rag(state: WarmupState) -> None:
    """Load bge-m3 + encode 1 cau ngan, de request dau tien khong phai cho load model (do duoc ~30-120 s, muc 3.22)."""
    started = time.perf_counter()
    try:
        # Import tai day: chi nap torch / sentence-transformers khi RAG bat
        from app.rag.embedder import get_default_embedder

        get_default_embedder().encode(["khởi động"])
        state.seconds = round(time.perf_counter() - started, 1)
        logger.info("Warm-up RAG xong trong %.1f s", state.seconds)
    except Exception as exc:  # Warm-up loi khong chan service: cham van chay, kiem chung se ra "unavailable"
        state.seconds = round(time.perf_counter() - started, 1)
        state.error = f"{type(exc).__name__}: {exc}"
        logger.error("Warm-up RAG that bai sau %.1f s: %s", state.seconds, state.error)
    finally:
        state.ready = True


@asynccontextmanager
async def lifespan(_: FastAPI):
    warmup.ready, warmup.seconds, warmup.error = False, None, None
    if get_settings().rag_enabled:
        # Thread rieng: server nhan request ngay (/health), /health/ready bao 503 trong luc load model
        threading.Thread(target=_warm_up_rag, args=(warmup,), name="rag-warmup", daemon=True).start()
    else:
        warmup.ready = True
    yield


app = FastAPI(
    title=settings.app_name,
    description="AI Evaluator service cho ADPP — cham diem lap luan tranh bien theo rubric",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(evaluate.router)
app.include_router(coaching.router)

if settings.rag_enabled:
    # Import tai day: RAG tat thi khong nap module RAG nao (torch, psycopg chi nap khi thuc su goi)
    from app.routers import rag

    app.include_router(rag.router)


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok", "llm_provider": settings.llm_provider}


@app.get("/health/ready", tags=["health"])
def readiness_check() -> JSONResponse:
    """503 trong luc warm-up model RAG; 200 khi xong (ke ca warm-up loi: van cham duoc, kiem chung se unavailable)."""
    if not warmup.ready:
        return JSONResponse(status_code=503, content={"status": "warming_up"})
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "rag_warmup_seconds": warmup.seconds, "rag_warmup_error": warmup.error},
    )


@app.get("/demo", response_class=HTMLResponse, tags=["demo"])
def demo_page() -> str:
    return DEMO_HTML
