from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.main import app as fastapi_app
from app.ratelimit import limiter
from app.services.generation.models import GenerationOperation


def test_me_requires_auth():
    # No overrides → real get_current_user → 401 without a token.
    fastapi_app.dependency_overrides.clear()
    c = TestClient(fastapi_app)
    assert c.get("/api/me/leagues").status_code == 401


def test_yahoo_cannot_be_added_through_generic_membership_without_connection(client):
    # Mutation: generic membership endpoint trusts a Yahoo key/client-supplied name.
    result = client.post("/api/me/leagues", json={"league_id": "999.l.123", "name": "Private"})
    assert result.status_code in (409, 503)
    assert client.get("/api/me/leagues").json() == []


class _FakeSleeper:
    async def get_user_id(self, username):
        return "sleeper-123"

    async def get_rosters(self, league_id):
        return []

    async def close(self):
        return None


@pytest.fixture()
def client(tmp_path, monkeypatch, maker):
    # Test clients share the process limiter; each isolated DB gets a new budget.
    limiter.reset()
    # Isolate the chain-cache lookups to a temp dir (cold → warm=False).
    monkeypatch.setattr("app.routes.me._cache_dir", lambda: tmp_path)
    monkeypatch.setattr("app.routes.me.SleeperClient", lambda: _FakeSleeper())

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
        limiter.reset()


def test_add_list_delete_cycle(client):
    assert client.get("/api/me/leagues").json() == []

    r = client.post("/api/me/leagues", json={"league_id": "L1"})
    assert r.status_code == 201
    body = r.json()
    assert body["league_id"] == "L1"
    assert body["warm"] is False  # cold cache
    assert body["refresh_job"] is None  # saved is not the same as running

    leagues = client.get("/api/me/leagues").json()
    assert [m["league_id"] for m in leagues] == ["L1"]

    # Idempotent: adding the same league again does not duplicate.
    assert client.post("/api/me/leagues", json={"league_id": "L1"}).status_code == 201
    assert len(client.get("/api/me/leagues").json()) == 1

    assert client.delete("/api/me/leagues/L1").status_code == 204
    assert client.get("/api/me/leagues").json() == []


@pytest.mark.parametrize("state", ["queued", "running", "needs_attention", "held", "succeeded", "cancelled"])
def test_league_reports_actual_refresh_state_without_job_payload(client, maker, state):
    assert client.post("/api/me/leagues", json={"league_id": "L1", "name": "My league"}).status_code == 201

    async def seed():
        async with maker.begin() as db:
            db.add_all([
                GenerationOperation(id="old", kind="refresh", league_id="L1", state="succeeded", created_at=1),
                GenerationOperation(id="current", kind="refresh", league_id="L1", state=state,
                                    reason="execution_failed" if state == "needs_attention" else "",
                                    created_at=2, payload_json='{"private": "not public"}'),
                # Neither a newer prose job nor another league's job describes
                # this membership's first data build.
                GenerationOperation(id="prose", kind="generation", league_id="L1", state="running", created_at=3),
                GenerationOperation(id="analyst", kind="analyst_refresh", league_id="L1", state="running", created_at=4),
                GenerationOperation(id="private", kind="refresh", league_id="L2", state="running", created_at=5),
            ])

    asyncio.run(seed())
    leagues = client.get("/api/me/leagues").json()
    assert len(leagues) == 1
    assert leagues[0]["warm"] is False
    assert leagues[0]["refresh_job"] == {
        "id": "current", "state": state,
        "reason": "execution_failed" if state == "needs_attention" else "",
    }
    # An idempotent re-add returns the same truthful status.
    added = client.post("/api/me/leagues", json={"league_id": "L1", "name": "My league"}).json()
    assert added["refresh_job"] == leagues[0]["refresh_job"]


def test_failed_update_preserves_cache_availability(client, maker, monkeypatch):
    assert client.post("/api/me/leagues", json={"league_id": "L1", "name": "My league"}).status_code == 201
    monkeypatch.setattr("app.routes.me.ChainCache.read", lambda *a, **kw: SimpleNamespace(
        league_name_by_id={"L1": "My league"}, league_season_by_id={"L1": 2026},
    ))

    async def seed():
        async with maker.begin() as db:
            db.add(GenerationOperation(id="failed", kind="refresh", league_id="L1",
                                       state="needs_attention", reason="execution_failed"))

    asyncio.run(seed())
    league = client.get("/api/me/leagues").json()[0]
    assert league["warm"] is True
    assert league["refresh_job"]["state"] == "needs_attention"


def test_replacement_job_wins_when_recovery_timestamps_tie(client, maker):
    assert client.post("/api/me/leagues", json={"league_id": "L1", "name": "My league"}).status_code == 201

    async def seed():
        async with maker.begin() as db:
            db.add_all([
                GenerationOperation(id="z-old", kind="refresh", league_id="L1", state="cancelled",
                                    created_at=1, updated_at=1),
                GenerationOperation(id="a-current", kind="refresh", league_id="L1", state="queued",
                                    active_key="refresh:L1", created_at=1, updated_at=1),
            ])

    asyncio.run(seed())
    assert client.get("/api/me/leagues").json()[0]["refresh_job"]["id"] == "a-current"


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
