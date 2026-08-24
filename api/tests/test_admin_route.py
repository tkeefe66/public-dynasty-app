from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import get_current_user
from app.db.base import Base
from app.db.models import LeagueMembership, User
from app.db.session import get_db
from app.main import app as fastapi_app


def _admin():
    return SimpleNamespace(id="u1", email="admin@test.local", is_admin=True)


def _non_admin():
    return SimpleNamespace(id="u1", email="user@test.local", is_admin=False)


@pytest.fixture()
def maker(tmp_path, monkeypatch):
    monkeypatch.setattr("app.routes.admin._cache_dir", lambda: tmp_path)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin.db'}")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        m = async_sessionmaker(engine, expire_on_commit=False)
        async with m() as db:
            db.add(
                User(
                    id="u1",
                    google_sub="g1",
                    email="admin@test.local",
                    is_admin=True,
                    active_days=4,
                    last_active_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                )
            )
            await db.flush()
            db.add(LeagueMembership(user_id="u1", league_id="L1", league_name="Alpha"))
            db.add(LeagueMembership(user_id="u1", league_id="L2"))
            await db.commit()
        return m

    m = asyncio.run(_setup())

    async def _override_get_db():
        async with m() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        yield m
    finally:
        fastapi_app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@pytest.fixture()
def client(maker):
    fastapi_app.dependency_overrides[get_current_user] = _admin
    return TestClient(fastapi_app)


def test_overview(client):
    r = client.get("/api/admin/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["users"] == 1
    assert body["memberships"] == 2
    assert body["leagues"] == 2
    assert "monthly_budget_usd" in body["budget"]


def test_leagues_and_users(client):
    leagues = client.get("/api/admin/leagues").json()
    assert {lg["league_id"] for lg in leagues} == {"L1", "L2"}
    assert all(lg["member_count"] == 1 and lg["warm"] is False for lg in leagues)

    users = client.get("/api/admin/users").json()
    assert len(users) == 1
    u = users[0]
    assert u["league_count"] == 2
    # Per-league list (id + resolved name; cold cache → falls back to stored name).
    assert {lg["league_id"] for lg in u["leagues"]} == {"L1", "L2"}
    names = {lg["league_id"]: lg["name"] for lg in u["leagues"]}
    assert names["L1"] == "Alpha"
    assert names["L2"] is None
    # Engagement tracking surfaced.
    assert u["active_days"] == 4
    assert u["last_active_at"].startswith("2026-06-01")


def test_budget_set_and_persist(client):
    r = client.put("/api/admin/budget", json={"monthly_budget_usd": 25})
    assert r.status_code == 200
    assert r.json()["monthly_budget_usd"] == 25.0
    # Persisted: overview reflects it.
    assert client.get("/api/admin/overview").json()["budget"]["monthly_budget_usd"] == 25.0


def test_admin_routes_require_admin(maker):
    fastapi_app.dependency_overrides[get_current_user] = _non_admin
    c = TestClient(fastapi_app)
    assert c.get("/api/admin/overview").status_code == 403
    assert c.get("/api/admin/leagues").status_code == 403
    assert c.put("/api/admin/budget", json={"monthly_budget_usd": 5}).status_code == 403
