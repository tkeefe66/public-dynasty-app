import pytest
import json
from sqlalchemy import select
from app.services.generation.store import dump, Held


def test_qualification_counts_distinct_current_successful_episodes():
    # Mutation: count repeated approvals, or count an earlier pass after a failed current review.
    from app.services.recap_video.corrections import qualified_episode_count
    assert qualified_episode_count([{'episode_id':'e1','passed':True}, {'episode_id':'e1','passed':True},
        {'episode_id':'e2','passed':False}]) == 1
    assert qualified_episode_count([{'episode_id':'e1','passed':True}, {'episode_id':'e1','passed':False}]) == 0


@pytest.mark.asyncio
async def test_absent_calibration_never_enables_automatic_media(maker):
    # Mutation: feature mode or cap-save alone grants rollout authority.
    from app.services.recap_video.corrections import qualification_status
    async with maker() as db:
        status = await qualification_status(db, 'series', 2026)
    assert not status['automatic'] and status['passed'] == 0
    assert status['reason'] == 'media_calibration_required'


async def qualified_series(maker,tmp_path,monkeypatch):
    from tests.test_recap_workflow import seed_media
    from app.services.recap_video import qualification as q, elevenlabs
    from app.services.generation import recap_models as m
    from app.services.generation.models import ContentArtifact, ProviderAttempt, GenerationPolicy, LeagueSeason
    ident,media_id=await seed_media(maker,tmp_path,monkeypatch,'media_check')
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH','test-serving')
    monkeypatch.setattr(elevenlabs,'preflight_config',lambda:{'voice':'synthetic-v8'})
    monkeypatch.setattr(q,'current_versions',lambda:{'source':'1','template':'1','narrator':'v8','review':'1'})
    async with maker.begin() as db:
        db.add(m.RecapPublicationControl(id='global',epoch='test-serving',reconciliation_digest='test',quarantined=False))
        db.add(m.RecapShareDecision(scope='series:series',allowed=True,opted_out=False))
        policy=await db.get(GenerationPolicy,'app')
        value=json.loads(policy.value_json)
        value['features']['analyst']['mode']=value['features']['recap_video']['mode']='automatic'
        policy.value_json=dump(value)
        for s in (await db.scalars(select(LeagueSeason))).all():
            s.season=2026
        db.add(m.RecapCalibration(id='calibration',series_id='series',season=2026,config_json=dump(elevenlabs.preflight_config()),
            metadata_json='{"account":"synthetic"}',rate_json='{"unit":"character"}',versions_json=dump(q.current_versions()),evidence_json='{}',actor_id='owner'))
        rows=(await db.scalars(select(m.RecapStage))).all()
        for row in rows:
            row.state='succeeded'
            row.result_json=dump({'asset_ids':[]})
        original=await db.get(m.RecapEpisode,ident)
        script=await db.get(ContentArtifact,'script')
        for index in range(3):
            eid=ident if index==0 else 'episode-'+str(index)
            sid='script' if index==0 else 'script-'+str(index)
            mid=media_id if index==0 else 'media-'+str(index)
            if index:
                db.add(m.RecapEpisode(episode_id=eid,series_id='series',season=2026,period_id=str(index+5),league_id='synthetic',
                    week=index+5,nfl_weeks_json='[5]',facts_digest=original.facts_digest,article_digest=original.article_digest))
                db.add(ContentArtifact(id=sid,operation_id='job-'+str(index),series_id='series',league_id='synthetic',feature='recap_video',
                    subject=sid,revision=1,provenance='managed',payload_json=script.payload_json,digest=script.digest))
                db.add(m.RecapStage(id=mid,episode_id=eid,revision=1,kind='media_check',chunk=0,script_id=sid,operation_id='job-'+str(index),
                    input_json='{}',input_digest='input',policy_digest='policy',epoch='test-epoch',state='succeeded',result_json='{}'))
            db.add(m.RecapProviderAttempt(id='narration-'+str(index),stage_id='paid-'+str(index),episode_id=eid,series_id='series',
                operation_id='job' if index==0 else 'job-'+str(index),provider='elevenlabs',account_key='primary',worker_id='worker',
                generation=1,epoch='test-epoch',request_digest='request',request_json='{}',pricing_json='{}',authority_digest='authority',
                state='received',cost_microusd=100))
            db.add(ProviderAttempt(operation_id='job' if index==0 else 'job-'+str(index),stage=0,generation=1,request_digest='test',
                request_json='{}',model='synthetic',state='received',cost_microusd=10))
            await db.flush()
            binding=await q.review_binding(db,eid,mid)
            db.add(m.RecapQualificationReview(id='review-'+str(index),episode_id=eid,series_id='series',season=2026,calibration_id='calibration',
                approval_id='approval-'+str(index),binding_json=dump(binding),evidence_json='{}',actor_id='owner',passed=True))
        db.add(m.RecapStandingAuthorization(id='standing',series_id='series',season=2026,calibration_id='calibration',
            review_ids_json=dump(['review-0','review-1','review-2']),actor_id='owner'))
    return ident,media_id


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['unchanged','season','versions','voice','article','facts','uncertain','future_disabled'])
async def test_rollout_requires_current_season_versions_content_receipts_and_permission(maker,tmp_path,monkeypatch,change):
    # Mutation: enable from three old approvals without validating current version/content/receipt/share authority.
    from app.services.recap_video import qualification as q, elevenlabs
    from app.services.generation import recap_models as m
    ident,_=await qualified_series(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        if change=='article': (await db.get(m.RecapEpisode,ident)).article_digest='typo-only-new-article'
        if change=='facts': (await db.get(m.RecapEpisode,ident)).facts_digest='corrected-score'
        if change=='uncertain': (await db.get(m.RecapProviderAttempt,'narration-0')).cost_microusd=None
        if change=='future_disabled':
            future=await db.get(m.RecapShareDecision,'series:series')
            future.allowed,future.opted_out=False,True
    if change=='versions':monkeypatch.setattr(q,'current_versions',lambda:{'template':'2'})
    if change=='voice':monkeypatch.setattr(elevenlabs,'preflight_config',lambda:{'voice':'changed'})
    async with maker() as db:
        status=await q.qualification_status(db,'series',2027 if change=='season' else 2026)
        assert status['automatic'] == (change=='unchanged'),status
        if change in ('article','facts','uncertain'):assert status['passed']==2


@pytest.mark.asyncio
async def test_manual_first_episode_calibration_reader_needs_no_rollout_approvals(maker,tmp_path,monkeypatch):
    # Mutation: require three episodes before admitting the first manual calibration episode.
    from app.services.recap_video import qualification as q
    from app.services.generation import recap_models as m
    from sqlalchemy import delete
    ident,_=await qualified_series(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        await db.execute(delete(m.RecapQualificationReview))
        await db.execute(delete(m.RecapStandingAuthorization))
        value=await q.qualification_reader(db,ident)
        assert value['revision']=='calibration' and value['config']=={'voice':'synthetic-v8'}
        assert (await q.qualification_status(db,'series',2026))['passed']==0
