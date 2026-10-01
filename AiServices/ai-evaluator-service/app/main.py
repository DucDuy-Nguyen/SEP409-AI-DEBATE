from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.demo_page import DEMO_HTML
from app.routers import evaluate

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="AI Evaluator service cho ADPP — cham diem lap luan tranh bien theo rubric",
    version="0.1.0",
)

app.include_router(evaluate.router)


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok", "llm_provider": settings.llm_provider}


@app.get("/demo", response_class=HTMLResponse, tags=["demo"])
def demo_page() -> str:
    return DEMO_HTML
