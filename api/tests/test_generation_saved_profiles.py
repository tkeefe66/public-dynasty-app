"""Receipt-only recovery must never enter the paid writer path."""

import json

import pytest
from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationOperation,
    ProviderAttempt,
)
from app.services.generation.store import Conflict, Held, digest, dump
from sqlalchemy import func, select

from tests.test_generation_gateway import BODY
from tests.test_generation_worker import prepare


async def saved_profile(maker, *, words=18, stop_reason="end_turn"):
    await prepare(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.state, job.reason, job.calls = "needs_attention", "execution_failed", 2
        payload = json.loads(job.payload_json)
        payload["facts"]["pillars"] = [{"label": "Results"}]
        job.payload_json, job.request_digest = dump(payload), digest(payload)
        for stage in (1, 2):
            text = json.dumps(
                {
                    "blurb": f"Saved profile revision {stage}.",
                    "highlights": {"Results": " ".join(["word"] * words)},
                }
            )
            body = {
                **BODY,
                "stop_reason": stop_reason,
                "content": [{"type": "text", "text": text}],
            }
            db.add(
                ProviderAttempt(
                    id=f"attempt-{stage}",
                    operation_id="job",
                    stage=stage,
                    generation=1,
                    model=BODY["model"],
                    request_digest="saved",
                    request_json="{}",
                    state="received",
                    usage_state="known",
                    cost_microusd=35,
                    receipt_json=dump(
                        {"status": 200, "body": json.dumps(body), "headers": {}}
                    ),
                )
            )


@pytest.mark.asyncio
async def test_saved_profile_recovery_uses_latest_receipt_preserves_cost_and_publishes_once(
    maker, monkeypatch
):
    # Mutation: replay the writer, discard an original receipt, or publish the first response.
    from app.services.generation.gateway import Gateway
    from app.services.generation.saved_profiles import recover_saved_profile

    async def no_provider(*args, **kwargs):
        pytest.fail("Recovery must not invoke the provider gateway")

    monkeypatch.setattr(Gateway, "invoke", no_provider)
    await saved_profile(maker)
    async with maker.begin() as db:
        artifact = await recover_saved_profile(
            db,
            "job",
            expected_generation=1,
            actor="owner",
            reason="Recover reviewed saved profile",
        )
        assert json.loads(artifact.payload_json)["blurb"] == "Saved profile revision 2."
        assert (
            len(json.loads(artifact.payload_json)["pillars"]["results"].split()) == 18
        )
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.state == "succeeded"
        assert job.reason == ""
        assert (job.calls, job.max_calls) == (2, 2)
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 2
        assert await db.scalar(select(func.sum(ProviderAttempt.cost_microusd))) == 70
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1
    async with maker.begin() as db:
        with pytest.raises(Conflict):
            await recover_saved_profile(
                db,
                "job",
                expected_generation=1,
                actor="owner",
                reason="Stale duplicate recovery",
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "cancelled",
        "restored",
        "stale",
        "missing_receipt",
        "unknown_cost",
        "unknown_outcome",
        "overlong",
        "incomplete",
        "changed_head",
        "revoked",
    ],
)
async def test_saved_profile_recovery_fails_closed(maker, fault):
    # Mutation: skip the corresponding receipt, state, validation, or publication fence.
    from app.services.generation.saved_profiles import recover_saved_profile

    await saved_profile(
        maker,
        words=25 if fault == "overlong" else 18,
        stop_reason="max_tokens" if fault == "incomplete" else "end_turn",
    )
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        attempt = await db.get(ProviderAttempt, "attempt-1")
        if fault == "cancelled":
            job.state = "cancelled"
        elif fault == "restored":
            job.reason = "restore_reapproval_required"
        elif fault == "missing_receipt":
            attempt.receipt_json = None
        elif fault == "unknown_cost":
            attempt.cost_microusd = None
        elif fault == "unknown_outcome":
            attempt.state = "unknown"
        elif fault == "changed_head":
            db.add(ArtifactHead(subject=job.subject, artifact_id="newer", revision=1))
        elif fault == "revoked":
            job.actor_id = "removed-owner"
    with pytest.raises((Held, Conflict)):
        async with maker.begin() as db:
            await recover_saved_profile(
                db,
                "job",
                expected_generation=0 if fault == "stale" else 1,
                actor="owner",
                reason="Review saved profile",
            )
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 0
        assert (await db.get(GenerationOperation, "job")).state != "running"


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
async def test_recovery_command_requires_apply_to_persist(maker, monkeypatch, apply):
    # Mutation: dry-run commits recovery, or apply reports success without saving.
    from argparse import Namespace

    from app.db import engine

    from scripts.recover_gm_profiles import run

    await saved_profile(maker)
    monkeypatch.setattr(engine, "get_sessionmaker", lambda: maker)
    report = await run(
        Namespace(job=["job:1"], actor="owner", reason="Reviewed recovery", apply=apply)
    )
    assert report[0]["applied"] is apply
    async with maker() as db:
        assert await db.scalar(
            select(func.count()).select_from(ContentArtifact)
        ) == int(apply)
        assert (await db.get(GenerationOperation, "job")).state == (
            "succeeded" if apply else "needs_attention"
        )
