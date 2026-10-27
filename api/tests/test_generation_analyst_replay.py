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
@pytest.mark.parametrize('correction_reason', ['', 'Correct reception scoring'])
@pytest.mark.parametrize("contract", ["legacy", "passage", "grounded_v1"])
async def test_legacy_recap_receipts_replay_without_spending_or_weakening_digest(
    maker, changed_facts, correction_reason, contract
):
    # Mutation: rebuild old repair requests with the new contract, or bypass request-digest checks to recover them.
    fixture = json.loads(
        (
            Path(__file__).parent / f"fixtures/synthetic_analyst_{contract}_receipts.json"
        ).read_text()
    )
    await seed_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.feature, job.calls, job.max_calls = "analyst", 4, 4
        job.reason = 'Automatic weekly recap'
        fixture['payload']['correction_reason'] = correction_reason
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
    elif fixture.get("expected_error"):
        with pytest.raises(ValueError, match=fixture["expected_error"]):
            await generate(job, gateway)
    else:
        result = await generate(job, gateway)
        assert (
            result.payload["markdown"] == "Team A scored **158 points**. Closing joke."
        )
        assert result.stages == 4
        # Mutation: leak an operational queue reason into the reader's correction notice.
        assert result.payload['correction_note'] == correction_reason
    assert transport.sends == 0
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).calls == 4
        assert len((await db.scalars(select(ProviderAttempt))).all()) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("contract", ["legacy", "passage", "grounded_v1", "grounded_v2", "new"])
async def test_first_saved_request_pins_prompt_version_before_the_next_stage(maker, contract):
    # Mutation: upgrade an interrupted v1 job to v2, disable resumed v2, or default new jobs to v1.
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket
    from sleeper_dynasty.llm.recap_writer import RecapWriter

    fixture_contract = contract if contract in ("legacy", "passage") else "grounded_v1"
    fixture = json.loads((Path(__file__).parent / f"fixtures/synthetic_analyst_{fixture_contract}_receipts.json").read_text())
    if contract == "grounded_v2":
        system, messages = RecapWriter(grounding_version="recap-owner-evidence-v2").build_request(ArchivedPacket(fixture["payload"]["edition"]["facts"]), lore=None)
        fixture["requests"][0] = {**fixture["requests"][0], "system": system, "messages": messages}
    saved_count = 0 if contract == "new" else 1
    await seed_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.feature, job.calls, job.max_calls = "analyst", saved_count, 4
        job.payload_json = dump(fixture["payload"])
        job.request_digest = digest(fixture["payload"])
        if saved_count:
            request = fixture["requests"][0]
            db.add(ProviderAttempt(operation_id=job.id, stage=1, generation=1,
                request_json=dump(request), request_digest=digest(request), model=request["model"],
                state="received", usage_state="known", cost_microusd=1,
                receipt_json=dump({"status": 200, "body": json.dumps(fixture["responses"][0]), "headers": {}})))
    outgoing = []

    class StopAtNextRequest(Gateway):
        async def invoke(self, operation_id, generation, stage, request):
            if stage > saved_count:
                outgoing.append(request)
                raise RuntimeError("Offline next-stage capture; no provider request")
            return await super().invoke(operation_id, generation, stage, request)

    transport = FakeTransport(lost=True)
    with pytest.raises(RuntimeError, match="Offline next-stage capture"):
        await generate(job, StopAtNextRequest(maker, transport, epoch="test-epoch"))
    assert len(outgoing) == 1
    if contract in ("legacy", "passage", "grounded_v1"):
        assert outgoing[0] == fixture["requests"][1]
    else:
        version = "recap-owner-evidence-v2" if contract == "grounded_v2" else "recap-owner-evidence-v3"
        assert outgoing[0]["system"][1]["text"].startswith(version + "\n")
        if contract == "grounded_v2":
            assert json.loads(outgoing[0]["messages"][0]["content"])["claim_evidence"]["player_usage"][0]["unit"] == "offensive_snaps"
    assert transport.sends == 0
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).calls == saved_count
        assert len((await db.scalars(select(ProviderAttempt))).all()) == saved_count
