from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import get_current_user
from app.db.base import Base
from app.db.models import LeagueMembership, PageEvent, User
from app.db.session import get_db
from app.main import app as fastapi_app


def _admin():
    return SimpleNamespace(id="u1", email="a@t.local", is_admin=True)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.routes.admin._cache_dir", lambda: tmp_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'at.db'}")
    now = datetime.now(tz=timezone.utc)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        m = async_sessionmaker(engine, expire_on_commit=False)
        async with m() as db:
            db.add(User(id="u1", google_sub="g1", email="a@t.local", is_admin=True))
            await db.flush()
            db.add(LeagueMembership(user_id="u1", league_id="L1", league_name="Alpha"))
            db.add(PageEvent(user_id="u1", league_id="L1", route="/league/[id]",
                             path="/league/L1", created_at=now))
            db.add(PageEvent(user_id="u1", league_id=None, route="/", path="/",
                             created_at=now))
            await db.commit()
        return m

    maker = asyncio.run(_setup())

    async def _override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_current_user] = _admin
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_active_users(client):
    body = client.get("/api/admin/telemetry/active-users").json()
    assert body["d1"] == 1 and body["d7"] == 1 and body["d30"] == 1
    assert sum(p["count"] for p in body["daily"]) == 1  # one distinct-user-day
    # Zero-filled: the 30-day window is dense, not just today.
    assert len(body["daily"]) > 1
    assert any(p["count"] == 0 for p in body["daily"])


def test_leagues_include_activity(client):
    leagues = {lg["league_id"]: lg for lg in client.get("/api/admin/leagues").json()}
    assert leagues["L1"]["active_users"] == 1
    assert leagues["L1"]["last_activity"] is not None


def test_user_activity_drilldown(client):
    body = client.get("/api/admin/users/u1/activity").json()
    assert len(body["recent"]) == 2
    league_ev = next(e for e in body["recent"] if e["league_id"] == "L1")
    assert league_ev["league_name"] == "Alpha"
    # Zero-filled: dense 30-day window, not just today.
    assert len(body["daily"]) > 1
    assert any(p["count"] == 0 for p in body["daily"])
    # The drill-down carries the user's identity so the page can render more
    # than a generic "User activity" heading.
    assert body["email"] == "a@t.local"
    assert body["name"] is None


def test_user_activity_unknown_user_404s(client):
    resp = client.get("/api/admin/users/nope/activity")
    assert resp.status_code == 404
