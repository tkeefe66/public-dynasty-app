"""Mutation targets: pause-before-send, receipt replay, unknown-response resend."""
import asyncio
import json

import pytest
from app.db.models import LeagueMembership, User
from app.services.generation.gateway import Gateway
from app.services.generation.models import (
    GenerationControl,
    GenerationOperation,
    GenerationPolicy,
    LeagueSeason,
    LeagueSeries,
    ProviderAttempt,
    stamp,
)
from app.services.generation.policy import Policy
from app.services.generation.store import Held, OwnershipLost, dump
from app.services.generation.transport import Receipt

REQUEST = {"model": "claude-haiku-4-5-20251001", "max_tokens": 128,
           "messages": [{"role": "user", "content": "synthetic facts"}]}
BODY = {"id": "synthetic-message", "type": "message", "role": "assistant",
        "model": REQUEST["model"], "content": [{"type": "text", "text": "saved"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}


class FakeTransport:
    def __init__(self, *, body=None, lost=False, blocked=False):
        self.body = json.dumps(BODY) if body is None else body
        self.lost = lost
        self.blocked = blocked
        self.sends = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def send(self, request):
        self.sends += 1
        self.started.set()
        if self.blocked:
            await self.release.wait()
        if self.lost:
            raise TimeoutError("accepted then response lost")
        return Receipt(200, self.body, {"request-id": "synthetic-request"})


async def seed_job(maker):
    async with maker.begin() as db:
        db.add(User(id="owner", google_sub="synthetic", email="owner@test.local", is_admin=True))
        db.add(LeagueMembership(user_id="owner", league_id="synthetic"))
        db.add(GenerationControl(id="global", epoch="test-epoch", hold=""))
        db.add(GenerationPolicy(scope="app", value_json=dump({"paused": False})))
        db.add(LeagueSeries(id="series", lifecycle="active", profile="dynasty", hold="", activated_at=1))
        db.add(LeagueSeason(league_id="synthetic", provider="sleeper", provider_key="synthetic",
            series_id="series", season=2026, verified_at=1,
            capabilities_json=dump({"format": "dynasty", "future_picks": True,
                "roster_continuity": True, "multiyear_history": True})))
        job = GenerationOperation(id="job", kind="generation", league_id="synthetic",
            series_id="series", feature="trade_story", subject="story", state="running",
            actor_id="owner", actor_kind="admin", generation=1, lease_until=stamp()+600,
            epoch="test-epoch", max_calls=2,
            policy_json=dump({"policy": Policy(paused=False).model_dump()}))
        db.add(job)
    return "job"


@pytest.mark.asyncio
async def test_completed_receipt_replays_without_second_call(maker):
    job = await seed_job(maker)
    transport = FakeTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    first = await gateway.invoke(job, 1, 1, REQUEST)
    second = await gateway.invoke(job, 1, 1, REQUEST)
    assert first == second == BODY
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_lost_response_stays_unknown_across_recovery(maker):
    job = await seed_job(maker)
    transport = FakeTransport(lost=True)
    for _ in range(3):
        with pytest.raises(Held, match="provider_outcome_unknown"):
            await Gateway(maker, transport, epoch="test-epoch").invoke(job, 1, 1, REQUEST)
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_pause_prevents_next_paid_stage(maker):
    job = await seed_job(maker)
    transport = FakeTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    await gateway.invoke(job, 1, 1, REQUEST)
    async with maker.begin() as db:
        row = await db.get(GenerationPolicy, "app")
        row.value_json = dump({"paused": True})
    with pytest.raises(Held, match="app_paused"):
        await gateway.invoke(job, 1, 2, REQUEST)
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_malformed_body_is_saved_before_parse_failure(maker):
    from sqlalchemy import select
    job = await seed_job(maker)
    transport = FakeTransport(body="not json")
    with pytest.raises(Held, match="response_invalid"):
        await Gateway(maker, transport, epoch="test-epoch").invoke(job, 1, 1, REQUEST)
    async with maker() as db:
        attempt = await db.scalar(select(ProviderAttempt))
        assert json.loads(attempt.receipt_json)["body"] == "not json"
        assert attempt.usage_state == "unknown"
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_late_cancelled_response_is_accounted_but_cannot_advance(maker):
    from app.services.generation.commands import cancel
    from sqlalchemy import select
    job = await seed_job(maker)
    transport = FakeTransport(blocked=True)
    gateway = Gateway(maker, transport, epoch="test-epoch")
    task = asyncio.create_task(gateway.invoke(job, 1, 1, REQUEST))
    await transport.started.wait()
    async with maker.begin() as db:
        await cancel(db, job, "owner", "cancel")
    transport.release.set()
    with pytest.raises(OwnershipLost):
        await task
    async with maker() as db:
        attempt = await db.scalar(select(ProviderAttempt))
        assert attempt.cost_microusd == 35
        assert attempt.state == "received"
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_checkpoint_request_cannot_change(maker):
    job = await seed_job(maker)
    transport = FakeTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    await gateway.invoke(job, 1, 1, REQUEST)
    with pytest.raises(Held, match="checkpoint_request_changed"):
        await gateway.invoke(job, 1, 1, {**REQUEST, "max_tokens": 129})
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_saved_raw_receipt_recovers_accounting_without_network(maker):
    from app.services.generation.accounting import pricing
    from app.services.generation.store import digest
    job = await seed_job(maker)
    async with maker.begin() as db:
        row = await db.get(GenerationOperation, job)
        row.calls = 1
        db.add(ProviderAttempt(operation_id=job, stage=1, generation=1,
            model=REQUEST["model"], request_json=dump(REQUEST), request_digest=digest(REQUEST),
            pricing_json=dump(pricing(REQUEST["model"])),
            receipt_json=dump({"status": 200, "body": json.dumps(BODY), "headers": {}})))
    transport = FakeTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    await gateway.reconcile_receipts()
    assert await gateway.invoke(job, 1, 1, REQUEST) == BODY
    assert transport.sends == 0


def test_cache_dimensions_are_priced_once_with_distinct_ttls():
    from app.services.generation.accounting import price_usage, pricing
    body = {**BODY, "usage": {"input_tokens": 10, "output_tokens": 5,
        "cache_read_input_tokens": 10, "cache_creation_input_tokens": 30,
        "cache_creation": {"ephemeral_5m_input_tokens": 10, "ephemeral_1h_input_tokens": 20}}}
    state, _, cost = price_usage(body, pricing(REQUEST["model"]))
    assert state == "known"
    assert cost == 89  # 10 + 25 + 1 + 12.5 + 40, rounded up once.


def test_unknown_usage_is_never_zero():
    from app.services.generation.accounting import price_usage, pricing
    state, _, cost = price_usage({"model": REQUEST["model"]}, pricing(REQUEST["model"]))
    assert state == "unknown"
    assert cost is None
