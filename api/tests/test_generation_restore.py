from types import SimpleNamespace

import pytest
from app.db.base import Base
from app.services.backup_service import dump_database
from app.services.generation.models import GenerationControl, GenerationOperation
from app.services.generation.worker import Worker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.test_generation_gateway import FakeTransport, seed_job


@pytest.mark.asyncio
async def test_restoring_pre_call_snapshot_cannot_repeat_paid_work(maker, tmp_path):
    from app.services.generation.recovery import restore_database
    await seed_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.state = "queued"
    async with maker() as db:
        blob, counts = await dump_database(db)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'restore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    restored = async_sessionmaker(engine, expire_on_commit=False)
    async with restored.begin() as db:
        assert await restore_database(db, blob) == counts
    transport = FakeTransport()
    await Worker(restored, tmp_path, transport=transport, epoch="test-epoch").tick()
    assert transport.sends == 0
    async with restored() as db:
        control = await db.get(GenerationControl, "global")
        assert control.hold == "restore_quarantine"
        assert control.epoch == "test-epoch"  # old epoch retained as rotation evidence
        assert (await db.get(GenerationOperation, "job")).state == "held"
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_import_is_idempotent_and_keeps_unknown_identity_visible(maker, tmp_path):
    from app.services.generation.migration import reconcile_legacy
    from app.services.generation.store import dump
    await seed_job(maker)
    (tmp_path / "chain_synthetic.json").write_text(dump({"league_id": "synthetic",
        "trade_stories": {"tx": {"body": "Saved prose"}}, "league_season_by_id": {"synthetic": 2026}}))
    (tmp_path / "chain_unknown.json").write_text(dump({"league_id": "unknown"}))
    async with maker.begin() as db:
        (await db.get(GenerationControl, "global")).hold = "owner_paused"
        first = await reconcile_legacy(db, tmp_path)
        second = await reconcile_legacy(db, tmp_path)
        assert first == second
        assert first["artifact_count"] == 1
        assert first["blocked"][0]["league_id"] == "unknown"
        assert not first["conflicts"]


@pytest.mark.asyncio
async def test_quarantine_cannot_be_cleared_by_pause_then_old_epoch_activation(maker, monkeypatch):
    from app.services.generation.administration import control_action
    from app.services.generation.recovery import quarantine
    from app.services.generation.store import Held
    await seed_job(maker)
    monkeypatch.setenv("TRADE_GRADER_GENERATION_EXECUTION_EPOCH", "test-epoch")
    async with maker.begin() as db:
        await quarantine(db)
        control = await db.get(GenerationControl, "global")
        await control_action(db, SimpleNamespace(action="pause", expected_revision=control.revision, reason="Pause"), "owner")
        with pytest.raises(Held, match="fresh_execution_epoch_required"):
            await control_action(db, SimpleNamespace(action="activate", expected_revision=control.revision,
                reason="Activate", workers_stopped=True), "owner")


@pytest.mark.asyncio
async def test_generation_rows_roundtrip_without_receipt_or_artifact_changes(maker, tmp_path):
    from app.services.generation.recap_budget import RecapCaps
    from app.services.generation.recap_models import RecapBudgetPolicy, RecapBudgetPlan, RecapBudgetAllocation
    from app.services.backup_service import load_database
    from app.services.generation.models import (
        ArtifactHead,
        ContentArtifact,
        GenerationAudit,
        GenerationCandidate,
        GenerationOutbox,
        GenerationSubmission,
        ProviderAttempt,
    )
    from app.services.generation.store import dump
    await seed_job(maker)
    async with maker.begin() as db:
        db.add(GenerationCandidate(key="candidate", series_id="series", league_id="synthetic",
            feature="analyst", subject="edition", event="week:2", payload_json="{}", digest="facts-hash"))
        db.add(ProviderAttempt(id="attempt", operation_id="job", stage=1, generation=1,
            request_digest="digest", request_json="{}", model="synthetic", receipt_json=dump({"body":"raw receipt"}),
            cost_microusd=123, state="received", usage_state="known"))
        db.add(ContentArtifact(id="artifact", series_id="series", league_id="synthetic",
            feature="analyst", subject="edition", digest="content-hash", payload_json=dump({"markdown":"Saved correction"}),
            revision=3, provenance="legacy_unreviewed"))
        db.add(ArtifactHead(subject="edition", artifact_id="artifact", revision=3))
        db.add(GenerationOutbox(key="outbox", kind="artifact", payload_json="{}"))
        db.add(GenerationSubmission(key="submission", request_digest="request", operation_id="job"))
        db.add(GenerationAudit(actor_id="owner", action="audit", target="job", reason="test"))
        db.add(RecapBudgetPolicy(series_id="series", revision=2,
            caps_json=dump(RecapCaps().model_dump()), updated_at=123))
        db.add(RecapBudgetPlan(id="plan", series_id="series", episode_id="episode", plan_key="first", digest="bound"))
        db.add(RecapBudgetAllocation(plan_id="plan", key="1", category="written", operation_id="job",
            attempt_id="attempt", month_key="2026-10", max_microusd=500, outstanding_microusd=0,
            actual_microusd=123, rate_json="{}", state="settled", evidence_json='{"receipt":"saved"}'))
    async with maker() as db:
        blob, counts = await dump_database(db)
    assert all(counts[t.name] for t in Base.metadata.sorted_tables if t.name not in
        ("app_settings", "page_events", "side_bets", "yahoo_connections", "yahoo_oauth_states", "yahoo_league_grants"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'roundtrip.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    restored = async_sessionmaker(engine, expire_on_commit=False)
    async with restored.begin() as db:
        assert await load_database(db, blob) == counts
    for table in Base.metadata.sorted_tables:
        async with maker() as a, restored() as b:
            assert list((await a.execute(select(table))).mappings()) == list((await b.execute(select(table))).mappings())
    await engine.dispose()
