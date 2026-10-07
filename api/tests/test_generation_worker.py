import json

import pytest
from app.services.generation.models import (
    ContentArtifact,
    GenerationOperation,
    ProviderAttempt,
)
from app.services.generation.store import digest, dump
from app.services.generation.worker import Worker
from sqlalchemy import func, select

from tests.test_generation_gateway import BODY, FakeTransport, seed_job


async def prepare(maker):
    await seed_job(maker)
    async with maker.begin() as db:
        row = await db.get(GenerationOperation, "job")
        row.state, row.feature = "queued", "gm_rating_blurb"
        row.payload_json = dump({"facts": {"user_id": "u", "owner_name": "Owner", "team_name": None,
            "scope_label": "career", "rank": 1, "rating": 80, "pillars": {}},
            "target": {"slot": "owner_rating_blurbs", "scope": "all", "key": "u"}})
        row.request_digest = digest(json.loads(row.payload_json))


def test_gm_feedback_identifies_the_overlong_highlight():
    from app.services.generation.features import validate

    from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts
    facts = OwnerRatingFacts(user_id="u", owner_name="Owner", team_name=None,
        scope_label="career", rank=1, rating=80, pillars={"results": {}})
    raw = {"content": [{"type": "text", "text": json.dumps({"blurb": "Profile",
        "highlights": {"Results": " ".join(["word"] * 17)}})}]}
    errors = validate("gm_rating_blurb", {"blurb": "Profile"}, facts, raw)
    assert len(errors) == 1
    assert "Results highlight has 17 words" in errors[0]


@pytest.mark.asyncio
async def test_changed_content_cannot_reuse_validation(maker):
    from app.services.generation.artifacts import save_artifact
    from app.services.generation.features import ValidatedOutput
    from app.services.generation.store import Held
    await prepare(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.state = "running"
        content = {"blurb": "Approved"}
        proof = ValidatedOutput(content, digest(content), job.request_digest, 1)
        content["blurb"] = "Unreviewed change"
        with pytest.raises(Held, match="validation_changed"):
            await save_artifact(db, job.id, job.generation, proof)


@pytest.mark.asyncio
async def test_worker_records_one_receipt_and_artifact_and_never_rebuys(maker, tmp_path):
    await prepare(maker)
    body = {**BODY, "content": [{"type": "text", "text": json.dumps({"blurb": "Strong record.", "highlights": {}})}]}
    transport = FakeTransport(body=json.dumps(body))
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    assert await worker.tick()
    assert not await worker.tick()
    assert transport.sends == 1
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.state == "succeeded"
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("format", ["dynasty", "keeper", "redraft"])
@pytest.mark.parametrize("shape", ["builder_list", "mapping"])
async def test_worker_accepts_real_gm_pillars_without_buying_a_repair(maker, tmp_path, format, shape):
    """Mutation: checking labels against the builder's list rejects valid highlights.

    Nonempty pillar values mirror the production canary packet, with synthetic identity.
    Build and JSON-round-trip it so the fixture exercises the actual persisted shape.
    """
    from sleeper_dynasty.engine.gm_rating_blurb import build_owner_rating_facts

    await prepare(maker)
    pillars = {"results": {"weight": 0.6, "contribution": -145,
        "signals": {"playoff_success": {"contribution": -58}, "luck": {"contribution": -44}}}}
    if format != "redraft":
        pillars["assets"] = {"weight": 0.4, "contribution": -53,
            "signals": {"young_core_share": {"contribution": -43}, "roster_value_share": {"contribution": -10}}}
    facts = build_owner_rating_facts(scope_label="career", owner_name="Owner", team_name="Synthetic Team",
        rank=11, rating=1302, pillars=pillars, outcome_signals={"made_playoffs": 0.25})
    facts.user_id = "u"
    packet = json.loads(json.dumps(facts.to_dict()))
    if shape == "mapping":
        packet["pillars"] = {item["label"].lower(): item for item in packet["pillars"]}
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        saved = json.loads(job.payload_json)
        saved["facts"] = packet
        job.payload_json = dump(saved)
        job.request_digest = digest(saved)
    highlights = {"Results": "Playoff success and close games weigh on the record."}
    if format != "redraft":
        highlights["Assets"] = "Young core and roster value need improvement."
    body = {**BODY, "content": [{"type": "text", "text": json.dumps({
        "blurb": "Ranked eleventh, with a 1302 rating and no championships.", "highlights": highlights})}]}
    transport = FakeTransport(body=json.dumps(body))
    worker = Worker(maker, tmp_path, transport=transport, epoch="test-epoch")
    assert await worker.tick()
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.state == "succeeded", job.reason
        artifact = await db.get(ContentArtifact, job.artifact_id)
        assert json.loads(artifact.payload_json)["pillars"] == {k.lower(): v for k, v in highlights.items()}
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 1
    assert not await worker.tick()
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_worker_restart_cannot_retry_unknown_call(maker, tmp_path):
    await prepare(maker)
    transport = FakeTransport(lost=True)
    for _ in range(3):
        await Worker(maker, tmp_path, transport=transport, epoch="test-epoch").tick()
    assert transport.sends == 1
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).state == "needs_attention"
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 0


@pytest.mark.asyncio
async def test_admin_removed_from_live_allowlist_cannot_send(maker, tmp_path, monkeypatch):
    await prepare(maker)
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "")
    transport = FakeTransport()
    await Worker(maker, tmp_path, transport=transport, epoch="test-epoch").tick()
    assert transport.sends == 0
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).reason == "admin_permission_removed"


@pytest.mark.asyncio
async def test_invalid_structured_blurb_uses_only_one_repair_and_never_publishes(maker, tmp_path):
    await prepare(maker)
    body = {**BODY, "content": [{"type": "text", "text": json.dumps({"blurb": "Strong record.",
        "highlights": {"invented_pillar": "Unsupported claim"}})}]}
    transport = FakeTransport(body=json.dumps(body))
    await Worker(maker, tmp_path, transport=transport, epoch="test-epoch").tick()
    assert transport.sends == 2
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).state == "needs_attention"
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 0
        attempts = (await db.scalars(select(ProviderAttempt).order_by(ProviderAttempt.stage))).all()
        assert len(attempts) == 2
        assert "Correct only these validation failures" in attempts[1].request_json
        assert all(a.cost_microusd is not None for a in attempts)
