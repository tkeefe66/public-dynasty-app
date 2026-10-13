"""Replay synthetic requests captured from the pre-passage writer, offline."""

import json
from pathlib import Path

import pytest
from app.services.generation.features import generate
from app.services.generation.gateway import Gateway
from app.services.generation.models import GenerationOperation, ProviderAttempt
from app.services.generation.store import Held, digest, dump
from sqlalchemy import select

from tests.test_generation_gateway import FakeTransport, seed_job


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_facts", [False, True])
async def test_legacy_recap_receipts_replay_without_spending_or_weakening_digest(
    maker, changed_facts
):
    # Mutation: rebuild old repair requests with the new contract, or bypass request-digest checks to recover them.
    fixture = json.loads(
        (
            Path(__file__).parent / "fixtures/synthetic_analyst_legacy_receipts.json"
        ).read_text()
    )
    await seed_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.feature, job.calls, job.max_calls = "analyst", 4, 4
        if changed_facts:
            fixture["payload"]["edition"]["facts"]["high_scorer"]["points"] = 170
        job.payload_json = dump(fixture["payload"])
        job.request_digest = digest(fixture["payload"])
        for stage, (request, body) in enumerate(
            zip(fixture["requests"], fixture["responses"]), 1
        ):
            db.add(
                ProviderAttempt(
                    operation_id=job.id,
                    stage=stage,
                    generation=1,
                    request_json=dump(request),
                    request_digest=digest(request),
                    model=request["model"],
                    state="received",
                    usage_state="known",
                    cost_microusd=1,
                    receipt_json=dump(
                        {"status": 200, "body": json.dumps(body), "headers": {}}
                    ),
                )
            )
    transport = FakeTransport(lost=True)
    gateway = Gateway(maker, transport, epoch="test-epoch")
    if changed_facts:
        with pytest.raises(Held, match="checkpoint_request_changed"):
            await generate(job, gateway)
    else:
        result = await generate(job, gateway)
        assert (
            result.payload["markdown"] == "Team A scored **158 points**. Closing joke."
        )
        assert result.stages == 4
    assert transport.sends == 0
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).calls == 4
        assert len((await db.scalars(select(ProviderAttempt))).all()) == 4
