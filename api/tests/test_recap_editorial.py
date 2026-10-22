"""Editorial authority cannot erase paid failures or bypass current source gates."""
import json

import pytest
from sqlalchemy import func, select

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationOperation, ProviderAttempt
from app.services.generation.store import Held, digest
from app.services.recap_video import editorial as e
from tests.test_recap_script_replacement import failed_script
from tests.test_recap_video_script import approved_payload


async def setup(maker, tmp_path, monkeypatch):
    ident, saved = await failed_script(maker, tmp_path, monkeypatch)
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EXECUTION_EPOCH', 'test-epoch')
    script = approved_payload(saved)['script']
    script.pop('reviews')
    names={owner['id']:owner['name'] for owner in saved['claims']['owners']}
    for segment in script['segments']:
        segment['text']=' and '.join(names[owner] for owner in segment['owner_ids'])+' tied this matchup.'
    from sleeper_dynasty.llm.recap_video_writer import Script
    script = Script.model_validate(script).model_dump()
    review = dict(reviewer_identity='Independent synthetic editor', reviewer_kind='delegated_ai_editorial_reviewer',
        approved=True, script_sha256=digest(script), article_digest=saved['published_article']['digest'],
        checks={k:True for k in ('facts','article_agreement','coverage','spoken_numbers','premise_variety')},
        checked_segment_ids=['opening',*[s['id'] for s in script['segments']],'closing'], issues=[])
    return ident, script, review


async def preview(db, script, review):
    return await e.preview_editorial(db,operation_id='job',script=script,semantic_review=review,
        actor_id='owner',reason='Reviewed exact saved draft without rewriting')


@pytest.mark.asyncio
async def test_editorial_apply_is_idempotent_preserves_failure_and_reserves_only_narration(maker,tmp_path,monkeypatch):
    from app.services.generation.recap_models import RecapBudgetAllocation, RecapBudgetPlan
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        original=await db.get(GenerationOperation,'job')
        before=(original.state,original.generation,original.payload_json,original.calls)
        p=await preview(db,script,review)
        assert await db.scalar(select(func.count()).select_from(ContentArtifact))==1
        assert await db.scalar(select(func.count()).select_from(RecapBudgetPlan))==0
        result=await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve exact review')
        artifact=await db.get(ContentArtifact,result['artifact_id'])
        assert artifact.provenance=='editorial_reviewed'
        job=await e.require_editorial_artifact(db,artifact)
        assert job.kind=='recap_editorial' and job.calls==job.max_calls==0 and job.active_key is None
        assert (original.state,original.generation,original.payload_json,original.calls)==before
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt))==4
        allocations=(await db.scalars(select(RecapBudgetAllocation).where(RecapBudgetAllocation.operation_id==job.id))).all()
        assert len(allocations)==1 and allocations[0].key=='narration-envelope'
        assert await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Replay')==result
        from app.services.recap_video.speech_reviews import context
        assert (await context(db,artifact))[0].episode_id==json.loads(artifact.payload_json)['episode_id']


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['review_digest','review_coverage','review_checks','script','unsettled','media'])
async def test_editorial_preview_rejects_incomplete_review_or_unsafe_original(maker,tmp_path,monkeypatch,change):
    from app.services.generation.recap_models import RecapStage
    ident,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        if change=='review_digest': review['script_sha256']='stale'
        elif change=='review_coverage': review['checked_segment_ids'].pop()
        elif change=='review_checks': review['checks']['facts']=False
        elif change=='script': script['opening']='Changed after review.'
        elif change=='unsettled': (await db.get(ProviderAttempt,'saved-1')).usage_state='unknown'
        else: db.add(RecapStage(episode_id=ident,kind='narrate',operation_id='job',script_id='other',revision=1,input_json='{}',input_digest='x',policy_digest='x'))
        with pytest.raises(Held): await preview(db,script,review)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['receipt','source','actor','policy','preview_script'])
async def test_editorial_apply_rechecks_preview_fences(maker,tmp_path,monkeypatch,change):
    from app.db.models import User
    from app.services.generation.models import GenerationAudit, GenerationPolicy
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await preview(db,script,review)
        if change=='receipt': (await db.get(ProviderAttempt,'saved-1')).receipt_json='{"changed":true}'
        elif change=='source': (await db.get(GenerationOperation,'job')).payload_json='{}'
        elif change=='actor': (await db.get(User,'owner')).is_admin=False
        elif change=='policy': (await db.get(GenerationPolicy,'app')).revision+=1
        else:
            row=await db.get(GenerationAudit,p['preview_id'])
            value=json.loads(row.after_json); value['script']['opening']='Mutated'; row.after_json=json.dumps(value)
        with pytest.raises(Held):
            await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
        assert await db.scalar(select(func.count()).select_from(ContentArtifact))==1


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['artifact','receipt','actor','proof'])
async def test_editorial_media_authority_rechecks_immutable_proof(maker,tmp_path,monkeypatch,change):
    from app.db.models import User
    from app.services.generation.models import GenerationAudit
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await preview(db,script,review)
        result=await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
        artifact=await db.get(ContentArtifact,result['artifact_id'])
        if change=='artifact': artifact.digest='changed'
        elif change=='receipt': (await db.get(ProviderAttempt,'saved-1')).cost_microusd+=1
        elif change=='actor': (await db.get(User,'owner')).is_admin=False
        else: (await db.get(GenerationAudit,json.loads(artifact.payload_json)['editorial_authority_id'])).after_json='{}'
        with pytest.raises(Held): await e.require_editorial_artifact(db,artifact)


@pytest.mark.asyncio
async def test_editorial_preserves_omitted_optional_fields_and_rebinds_only_free_preflight(maker,tmp_path,monkeypatch):
    from app.services.recap_video import workflow
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    script['premises']=[dict(premise='Everyone tied again.',punchline='Nobody escaped.',owner_ids=[])]
    review['script_sha256']=digest(script)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,'job')
        old=json.loads(job.payload_json)
        original=job.payload_json
        evidence=await workflow.require_media_preflight(db,old['episode_id'])
        evidence['qualification_revision']='renewed-free-proof'
        # Envelope qualification must remain consistent with the fresh free proof.
        from app.services.recap_video import elevenlabs
        reader=elevenlabs.QUALIFICATION_READER
        approval=await reader(db,old['episode_id'])
        approval['revision']='renewed-free-proof'
        async def fresh(db,episode_id): return evidence
        monkeypatch.setattr(workflow,'require_media_preflight',fresh)
        p=await preview(db,script,review)
        result=await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
        artifact=await db.get(ContentArtifact,result['artifact_id'])
        new=await db.get(GenerationOperation,result['operation_id'])
        assert job.payload_json==original
        assert json.loads(new.payload_json)=={**old,'media_qualification_digest':digest(evidence)}
        assert 'callback_reason' not in json.loads(artifact.payload_json)['script']['premises'][0]
        await e.require_editorial_artifact(db,artifact)


@pytest.mark.asyncio
async def test_editorial_media_stage_requires_exact_proof_and_current_policy(maker,tmp_path,monkeypatch):
    from app.services.recap_video import workflow
    from app.services.generation.recap_models import RecapStage
    from app.services.generation.models import GenerationPolicy
    from app.services.generation.store import dump, resolve_policy
    ident,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await preview(db,script,review)
        result=await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
        artifact=await db.get(ContentArtifact,result['artifact_id'])
        job=await db.get(GenerationOperation,result['operation_id'])
        policy=await resolve_policy(db,job.series_id)
        evidence=await workflow.require_media_preflight(db,ident)
        stage=RecapStage(episode_id=ident,revision=artifact.revision,kind='narrate',script_id=artifact.id,
            operation_id=job.id,epoch=job.epoch,input_json='{}',input_digest=digest({}),
            policy_digest=digest([policy['policy']['features']['recap_video'],policy['revisions'],evidence]))
        db.add(stage)
        await db.flush()
        assert (await workflow._current(db,stage,now=0))[0].episode_id==ident
        (await db.get(GenerationPolicy,'app')).revision+=1
        with pytest.raises(Held,match='recap_editorial_execution_changed'):
            await workflow._current(db,stage,now=0)


@pytest.mark.asyncio
async def test_editorial_expired_preview_cannot_create_authority(maker,tmp_path,monkeypatch):
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await preview(db,script,review)
        monkeypatch.setattr(e,'stamp',lambda:p['expires_at'])
        with pytest.raises(Held,match='recap_editorial_preview_expired'):
            await e.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
        assert await db.scalar(select(func.count()).select_from(GenerationOperation))==1


@pytest.mark.asyncio
async def test_editorial_source_reports_missing_saved_draft_explicitly(maker,tmp_path,monkeypatch):
    await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        with pytest.raises(Held,match='recap_editorial_saved_script_missing'):
            await e.get_editorial_source(db,operation_id='job',actor_id='owner')


@pytest.mark.asyncio
async def test_editorial_preview_rejects_missing_visual_result_anchor_before_approval(maker,tmp_path,monkeypatch):
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    script['segments'][0]['text']=script['segments'][0]['text'].replace('tied this matchup','discussed this matchup')
    review['script_sha256']=digest(script)
    from app.services.generation.models import GenerationAudit
    async with maker.begin() as db:
        with pytest.raises(Held,match='recap_editorial_review_invalid'):
            await preview(db,script,review)
        assert await db.scalar(select(GenerationAudit.id).where(GenerationAudit.action=='recap_editorial_preview')) is None
