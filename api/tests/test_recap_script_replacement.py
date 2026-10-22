"""Failed script review is free, source-current, and never automatic authority."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.services.generation.models import GenerationOperation, GenerationCandidate, ProviderAttempt
from app.services.generation.store import Held
from tests.test_recap_video_script import seed


async def failed_script(maker,tmp_path,monkeypatch):
    ident,saved=await seed(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job')
        job.subject='recap_video:'+ident
        job.state,job.reason='needs_attention','execution_failed'
        job.calls=job.max_calls=4
        for n in range(1,5):
            db.add(ProviderAttempt(id='saved-'+str(n),operation_id=job.id,stage=n,generation=job.generation,
                request_digest='request-'+str(n),request_json='{}',model='saved',state='received',
                usage_state='known',cost_microusd=10,receipt_json='{}'))
    return ident,saved


@pytest.mark.asyncio
async def test_failed_script_rebuilds_free_preview_with_separate_paid_gate(maker,tmp_path,monkeypatch):
    from app.services.generation.resolution import prepare_replacement,resolution
    from app.services.generation.planner import observe
    from app.services.generation.commands import authorize_candidate
    ident,saved=await failed_script(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job')
        original=job.payload_json
        assert (await resolution(db,job))['action']=='replacement'
        body=SimpleNamespace(expected_generation=job.generation,expected_state=job.state,reason='Review fixed compiler replacement')
        preview=await prepare_replacement(db,job.id,body,'owner')
        assert preview['maximum_additional_microusd']>0 and preview['prior_cost_microusd']==40
        assert preview['max_calls']==4
        assert job.state=='cancelled' and job.payload_json==original
        assert await db.scalar(select(func.count()).select_from(GenerationOperation))==1
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt))==4
        candidate=await db.get(GenerationCandidate,preview['items'][0]['key'])
        fresh=json.loads(candidate.payload_json)
        assert fresh['episode_id']==ident and fresh['published_article']==saved['published_article']
        await observe(db,series_id=candidate.series_id,league_id=candidate.league_id,feature=candidate.feature,
            subject=candidate.subject,event=candidate.event,payload=fresh)
        assert candidate.hold=='manual_approval_required'
        with pytest.raises(Held,match='manual_approval_required|manual_only'):
            await authorize_candidate(db,candidate.key,actor_id=None,actor_kind='scheduler',reason='automatic',authorization_key='unexpected')


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['unknown','missing','active','artifact','allowance'])
async def test_script_replacement_refuses_unsettled_or_already_existing_work(maker,tmp_path,monkeypatch,change):
    from app.services.generation.resolution import prepare_replacement
    from app.services.generation.models import ArtifactHead
    await failed_script(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job')
        if change=='unknown': (await db.get(ProviderAttempt,'saved-1')).usage_state='unknown'
        elif change=='missing': await db.delete(await db.get(ProviderAttempt,'saved-1'))
        elif change=='active':
            db.add(GenerationOperation(id='other',kind='generation',feature='recap_video',subject=job.subject,
                series_id=job.series_id,league_id=job.league_id,state='running'))
        elif change=='artifact': db.add(ArtifactHead(subject=job.subject,artifact_id='saved-script',revision=1))
        else: job.max_calls=5
        await db.flush()
        body=SimpleNamespace(expected_generation=job.generation,expected_state=job.state,reason='Review replacement')
        with pytest.raises(Held):
            await prepare_replacement(db,job.id,body,'owner')
        assert job.state=='needs_attention'


@pytest.mark.asyncio
async def test_separate_campaign_apply_is_the_only_new_job_authority(maker,tmp_path,monkeypatch):
    from app.services.generation.resolution import prepare_replacement
    from app.services.generation.administration import apply_campaign
    await failed_script(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job')
        preview=await prepare_replacement(db,job.id,SimpleNamespace(expected_generation=job.generation,
            expected_state=job.state,reason='Prepare review'),'owner')
    async with maker.begin() as db:
        result=await apply_campaign(db,preview['id'],preview['digest'],'owner','Explicit replacement approval')
        assert len(result['jobs'])==1
        assert await db.scalar(select(func.count()).select_from(GenerationOperation))==2
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt))==4
        old=await db.get(GenerationOperation,'job')
        assert old.state=='cancelled' and old.calls==4


@pytest.mark.asyncio
async def test_failed_fresh_input_preview_rolls_back_old_job_cancellation(maker,tmp_path,monkeypatch):
    from app.services.generation.resolution import prepare_replacement
    from app.services.recap_video import workflow
    await failed_script(maker,tmp_path,monkeypatch)
    async def changed(*args,**kwargs):
        raise Held('recap_article_changed')
    monkeypatch.setattr(workflow,'prepare_episode_script',changed)
    with pytest.raises(Held,match='recap_article_changed'):
        async with maker.begin() as db:
            job=await db.get(GenerationOperation,'job')
            await prepare_replacement(db,job.id,SimpleNamespace(expected_generation=job.generation,
                expected_state=job.state,reason='Prepare review'),'owner')
    async with maker() as db:
        assert (await db.get(GenerationOperation,'job')).state=='needs_attention'
        assert await db.scalar(select(func.count()).select_from(GenerationCandidate))==0


@pytest.mark.asyncio
async def test_episode_view_reports_stopped_script_instead_of_running(maker,tmp_path,monkeypatch):
    from app.services.recap_video.admin_actions import episode_view
    ident,_=await failed_script(maker,tmp_path,monkeypatch)
    async with maker() as db:
        view=await episode_view(db,ident)
        assert view['script_operation_id']=='job'
        assert view['script_operation']['state']=='needs_attention'
        assert view['episode']['lifecycle']=='needs_attention'
        assert view['reason']=='execution_failed'
        assert 'prepare_preview' not in view['actions']


@pytest.mark.asyncio
async def test_campaign_apply_rechecks_original_receipt_settlement(maker,tmp_path,monkeypatch):
    from app.services.generation.resolution import prepare_replacement
    from app.services.generation.administration import apply_campaign
    await failed_script(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job')
        preview=await prepare_replacement(db,job.id,SimpleNamespace(expected_generation=job.generation,
            expected_state=job.state,reason='Prepare review'),'owner')
        (await db.get(ProviderAttempt,'saved-1')).usage_state='unknown'
    async with maker.begin() as db:
        with pytest.raises(Held,match='recap_script_previous_receipts_unsettled'):
            await apply_campaign(db,preview['id'],preview['digest'],'owner','Explicit replacement approval')
        assert await db.scalar(select(func.count()).select_from(GenerationOperation))==1


@pytest.mark.asyncio
async def test_expired_replacement_can_reprepare_cancelled_original_and_generic_preview_keeps_price(maker,tmp_path,monkeypatch):
    from app.services.generation.resolution import prepare_replacement,resolution
    from app.services.generation import administration
    from app.services.generation.store import Conflict
    await failed_script(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job')
        first=await prepare_replacement(db,job.id,SimpleNamespace(expected_generation=job.generation,
            expected_state=job.state,reason='Prepare review'),'owner')
    monkeypatch.setattr(administration,'stamp',lambda:first['expires_at']+1)
    async with maker.begin() as db:
        with pytest.raises(Conflict,match='expired'):
            await administration.apply_campaign(db,first['id'],first['digest'],'owner','Old review')
        job=await db.get(GenerationOperation,'job')
        assert (await resolution(db,job))['action']=='replacement'
        again=await prepare_replacement(db,job.id,SimpleNamespace(expected_generation=job.generation,
            expected_state='cancelled',reason='Refresh expired review after free preflight'),'owner')
        assert again['id']!=first['id'] and again['replacement_job_id']=='job'
        assert again['maximum_additional_microusd']==first['maximum_additional_microusd']
        generic=await administration.preview(db,[again['items'][0]['key']],'owner','Fresh generic review')
        assert generic['replacement_job_id']=='job'
        assert generic['replacement_pricing_plan']==again['replacement_pricing_plan']
        assert generic['prior_cost_microusd']==40
        assert await db.scalar(select(func.count()).select_from(GenerationOperation))==1


@pytest.mark.asyncio
async def test_generic_campaign_apply_cannot_drop_replacement_pricing_fence(maker,tmp_path,monkeypatch):
    from app.services.generation.resolution import prepare_replacement
    from app.services.generation.administration import apply_campaign
    from app.services.generation.models import GenerationAudit
    from app.services.generation.store import digest,dump
    await failed_script(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job')
        preview=await prepare_replacement(db,job.id,SimpleNamespace(expected_generation=job.generation,
            expected_state=job.state,reason='Prepare review'),'owner')
        record=await db.get(GenerationAudit,preview['id'])
        manifest=json.loads(record.after_json)
        del manifest['replacement_pricing_plan']
        record.after_json=dump(manifest)
        with pytest.raises(Held,match='recap_script_replacement_price_review_required'):
            await apply_campaign(db,preview['id'],digest(manifest),'owner','Unpriced approval')
        assert await db.scalar(select(func.count()).select_from(GenerationOperation))==1


@pytest.mark.asyncio
async def test_unreviewed_cancelled_original_cannot_reprepare(maker,tmp_path,monkeypatch):
    from app.services.generation.resolution import prepare_replacement
    await failed_script(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job');job.state='cancelled'
        with pytest.raises(Held):
            await prepare_replacement(db,job.id,SimpleNamespace(expected_generation=job.generation,
                expected_state='cancelled',reason='No durable original review'),'owner')


@pytest.mark.asyncio
async def test_prepared_replacement_episode_waits_for_approval(maker,tmp_path,monkeypatch):
    from app.services.generation.resolution import prepare_replacement
    from app.services.recap_video.admin_actions import episode_view
    ident,_=await failed_script(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job')
        await prepare_replacement(db,job.id,SimpleNamespace(expected_generation=job.generation,
            expected_state=job.state,reason='Prepare review'),'owner')
        view=await episode_view(db,ident)
        assert view['script_operation']['state']=='cancelled'
        assert view['episode']['lifecycle']=='awaiting_approval'
        assert view['reason']=='replacement_approval_required'
        assert 'prepare_preview' not in view['actions']
