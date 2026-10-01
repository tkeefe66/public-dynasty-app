import asyncio
import json
from types import SimpleNamespace

import pytest
from app.services.generation.administration import job_action
from app.services.generation.models import (
    ContentArtifact,
    GenerationAudit,
    GenerationOperation,
    ProviderAttempt,
)
from app.services.generation.store import Held
from app.services.generation.transport import Receipt
from app.services.generation.worker import Worker
from sqlalchemy import func, select

from tests.test_generation_gateway import BODY, FakeTransport
from tests.test_generation_worker import prepare

VALID_BODY = json.dumps({**BODY, "content": [{"type": "text", "text": json.dumps({"blurb": "Valid profile", "highlights": {}})}]})


async def resume(maker):
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        return await job_action(db, job.id, SimpleNamespace(expected_generation=job.generation,
            expected_state=job.state, action="resume", reason="Recover saved provider work"), "owner")


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_saved_paid_result_recovers_after_local_failure_without_repurchase(maker, tmp_path, monkeypatch, interrupted):
    from app.services.generation import artifacts
    await prepare(maker)
    transport = FakeTransport(body=VALID_BODY)
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    original = artifacts.save_artifact
    async def fail_once(*args):
        if interrupted:
            raise asyncio.CancelledError()
        raise RuntimeError("temporary artifact storage failure")
    monkeypatch.setattr(artifacts, "save_artifact", fail_once)
    if interrupted:
        with pytest.raises(asyncio.CancelledError):
            await worker.tick()
    else:
        await worker.tick()
    monkeypatch.setattr(artifacts, "save_artifact", original)
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        original_authorization = (job.calls, job.max_calls, job.payload_json, job.policy_json)
        assert job.state == "held"
        assert job.reason == ("worker_shutdown" if interrupted else "publication_failed")
    await resume(maker)
    await worker.tick()
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.state == "succeeded"
        assert (job.calls, job.max_calls, job.payload_json, job.policy_json) == original_authorization
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1
        assert await db.scalar(select(GenerationAudit.id).where(GenerationAudit.action == "job_resumed"))
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_settled_late_receipt_resumes_original_authorization_without_repurchase(maker, tmp_path):
    await prepare(maker)
    transport = FakeTransport(lost=True)
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    await worker.tick()
    with pytest.raises(Held, match="provider_outcome_unknown"):
        await resume(maker)
    async with maker() as db:
        attempt = await db.scalar(select(ProviderAttempt))
        ident = attempt.id
    await worker.gateway.record_receipt(ident, Receipt(200, VALID_BODY, {"request-id": "late"}))
    async with maker() as db:
        attempt = await db.get(ProviderAttempt, ident)
        assert attempt.error_code == ""
        assert attempt.cost_microusd == 35
        audit = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == "attempt_settled"))
        assert json.loads(audit.before_json)["error_code"] == "provider_outcome_unknown"
    await resume(maker)
    await worker.tick()
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).state == "succeeded"
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_saved_receipt_recovers_after_local_accounting_failure(maker, tmp_path, monkeypatch):
    from app.services.generation import gateway
    await prepare(maker)
    transport = FakeTransport(body=VALID_BODY)
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    original = gateway.price_usage
    def fail(*args):
        raise RuntimeError("temporary local settlement failure")
    monkeypatch.setattr(gateway, "price_usage", fail)
    await worker.tick()
    monkeypatch.setattr(gateway, "price_usage", original)
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.state == "held"
        assert job.reason == "receipt_persistence_failed"
        assert (await db.scalar(select(ProviderAttempt))).receipt_json
    with pytest.raises(Held, match="provider_outcome_unknown"):
        await resume(maker)
    await worker.gateway.reconcile_receipts()
    await resume(maker)
    await worker.tick()
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).state == "succeeded"
    assert transport.sends == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state,reason", [("cancelled", "owner_cancelled"), ("held", "restore_reapproval_required"),
    ("needs_attention", "execution_failed")])
async def test_recovery_does_not_revive_terminal_or_restored_work(maker, state, reason):
    await prepare(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.state, job.reason = state, reason
    with pytest.raises(Held):
        await resume(maker)
