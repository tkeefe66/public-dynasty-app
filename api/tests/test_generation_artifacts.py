import json
from types import SimpleNamespace

import pytest
from app.services.generation.artifacts import import_artifact, overlay
from app.services.generation.models import (
    ContentArtifact,
    GenerationCandidate,
    GenerationOperation,
    LeagueSeries,
)
from app.services.generation.planner import observe
from sqlalchemy import func, select

from tests.test_generation_gateway import seed_job


@pytest.mark.asyncio
async def test_legacy_prose_survives_cache_schema_and_fact_changes(maker):
    await seed_job(maker)
    async with maker.begin() as db:
        for _ in range(2):
            await import_artifact(db, series_id="series", league_id="synthetic", feature="trade_story",
                subject="trade-stable", payload={"body": "saved"}, target={"slot": "trade_stories", "key": "tx"})
        await observe(db, series_id="series", league_id="synthetic", feature="trade_story",
            subject="trade-stable", event="created", payload={"facts": {"changed": True}, "event_at": 100})
        entry = SimpleNamespace(league_id="synthetic", trade_stories={}, owner_rating_blurbs={}, franchise_blurbs={})
        await overlay(db, entry, "series")
        assert entry.trade_stories == {"tx": {"body": "saved"}}
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 1  # seeded only


@pytest.mark.asyncio
async def test_existing_artifact_conflict_is_visible_and_never_overwritten(maker):
    await seed_job(maker)
    async with maker.begin() as db:
        first = await import_artifact(db, series_id="series", league_id="synthetic", feature="trade_story",
            subject="same", payload={"body": "first"}, target={})
        second = await import_artifact(db, series_id="series", league_id="synthetic", feature="trade_story",
            subject="same", payload={"body": "different"}, target={})
        assert first.id == second.id
        assert json.loads(first.payload_json)["body"] == "first"
        from app.services.generation.models import ArtifactHead
        assert (await db.get(ArtifactHead, "same")).hold == "legacy_artifact_conflict"


@pytest.mark.asyncio
async def test_activation_watermark_and_summary_coalescing(maker):
    await seed_job(maker)
    async with maker.begin() as db:
        series = await db.get(LeagueSeries, "series")
        series.activated_at = 100
        series.activation_week = 4
        old = await observe(db, series_id="series", league_id="synthetic", feature="analyst",
            subject="edition-old", event="week:3", payload={"week": 3, "event_at": 200})
        assert old.hold == "historical_approval_required"
        for week in (5, 6):
            newest = await observe(db, series_id="series", league_id="synthetic", feature="gm_rating_blurb",
                subject="owner-summary", event=f"week:{week}", payload={"week": week, "event_at": 200})
        assert newest.event == "week:6"
        assert newest.hold == ""
        assert await db.scalar(select(func.count()).select_from(GenerationCandidate).where(
            GenerationCandidate.subject == "owner-summary")) == 1


@pytest.mark.asyncio
async def test_failed_subject_remains_held_after_new_facts(maker):
    await seed_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.state = "needs_attention"
        row = await observe(db, series_id="series", league_id="synthetic", feature="trade_story",
            subject="story", event="created", payload={"event_at": 200, "facts": {"version": 2}})
        assert row.hold == "subject_needs_attention"
