import json

import pytest
from sqlalchemy import func, select

from app.services.generation.accounting import price_usage, pricing
from app.services.generation.gateway import Gateway
from app.services.generation.models import GenerationAudit, GenerationOutbox, ProviderAttempt
from app.services.generation.recap_models import ProviderAccountControl, RecapBudgetAllocation, RecapBudgetPlan
from app.services.generation.store import Held, data, dump
from app.services.generation.transport import Receipt
from tests.test_generation_gateway import BODY, REQUEST, FakeTransport, seed_job


# Captured production usage shape; contains no account or request identifiers.
USAGE = {"input_tokens": 4925, "output_tokens": 172,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
         "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0},
         "service_tier": "standard", "inference_geo": "not_available"}


@pytest.mark.parametrize("geo", ["not_available", "global"])
def test_standard_geography_is_priced(geo):
    # Mutation: reject all geography metadata as an unknown billable dimension.
    body = {**BODY, "usage": {**USAGE, "inference_geo": geo}}
    assert price_usage(body, pricing(REQUEST["model"])) == ("known", body["usage"], 5785)


@pytest.mark.parametrize("geo", ["us", "future-region", None, {}, 1])
def test_unqualified_geography_stays_unknown(geo):
    # Mutation: accept any geography at standard rates, undercounting US pricing.
    body = {**BODY, "usage": {**USAGE, "inference_geo": geo}}
    assert price_usage(body, pricing(REQUEST["model"]))[2] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("extra_usage", [{}, {"speed": "standard"}])
async def test_reprice_saved_receipt_once_without_network(maker, extra_usage):
    # Mutation: settled_at prevents repairing unknown prices; repeat emits duplicate usage.
    await seed_job(maker)
    receipt = Receipt(200, json.dumps({**BODY, "usage": {**USAGE, **extra_usage}}), {"request-id": "synthetic"})
    raw = dump({"status": receipt.status, "body": receipt.body, "headers": receipt.headers})
    async with maker.begin() as db:
        row = ProviderAttempt(operation_id="job", stage=1, generation=1,
            request_digest="synthetic", request_json=dump(REQUEST), model=REQUEST["model"],
            pricing_json=dump(pricing(REQUEST["model"])), state="received", usage_state="pricing_unknown",
            error_code="pricing_unknown", receipt_json=raw, settled_at=1)
        db.add(row)
        await db.flush()
        ident = row.id
        db.add(ProviderAccountControl(provider="anthropic", account_key="primary", hold="accounting_attention"))
        db.add(RecapBudgetPlan(id="plan", episode_id="synthetic", series_id="series", plan_key="repair", digest="synthetic"))
        db.add(RecapBudgetAllocation(id="allocation", plan_id="plan", key="1", category="managed",
            operation_id="job", attempt_id=ident, month_key="2026-10", max_microusd=10000,
            outstanding_microusd=10000, rate_json=dump(pricing(REQUEST["model"])), state="unknown"))
    transport = FakeTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    for _ in range(2):
        await gateway.record_receipt(ident, receipt, reprice=True)
    async with maker() as db:
        row = await db.get(ProviderAttempt, ident)
        assert (row.cost_microusd, row.usage_state, row.error_code, row.receipt_json) == (5785, "known", "", raw)
        assert await db.scalar(select(func.count()).select_from(GenerationOutbox)) == 1
        allocation = await db.get(RecapBudgetAllocation, "allocation")
        assert (allocation.actual_microusd, allocation.outstanding_microusd, allocation.state) == (5785, 0, "settled")
        assert (await db.get(ProviderAccountControl, ("anthropic", "primary"))).hold == "accounting_attention"
        assert await db.scalar(select(func.count()).select_from(GenerationAudit).where(
            GenerationAudit.action == "budget_settled")) == 1
    with pytest.raises(Held, match="receipt_conflict"):
        await gateway.record_receipt(ident, Receipt(200, receipt.body, {"request-id": "changed"}), reprice=True)
    assert transport.sends == 0


@pytest.mark.parametrize("speed", ["fast", "future", None, {}, 1])
def test_unqualified_speed_stays_unknown(speed):
    body = {**BODY, "usage": {**USAGE, "speed": speed}}
    assert price_usage(body, pricing(REQUEST["model"]))[2] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,kind,extra,expected", [(400, "invalid_request_error", {}, 0),
    (500, "api_error", {}, None), (400, "unknown_error", {}, None),
    (500, "invalid_request_error", {}, None),
    (400, "invalid_request_error", {"usage": {}}, None),
    (400, "invalid_request_error", {"content": []}, None)])
async def test_rejected_request_cost_preserves_uncertain_server_errors(maker, status, kind, extra, expected):
    # Mutation: all errors remain unknown, or all errors incorrectly become free.
    await seed_job(maker)
    async with maker.begin() as db:
        row = ProviderAttempt(operation_id="job", stage=1, generation=1,
            request_digest="synthetic", request_json=dump(REQUEST), model=REQUEST["model"],
            pricing_json=dump(pricing(REQUEST["model"])))
        db.add(row)
        await db.flush()
        ident = row.id
    receipt = Receipt(status, json.dumps({"type": "error", "error": {"type": kind,
        "message": "Your credit balance is too low to access the Anthropic API."}, **extra}), {})
    await Gateway(maker, FakeTransport(), epoch="test-epoch").record_receipt(ident, receipt)
    async with maker() as db:
        row = await db.get(ProviderAttempt, ident)
        assert row.cost_microusd == expected
        assert row.state == ("rejected" if status == 400 else "unknown")
        if expected == 0:
            assert row.usage_state == "not_billed"
        assert await db.scalar(select(func.count()).select_from(GenerationOutbox)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 429])
async def test_unsuccessful_reprice_does_not_repeat_provider_failure(maker, status):
    # Mutation: replaying unpriceable receipts resets holds/cooldowns and adds audit events.
    await seed_job(maker)
    async with maker.begin() as db:
        row = ProviderAttempt(operation_id="job", stage=1, generation=1,
            request_digest="synthetic", request_json=dump(REQUEST), model=REQUEST["model"],
            pricing_json=dump(pricing(REQUEST["model"])))
        db.add(row)
        await db.flush()
        ident = row.id
    receipt = Receipt(status, json.dumps({"type": "error", "error": {"type": "synthetic"}}), {})
    gateway = Gateway(maker, FakeTransport(), epoch="test-epoch")
    await gateway.record_receipt(ident, receipt)
    async with maker.begin() as db:
        control = await db.get(ProviderAccountControl, ("anthropic", "primary"))
        control.hold, control.cooldown_until = "", 0
        await db.flush()
        before = data(control)
        events = await db.scalar(select(func.count()).select_from(GenerationAudit))
    await gateway.record_receipt(ident, receipt, reprice=True)
    async with maker() as db:
        assert data(await db.get(ProviderAccountControl, ("anthropic", "primary"))) == before
        assert await db.scalar(select(func.count()).select_from(GenerationAudit)) == events
