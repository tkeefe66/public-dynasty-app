"""Reviewed free refresh recovery must never become paid retry authorization."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select

from app.auth.deps import get_current_user, require_admin
from app.db.models import LeagueMembership, User, YahooConnection, YahooLeagueGrant
from app.db.session import get_db
from app.services.generation.administration import job_action
from app.services.generation.bulk_jobs import preview_jobs
from app.services.generation.models import (
    GenerationAudit, GenerationControl, GenerationOperation, ProviderAttempt, stamp,
)
from app.services.generation.store import Held, data

LEAGUE = "470.l.123456"
REASON = "Yahoo scoring import repaired; resume the saved data refresh"


async def seed_failed(maker, kind="refresh", reason="execution_failed"):
    async with maker.begin() as db:
        db.add_all([
            User(id="member", google_sub="member", email="member@test.local", is_admin=False),
            User(id="owner", google_sub="owner", email="owner@test.local", is_admin=True),
            LeagueMembership(user_id="member", league_id=LEAGUE),
            YahooConnection(user_id="member", generation="original", sealed_tokens="not-used",
                            status="connected", expires_at=stamp() - 1),
            # Expiry is renewed by connected_client in the worker, outside the
            # global mutation lock. Identity and generation must still match.
            YahooLeagueGrant(user_id="member", league_id=LEAGUE, generation="original", expires_at=stamp() - 1),
            GenerationControl(id="global", epoch="unchanged", hold="owner_paused",
                              provider_hold="provider_issue", cooldown_until=stamp() + 900,
                              breakers_json='{"analyst":{"open":true}}'),
            GenerationOperation(id="free-job", kind=kind, league_id=LEAGUE,
                                actor_id="member", actor_kind="member", connection_generation="original",
                                state="needs_attention", reason=reason, generation=3,
                                active_key="refresh:" + LEAGUE, calls=0, max_calls=0,
                                progress_json='{"stage":"chain","message":"Previous attempt"}'),
        ])


def resume_body():
    return SimpleNamespace(action="resume", expected_generation=3,
                           expected_state="needs_attention", reason=REASON)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["refresh", "analyst_refresh"])
async def test_reviewed_free_failure_requeues_same_actor_without_changing_ai_controls(maker, monkeypatch, kind):
    await seed_failed(maker, kind)

    async def no_network(*args, **kwargs):
        raise AssertionError("Recovery must not renew Yahoo credentials under the global lock")

    monkeypatch.setattr("app.services.yahoo_connection.YahooConnectionService.ensure_grant", no_network)
    async with maker.begin() as db:
        before = data(await db.get(GenerationControl, "global"))
        result = await job_action(db, "free-job", resume_body(), "owner")
        assert result["state"] == "queued"
        assert result["reason"] == ""
        assert result["actor_id"] == "member"
        assert result["actor_kind"] == "member"
        assert result["connection_generation"] == "original"
        assert result["generation"] == 3  # the next worker claim advances ownership
        assert result["calls"] == result["max_calls"] == 0
        assert json.loads(result["progress_json"])["stage"] == "queued"
        assert data(await db.get(GenerationControl, "global")) == before
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 1
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
        audit = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == "job_resumed"))
        assert audit.actor_id == "owner" and audit.reason == REASON


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["dispatching", "unknown"])
async def test_free_recovery_refuses_unresolved_provider_attempts(maker, state):
    await seed_failed(maker)
    async with maker.begin() as db:
        db.add(ProviderAttempt(operation_id="free-job", stage=1, generation=3,
                               request_digest="saved", request_json="{}", model="saved-model", state=state))
    async with maker.begin() as db:
        with pytest.raises(Held, match="provider_outcome_unknown"):
            await job_action(db, "free-job", resume_body(), "owner")
        assert (await db.get(GenerationOperation, "free-job")).state == "needs_attention"


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", ["membership", "actor", "connection", "grant", "generation"])
async def test_free_recovery_rechecks_original_access(maker, revoked):
    await seed_failed(maker)
    async with maker.begin() as db:
        if revoked == "membership":
            # A different member still exists; that must not replace the job's
            # original Yahoo actor during owner-approved recovery.
            db.add(LeagueMembership(user_id="owner", league_id=LEAGUE))
            await db.execute(delete(LeagueMembership).where(LeagueMembership.user_id == "member"))
        elif revoked == "actor":
            await db.execute(delete(User).where(User.id == "member"))
        elif revoked == "connection":
            (await db.get(YahooConnection, "member")).status = "disconnected"
        elif revoked == "grant":
            await db.execute(delete(YahooLeagueGrant))
        else:
            (await db.get(YahooConnection, "member")).generation = "replacement"
            (await db.get(YahooLeagueGrant, ("member", LEAGUE))).generation = "replacement"
    async with maker.begin() as db:
        with pytest.raises(Held):
            await job_action(db, "free-job", resume_body(), "owner")
        assert (await db.get(GenerationOperation, "free-job")).state == "needs_attention"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,reason", [
    ("generation", "execution_failed"), ("unregistered", "execution_failed"),
    ("refresh", "yahoo_rate_limited"), ("analyst_refresh", "response_invalid"),
])
async def test_new_recovery_permission_is_limited_to_free_execution_failures(maker, kind, reason):
    await seed_failed(maker, kind, reason)
    async with maker.begin() as db:
        with pytest.raises(Held, match="Only held jobs"):
            await job_action(db, "free-job", resume_body(), "owner")
        assert (await db.get(GenerationOperation, "free-job")).state == "needs_attention"


@pytest.mark.asyncio
async def test_failed_free_refresh_still_requires_individual_review_in_bulk(maker):
    await seed_failed(maker)
    async with maker.begin() as db:
        result = await preview_jobs(db, ["free-job"], "resume", "owner", "Review selected jobs")
        assert result["items"] == []
        assert result["skipped"][0]["reason"] == "free_refresh_requires_individual_review"


@pytest.fixture
def free_db(app, maker):
    asyncio.run(seed_failed(maker))

    async def isolated():
        async with maker.begin() as db:
            yield db

    app.dependency_overrides[get_db] = isolated
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="owner", is_admin=True)
    yield maker
    app.dependency_overrides.pop(get_db, None)


def test_recovery_endpoint_requires_owner_reason_and_observed_job_version(client, app, free_db):
    payload = vars(resume_body())
    assert client.post("/api/admin/generation/jobs/free-job", json={**payload, "reason": ""}).status_code == 422
    assert client.post("/api/admin/generation/jobs/free-job", json={**payload, "expected_generation": 2}).status_code == 409
    app.dependency_overrides.pop(require_admin)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="member", is_admin=False)
    assert client.post("/api/admin/generation/jobs/free-job", json=payload).status_code == 403
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="owner", is_admin=True)
    resumed = client.post("/api/admin/generation/jobs/free-job", json=payload)
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "queued"
    assert client.post("/api/admin/generation/jobs/free-job", json=payload).status_code == 409
