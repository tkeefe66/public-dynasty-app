from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import get_current_user
from app.db.base import Base
from app.db.models import User
from app.db.session import get_db
from app.main import app as fastapi_app


def test_me_requires_auth():
    # No overrides → real get_current_user → 401 without a token.
    fastapi_app.dependency_overrides.clear()
    c = TestClient(fastapi_app)
    assert c.get("/api/me/leagues").status_code == 401


class _FakeSleeper:
    async def get_user_id(self, username):
        return "sleeper-123"

    async def get_rosters(self, league_id):
        return []

    async def close(self):
        return None


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolate the chain-cache lookups to a temp dir (cold → warm=False).
    monkeypatch.setattr("app.routes.me._cache_dir", lambda: tmp_path)
    monkeypatch.setattr("app.routes.me.SleeperClient", lambda: _FakeSleeper())

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'me.db'}")

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _seed_user():
        async with maker() as db:
            db.add(User(id="u1", google_sub="g1", email="u@test.local", is_admin=False))
            await db.commit()

    asyncio.run(_seed_user())

    async def _override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Shared in-memory user so link/unlink mutations persist across requests.
    fake = SimpleNamespace(
        id="u1", email="u@test.local", name="U", avatar_url=None,
        sleeper_user_id=None, sleeper_username=None, is_admin=False,
    )
    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_current_user] = lambda: fake
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


def test_add_list_delete_cycle(client):
    assert client.get("/api/me/leagues").json() == []

    r = client.post("/api/me/leagues", json={"league_id": "L1"})
    assert r.status_code == 201
    body = r.json()
    assert body["league_id"] == "L1"
    assert body["warm"] is False  # cold cache

    leagues = client.get("/api/me/leagues").json()
    assert [m["league_id"] for m in leagues] == ["L1"]

    # Idempotent: adding the same league again does not duplicate.
    assert client.post("/api/me/leagues", json={"league_id": "L1"}).status_code == 201
    assert len(client.get("/api/me/leagues").json()) == 1

    assert client.delete("/api/me/leagues/L1").status_code == 204
    assert client.get("/api/me/leagues").json() == []


def test_get_me_profile(client):
    body = client.get("/api/me").json()
    assert body["email"] == "u@test.local"
    assert body["sleeper_username"] is None
    assert body["is_admin"] is False


def test_link_and_unlink_sleeper(client):
    r = client.post("/api/me/link-sleeper", json={"username": "tom"})
    assert r.status_code == 200
    assert r.json()["sleeper_username"] == "tom"
    assert r.json()["sleeper_user_id"] == "sleeper-123"
    # Reflected on the profile.
    assert client.get("/api/me").json()["sleeper_username"] == "tom"
    # Unlink clears it.
    assert client.delete("/api/me/link-sleeper").json()["sleeper_username"] is None


def test_discovery_requires_a_username(client):
    # No username arg and none linked → 400 (no Sleeper fan-out).
    assert client.get("/api/me/sleeper-leagues").status_code == 400


def test_per_user_cap_enforced(client, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_MAX_LEAGUES_PER_USER", "1")
    assert client.post("/api/me/leagues", json={"league_id": "L1"}).status_code == 201
    over = client.post("/api/me/leagues", json={"league_id": "L2"})
    assert over.status_code == 403
    assert "limit" in over.json()["detail"].lower()
    # The cap does not block re-adding an already-imported league.
    assert client.post("/api/me/leagues", json={"league_id": "L1"}).status_code == 201
