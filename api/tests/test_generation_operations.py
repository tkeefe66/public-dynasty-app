"""Mutation targets: dedup key, ownership fence, unresolved-attempt recovery."""
import pytest
from app.services.generation.commands import (
    cancel,
    claim_operation,
    finish,
    submit_refresh,
)
from app.services.generation.models import GenerationOperation, ProviderAttempt
from app.services.generation.store import Conflict, OwnershipLost


@pytest.mark.asyncio
async def test_duplicate_refresh_joins_and_payload_key_conflicts(maker):
    async with maker.begin() as db:
        first = await submit_refresh(db, "synthetic-league", "user", idempotency_key="click")
    async with maker.begin() as db:
        second = await submit_refresh(db, "synthetic-league", "user", idempotency_key="other-click")
        assert second.id == first.id
    async with maker.begin() as db:
        with pytest.raises(Conflict):
            await submit_refresh(db, "other-league", "user", idempotency_key="click")
    async with maker.begin() as db:
        with pytest.raises(Conflict):
            await submit_refresh(db, "other-league", "user", idempotency_key="other-click")


@pytest.mark.asyncio
async def test_expired_worker_cannot_finish_after_reclaim(maker):
    async with maker.begin() as db:
        job = await submit_refresh(db, "synthetic-league", "user")
    async with maker.begin() as db:
        first = await claim_operation(db, "worker-a", now=100)
        first_generation = first.generation
    async with maker.begin() as db:
        second = await claim_operation(db, "worker-b", now=10000)
        assert second.generation > first_generation
    async with maker.begin() as db:
        with pytest.raises(OwnershipLost):
            await finish(db, job.id, first_generation, now=10001)


@pytest.mark.asyncio
async def test_expired_paid_attempt_is_held_not_reclaimed(maker):
    async with maker.begin() as db:
        job = GenerationOperation(kind="generation", league_id="synthetic", subject="item",
            active_key="item", state="running", worker_id="a", generation=1, lease_until=1)
        db.add(job)
        await db.flush()
        db.add(ProviderAttempt(operation_id=job.id, stage=1, generation=1,
            request_digest="digest", request_json="{}", model="synthetic-model"))
    async with maker.begin() as db:
        assert await claim_operation(db, "b", now=10000) is None
        held = await db.get(GenerationOperation, job.id)
        assert held.state == "needs_attention"
        assert held.reason == "provider_outcome_unknown"


@pytest.mark.asyncio
async def test_cancel_revokes_ownership_but_retains_attempt(maker):
    async with maker.begin() as db:
        job = await submit_refresh(db, "synthetic-league", "user")
        owned = await claim_operation(db, "worker", now=100)
        generation = owned.generation
    async with maker.begin() as db:
        await cancel(db, job.id, "owner", "stop unwanted work")
    async with maker.begin() as db:
        with pytest.raises(OwnershipLost):
            await finish(db, job.id, generation, now=101)
