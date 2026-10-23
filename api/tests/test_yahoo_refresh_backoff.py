"""Durable Yahoo throttling must not require a human or repeat paid work."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services.generation.commands import claim_operation
from app.services.generation.models import GenerationOperation, ProviderAttempt, stamp
from app.services.generation.worker import Worker
from sqlalchemy import func, select

from sleeper_dynasty.api.yahoo import YahooRateLimitError
from tests.test_generation_gateway import FakeTransport
from tests.test_generation_refresh_recovery import seed_refresh


@pytest.mark.asyncio
async def test_rate_limit_survives_restart_and_resumes_same_free_job(maker, tmp_path, monkeypatch):
    # Mutation: attention() on throttling or ignoring next_attempt_at breaks automatic recovery.
    await seed_refresh(maker, state="queued")
    monkeypatch.setattr("app.services.platform_client.connected_client",
                        AsyncMock(return_value=SimpleNamespace(close=AsyncMock())))
    build = AsyncMock(side_effect=YahooRateLimitError("slow down"))
    monkeypatch.setattr("app.services.refresh_service.refresh_league", build)
    transport = FakeTransport()
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    assert await worker.tick()
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert (job.state, job.reason) == ("queued", "yahoo_rate_limited")
        assert job.next_attempt_at >= stamp() + 899
        assert job.retry_count == 1
        assert json.loads(job.progress_json)["stage"] == "cooldown"
        due = job.next_attempt_at
    restarted = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    assert not await restarted.tick()
    async with maker.begin() as db:
        assert await claim_operation(db, "early", now=due - 1) is None
        job = await db.get(GenerationOperation, "job")
        job.next_attempt_at = stamp() - 1
    build.side_effect = None
    assert await restarted.tick()
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.state == "succeeded"
        assert job.calls == job.max_calls == transport.sends == 0
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 1
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0


@pytest.mark.asyncio
async def test_repeated_throttles_increase_delay_and_honor_retry_after(maker, tmp_path, monkeypatch):
    # Mutation: fixed delay or dropping Retry-After retries before Yahoo permits it.
    await seed_refresh(maker, state="queued")
    connect = AsyncMock(side_effect=YahooRateLimitError("slow", retry_after=3600))
    monkeypatch.setattr("app.services.platform_client.connected_client", connect)
    worker = Worker(maker, tmp_path, transport=FakeTransport(), epoch="test-epoch")
    assert await worker.tick()
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.next_attempt_at >= stamp() + 3599
        job.next_attempt_at = stamp() - 1
    connect.side_effect = YahooRateLimitError("slow")
    assert await worker.tick()
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.retry_count == 2
        assert job.next_attempt_at >= stamp() + 1799


@pytest.mark.asyncio
async def test_cooling_yahoo_job_does_not_starve_sleeper(maker):
    # Mutation: selecting oldest queued job before checking due time starves other leagues.
    await seed_refresh(maker, state="queued")
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.league_id = "999.l.123"
        job.next_attempt_at = stamp() + 900
        db.add(GenerationOperation(id="ready", kind="refresh", league_id="other",
                                   state="queued", created_at=stamp() + 1))
    async with maker.begin() as db:
        assert (await claim_operation(db, "worker")).id == "ready"


@pytest.mark.asyncio
async def test_yahoo_cooldown_blocks_other_yahoo_jobs_until_exact_boundary(maker):
    # Mutation: per-job gating alone lets another Yahoo league immediately hit the provider.
    await seed_refresh(maker, state="queued")
    due = stamp() + 900
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.league_id, job.next_attempt_at = "999.l.123", due
        db.add(GenerationOperation(id="other", kind="refresh", league_id="999.l.456",
                                   state="queued", created_at=stamp() - 1))
    async with maker.begin() as db:
        assert await claim_operation(db, "early", now=due - 1) is None
        assert (await claim_operation(db, "due", now=due)).id == "other"


@pytest.mark.asyncio
@pytest.mark.parametrize("activity", ["calls", "allowance", "receipt"])
async def test_automatic_backoff_refuses_paid_activity(maker, activity):
    # Mutation: a free kind alone authorizes retry of rows containing paid activity.
    from app.services.generation.yahoo_backoff import defer_refresh
    await seed_refresh(maker, state="running")
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        if activity == "calls":
            job.calls = 1
        elif activity == "allowance":
            job.max_calls = 1
        else:
            db.add(ProviderAttempt(operation_id=job.id, stage=1, generation=1,
                request_digest="saved", request_json="{}", model="saved", state="received"))
        await db.flush()
        assert not await defer_refresh(db, job, YahooRateLimitError("slow"))
        assert job.state == "running" and job.next_attempt_at == 0


@pytest.mark.asyncio
async def test_resume_rechecks_membership_before_network(maker, tmp_path, monkeypatch):
    # Mutation: resuming directly from a stored client bypasses revoked membership.
    from app.db.models import LeagueMembership
    from sqlalchemy import delete
    await seed_refresh(maker, state="queued")
    connect = AsyncMock(side_effect=YahooRateLimitError("slow"))
    monkeypatch.setattr("app.services.platform_client.connected_client", connect)
    worker = Worker(maker, tmp_path, transport=FakeTransport(), epoch="test-epoch")
    assert await worker.tick()
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.next_attempt_at = stamp() - 1
        await db.execute(delete(LeagueMembership))
    assert await worker.tick()
    assert connect.await_count == 1
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert (job.state, job.reason) == ("held", "membership_removed")


def test_http_wrapper_preserves_only_typed_yahoo_throttles():
    # Mutation: treating every HTTP 503 as throttling retries permanent unrelated failures.
    from app.services.generation.yahoo_backoff import throttle_error
    from fastapi import HTTPException
    generic = HTTPException(503, "unavailable")
    assert throttle_error(generic) is None
    generic.__cause__ = YahooRateLimitError("slow", retry_after=7200)
    assert throttle_error(generic).retry_after == 7200
