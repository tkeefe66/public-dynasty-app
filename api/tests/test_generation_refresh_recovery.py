"""Free collection recovery stays explicit and cannot renew paid authorization."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, func, select

from app.db.models import LeagueMembership, YahooConnection, YahooLeagueGrant
from app.services.generation.administration import job_action
from app.services.generation.bulk_jobs import blocked_reason
from app.services.generation.commands import submit_refresh
from app.services.generation.models import (
    GenerationAudit,
    GenerationControl,
    GenerationOperation,
    ProviderAttempt,
    stamp,
)
from app.services.generation.store import Conflict, Held
from app.services.generation.worker import Worker
from tests.test_generation_gateway import FakeTransport, seed_job


async def seed_refresh(maker, *, kind="refresh", state="needs_attention"):
    await seed_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.kind, job.feature, job.subject = kind, "", ""
        job.max_calls, job.calls = 0, 0
        job.state, job.reason = state, "execution_failed" if state == "needs_attention" else ""
        job.active_key = "refresh:synthetic"
        job.progress_json = '{"stage":"chain","message":"Previous attempt"}'


def retry_body(job):
    return SimpleNamespace(action="resume", expected_generation=job.generation,
        expected_state=job.state, reason="Scoring mapping repaired; retry data collection")


@pytest.mark.asyncio
async def test_failed_refresh_waits_for_review_then_runs_one_new_attempt_without_paid_work(maker, tmp_path, monkeypatch):
    await seed_refresh(maker, state="queued")
    client = SimpleNamespace(close=AsyncMock())
    connected = AsyncMock(return_value=client)
    monkeypatch.setattr("app.services.platform_client.connected_client", connected)
    build = AsyncMock(side_effect=RuntimeError("Scoring mapping needs repair"))
    monkeypatch.setattr("app.services.refresh_service.refresh_league", build)
    transport = FakeTransport()
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")

    assert await worker.tick()
    assert not await worker.tick()  # A permanent failure never retries itself.
    async with maker.begin() as db:
        stopped = await db.get(GenerationOperation, "job")
        assert (stopped.state, stopped.reason) == ("needs_attention", "execution_failed")
        generation = stopped.generation
        body = retry_body(stopped)
        # Repeated member submissions join the stopped job; they do not retry it.
        joined = await submit_refresh(db, "synthetic", "owner", idempotency_key="new-browser-request")
        assert joined.id == stopped.id and joined.state == "needs_attention"
        result = await job_action(db, stopped.id, body, "owner")
        assert result["state"] == "queued" and result["progress_json"] == "{}"
        assert result["actor_id"] == "owner" and result["max_calls"] == 0
    async with maker.begin() as db:
        with pytest.raises(Conflict, match="Job state changed"):
            await job_action(db, "job", body, "owner")

    build.side_effect = None
    assert await worker.tick()
    assert not await worker.tick()
    assert build.await_count == 2
    assert transport.sends == 0
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.state == "succeeded" and job.generation == generation + 1
        assert job.active_key is None and job.calls == job.max_calls == 0
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 1
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
        audit = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == "job_resumed"))
        assert audit.reason == body.reason and audit.target == job.id


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["refresh", "analyst_refresh"])
async def test_explicit_batch_review_can_include_free_refresh_failure(maker, kind):
    await seed_refresh(maker, kind=kind)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        control = await db.get(GenerationControl, "global")
        assert await blocked_reason(db, job, control) == ""
        assert (await job_action(db, job.id, retry_body(job), "owner"))["state"] == "queued"


@pytest.mark.asyncio
@pytest.mark.parametrize("activity", ["allowance", "calls", "receipt"])
async def test_free_refresh_retry_never_reclassifies_paid_activity(maker, activity):
    await seed_refresh(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        if activity == "allowance":
            job.max_calls = 2
        elif activity == "calls":
            job.calls = 1
        else:
            db.add(ProviderAttempt(operation_id=job.id, stage=1, generation=job.generation,
                request_digest="saved", request_json="{}", model="saved", state="received"))
        await db.flush()
        control = await db.get(GenerationControl, "global")
        assert await blocked_reason(db, job, control) == "data_refresh_has_provider_activity"
        with pytest.raises(Held, match="data_refresh_has_provider_activity"):
            await job_action(db, job.id, retry_body(job), "owner")
        assert job.state == "needs_attention"


@pytest.mark.asyncio
async def test_retry_rechecks_original_member_instead_of_using_the_admins_access(maker):
    await seed_refresh(maker)
    async with maker.begin() as db:
        await db.execute(delete(LeagueMembership))
        job = await db.get(GenerationOperation, "job")
        with pytest.raises(Held, match="membership_removed"):
            await job_action(db, job.id, retry_body(job), "different-admin")
        assert job.state == "needs_attention" and job.actor_id == "owner"


@pytest.mark.asyncio
async def test_yahoo_retry_cannot_switch_to_a_new_connection_generation(maker):
    await seed_refresh(maker)
    league_id = "999.l.100000001"
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.league_id, job.active_key = league_id, "refresh:" + league_id
        job.connection_generation = "original-connection"
        db.add(LeagueMembership(user_id="owner", league_id=league_id))
        db.add(YahooConnection(user_id="owner", generation="replacement-connection",
            sealed_tokens="synthetic", expires_at=stamp() + 3600))
        db.add(YahooLeagueGrant(user_id="owner", league_id=league_id,
            generation="replacement-connection", expires_at=stamp() + 300))
        await db.flush()
        with pytest.raises(Held, match="provider_grant_changed"):
            await job_action(db, job.id, retry_body(job), "owner")
        assert job.state == "needs_attention" and job.connection_generation == "original-connection"
