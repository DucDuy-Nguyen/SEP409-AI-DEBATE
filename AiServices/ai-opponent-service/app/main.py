from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import dispose_engine
from app.opponent import router as opponent_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    description="AI Generation service cho ADPP — AI doi thu tranh bien (Case Planning, ...)",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(opponent_router.router)


@app.get("/health", tags=["health"])
def health_check() -> dict:
    return {"status": "ok", "llm_provider": settings.llm_provider}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.app_port, reload=True)
