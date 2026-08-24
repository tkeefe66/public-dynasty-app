from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> AsyncEngine:
    """Create the process-wide async engine + sessionmaker. Call once at
    startup (app lifespan). Idempotent: returns the existing engine if already
    initialized."""
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"pool_pre_ping": True}
        # SQLite (aiosqlite) doesn't take pool_size/max_overflow.
        if not settings.database_url.startswith("sqlite"):
            kwargs["pool_size"] = settings.db_pool_size
            kwargs["max_overflow"] = settings.db_max_overflow
        _engine = create_async_engine(settings.database_url, **kwargs)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    """Process-wide async engine. Eagerly created in the app lifespan; falls
    back to lazy init for tests/scripts/CLI callers."""
    return init_engine()


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    """Dispose the engine on shutdown (called from the app lifespan)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Session for non-request callers (scheduler, scripts). Commits on
    success, rolls back on error, always closes."""
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
