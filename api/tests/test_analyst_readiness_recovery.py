"""Readiness waits cannot consume recovery attempts or authorize paid writing."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.services.generation.models import GenerationOperation, ProviderAttempt, stamp
from app.services.generation.worker import Worker
from tests.test_generation_gateway import FakeTransport
from tests.test_generation_refresh_recovery import seed_refresh


@pytest.mark.asyncio
async def test_incomplete_results_wait_across_restart_then_complete_without_ai(maker, tmp_path, monkeypatch):
    from app.services.generation.readiness import ResultsNotReady
    await seed_refresh(maker, kind="analyst_refresh", state="queued")
    monkeypatch.setattr("app.services.platform_client.connected_client",
                        AsyncMock(return_value=SimpleNamespace(close=AsyncMock())))
    build = AsyncMock(side_effect=ResultsNotReady(7))
    monkeypatch.setattr("app.services.analyst.generate_analyst", build)
    transport = FakeTransport()
    assert await Worker(maker, tmp_path, transport=transport, epoch="test-epoch").tick()
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert (job.state, job.reason) == ("queued", "results_not_ready")
        assert job.next_attempt_at >= stamp() + 899
        assert json.loads(job.progress_json)["week"] == 7
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    assert not await worker.tick()
    async with maker.begin() as db:
        (await db.get(GenerationOperation, "job")).next_attempt_at = stamp() - 1
    build.side_effect = None
    assert await worker.tick()
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).state == "succeeded"
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
    assert transport.sends == 0


@pytest.mark.asyncio
async def test_persistent_readiness_escalates_with_cause(maker):
    from app.services.generation.readiness import ResultsNotReady, defer_results
    await seed_refresh(maker, kind="analyst_refresh", state="running")
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.progress_json = json.dumps(dict(readiness_since=stamp() - 48 * 3600, week=7))
        assert await defer_results(db, job, ResultsNotReady(7))
        assert (job.state, job.reason) == ("needs_attention", "results_not_ready")
        assert job.next_attempt_at == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("activity", ["calls", "max_calls", "receipt", "paid_kind"])
async def test_readiness_never_retries_paid_work(maker, activity):
    from app.services.generation.readiness import ResultsNotReady, defer_results
    await seed_refresh(maker, kind="analyst_refresh", state="running")
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        if activity in ("calls", "max_calls"):
            setattr(job, activity, 1)
        elif activity == "paid_kind":
            job.kind = "generation"
        else:
            db.add(ProviderAttempt(operation_id=job.id, stage=1, generation=1,
                request_digest="saved", request_json="{}", model="saved"))
            await db.flush()
        assert not await defer_results(db, job, ResultsNotReady(7))
        assert job.state == "running"


@pytest.mark.asyncio
async def test_exhausted_recovery_email_retains_actual_job_cause(maker):
    from app.services.recap_monitor.recovery import recover
    from app.services.recap_monitor.mail import message
    await seed_refresh(maker, kind="analyst_refresh")
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.reason = "results_not_ready"
        result = await recover(db, dict(job_id="job", league_id=job.league_id,
            recovery_attempts=2, week=7), job.actor_id, stamp())
        assert result["job_reason"] == "results_not_ready"
        payload = message(result, "owner@example.test", "recaps@example.test")
        assert "Week 7 results are incomplete" in payload["text"]
        assert "Week 7 results are incomplete" in payload["html"]
        assert "additional calls require" not in payload["text"]


@pytest.mark.asyncio
async def test_readiness_wait_does_not_block_another_yahoo_league(maker):
    from app.services.generation.commands import claim_operation
    await seed_refresh(maker, kind="analyst_refresh", state="queued")
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.league_id, job.reason = "999.l.123", "results_not_ready"
        job.next_attempt_at = stamp() + 3600
        db.add(GenerationOperation(id="other", kind="refresh", league_id="999.l.456", state="queued"))
    async with maker.begin() as db:
        claimed = await claim_operation(db, "worker")
        assert claimed is not None and claimed.id == "other"


@pytest.mark.asyncio
async def test_readiness_wait_preserves_recovery_allowance(maker):
    from app.services.recap_monitor.recovery import recover
    await seed_refresh(maker, kind="analyst_refresh", state="queued")
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.reason, job.next_attempt_at = "results_not_ready", stamp() + 900
        out = await recover(db, dict(job_id="job", league_id=job.league_id,
            recovery_attempts=2), job.actor_id, stamp())
        assert out["status"] == "waiting" and out["gate"] == job.next_attempt_at
        assert out["recovery_attempts"] == 2 and not out["recoverable"]
