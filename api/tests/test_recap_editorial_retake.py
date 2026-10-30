"""A reviewed rewrite purchases one new narration, never retries old audio."""
import json

import pytest
from sqlalchemy import select

from app.services.generation.models import ContentArtifact
from app.services.generation.recap_models import RecapStage, RecapProviderAttempt
from app.services.generation.store import Held, digest, dump
from tests.test_recap_pronunciation import seeded


async def ready(maker, tmp_path, monkeypatch):
    episode, original = await seeded(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        for stage in (await db.scalars(select(RecapStage).where(RecapStage.kind == 'narrate'))).all():
            stage.state = 'succeeded'
            db.add(RecapProviderAttempt(stage_id=stage.id, episode_id=episode, series_id='series',
                operation_id=stage.operation_id, provider='elevenlabs', account_key='primary',
                worker_id='synthetic', generation=0, epoch='test-epoch', request_digest='synthetic',
                request_json='{}', pricing_json='{}', authority_digest='synthetic', state='received',
                cost_microusd=100, receipt_json='{"verified":true}'))
        artifact = await db.get(ContentArtifact, original['artifact_id'])
        script = json.loads(artifact.payload_json)['script']
        script['opening'] = 'The whole league shared the spoils.'
        review = dict(reviewer_identity='Independent synthetic review', reviewer_kind='delegated_ai_editorial_reviewer',
            approved=True, script_sha256=digest(script), article_digest=script['article_digest'],
            checks={k:True for k in ('facts','article_agreement','coverage','spoken_numbers','premise_variety')},
            checked_segment_ids=['opening',*[s['id'] for s in script['segments']],'closing'], issues=[])
    return episode, original, script, review


@pytest.mark.asyncio
async def test_retake_creates_one_exact_request_retains_old_receipts_and_is_idempotent(maker,tmp_path,monkeypatch):
    # Mutation: replay old chunks, overwrite the old script, or authorize again on replay.
    from app.services.recap_video import editorial_retake as r, editorial, workflow, elevenlabs
    from app.services.generation.recap_models import RecapBudgetAllocation
    episode, old, script, review = await ready(maker,tmp_path,monkeypatch)
    monkeypatch.setattr(workflow,'MEDIA_PLAN_BUILDER',elevenlabs.build_media_plan)
    async with maker.begin() as db:
        original = await db.get(ContentArtifact,old['artifact_id'])
        before = original.payload_json
        p = await r.preview_retake(db,artifact_id=original.id,script=script,semantic_review=review,
            maximum_microusd=250000,actor_id='owner',reason='Approved shorter recording')
        result = await r.apply_retake(db,preview_id=p['preview_id'],preview_digest=p['digest'],
            actor_id='owner',reason='One recording only')
        assert result['requests']==1 and result['maximum_microusd']<=250000
        assert original.payload_json==before
        artifact=await db.get(ContentArtifact,result['artifact_id'])
        job=await editorial.require_editorial_artifact(db,artifact)
        assert job.calls==job.max_calls==0
        rows=(await db.scalars(select(RecapStage).where(RecapStage.script_id==artifact.id))).all()
        assert len(rows)==4
        narration=next(s for s in rows if s.kind=='narrate')
        assert json.loads(narration.input_json)['paid']['request']['inputs'][0]['text'].startswith(script['opening'])
        allocations=(await db.scalars(select(RecapBudgetAllocation).where(RecapBudgetAllocation.operation_id==narration.id))).all()
        assert len(allocations)==1 and allocations[0].max_microusd==result['maximum_microusd']
        assert await r.apply_retake(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Replay')==result
        assert len((await db.scalars(select(RecapProviderAttempt))).all())==2
        for row in rows: await workflow._current(db,row,now=0)
        changed=json.loads(narration.input_json); changed['paid']['max_microusd']+=1
        narration.input_json=dump(changed); narration.input_digest=digest(changed)
        with pytest.raises(Held,match='retake_request_changed'):
            await workflow._current(db,narration,now=0)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['cap','review','active','uncertain','two_chunks'])
async def test_retake_preview_cannot_expand_authority(maker,tmp_path,monkeypatch,change):
    # Mutation: spend above approval, skip semantic review, or retry uncertain audio.
    from app.services.recap_video import editorial_retake as r
    _,old,script,review=await ready(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        maximum=250000
        if change=='cap': maximum=1
        elif change=='review': review['approved']=False
        elif change=='active': (await db.scalar(select(RecapStage).where(RecapStage.kind=='speech_check'))).state='running'
        elif change=='uncertain': (await db.scalar(select(RecapProviderAttempt))).cost_microusd=None
        else:
            script['opening']='Football. '*190
            script['closing']='Football. '*190
            review['script_sha256']=digest(script)
        with pytest.raises(Held):
            await r.preview_retake(db,artifact_id=old['artifact_id'],script=script,semantic_review=review,
                maximum_microusd=maximum,actor_id='owner',reason='Synthetic retake')


@pytest.mark.asyncio
async def test_retake_apply_rechecks_receipts(maker,tmp_path,monkeypatch):
    # Mutation: stale previews can spend after prior financial evidence changes.
    from app.services.recap_video import editorial_retake as r
    _,old,script,review=await ready(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await r.preview_retake(db,artifact_id=old['artifact_id'],script=script,semantic_review=review,
            maximum_microusd=250000,actor_id='owner',reason='Synthetic retake')
        (await db.scalar(select(RecapProviderAttempt))).receipt_json='{"changed":true}'
        with pytest.raises(Held):
            await r.apply_retake(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')


@pytest.mark.asyncio
async def test_retake_claim_dispatch_once_and_settle_exact_budget(maker,tmp_path,monkeypatch):
    # Mutation: new authority cannot dispatch, can dispatch twice, or loses its budget allocation.
    from app.services.recap_video import editorial_retake as r, workflow, elevenlabs
    from app.services.generation.models import stamp
    from app.services.generation.recap_models import RecapBudgetAllocation
    from tests.test_recap_workflow import fence
    _,old,script,review=await ready(maker,tmp_path,monkeypatch)
    monkeypatch.setattr(workflow,'MEDIA_PLAN_BUILDER',elevenlabs.build_media_plan)
    monkeypatch.setattr(workflow,'RECEIPT_SETTLERS',{'elevenlabs':elevenlabs.settle_receipt})
    async with maker.begin() as db:
        p=await r.preview_retake(db,artifact_id=old['artifact_id'],script=script,semantic_review=review,
            maximum_microusd=250000,actor_id='owner',reason='Approved one request')
        created=await r.apply_retake(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
    async with maker.begin() as db:
        lease=await workflow.claim_stage(db,'retake-worker',{'narrate'},stamp())
        assert lease
        assert (await db.get(RecapStage,lease['stage_id'])).script_id==created['artifact_id']
        auth=await workflow.authorize_dispatch(db,**fence(lease),worker_id='retake-worker')
    async with maker.begin() as db:
        with pytest.raises(Held,match='dispatch_authority_already_issued'):
            await workflow.authorize_dispatch(db,**fence(lease),worker_id='retake-worker')
    async with maker.begin() as db:
        attempt=await db.get(RecapProviderAttempt,auth['attempt_id'])
        request=json.loads(attempt.request_json)
        rate=json.loads(attempt.pricing_json)
        credits=len(request['inputs'][0]['text'])*float(rate['max_credits_per_character'])
        identity={'request_id':'synthetic-retake-request','history_item_id':'synthetic-retake-history'}
        await workflow.persist_identity(db,attempt.id,identity,worker_id='retake-worker')
        receipt=dict(schema='elevenlabs-v1',request_digest=digest(request),status=200,outcome='received',identity=identity,
            metering={'source':'character-cost-header','credits':str(credits)},
            timing={'duration_seconds':1},asset={'asset_id':'synthetic-audio'})
        await workflow.record_receipt(db,attempt.id,receipt,worker_id='retake-worker')
        assert attempt.state=='received' and attempt.cost_microusd==created['maximum_microusd']
        allocation=await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id==attempt.id))
        assert allocation.actual_microusd==attempt.cost_microusd and allocation.outstanding_microusd==0
        assert len((await db.scalars(select(RecapProviderAttempt))).all())==3
