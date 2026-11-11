from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.demo_page import DEMO_HTML
from app.routers import multimodal
from app.services.analyzer import ensure_models_loaded, get_model_status

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.prewarm_models:
        ensure_models_loaded(load_whisper=True)
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "Microservice phan tich da phuong thuc (Facial Emotion bang DeepFace YuNet "
        "+ Speech-to-Text & Voice Pace bang Faster-Whisper) cho he thong tranh bien ADPP"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(multimodal.router)


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/demo")


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {
        "status": "ok",
        "service": "ai-multimodal-service",
        "models": get_model_status(),
    }


@app.get("/demo", response_class=HTMLResponse, tags=["demo"])
def demo_page() -> str:
    return DEMO_HTML

