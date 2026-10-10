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


@pytest.mark.asyncio
@pytest.mark.parametrize('existing',['none','member_article','revised','previous_media','revoked','future_disabled','revoked_after_approval'])
async def test_standing_policy_attaches_initial_article_but_never_reverses_review_or_consent(maker,tmp_path,monkeypatch,existing):
    # Mutation: reject every existing article, allow revised media, or ignore consent CAS.
    from app.services.recap_video import publication as p,qualification as q,workflow
    from app.services.generation import recap_models as m
    from app.services.generation.models import ContentArtifact
    from app.services.generation.store import digest,resolve_policy
    ident,mid=await qualified_series(maker,tmp_path,monkeypatch)
    async def verified(*args):return {'id':'synthetic-new-media'},'script'
    monkeypatch.setattr(p,'verified_media',verified)
    async with maker.begin() as db:
        policy=await resolve_policy(db,'series')
        evidence=await workflow.require_media_preflight(db,ident)
        stage=await db.get(m.RecapStage,mid)
        stage.policy_digest=digest([policy['policy']['features']['recap_video'],policy['revisions'],evidence])
        episode=await db.get(m.RecapEpisode,ident)
        if existing!='none':
            # Use actual member article-only share bootstrap and current authority revision.
            share=await p.change_share(db,enabled=True,actor_id='member',league_id='synthetic',season=2026,week=4)
            authority=await p.authority_for_episode(db,episode)
            assert authority.media_id is None
            if existing=='revised':authority.article_revision=2
            if existing=='previous_media':authority.media_id='previously-reviewed'
            if existing=='revoked':await p.change_share(db,enabled=False,actor_id='member',league_id='synthetic',season=2026,week=4)
            if existing=='future_disabled':await p.set_future_sharing(db,'series',allowed=False,actor_id='owner')
            expected=authority.authority_revision
        else:expected=0
    async with maker.begin() as db:
        if existing in ('revised','previous_media','revoked','future_disabled'):
            with pytest.raises(Held):await q.record_standing_approval(db,ident,expected,mid)
            return
        proof=await q.record_standing_approval(db,ident,expected,mid)
        saved=await db.get(m.RecapPublicationApproval,proof['approval_id'])
        assert saved.authorization_kind=='standing' and not saved.reviewer_id and saved.authorization_id=='standing'
    if existing=='revoked_after_approval':
        async with maker.begin() as db:
            await p.change_share(db,enabled=False,actor_id='member',league_id='synthetic',season=2026,week=4)
        from app.services.generation.store import Conflict
        async with maker.begin() as db:
            with pytest.raises((Held,Conflict)):
                await p.select_publication(db,ident,expected,mid,proof)
        return
    async with maker.begin() as db:
        selected=await p.select_publication(db,ident,expected,mid,proof)
        assert selected['authority_revision']==expected+1
        assert (await p.authority_for_episode(db,await db.get(m.RecapEpisode,ident))).media_id==mid


@pytest.mark.asyncio
@pytest.mark.parametrize('format_change',['known','unknown_rules','unknown_teams','unresolved','identity_mismatch'])
async def test_standing_postseason_uses_saved_authoritative_format(maker,tmp_path,monkeypatch,format_change):
    from tests.test_recap_readiness import snapshot,playoff_fixture
    from app.services.recap_video import qualification as q,publication as p
    from app.services.recap_video.periods import build_participants,scoring_period
    from app.services.recap_video.readiness import competitive_digest
    from app.services.generation import recap_models as m
    await qualified_series(maker,tmp_path,monkeypatch)
    rosters,bracket,rows=playoff_fixture()
    rules={'playoff_week_start':15,'playoff_round_type':0,'playoff_teams':6}
    period=scoring_period(15,rules,bracket)
    source={**snapshot(),**period,'rules':rules}
    source.update(build_participants(rosters,{'15':rows},bracket,source))
    if format_change=='unknown_rules':source['rules']['playoff_round_type']=9
    if format_change=='unknown_teams':source['rules']['playoff_teams']=10
    if format_change=='unresolved':source['bracket']['ok']=False
    if format_change=='identity_mismatch':source['round']=2
    async with maker.begin() as db:
        episode=m.RecapEpisode(episode_id='playoff',series_id='series',season=2026,period_id='playoff:1',week=15,
            league_id='synthetic',round=1,nfl_weeks_json='[15]',facts_digest=competitive_digest(source),
            stable_since=1,observed_at=4600,latest_observation_id='post-observation')
        db.add(episode)
        db.add(m.RecapObservation(id='post-observation',episode_id='playoff',observed_at=4600,snapshot_json=dump(source),
            snapshot_digest='synthetic',facts_digest=episode.facts_digest,decision='ready'))
    async def verified(*args):return {'id':'post-media'},'post-script'
    async def scope(*args):return {'article':{'artifact_id':'post-article','revision':1,'digest':'post-article-digest'}}
    monkeypatch.setattr(p,'verified_media',verified)
    monkeypatch.setattr(p,'current_scope',scope)  # Task9 bindings exercised by initial-article test above.
    async with maker.begin() as db:
        if format_change!='known':
            with pytest.raises(Held,match='recap_format_review_required'):
                await q.record_standing_approval(db,'playoff',0,'post-media')
        else:
            proof=await q.record_standing_approval(db,'playoff',0,'post-media')
            await q.require_standing_proof(db,await db.get(m.RecapPublicationApproval,proof['approval_id']))


@pytest.mark.asyncio
async def test_automatic_projector_carries_member_article_revision_through_selection(maker,tmp_path,monkeypatch):
    from app.services.recap_video import publication as p,qualification as q,workflow
    from app.services.generation import recap_models as m
    from app.services.generation.store import digest,resolve_policy
    ident,mid=await qualified_series(maker,tmp_path,monkeypatch)
    async def verified(*args):return {'id':'synthetic-media'},'script'
    monkeypatch.setattr(p,'verified_media',verified)
    async with maker.begin() as db:
        config=await resolve_policy(db,'series')
        stage=await db.get(m.RecapStage,mid)
        stage.policy_digest=digest([config['policy']['features']['recap_video'],config['revisions'],await workflow.require_media_preflight(db,ident)])
        (await db.get(m.RecapEpisode,ident)).lifecycle='review'
        await p.change_share(db,enabled=True,actor_id='member',league_id='synthetic',season=2026,week=4)
        assert (await p.authority_for_episode(db,await db.get(m.RecapEpisode,ident))).authority_revision==1
    await q.advance_qualified_publication(maker)
    async with maker() as db:
        authority=await p.authority_for_episode(db,await db.get(m.RecapEpisode,ident))
        assert authority.authority_revision==2 and authority.media_id==mid
        assert (await db.get(m.RecapEpisode,ident)).lifecycle=='published'
