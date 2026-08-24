from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import PageEvent, User
from app.repositories import events


@pytest.fixture()
def maker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ev.db'}")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        m = async_sessionmaker(engine, expire_on_commit=False)
        async with m() as db:
            db.add(User(id="u1", google_sub="g1", email="a@t.local"))
            db.add(User(id="u2", google_sub="g2", email="b@t.local"))
            await db.commit()
        return m

    m = asyncio.run(_setup())
    try:
        yield m
    finally:
        asyncio.run(engine.dispose())


def _seed(maker, rows):
    async def _run():
        async with maker() as db:
            for uid, lid, route, path, ts in rows:
                db.add(PageEvent(user_id=uid, league_id=lid, route=route, path=path, created_at=ts))
            await db.commit()
    asyncio.run(_run())


def test_record_event_normalizes_and_inserts(maker):
    async def _run():
        async with maker() as db:
            await events.record_event(db, user_id="u1", path="/league/55/owner/x?foo=1")
            await db.commit()
            la = await events.league_activity(db)
        return la
    la = asyncio.run(_run())
    assert la["55"]["events"] == 1
    assert la["55"]["active_users"] == 1


def test_active_user_counts_windows(maker):
    now = datetime.now(tz=timezone.utc)
    _seed(maker, [
        ("u1", None, "/", "/", now),
        ("u2", None, "/", "/", now - timedelta(days=3)),
        ("u1", None, "/", "/", now - timedelta(days=10)),
    ])
    async def _run():
        async with maker() as db:
            return await events.active_user_counts(db)
    c = asyncio.run(_run())
    assert c["d1"] == 1   # only u1 today
    assert c["d7"] == 2   # u1 + u2
    assert c["d30"] == 2  # distinct users


def test_user_activity_drilldown(maker):
    now = datetime.now(tz=timezone.utc)
    _seed(maker, [
        ("u1", "55", "/league/[id]", "/league/55", now),
        ("u1", "55", "/league/[id]/gm", "/league/55/gm", now - timedelta(minutes=5)),
        ("u2", None, "/", "/", now),
    ])
    async def _run():
        async with maker() as db:
            return await events.user_activity(db, "u1", recent_limit=10, days=30)
    ua = asyncio.run(_run())
    assert len(ua["recent"]) == 2
    assert ua["recent"][0]["path"] == "/league/55"  # newest first
    assert sum(n for _, n in ua["daily"]) == 2
    # Zero-filled: a 30-day window is dense, not just the two active days.
    dates = [d for d, _ in ua["daily"]]
    parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    assert all((parsed[i + 1] - parsed[i]).days == 1 for i in range(len(parsed) - 1))
    assert len(dates) > 2


def test_daily_active_users_buckets_by_day(maker):
    now = datetime.now(tz=timezone.utc)
    _seed(maker, [
        ("u1", None, "/", "/", now),
        ("u2", None, "/", "/", now),                       # same day as u1
        ("u1", None, "/", "/", now - timedelta(days=2)),   # earlier day
    ])
    async def _run():
        async with maker() as db:
            return await events.daily_active_users(db, days=30)
    series = asyncio.run(_run())
    counts = dict(series)
    today = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    earlier = (now - timedelta(days=2)).astimezone(timezone.utc).strftime("%Y-%m-%d")
    assert counts[today] == 2       # u1 + u2 distinct
    assert counts[earlier] == 1     # u1
    assert series == sorted(series) # ascending by date


def test_daily_active_users_zero_fills_quiet_days(maker):
    """A day with no events must still appear in the series (as 0), not be
    dropped — the server, not the client, is responsible for the dense axis."""
    now = datetime.now(tz=timezone.utc)
    _seed(maker, [
        ("u1", None, "/", "/", now),
        ("u1", None, "/", "/", now - timedelta(days=5)),
    ])
    async def _run():
        async with maker() as db:
            return await events.daily_active_users(db, days=10)
    series = asyncio.run(_run())
    dates = [d for d, _ in series]
    counts = dict(series)
    # Contiguous: every consecutive pair of days differs by exactly one day —
    # no gaps for quiet days, no duplicates.
    parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    assert all((parsed[i + 1] - parsed[i]).days == 1 for i in range(len(parsed) - 1))
    quiet_day = (now - timedelta(days=2)).astimezone(timezone.utc).strftime("%Y-%m-%d")
    assert counts[quiet_day] == 0
