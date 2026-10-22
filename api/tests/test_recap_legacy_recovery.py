"""Receipt-only recovery of a demonstrably false legacy withdrawal."""
import json

import pytest
from sqlalchemy import func, select

from app.services.generation.models import (ArtifactHead, ContentArtifact, GenerationAudit,
    GenerationOperation, ProviderAttempt)
from app.services.generation.recap_models import (RecapEpisode, RecapObservation,
    RecapPublication, RecapShareDecision)
from app.services.generation.store import Held, digest, dump
from tests.test_recap_publication import ready_article, legacy_for_canonical


async def recovery_fixture(maker, tmp_path, monkeypatch):
    from app.services.analyst_store import AnalystStore
    from app.services.recap_video.publication import public_article, withdraw_edition
    from tests.test_recap_competitive_facts import live_change
    ident = await ready_article(maker, tmp_path, monkeypatch)
    legacy, _ = await legacy_for_canonical(maker)
    async with maker.begin() as db:
        article = await db.get(ContentArtifact, 'article')
        article.created_at = 100
        article.operation_id = 'original-approved'
        data = json.loads(article.payload_json)
        AnalystStore(tmp_path).save('synthetic', data)
        row = await db.get(RecapPublication, legacy)
        row.article_json = dump(public_article(data))
        row.article_digest = digest(public_article(data))
        row.published_at = 200
        row.media_id, row.media_json = 'saved-video', dump({'id': 'saved-video', 'storage': 'legacy'})
        row.enabled = False
        share = await db.get(RecapShareDecision, 'edition:' + legacy)
        share.allowed, share.opted_out = False, True
        db.add(GenerationOperation(id='original-approved', kind='generation', league_id='synthetic',
            series_id='series', feature='analyst', subject=article.subject, state='succeeded',
            artifact_id='article', calls=1, max_calls=1, created_at=50, updated_at=100))
        db.add(ProviderAttempt(id='saved-receipt', operation_id='original-approved', stage=1,
            generation=1, request_digest='request', request_json='{}', model='saved-model',
            state='received', usage_state='known', receipt_json='{}', cost_microusd=5))
        episode = await db.get(RecapEpisode, ident)
        episode.admitted_at, episode.article_digest = 0, ''
        episode.lifecycle, episode.hold = 'correction', 'recap_facts_changed'
        old = await db.get(RecapObservation, episode.latest_observation_id)
        old.observed_at = 300
        source = json.loads(old.snapshot_json)
        changed = live_change(source)
        db.add(RecapObservation(id='latest', episode_id=ident, observed_at=5000,
            snapshot_json=dump(changed), snapshot_digest=digest(changed),
            facts_digest='legacy-raw', decision='recap_facts_changed'))
        episode.latest_observation_id = 'latest'
        await withdraw_edition(db, 'synthetic', 2026, 4, expected_revision=7,
            actor_id='api-observer', reason='recap_facts_changed')
        await db.flush()
        audit = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == 'recap_publication_withdrawn'))
        audit.created_at = 400
    return ident, legacy


@pytest.mark.asyncio
async def test_recovery_dry_run_and_apply_preserve_paid_content_and_sharing(maker, tmp_path, monkeypatch):
    # Mutation: preview mutates, apply generates content, or recovery restores a public link.
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        row = await db.get(RecapPublication, legacy)
        before = (row.article_json, row.media_id, row.media_json, row.enabled)
        share = await db.get(RecapShareDecision, 'edition:' + legacy)
        share_before = (share.allowed, share.opted_out, share.token, share.revision)
        counts = [await db.scalar(select(func.count()).select_from(model))
            for model in (GenerationOperation, ProviderAttempt, GenerationAudit)]
        preview = await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Reviewed false live-roster drift')
        assert row.withdrawn and row.authority_revision == 8
        assert counts == [await db.scalar(select(func.count()).select_from(model))
            for model in (GenerationOperation, ProviderAttempt, GenerationAudit)]
        result = await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Reviewed false live-roster drift',
            apply=True, expected_digest=preview['digest'])
        assert result['applied'] and not row.withdrawn
        assert row.authority_revision == row.projected_revision == 9
        assert before == (row.article_json, row.media_id, row.media_json, row.enabled)
        assert share_before == (share.allowed, share.opted_out, share.token, share.revision)
        assert (await db.get(RecapEpisode, ident)).hold == 'historical_approval_required'
        assert counts[:2] == [await db.scalar(select(func.count()).select_from(model))
            for model in (GenerationOperation, ProviderAttempt)]


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['score', 'reverted_score', 'reason', 'head', 'article', 'receipt', 'revision', 'admin', 'missing_source', 'different_source'])
async def test_recovery_rejects_unproved_or_changed_evidence(maker, tmp_path, monkeypatch, change):
    # Mutation: clear withdrawal without checking historical truth, authority and original output.
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        if change in ('score', 'reverted_score'):
            latest = await db.get(RecapObservation, 'latest')
            source = json.loads(latest.snapshot_json)
            source['scores']['4'][0]['points'] = '900.00'
            if change == 'score':
                latest.snapshot_json = dump(source)
                latest.snapshot_digest = digest(source)
            else:
                db.add(RecapObservation(id='intermediate', episode_id=ident, observed_at=4500,
                    snapshot_json=dump(source), snapshot_digest=digest(source), facts_digest='changed', decision='facts_unstable'))
        elif change == 'reason':
            audit = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == 'recap_publication_withdrawn'))
            audit.reason = 'manual_withdrawal'
        elif change == 'head':
            (await db.get(ArtifactHead, 'article-subject')).artifact_id = 'new-unreviewed'
        elif change == 'article':
            row = await db.get(RecapPublication, legacy)
            data = {**json.loads(row.article_json), 'markdown': 'Unreviewed replacement'}
            row.article_json, row.article_digest = dump(data), digest(data)
        elif change == 'receipt':
            (await db.get(ProviderAttempt, 'saved-receipt')).usage_state = 'unknown'
        elif change in ('missing_source', 'different_source'):
            from app.services.recap_video.publication import public_article
            artifact = await db.get(ContentArtifact, 'article')
            data = json.loads(artifact.payload_json)
            if change == 'missing_source':
                del data['facts']['source_snapshot']
            else:
                data['facts']['source_snapshot']['scores']['4'][0]['points'] = '88.00'
            artifact.payload_json, artifact.digest = dump(data), digest(data)
            row = await db.get(RecapPublication, legacy)
            row.article_json, row.article_digest = dump(public_article(data)), digest(public_article(data))
        with pytest.raises(Held):
            await recover_false_withdrawal(db, ident, expected_revision=99 if change == 'revision' else 8,
                artifact_id='article', actor_id='missing' if change == 'admin' else 'owner', reason='Review')
        assert (await db.get(RecapPublication, legacy)).withdrawn


@pytest.mark.asyncio
async def test_recovery_apply_rejects_changed_preview(maker, tmp_path, monkeypatch):
    # Mutation: a preview remains valid after sharing authority changes.
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        preview = await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Review')
        (await db.get(RecapShareDecision, 'edition:' + legacy)).revision += 1
        with pytest.raises(Held, match='recovery_preview_changed'):
            await recover_false_withdrawal(db, ident, expected_revision=8,
                artifact_id='article', actor_id='owner', reason='Review', apply=True,
                expected_digest=preview['digest'])


@pytest.mark.asyncio
async def test_recovered_authority_still_requires_original_files_on_read(maker, tmp_path, monkeypatch):
    # Mutation: DB recovery bypasses article_current and serves an unreviewed file.
    from app.services.analyst_store import AnalystStore
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    from app.services.recap_video.publication import authorize_member_read
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        preview = await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Review')
        await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Review', apply=True,
            expected_digest=preview['digest'])
        assert (await authorize_member_read(db, 'synthetic', 2026, 4))['media']['id'] == 'saved-video'
        path = AnalystStore(tmp_path).edition_path('synthetic', 2026, 4)
        path.write_text(dump({**json.loads(path.read_text()), 'markdown': 'Unreviewed replacement'}))
        with pytest.raises(Held, match='public_unavailable'):
            await authorize_member_read(db, 'synthetic', 2026, 4)
