"""Canonical article correction must never regenerate already-paid work."""
import json

import pytest
from sqlalchemy import select, func

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationOperation, ProviderAttempt
from app.services.generation.recap_models import RecapEpisode, RecapObservation
from app.services.generation.store import Held, digest, dump
from tests.test_recap_publication import ready_article


async def fixture(maker, tmp_path, monkeypatch):
    from app.services.analyst_store import AnalystEdition, AnalystStore
    from app.services.recap_video.readiness import competitive_digest
    ident = await ready_article(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        observation = await db.get(RecapObservation, episode.latest_observation_id)
        source = json.loads(observation.snapshot_json)
        source['scoring_settings'] = {'rec': '1.0'}
        observation.snapshot_json, observation.snapshot_digest = dump(source), digest(source)
        observation.facts_digest = competitive_digest(source)
        episode.facts_digest = observation.facts_digest
        episode.source_digest = observation.snapshot_digest
        episode.lifecycle, episode.hold = 'correction', 'recap_editorial_correction_required'
        episode.observed_at, episode.stable_since = 4600, 1
        artifact = await db.get(ContentArtifact, 'article')
        data = json.loads(artifact.payload_json)
        data['facts']['source_snapshot'] = source
        data['markdown'] = 'In a league with half-PPR scoring, this result stands.'
        data['correction_note'] = 'Automatic eligible period'
        data = AnalystEdition.model_validate(data).model_dump()
        artifact.payload_json, artifact.digest = dump(data), digest(data)
        artifact.facts_json = dump({'recap_facts_digest':episode.facts_digest})
        artifact.operation_id = 'original-canonical'
        episode.article_digest = artifact.digest
        db.add(GenerationOperation(id='original-canonical', kind='generation', feature='analyst',
            subject=artifact.subject, league_id=artifact.league_id, series_id=artifact.series_id,
            state='succeeded', artifact_id=artifact.id, calls=1, payload_json=dump({'facts':data['facts']})))
        db.add(ProviderAttempt(id='original-canonical-receipt', operation_id='original-canonical',
            stage=1, generation=1, request_digest='saved',request_json='{}',model='saved',state='received',
            usage_state='known',cost_microusd=100,receipt_json='{}'))
        (await db.get(GenerationOperation, 'job')).state = 'cancelled'
        AnalystStore(tmp_path).save('synthetic',data)
    return ident


@pytest.mark.asyncio
async def test_canonical_scoring_correction_appends_revision_without_paid_requests(maker,tmp_path,monkeypatch):
    from app.services.recap_video.article_recovery import correct_scoring_label
    from app.services.recap_video.contracts import _published_article
    ident = await fixture(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        original=await db.get(ContentArtifact,'article'); before=original.payload_json
        kwargs=dict(artifact_id='article',actor_id='owner',cache_dir=tmp_path)
        preview=await correct_scoring_label(db,ident,**kwargs)
        assert (await db.get(RecapEpisode,ident)).hold == 'recap_editorial_correction_required'
        result=await correct_scoring_label(db,ident,**kwargs,apply=True,expected_digest=preview['digest'])
        assert original.payload_json == before
        replacement=await db.get(ContentArtifact,result['corrected_artifact_id'])
        assert replacement.operation_id is None
        assert (await db.get(GenerationOperation,'original-canonical')).artifact_id == original.id
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 1
        episode=await db.get(RecapEpisode,ident)
        assert episode.article_digest == replacement.digest and not episode.hold and episode.lifecycle == 'ready'
        article=await _published_article(db,episode)
        assert article['markdown'] == 'In a league with full-PPR scoring, this result stands.'
        assert article['correction_note'] == 'Corrected the scoring label to full PPR: the saved league rules award 1 point per reception. Matchup results are unchanged.'


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['source','head','receipt','duplicate','preview'])
async def test_canonical_correction_rejects_unproved_or_changed_evidence(maker,tmp_path,monkeypatch,change):
    from app.services.recap_video.article_recovery import correct_scoring_label
    ident=await fixture(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        kwargs=dict(artifact_id='article',actor_id='owner',cache_dir=tmp_path)
        preview=await correct_scoring_label(db,ident,**kwargs)
        if change=='source':
            observation=await db.get(RecapObservation,'observation')
            source=json.loads(observation.snapshot_json);source['scoring_settings']['rec']='0.5'
            observation.snapshot_json,observation.snapshot_digest=dump(source),digest(source)
        elif change=='head': (await db.get(ArtifactHead,'article-subject')).hold='review'
        elif change=='receipt': (await db.get(ProviderAttempt,'original-canonical-receipt')).usage_state='unknown'
        elif change=='duplicate':
            artifact=await db.get(ContentArtifact,'article');data=json.loads(artifact.payload_json)
            data['markdown']+=' half-PPR';artifact.payload_json,artifact.digest=dump(data),digest(data)
        with pytest.raises(Held):
            await correct_scoring_label(db,ident,**kwargs,apply=True,expected_digest='stale' if change=='preview' else preview['digest'])
        assert (await db.get(RecapEpisode,ident)).hold == 'recap_editorial_correction_required'
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1


def test_complete_editorial_correction_plan_is_derived_from_saved_rules_and_results():
    from app.services.recap_video.article_recovery import corrected_prose
    source={'week':6,'scoring_settings':{'rec':'1.0','rush_yd':'0.1','rec_yd':'0.1'},
        'participants':[{'owner_name':'Alpha','roster_id':1},{'owner_name':'Beta','roster_id':2}],
        'scores':{'6':[{'roster_id':1,'matchup_id':1,'points':'91.1'}, {'roster_id':2,'matchup_id':1,'points':'90.62'}]}}
    data={'markdown':"half-PPR. Beta Posts His Lowest Score of the Season. Alpha's starting roster put up **91.1 points** — the second-lowest total among all winners this week. One reception. One extra yard. One overtime extra point. Gone."}
    plan=[{'kind':'scoring_label'},{'kind':'remove_season_low','owner':'Beta'},
        {'kind':'winner_rank','owner':'Alpha'},{'kind':'remove_unsupported_yard_example'}]
    result=corrected_prose(data,source,plan)
    assert 'full-PPR' in result and 'Beta Posts 90.62' in result
    assert 'the lowest total' in result and 'One extra yard' not in result
    with pytest.raises(Held,match='article_winner_rank_unproved'):
        corrected_prose(data,source,[{'kind':'winner_rank','owner':'Beta'}])
    source['scores']['6'][1]['matchup_id']=None
    with pytest.raises(Held,match='article_winner_pairing_unproved'):
        corrected_prose(data,source,[{'kind':'winner_rank','owner':'Alpha'}])


@pytest.mark.asyncio
async def test_canonical_recovery_refuses_pending_script(maker,tmp_path,monkeypatch):
    from app.services.recap_video.article_recovery import correct_scoring_label
    ident=await fixture(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        (await db.get(GenerationOperation,'job')).state='queued'
        with pytest.raises(Held,match='article_script_started_requires_separate_review'):
            await correct_scoring_label(db,ident,artifact_id='article',actor_id='owner',cache_dir=tmp_path)


@pytest.mark.asyncio
async def test_canonical_recovery_file_projection_rollback_stays_held_and_retries(maker,tmp_path,monkeypatch):
    from app.services.recap_video.article_recovery import correct_scoring_label
    ident=await fixture(maker,tmp_path,monkeypatch)
    kwargs=dict(artifact_id='article',actor_id='owner',cache_dir=tmp_path)
    async with maker.begin() as db:
        preview=await correct_scoring_label(db,ident,**kwargs)
    with pytest.raises(RuntimeError):
        async with maker.begin() as db:
            await correct_scoring_label(db,ident,**kwargs,apply=True,expected_digest=preview['digest'])
            raise RuntimeError('commit failed')
    async with maker.begin() as db:
        assert (await db.get(RecapEpisode,ident)).hold=='recap_editorial_correction_required'
        assert await db.scalar(select(func.count()).select_from(ContentArtifact))==1
        result=await correct_scoring_label(db,ident,**kwargs,apply=True,expected_digest=preview['digest'])
        assert result['applied']
