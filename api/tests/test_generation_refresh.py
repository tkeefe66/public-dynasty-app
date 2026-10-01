import asyncio
from unittest.mock import AsyncMock

import pytest
from app.db.models import LeagueMembership, User
from app.db.session import get_db
from app.services.generation.models import GenerationOperation
from sqlalchemy import func, select


@pytest.fixture
def refresh_db(app, maker):
    async def seed():
        async with maker.begin() as db:
            db.add(User(id="test-user", google_sub="synthetic", email="admin@test.local", is_admin=True))
            db.add(LeagueMembership(user_id="test-user", league_id="synthetic"))
    asyncio.run(seed())
    async def isolated():
        async with maker.begin() as db:
            yield db
    app.dependency_overrides[get_db] = isolated
    yield maker
    app.dependency_overrides.pop(get_db, None)


def test_legacy_get_never_starts_work(client, monkeypatch):
    run = AsyncMock(side_effect=AssertionError("GET cannot run refresh"))
    monkeypatch.setattr("app.services.refresh_service.refresh_league", run)
    response = client.get("/api/league/synthetic/refresh?force=1")
    assert response.status_code == 410
    run.assert_not_awaited()


def test_post_joins_job_and_observation_is_read_only(client, refresh_db):
    first = client.post("/api/league/synthetic/refresh-jobs", json={"idempotency_key": "one"})
    second = client.post("/api/league/synthetic/refresh-jobs", json={"idempotency_key": "two"})
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    path = "/api/league/synthetic/refresh-jobs/" + first.json()["id"]
    for _ in range(3):
        response = client.get(path)
        assert response.json()["state"] == "queued"
        assert "payload_json" not in response.json()
    async def count():
        async with refresh_db() as db:
            return await db.scalar(select(func.count()).select_from(GenerationOperation))
    assert asyncio.run(count()) == 1


def test_job_id_cannot_be_observed_through_another_league(client, refresh_db):
    submitted = client.post("/api/league/synthetic/refresh-jobs", json={}).json()
    response = client.get("/api/league/another/refresh-jobs/" + submitted["id"])
    assert response.status_code == 404


def test_force_is_not_a_member_bypass(client, refresh_db):
    response = client.post("/api/league/synthetic/refresh-jobs", json={"force": True})
    assert response.status_code == 422


def test_deleted_cache_can_rebuild_after_recent_success_without_paid_work(client, refresh_db, monkeypatch):
    monkeypatch.setattr("app.services.chain_cache.ChainCache.read", lambda *a, **kw: None)
    first = client.post("/api/league/synthetic/refresh-jobs",json={}).json()
    async def finish():
        async with refresh_db.begin() as db:
            job=await db.get(GenerationOperation,first["id"])
            job.state,job.active_key="succeeded",None
    asyncio.run(finish())
    second=client.post("/api/league/synthetic/refresh-jobs",json={}).json()
    assert second["id"] != first["id"]
    assert second["state"] == "queued"


def test_yahoo_submission_requires_own_current_grant(client, refresh_db, monkeypatch):
    monkeypatch.setenv("YAHOO_DEV_ACCESS_TOKEN", "not-an-account-connection")
    response = client.post("/api/league/470.l.100000001/refresh-jobs", json={})
    assert response.status_code == 409
    assert "connection" in response.json()["detail"].lower()
