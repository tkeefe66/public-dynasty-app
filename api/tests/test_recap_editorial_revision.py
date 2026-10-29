import json

import pytest
from sqlalchemy import func, select

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationOperation, ProviderAttempt
from app.services.generation.recap_models import RecapEpisode, RecapObservation, RecapPublicationControl, RecapStage
from app.services.generation.store import Held, digest, dump
from tests.test_recap_article_recovery import fixture


async def setup(maker, tmp_path, monkeypatch):
    ident = await fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        (await db.get(GenerationOperation, 'original-canonical')).epoch = 'test-epoch'
        receipt = await db.get(ProviderAttempt, 'original-canonical-receipt')
        receipt.receipt_json = dump({'body': {'content': [{'type': 'tool_use', 'name': 'submit_recap_review', 'input': {'approved': True}}]}})
        article = await db.get(ContentArtifact, 'article')
        data = json.loads(article.payload_json)
        headings = '\n\n'.join('### ' + m['winner'] + ' / ' + m['loser'] for m in data['facts']['matchups'])
    return ident, dict(artifact_id='article', actor_id='owner', cache_dir=tmp_path,
        edits=[{'before': data['markdown'], 'after': headings + '\n\nVerified full-PPR result.'}],
        reviewer='Independent editorial reviewer', review_notes='Full source and passage audit.', reason='Corrected scoring prose.')


@pytest.mark.asyncio
async def test_revision_serves_exact_reviewed_text_and_invalidates_on_source_change(maker, tmp_path, monkeypatch):
    # Mutation: require a new paid job for monitoring an operator-reviewed revision.
    from app.services.recap_video.editorial_revision import revise
    from app.services.recap_video.text_authority import member_text_current
    ident, kwargs = await setup(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        old = await db.get(ContentArtifact, 'article')
        before = old.payload_json
        preview = await revise(db, ident, **kwargs)
        result = await revise(db, ident, **kwargs, apply=True, expected_digest=preview['digest'])
        new = await db.get(ContentArtifact, result['artifact_id'])
        episode = await db.get(RecapEpisode, ident)
        assert await member_text_current(db, episode, json.loads(new.payload_json))
        from app.services.recap_monitor.evidence import publication_proof
        monitor = await publication_proof(db, tmp_path, 'synthetic', 2026, 4)
        assert monitor and monitor['artifact_id'] == new.id
        assert monitor['review_kind'] == 'operator_editorial'
        assert episode.lifecycle == 'correction' and episode.hold == 'recap_editorial_correction_required'
        assert old.payload_json == before and new.operation_id is None
        assert (await db.get(GenerationOperation, 'original-canonical')).artifact_id == old.id
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 1
        observation = await db.get(RecapObservation, episode.latest_observation_id)
        source = json.loads(observation.snapshot_json)
        source['scores']['4'][0]['points'] = '99'
        observation.snapshot_json, observation.snapshot_digest = dump(source), digest(source)
        episode.source_digest = digest(source)
        assert not await member_text_current(db, episode, json.loads(new.payload_json))
        assert not await publication_proof(db, tmp_path, 'synthetic', 2026, 4)


@pytest.mark.asyncio
async def test_text_repair_does_not_restart_automatic_media(maker, tmp_path, monkeypatch):
    from app.services.recap_video.editorial_revision import revise
    from app.services.recap_video.workflow import advance_media
    ident, kwargs = await setup(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        preview = await revise(db, ident, **kwargs)
        await revise(db, ident, **kwargs, apply=True, expected_digest=preview['digest'])
        before = await db.scalar(select(func.count()).select_from(GenerationOperation))
    await advance_media(maker)
    async with maker() as db:
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == before
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['preview', 'review', 'receipt', 'source', 'anchor', 'head', 'epoch', 'stage', 'results', 'starters', 'positions'])
async def test_changed_editorial_review_cannot_publish(maker, tmp_path, monkeypatch, change):
    from app.services.recap_video.editorial_revision import revise
    ident, kwargs = await setup(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        preview = await revise(db, ident, **kwargs)
        if change == 'review':
            kwargs['review_notes'] += ' Changed.'
        if change == 'anchor':
            kwargs['edits'] = [{'before': 'nonexistent', 'after': 'replacement'}]
        if change == 'receipt':
            (await db.get(ProviderAttempt, 'original-canonical-receipt')).usage_state = 'unknown'
        if change == 'source':
            (await db.get(RecapEpisode, ident)).source_digest = 'changed'
        if change in ('results', 'starters', 'positions'):
            observation = await db.get(RecapObservation, 'observation')
            source = json.loads(observation.snapshot_json)
            if change == 'results':
                source['pairings'][0]['scores'][0] = '99'
            elif change == 'starters':
                source['starters']['4']['1'] = ['different']
            else:
                source['roster_positions'] = ['FLEX', 'QB']
            observation.snapshot_json, observation.snapshot_digest = dump(source), digest(source)
            (await db.get(RecapEpisode, ident)).source_digest = digest(source)
        if change == 'head':
            (await db.get(ArtifactHead, 'article-subject')).hold = 'operator_hold'
        if change == 'epoch':
            (await db.get(RecapPublicationControl, 'global')).epoch = 'restored'
        if change == 'stage':
            db.add(RecapStage(id='new-stage', episode_id=ident, kind='script', state='queued',
                revision=1, script_id='', operation_id='', input_json='{}', input_digest='input', policy_digest='policy'))
        with pytest.raises(Held):
            await revise(db, ident, **kwargs, apply=True,
                expected_digest='wrong' if change == 'preview' else preview['digest'])
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['job', 'execution_epoch', 'receipt'])
async def test_review_authority_remains_checked_on_reads(maker, tmp_path, monkeypatch, change):
    from app.services.recap_video.editorial_revision import revise
    from app.services.recap_video.text_authority import member_text_current
    ident, kwargs = await setup(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        preview = await revise(db, ident, **kwargs)
        result = await revise(db, ident, **kwargs, apply=True, expected_digest=preview['digest'])
        article = await db.get(ContentArtifact, result['artifact_id'])
        if change == 'job':
            (await db.get(GenerationOperation, 'original-canonical')).state = 'cancelled'
        if change == 'execution_epoch':
            monkeypatch.setenv('TRADE_GRADER_GENERATION_EXECUTION_EPOCH', 'restored')
        if change == 'receipt':
            (await db.get(ProviderAttempt, 'original-canonical-receipt')).receipt_json = '{}'
        assert not await member_text_current(db, await db.get(RecapEpisode, ident), json.loads(article.payload_json))
