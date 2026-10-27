"""An interrupted review remains a financial obligation after explicit recovery."""
import json

import pytest
from sqlalchemy import select

from app.services.generation.analyst_review_recovery import authorize, publication_attempts
from app.services.generation.artifacts import save_artifact
from app.services.generation.features import generate
from app.services.generation.gateway import Gateway
from app.services.generation.models import GenerationOperation, ProviderAttempt, stamp
from app.services.generation.recap_models import RecapBudgetAllocation
from app.services.generation.store import Held, digest, dump
from tests.test_generation_gateway import FakeTransport
from tests.test_generation_saved_draft_repair import failed_recap, running


async def interrupted(maker):
    fixture = await failed_recap(maker, calls=2, reason="provider_outcome_unknown")
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.max_calls = 4
        first = await db.get(ProviderAttempt, "source-1")
        receipt = json.loads(first.receipt_json)
        body = json.loads(receipt["body"])
        body["content"] = [{"type": "text", "text": "Team A scored 158 points."}]
        receipt["body"] = json.dumps(body)
        first.receipt_json = dump(receipt)
        lost = await db.get(ProviderAttempt, "source-2")
        request = json.loads(lost.request_json)
        evidence = json.loads(request["messages"][0]["content"])
        evidence["draft"] = "Team A scored 158 points."
        request["messages"][0]["content"] = json.dumps(evidence)
        lost.request_json, lost.request_digest = dump(request), digest(request)
        from app.services.generation.accounting import bounded_plan
        from app.services.generation.recap_budget import reserve_plan, operation_episode, settle_attempt
        feature = json.loads(job.policy_json)["policy"]["features"]["analyst"]
        plan = await reserve_plan(db, operation_episode(job), job.series_id, "operation:job",
                                  bounded_plan(job.id, "analyst", feature, feature, 4), stamp())
        allocation = await db.scalar(select(RecapBudgetAllocation).where(
            RecapBudgetAllocation.attempt_id == lost.id))
        reserved = await db.scalar(select(RecapBudgetAllocation).where(
            RecapBudgetAllocation.plan_id == plan, RecapBudgetAllocation.key == "2"))
        allocation.max_microusd = reserved.max_microusd
        allocation.actual_microusd = None
        allocation.outstanding_microusd = reserved.max_microusd
        allocation.rate_json = reserved.rate_json
        lost.state, lost.usage_state, lost.cost_microusd = "unknown", "unknown", None
        lost.receipt_json, lost.settled_at, lost.status_code = "", 0, None
        await settle_attempt(db, first, {"receipt": first.id})
        await settle_attempt(db, lost, {"interrupted": lost.id})
    return fixture


async def approve(maker, **overrides):
    async with maker.begin() as db:
        return await authorize(db, "job", **{**dict(actor="owner", expected_generation=1,
            workers_stopped=True, evidence="Synthetic stopped deployment, no receipt",
            reason="Owner approved one replacement review", maximum_total_microusd=3_000_000), **overrides})


@pytest.mark.asyncio
async def test_review_replacement_preserves_unknown_cost_and_requires_exact_approval(maker):
    # Mutation: zeroing the old charge, redrafting, or resending the new review on replay.
    fixture = await interrupted(maker)
    approval = await approve(maker)
    assert approval["maximum_total_microusd"] == 100 + 2 * approval["maximum_additional_microusd"]
    job = await running(maker, "job")
    body = fixture["responses"][1]
    body["content"][0]["input"] = {"approved": True, "checks": []}
    transport = FakeTransport(body=json.dumps(body))
    gateway = Gateway(maker, transport, epoch="test-epoch")
    result = await generate(job, gateway)
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
    assert (await generate(job, gateway)).payload["markdown"] == "Team A scored 158 points."
    assert transport.sends == 1
    async with maker.begin() as db:
        artifact = await save_artifact(db, job.id, job.generation, result)
        assert artifact.operation_id == "job"
        lost = await db.get(ProviderAttempt, "source-2")
        assert lost.state == "abandoned" and lost.cost_microusd is None and not lost.receipt_json
        allocation = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id == lost.id))
        assert allocation.outstanding_microusd == approval["source"]["unknown_ceiling_microusd"]
        attempts = list((await db.scalars(select(ProviderAttempt).order_by(ProviderAttempt.stage))).all())
        assert len(attempts) == 3
        assert len(await publication_attempts(db, job, result.payload, attempts)) == 2
        # Financial reconciliation must not erase valid publication evidence.
        from app.services.generation.recap_budget import reconcile_allocation
        await reconcile_allocation(db, allocation.id, 123, {"statement": "synthetic"},
                                   "owner", "Reconcile provider statement")
        assert len(await publication_attempts(db, job, result.payload, attempts)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["ceiling", "stopped", "draft", "receipt", "unbounded"])
async def test_review_replacement_rejects_missing_or_changed_evidence(maker, change):
    # Mutation: allowing replacement without a complete saved draft and bounded unknown charge.
    await interrupted(maker)
    if change in ("draft", "receipt", "unbounded"):
        async with maker.begin() as db:
            lost = await db.get(ProviderAttempt, "source-2")
            if change == "receipt":
                lost.receipt_json = "{}"
            elif change == "unbounded":
                allocation = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id == lost.id))
                allocation.outstanding_microusd = 0
            else:
                first = await db.get(ProviderAttempt, "source-1")
                receipt = json.loads(first.receipt_json)
                body = json.loads(receipt["body"])
                body["content"][0]["text"] = "Changed draft"
                receipt["body"] = json.dumps(body)
                first.receipt_json = dump(receipt)
    with pytest.raises(Held, match="lost_review"):
        await approve(maker, **({"maximum_total_microusd": 1} if change == "ceiling" else
                               {"workers_stopped": False} if change == "stopped" else {}))


@pytest.mark.asyncio
async def test_rejected_replacement_review_never_publishes_or_retries(maker):
    # Mutation: treating any received review as approval, or auto-retrying its rejection.
    fixture = await interrupted(maker)
    await approve(maker)
    job = await running(maker, "job")
    transport = FakeTransport(body=json.dumps(fixture["responses"][1]))
    gateway = Gateway(maker, transport, epoch="test-epoch")
    with pytest.raises(Held, match="saved_repair_valid_verdict_required"):
        await generate(job, gateway)
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
    with pytest.raises(Held):
        await generate(job, gateway)
    assert transport.sends == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["request", "next_stage", "source", "reservation"])
async def test_recovery_authorization_cannot_buy_other_work(maker, change):
    # Mutation: letting a recovery authorization buy an altered request or extra stage.
    await interrupted(maker)
    await approve(maker)
    job = await running(maker, "job")
    async with maker.begin() as db:
        lost = await db.get(ProviderAttempt, "source-2")
        request = json.loads(lost.request_json)
        if change == "request":
            request["max_tokens"] -= 1
        elif change == "source":
            lost.request_digest = "changed"
        elif change == "reservation":
            allocation = await db.scalar(select(RecapBudgetAllocation).where(
                RecapBudgetAllocation.operation_id == job.id, RecapBudgetAllocation.key == "3"))
            allocation.max_microusd += 1
    transport = FakeTransport()
    with pytest.raises(Held, match="lost_review"):
        await Gateway(maker, transport, epoch="test-epoch").invoke(
            job.id, job.generation, 4 if change == "next_stage" else 3, request)
    assert transport.sends == 0
