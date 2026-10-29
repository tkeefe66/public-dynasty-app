"""Synthetic Yahoo receipts reach the real archive only through current authority."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.db.models import LeagueMembership, User, YahooConnection, YahooLeagueGrant
from app.routes.analyst import analyst_archive
from app.services.analyst_store import AnalystStore
from app.services.generation.artifacts import save_artifact
from app.services.generation.commands import authorize_candidate, claim_operation
from app.services.generation.features import generate
from app.services.generation.gateway import Gateway
from app.services.generation.models import (
    ContentArtifact,
    GenerationCandidate,
    GenerationControl,
    GenerationOperation,
    GenerationOutbox,
    GenerationPolicy,
    LeagueSeason,
    LeagueSeries,
    ProviderAttempt,
    stamp,
)
from app.services.generation.planner import collect_analyst
from app.services.generation.publication import drain
from app.services.generation.recap_models import RecapPublicationControl
from app.services.generation.store import Held, digest, dump
from app.services.generation.worker import admit_automatic
from sqlalchemy import delete, func, select

from tests.test_generation_gateway import FakeTransport

YAHOO_ID = "999.l.100000001"
SERIES_ID = "synthetic-yahoo-series"


async def staged_results(maker, tmp_path, monkeypatch, *, mode="automatic"):
    """Use captured synthetic writer requests; no external account or network."""
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "owner@test.local")
    monkeypatch.setenv("TRADE_GRADER_GENERATION_EXECUTION_EPOCH", "test-epoch")
    monkeypatch.setenv("TRADE_GRADER_RECAP_PUBLICATION_MODE", "database")
    monkeypatch.setenv("TRADE_GRADER_RECAP_SERVING_EPOCH", "test-serving-epoch")
    monkeypatch.setattr("app.routes.analyst.get_cache_dir", lambda: tmp_path)
    fixture = json.loads((Path(__file__).parent /
        "fixtures/synthetic_analyst_passage_receipts.json").read_text())
    edition = {
        **fixture["payload"]["edition"],
        "league_name": "Synthetic League",
        "generated_at": datetime.now(UTC).isoformat(),
        "model": "verified-results-v1",
        "edition_type": "results",
        "markdown": "Private original results: Team A scored 158 points.",
    }
    store = AnalystStore(tmp_path)
    store.save(YAHOO_ID, edition)
    store.save_correction(YAHOO_ID, {
        **edition, "markdown": "Private revised results: Team A scored 158 points."
    }, "Source formatting corrected")
    before = {path: path.read_bytes() for path in store.league_dir(YAHOO_ID).rglob("*.json")}
    async with maker.begin() as db:
        db.add(User(id="owner", google_sub="synthetic-owner", email="owner@test.local", is_admin=True))
        db.add(LeagueMembership(user_id="owner", league_id=YAHOO_ID))
        db.add(YahooConnection(user_id="owner", generation="current", sealed_tokens="synthetic",
            expires_at=stamp() + 3600, status="connected"))
        db.add(YahooLeagueGrant(user_id="owner", league_id=YAHOO_ID, generation="current",
            expires_at=stamp() + 3600))
        db.add(GenerationControl(id="global", epoch="test-epoch", hold=""))
        # Archived receipt replay exercises the explicit legacy text workflow.
        db.add(GenerationPolicy(scope="app", value_json=dump({"paused": False, "recap_text_reconciliation": False,
            "features": {"analyst": {"mode": "automatic"}}})))
        db.add(GenerationPolicy(scope="series:" + SERIES_ID, value_json=dump({
            "features": {"analyst": {"mode": mode}}})))
        db.add(LeagueSeries(id=SERIES_ID, lifecycle="active", profile="redraft", hold="",
            activated_at=1, activation_week=0))
        db.add(LeagueSeason(league_id=YAHOO_ID, provider="yahoo", provider_key=YAHOO_ID,
            series_id=SERIES_ID, season=2026, latest_week=5, verified_at=1,
            capabilities_json=dump({"format": "redraft", "future_picks": False,
                "roster_continuity": False, "multiyear_history": True})))
        db.add(RecapPublicationControl(id="global", epoch="test-serving-epoch",
            reconciliation_digest="synthetic-reconciliation", quarantined=False))
    async with maker.begin() as db:
        await collect_analyst(db, YAHOO_ID, SERIES_ID, tmp_path)
        candidate = await db.scalar(select(GenerationCandidate))
        assert candidate and candidate.hold == ""
        assert json.loads(candidate.payload_json)["facts"] == edition["facts"]
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
        assert await analyst_archive(YAHOO_ID, db) == {"editions": []}
    return fixture, candidate.key, before


async def admitted_job(maker):
    await admit_automatic(maker)
    async with maker.begin() as db:
        job = await claim_operation(db, "synthetic-worker", capabilities={"generation"})
        assert job and job.league_id == YAHOO_ID and job.actor_kind == "scheduler"
        assert job.connection_generation == "current"
    return job


async def replay_reviewed_receipts(maker, job, fixture):
    async with maker.begin() as db:
        saved = await db.get(GenerationOperation, job.id)
        saved.calls = len(fixture["requests"])
        for stage, (request, response) in enumerate(zip(fixture["requests"], fixture["responses"]), 1):
            db.add(ProviderAttempt(operation_id=job.id, stage=stage, generation=job.generation,
                request_json=dump(request), request_digest=digest(request), model=request["model"],
                state="received", usage_state="known", cost_microusd=1,
                receipt_json=dump({"status": 200, "body": json.dumps(response), "headers": {}})))
    transport = FakeTransport(lost=True)
    validated = await generate(job, Gateway(maker, transport, epoch="test-epoch"))
    assert validated.payload["markdown"] == "Team A scored **158 points**. Closing joke."
    assert validated.stages == 4 and transport.sends == 0
    return validated, transport


@pytest.mark.asyncio
async def test_yahoo_reviewed_receipts_publish_through_outbox_to_database_archive(maker, tmp_path, monkeypatch):
    # Mutation: skip Yahoo collection/projection, expose raw results, or overwrite predecessor revisions.
    fixture, _, before = await staged_results(maker, tmp_path, monkeypatch)
    job = await admitted_job(maker)
    validated, transport = await replay_reviewed_receipts(maker, job, fixture)
    async with maker.begin() as db:
        artifact = await save_artifact(db, job.id, job.generation, validated)
        assert artifact.provenance == "managed" and artifact.revision == 3
        assert (await db.get(GenerationOperation, job.id)).state == "succeeded"
        assert await analyst_archive(YAHOO_ID, db) == {"editions": []}
    await drain(maker, tmp_path)
    await drain(maker, tmp_path)
    async with maker() as db:
        archive = await analyst_archive(YAHOO_ID, db)
        assert len(archive["editions"]) == 1
        published = archive["editions"][0]
        assert published["markdown"] == "Team A scored **158 points**. Closing joke."
        assert published["edition_type"] == "roast" and published["revision"] == 3
        assert published["original_markdown"] is None
        assert published["facts"] == fixture["payload"]["edition"]["facts"]
        outbox = (await db.scalars(select(GenerationOutbox))).all()
        assert len(outbox) == 1 and outbox[0].delivered and not outbox[0].error
        artifacts = (await db.scalars(select(ContentArtifact).order_by(ContentArtifact.revision))).all()
        assert [row.revision for row in artifacts] == [1, 2, 3]
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 4
        assert (await db.get(GenerationOperation, job.id)).calls == 4
    assert {path: path.read_bytes() for path in before} == before
    assert transport.sends == 0


@pytest.mark.asyncio
async def test_yahoo_series_manual_mode_stages_facts_but_blocks_admission_and_dispatch(maker, tmp_path, monkeypatch):
    # Mutation: ignore the series manual override at automatic admission or at the final provider boundary.
    fixture, candidate_key, before = await staged_results(maker, tmp_path, monkeypatch, mode="manual")
    await admit_automatic(maker)
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 0
    async with maker.begin() as db:
        with pytest.raises(Held, match="manual_only"):
            await authorize_candidate(db, candidate_key, actor_id="owner", actor_kind="scheduler",
                reason="Synthetic automatic admission", authorization_key="manual-must-block")
        policy = await db.get(GenerationPolicy, "series:" + SERIES_ID)
        policy.value_json = dump({"features": {"analyst": {"mode": "automatic"}}})
        (await db.get(GenerationCandidate, candidate_key)).eligible_at = stamp()
    job = await admitted_job(maker)
    async with maker.begin() as db:
        policy = await db.get(GenerationPolicy, "series:" + SERIES_ID)
        policy.value_json = dump({"features": {"analyst": {"mode": "manual"}}})
    transport = FakeTransport(lost=True)
    with pytest.raises(Held, match="manual_only"):
        await Gateway(maker, transport, epoch="test-epoch").invoke(job.id, job.generation, 1, fixture["requests"][0])
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
        assert await db.scalar(select(func.count()).select_from(GenerationOutbox)) == 0
        assert await analyst_archive(YAHOO_ID, db) == {"editions": []}
    assert {path: path.read_bytes() for path in before} == before
    assert transport.sends == 0


@pytest.mark.asyncio
async def test_yahoo_revoked_grant_cannot_publish_already_reviewed_receipts(maker, tmp_path, monkeypatch):
    # Mutation: omit current Yahoo grant revalidation when committing a paid, reviewed artifact.
    fixture, _, before = await staged_results(maker, tmp_path, monkeypatch)
    job = await admitted_job(maker)
    validated, transport = await replay_reviewed_receipts(maker, job, fixture)
    async with maker.begin() as db:
        await db.execute(delete(YahooLeagueGrant).where(YahooLeagueGrant.user_id == "owner",
            YahooLeagueGrant.league_id == YAHOO_ID))
    async with maker.begin() as db:
        with pytest.raises(Held, match="provider_grant_changed"):
            await save_artifact(db, job.id, job.generation, validated)
    await drain(maker, tmp_path)
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 2
        assert await db.scalar(select(func.count()).select_from(GenerationOutbox)) == 0
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 4
        assert await analyst_archive(YAHOO_ID, db) == {"editions": []}
    assert {path: path.read_bytes() for path in before} == before
    assert transport.sends == 0
