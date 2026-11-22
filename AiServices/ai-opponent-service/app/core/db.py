"""
Async SQLAlchemy engine + session dependency cho FastAPI.

Engine tao lazy (lan dau goi get_db) de import app khong can DB dang chay
(vd: chay script thu LLM, hoac GET /health).
"""
from collections.abc import AsyncIterator
from datetime import datetime, timezone
import uuid

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _register_sqlite_pg_compat(engine: AsyncEngine) -> None:
    """Register PostgreSQL functions (clock_timestamp, gen_random_uuid) on SQLite connections."""
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _connection_record) -> None:
        dbapi_conn.create_function(
            "clock_timestamp",
            0,
            lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"),
        )
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=settings.db_echo, pool_pre_ping=True)
        if settings.database_url.startswith("sqlite"):
            _register_sqlite_pg_compat(_engine)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def get_db() -> AsyncIterator[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    async with _sessionmaker() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
