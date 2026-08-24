from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import User
from app.repositories import users


@pytest.fixture()
def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'activity.db'}")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        m = async_sessionmaker(engine, expire_on_commit=False)
        async with m() as db:
            db.add(User(id="u1", google_sub="g1", email="u@test.local"))
            await db.commit()
        return m

    m = asyncio.run(_setup())
    try:
        yield m
    finally:
        asyncio.run(engine.dispose())


def _get(maker):
    async def _run():
        async with maker() as db:
            u = await users.get_by_google_sub(db, "g1")
            return u.active_days, u.last_active_at

    return asyncio.run(_run())


def test_first_activity_counts_one_day(maker):
    async def _run():
        async with maker() as db:
            u = await users.get_by_google_sub(db, "g1")
            assert u.active_days == 0 and u.last_active_at is None
            await users.touch_activity(db, u)
            await db.commit()

    asyncio.run(_run())
    days, last = _get(maker)
    assert days == 1
    assert last is not None


def test_same_day_is_idempotent(maker):
    async def _run():
        async with maker() as db:
            u = await users.get_by_google_sub(db, "g1")
            await users.touch_activity(db, u)
            await users.touch_activity(db, u)
            await users.touch_activity(db, u)
            await db.commit()

    asyncio.run(_run())
    days, _ = _get(maker)
    assert days == 1  # three touches, same day → one


def test_new_day_increments(maker):
    async def _run():
        async with maker() as db:
            u = await users.get_by_google_sub(db, "g1")
            await users.touch_activity(db, u)  # day 1
            # Backdate last activity to "yesterday" so the next touch rolls over.
            u.last_active_at = datetime.now(tz=timezone.utc) - timedelta(days=1)
            await db.flush()
            await users.touch_activity(db, u)  # new day → day 2
            await db.commit()

    asyncio.run(_run())
    days, _ = _get(maker)
    assert days == 2
