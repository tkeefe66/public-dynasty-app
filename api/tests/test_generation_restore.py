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
    from app.services.generation.recap_models import RecapEpisode, RecapObservation, RecapScheduleInventory
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
        db.add(RecapEpisode(episode_id="episode", series_id="series", season=2026,
            period_id="2", league_id="synthetic", week=2, nfl_weeks_json="[2]",
            admitted_at=123, latest_observation_id="observation", facts_digest="facts"))
        db.add(RecapObservation(id="observation", episode_id="episode", observed_at=123,
            snapshot_json='{"score":"100.0100"}', snapshot_digest="raw", facts_digest="facts", decision="ready"))
        db.add(RecapScheduleInventory(version="source", season=2026, revision="schedule",
            qualified_at=123, inventory_json='{"source_bytes":"synthetic"}'))
        from app.services.generation.recap_models import ProviderAccountControl, RecapStage, RecapProviderAttempt, RecapAsset
        db.add(ProviderAccountControl(provider="elevenlabs", account_key="synthetic", hold="provider_auth_failed"))
        db.add(RecapStage(id="media-stage", episode_id="episode", revision=3, kind="narrate", script_id="script",
            operation_id="job", input_json="{}", input_digest="inputs", policy_digest="policy"))
        db.add(RecapProviderAttempt(id="media-attempt", stage_id="media-stage", episode_id="episode", series_id="series",
            operation_id="job", provider="elevenlabs", account_key="synthetic", worker_id="worker", generation=1,
            epoch="test-epoch", request_digest="request", request_json="{}", pricing_json="{}", authority_digest="authority",
            receipt_json='{"status":200}', state="received", cost_microusd=17))
        db.add(RecapAsset(stage_id="media-stage", generation=1, digest="media-digest", size=17,
            media_type="audio/wav", storage_key="synthetic-immutable-key"))
        from app.services.generation.recap_models import RecapSpeechReview
        db.add(RecapSpeechReview(id="speech-review", series_id="series", season=2026,
            entity_kind="owner", entity_id="synthetic-owner", canonical_name="Avery",
            canonical_token="avery", reusable=True, aliases_json='["averie"]',
            script_id="script", script_digest="synthetic-script-digest", script_revision=3,
                reviewer_id="owner", reason="Reviewed synthetic spelling", created_at=123))
        from app.services.generation.recap_models import (RecapPublicationControl, RecapPublication,
            RecapPublicationApproval, RecapPublicationSelection, RecapShareDecision)
        db.add(RecapPublicationControl(id='global', epoch='synthetic-serving-epoch',
            reconciliation_digest='synthetic-reconciled-inventory', quarantined=True))
        db.add(RecapPublication(episode_id='episode', series_id='series', league_id='synthetic', season=2026, week=2,
            article_id='artifact', article_revision=3, article_digest='content-hash', article_json='{"markdown":"Saved correction"}',
            facts_digest='facts', media_id='media-stage', media_json='{"id":"retained-bundle"}', script_id='script',
            approval_id='publication-approval', policy_digest='policy', share_revision=2,
            authority_revision=4, projected_revision=3, epoch='synthetic-serving-epoch', withdrawn=True))
        db.add(RecapPublicationApproval(id='publication-approval', episode_id='episode',
            scope_json='{"article_revision":3}', reviewer_id='owner', reason='Reviewed synthetic preview', consumed=True))
        db.add(RecapPublicationSelection(episode_id='episode',series_id='series',script_id='script',authority_revision=3))
        db.add(RecapShareDecision(scope='edition:episode',revision=2,allowed=False,opted_out=True,token=None,token_digest=None))
        from app.services.generation.recap_models import (RecapCalibration,RecapQualificationReview,
            RecapStandingAuthorization,RecapDependency,RecapRecovery,RecapAttention,RecapRecoveryRequest)
        db.add(RecapCalibration(id='calibration',series_id='series',season=2026,config_json='{"voice":"synthetic"}',
            metadata_json='{"account":"synthetic"}',rate_json='{"unit":"character"}',versions_json='{"renderer":"1"}',
            evidence_json='{"billing":"synthetic-proof"}',actor_id='owner'))
        db.add(RecapQualificationReview(id='review',episode_id='episode',series_id='series',season=2026,
            calibration_id='calibration',approval_id='publication-approval',binding_json='{"script":"retained"}',
            evidence_json='{"phone":"synthetic-proof"}',actor_id='owner',passed=True))
        db.add(RecapStandingAuthorization(id='standing',series_id='series',season=2026,calibration_id='calibration',
            review_ids_json='["review"]',actor_id='owner'))
        db.add(RecapDependency(episode_id='episode',prior_episode_id='prior',observation_id='observation',facts_digest='facts'))
        db.add(RecapRecovery(episode_id='episode',stage_id='media-stage',action='resume_free',before_json='{"generation":1}',actor_id='owner',reason='synthetic'))
        db.add(RecapRecoveryRequest(attempt_id='synthetic-attempt',worker_id='worker',actor_id='owner',identity_json='{}',request_digest='synthetic',epoch='test-epoch',reason='synthetic'))
        db.add(RecapAttention(key='attention',episode_id='episode',state='held',reason='speech_verification_failed'))
        from app.services.generation.recap_models import RecapBackupPoint,RecapObjectDeletion,RecapRestoreReport
        db.add(RecapBackupPoint(run_id='synthetic-backup',state='complete',created_at=123,expires_at=999,
            objects_json='{"synthetic-immutable-key":{"sha256":"media-digest","size":17}}',
            authority_json='{"share_decisions":[{"scope":"edition:episode","revision":2,"allowed":false}]}'))
        db.add(RecapObjectDeletion(storage_key='synthetic-retired-key',state='deleted',claimed_at=122,
            asset_json='{"stage_id":"previous-stage","digest":"prior-byte-hash"}'))
        db.add(RecapRestoreReport(epoch='synthetic-prior-restore',digest='report-hash',
            report_json='{"reconciled":false,"current_authority_verified":false}',created_at=123))
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
