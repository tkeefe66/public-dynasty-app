import json

import pytest
from sqlalchemy import select, func

from app.services.generation.models import ContentArtifact, GenerationOperation
from app.services.generation.recap_models import RecapStage, RecapProviderAttempt, RecapBudgetAllocation
from app.services.generation.store import Held, digest, dump
from app.services.recap_video import editorial, pronunciation, workflow
from tests.test_recap_editorial import setup, preview

DICTIONARY={'pronunciation_dictionary_id':'synthetic-dictionary','version_id':'synthetic-version',
    'rules':[{'grapheme':'Ago','alphabet':'ipa','phoneme':'ˈæɡoʊ'}]}
EVIDENCE={k:'a'*64 for k in ('dictionary_readback','sample_request','sample_audio','human_listening_review')}
EVIDENCE['dictionary_readback']=digest(DICTIONARY['rules'])


async def seeded(maker,tmp_path,monkeypatch):
    episode,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await preview(db,script,review)
        output=await editorial.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Synthetic editorial review')
    async def plan(db,artifact,evidence):
        from app.services.recap_video.elevenlabs import qualification
        q=await qualification(db,episode)
        paid={'request':{'model_id':'eleven_v4','inputs':[{'voice_id':q['config']['voice_id'],'text':'Ago wins.'}],
            'settings':q['config']['settings']},'rate_snapshot':q['rate_snapshot'],'max_microusd':100000}
        return [dict(kind='narrate',chunk=i,input={'paid':paid}) for i in range(2)]+[
            dict(kind=k,chunk=0,input={'script':script}) for k in ('speech_check','render','media_check')]
    monkeypatch.setattr(workflow,'MEDIA_PLAN_BUILDER',plan)
    async def validate(db,stage,result): return result
    monkeypatch.setattr(workflow,'RESULT_VALIDATORS',{k:validate for k in workflow.MEDIA_KINDS})
    async with maker.begin() as db:
        await workflow.start_media(db,output['artifact_id'])
    return episode,output


@pytest.mark.asyncio
async def test_pronunciation_preview_and_approval_preserve_script_and_exact_two_requests(maker,tmp_path,monkeypatch):
    # Mutation: amendment rewrites canonical text, invents a writer call, or changes original stage inputs.
    episode,output=await seeded(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        original=(await db.get(ContentArtifact,output['artifact_id'])).payload_json
        before={s.id:s.input_json for s in (await db.scalars(select(RecapStage).where(RecapStage.kind=='narrate'))).all()}
        p=await pronunciation.preview_pronunciation(db,episode_id=episode,dictionary=DICTIONARY,actor_id='owner',reason='Fix Ago pronunciation')
        assert len(p['requests'])==2 and p['new_writer_calls']==0
        assert all(r['request']['inputs'][0]['text']=='Ago wins.' for r in p['requests'])
        assert await db.scalar(select(func.count()).select_from(RecapProviderAttempt))==0
        result=await pronunciation.approve_pronunciation(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Reviewed synthetic sample',sample_evidence=EVIDENCE)
        assert result['requests']==2 and result['new_writer_calls']==0
        assert (await db.get(ContentArtifact,output['artifact_id'])).payload_json==original
        assert (await db.get(GenerationOperation,output['operation_id'])).calls==0
        old_envelope=await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.operation_id==output['operation_id'],RecapBudgetAllocation.key=='narration-envelope'))
        assert old_envelope.actual_microusd==0 and old_envelope.outstanding_microusd==0
        allocations=(await db.scalars(select(RecapBudgetAllocation).where(RecapBudgetAllocation.outstanding_microusd>0))).all()
        assert sum(a.outstanding_microusd for a in allocations)==result['maximum_microusd']
        rows=(await db.scalars(select(RecapStage).where(RecapStage.kind=='narrate'))).all()
        for row in rows:
            if row.id in before: assert row.input_json==before[row.id]
            else:
                assert row.script_id==output['artifact_id']
                assert json.loads(row.input_json)['paid']['request']['pronunciation_dictionary_locators'][0]['version_id']=='synthetic-version'
                await workflow._current(db,row,now=0)
                changed=json.loads(row.input_json);changed['paid']['request']['inputs'][0]['text']='Different script'
                row.input_json=dump(changed);row.input_digest=digest(changed)
                with pytest.raises(Held): await workflow._current(db,row,now=0)


@pytest.mark.asyncio
async def test_pronunciation_requires_actual_sample_evidence_before_approval(maker,tmp_path,monkeypatch):
    # Mutation: a free preview silently authorizes narration without a reviewed sample.
    episode,_=await seeded(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await pronunciation.preview_pronunciation(db,episode_id=episode,dictionary=DICTIONARY,actor_id='owner',reason='Fix name')
        with pytest.raises(Held,match='qualification_evidence_required'):
            await pronunciation.approve_pronunciation(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='No sample',sample_evidence={})


@pytest.mark.asyncio
async def test_pronunciation_rebinds_only_same_voice_requalification_and_explicit_authority(maker,tmp_path,monkeypatch):
    # Mutation: calibration renewal invalidates approved correction, or changed voice bypasses editorial authority.
    from app.services.recap_video import elevenlabs
    episode,output=await seeded(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        qualified=await elevenlabs.qualification(db,episode)
        renewed={**qualified,'revision':'renewed-synthetic-qualification'}
        async def qualification(db,episode_id): return renewed
        old_preflight=await workflow.require_media_preflight(db,episode)
        async def preflight(db,episode_id): return {**old_preflight,'qualification_revision':renewed['revision']}
        monkeypatch.setattr(elevenlabs,'QUALIFICATION_READER',qualification)
        monkeypatch.setattr(workflow,'require_media_preflight',preflight)
        artifact=await db.get(ContentArtifact,output['artifact_id'])
        with pytest.raises(Held): await editorial.require_editorial_artifact(db,artifact)
        p=await pronunciation.preview_pronunciation(db,episode_id=episode,dictionary=DICTIONARY,actor_id='owner',reason='Same voice with pronunciation correction')
        await pronunciation.approve_pronunciation(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Reviewed synthetic sample',sample_evidence=EVIDENCE)
        await editorial.require_editorial_artifact(db,artifact)
        from app.services.recap_video.admin_actions import active_stages
        for stage in await active_stages(db,episode): await workflow._current(db,stage,now=0)
        renewed['metadata']={**renewed['metadata'],'changed':True}
        with pytest.raises(Held): await editorial.require_editorial_artifact(db,artifact)


@pytest.mark.asyncio
async def test_pronunciation_preview_refuses_insufficient_existing_cap(maker,tmp_path,monkeypatch):
    # Mutation: free preview offers unaffordable paid replacement or raises episode/global caps itself.
    from app.services.generation.recap_budget import RecapCaps, save_caps
    episode,_=await seeded(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        await save_caps(db,'series',RecapCaps(video_episode_microusd=1),0,'owner','Synthetic tight cap',True)
        with pytest.raises(Held,match='recap_budget_video_episode'):
            await pronunciation.preview_pronunciation(db,episode_id=episode,dictionary=DICTIONARY,actor_id='owner',reason='Fix pronunciation')


@pytest.mark.parametrize('locator',[{}, {'pronunciation_dictionary_id':'synthetic'},
    {'pronunciation_dictionary_id':'synthetic','version_id':''},
    {'pronunciation_dictionary_id':'synthetic','version_id':'v1','extra':True}])
def test_dictionary_version_locator_is_strict(locator):
    # Mutation: a missing mutable dictionary version or unexpected setting reaches paid transport.
    from app.services.recap_video.elevenlabs import validate_request
    from tests.test_recap_elevenlabs import REQUEST,RATE
    with pytest.raises(ValueError): validate_request({**REQUEST,'pronunciation_dictionary_locators':[locator]},RATE,100000)
