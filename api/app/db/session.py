from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a request-scoped async session.

    Commits on success so route handlers (e.g. the user upsert in
    get_current_user) don't each have to; rolls back on error.
    """
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
