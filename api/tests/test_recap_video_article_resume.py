import json

import pytest
from sqlalchemy import func, select

from app.services.generation.models import ContentArtifact, GenerationOperation, ProviderAttempt
from app.services.generation.recap_models import RecapEpisode, RecapStage
from app.services.generation.store import Held
from tests.test_recap_editorial_revision import setup


async def corrected(maker, tmp_path, monkeypatch):
    from app.services.recap_video.editorial_revision import revise
    from app.services.recap_video import qualification
    from types import SimpleNamespace
    ident, kwargs = await setup(maker, tmp_path, monkeypatch)
    async def calibrated(*args):
        return SimpleNamespace(id='calibration')
    monkeypatch.setattr(qualification, 'calibration', calibrated)
    async with maker.begin() as db:
        preview = await revise(db, ident, **kwargs)
        result = await revise(db, ident, **kwargs, apply=True, expected_digest=preview['digest'])
    return ident, result['artifact_id']


@pytest.mark.asyncio
async def test_resume_binds_reviewed_article_without_provider_calls(maker, tmp_path, monkeypatch):
    # Mutation: leave corrected text permanently stranded, or generate fresh text during resume.
    from app.services.recap_video.article_resume import resume_video
    ident, artifact_id = await corrected(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        jobs = await db.scalar(select(func.count()).select_from(GenerationOperation))
        result = await resume_video(db, ident, actor_id='owner', reason='Resume corrected video under current caps')
        assert result['article_id'] == artifact_id
        episode = await db.get(RecapEpisode, ident)
        assert episode.lifecycle == 'ready' and episode.hold == ''
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == jobs
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 1
        from app.services.recap_video.article_resume import first_video_resume_authorized
        from app.services.recap_video.contracts import _published_article
        article = await _published_article(db, episode)
        assert await first_video_resume_authorized(db, episode, article)
        assert not await first_video_resume_authorized(db, episode, {**article, 'digest': 'later-revision'})


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['source', 'article', 'paid_script', 'stage', 'unstable', 'operator_hold'])
async def test_resume_refuses_changed_or_already_started_work(maker, tmp_path, monkeypatch, change):
    # Mutation: clear every correction hold without validating source, article and saved work.
    from app.services.recap_video.article_resume import resume_video
    ident, artifact_id = await corrected(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        if change == 'source': episode.source_digest = 'changed'
        if change == 'article': (await db.get(ContentArtifact, artifact_id)).payload_json = '{}'
        if change == 'unstable': episode.stable_since = 0
        if change == 'operator_hold': episode.hold = 'owner_paused'
        if change == 'paid_script':
            db.add(GenerationOperation(id='paid-video', kind='generation', feature='recap_video',
                league_id='synthetic', series_id='series', subject='recap_video:'+ident,
                state='failed', calls=1, payload_json=json.dumps({'episode_id': ident})))
        if change == 'stage':
            db.add(RecapStage(id='narration', episode_id=ident, revision=1, kind='narrate',
                script_id='', operation_id='', input_json='{}', input_digest='', policy_digest=''))
        await db.flush()
        with pytest.raises(Held):
            await resume_video(db, ident, actor_id='owner', reason='Resume corrected video under current caps')
        assert episode.hold


@pytest.mark.asyncio
async def test_managed_automatic_text_correction_resumes_first_video(maker, tmp_path, monkeypatch):
    # Mutation: corrected text finishes while its enabled first video stays held forever.
    from tests.test_recap_automatic_corrections import published, changed_source, ReviewedTransport, run_correction
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.recap_video.article_resume import resume_automatic_articles
    from app.services.recap_video import qualification
    from types import SimpleNamespace
    ident = await published(maker, tmp_path, monkeypatch)
    async def qualified(*args): return {'automatic': True}
    async def calibrated(*args): return SimpleNamespace(id='calibration')
    monkeypatch.setattr(qualification, 'qualification_status', qualified)
    monkeypatch.setattr(qualification, 'calibration', calibrated)
    async with maker.begin() as db:
        (await db.get(GenerationOperation, 'job')).state = 'cancelled'
        source = await changed_source(db, ident, '102')
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600)
    await run_correction(maker, tmp_path, ReviewedTransport())
    async with maker.begin() as db:
        before = await db.scalar(select(func.count()).select_from(ProviderAttempt))
        assert (await db.get(RecapEpisode, ident)).hold == 'recap_facts_changed'
        await resume_automatic_articles(db)
        episode = await db.get(RecapEpisode, ident)
        assert episode.lifecycle == 'ready' and episode.hold == ''
        await resume_automatic_articles(db)
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == before


@pytest.mark.asyncio
async def test_operator_text_only_revision_does_not_implicitly_resume_video(maker, tmp_path, monkeypatch):
    # Mutation: treat a text-only manual repair as permission for new video spending.
    from app.services.recap_video.article_resume import resume_automatic_articles
    ident, _ = await corrected(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        await resume_automatic_articles(db)
        assert (await db.get(RecapEpisode, ident)).hold == 'recap_editorial_correction_required'
