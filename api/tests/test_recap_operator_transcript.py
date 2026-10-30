import copy
import pytest
from tests.test_recap_audio import transcript


def sample():
    script={'segments':[{'id':'s','text':'Jaxon won with a buzz saw.'}]}
    raw=transcript('Jackson won with a buzzsaw.')
    raw['segments']=[dict(text=raw['text'],start=0,end=.72,avg_logprob=-.1,no_speech_prob=0)]
    edits=[dict(start=0,end=1,before='Jackson',after='Jaxon'),dict(start=4,end=5,before='buzzsaw.',after='buzz saw')]
    return script,raw,edits


def test_operator_derivation_keeps_original_and_word_timing():
    # Mutation: overwriting recognizer output or fabricating word timestamps.
    from app.services.recap_video.operator_transcript import derive
    script,raw,edits=sample(); before=copy.deepcopy(raw)
    derived=derive(script,raw,edits,name_tokens={'jaxon'})
    assert raw==before
    assert derived['segments'][0]['end']==1
    assert derived['words'][-1]['word']=='buzz saw'
    assert [(w['start'],w['end'],w['probability']) for w in derived['words']]==[(w['start'],w['end'],w['probability']) for w in raw['words']]


@pytest.mark.parametrize('change',['drift','overlap','result','unresolved','confidence','nan','inf','bool'])
def test_operator_derivation_does_not_waive_other_failures(change):
    # Mutation: release accepts semantic changes, unreliable timing, or unresolved speech.
    from app.services.recap_video.operator_transcript import derive
    script,raw,edits=sample()
    if change=='drift': raw['segments'][0]['end']=-1
    elif change=='overlap':raw['words'][1]['start']=0
    elif change=='result':
        raw['text']=raw['text'].replace('won','lost');raw['words'][1]['word']='lost';raw['segments'][0]['text']=raw['text']
    elif change=='unresolved':edits=[]
    elif change=='confidence':raw['segments'][0]['avg_logprob']=-3
    else:raw['segments'][0]['end']={'nan':float('nan'),'inf':float('inf'),'bool':True}[change]
    with pytest.raises(ValueError):derive(script,raw,edits,name_tokens={'jaxon'})


def test_correction_cannot_replace_another_source_owner():
    from app.services.recap_video.operator_transcript import derive
    raw=transcript('Parker beat Mikey.')
    raw['segments']=[dict(text=raw['text'],start=0,end=.6,avg_logprob=-.1,no_speech_prob=0)]
    with pytest.raises(ValueError,match='publication_spelling_not_bound_to_entity'):
        derive({'segments':[{'text':'Bobby beat Mikey.'}]},raw,[dict(start=0,end=1,before='Parker',after='Bobby')],
            name_tokens={'parker','bobby','mikey'})


@pytest.mark.asyncio
async def test_operator_acceptance_preserves_assets_binds_admin_and_replays_once(maker,monkeypatch):
    # Mutation: replacement overwrites raw ASR, accepts changed assets, or makes a second release on replay.
    import json,hashlib
    from sqlalchemy import select
    from app.services.recap_video import operator_transcript as op, workflow,rendering,elevenlabs,storage,listening
    from app.services.generation.recap_models import RecapStage,RecapAsset,RecapRecovery
    from app.services.generation.store import dump,digest,Held
    from app.services.recap_video.audio import verify_speech
    script,raw,edits=sample();payload=dump(raw).encode();sha=hashlib.sha256(payload).hexdigest()
    async def admin(db,actor):
        if actor!='owner':raise Held('admin_permission_removed')
    async def current(*args,**kwargs):pass
    monkeypatch.setattr(op,'require_admin_actor',admin)
    monkeypatch.setattr(op,'lock_control',current)
    monkeypatch.setattr(workflow,'_current',current)
    objects={'raw':payload}
    class Store:
        def read_range(self,key,start,end):return objects[key][start:end+1]
        def put_verified(self,key,data,checksum):
            assert key not in objects and hashlib.sha256(data).hexdigest()==checksum
            objects[key]=data
    monkeypatch.setattr(storage,'configured_store',Store)
    monkeypatch.setattr(rendering,'configured_store',Store)
    async def validate(db,stage,result):
        asset,data=await rendering.read(db,result['report']['transcript_asset_id'],stage=stage)
        derived=json.loads(data)
        assert verify_speech(script,derived)['passed']
        assert derived['operator_derivation']['source_asset_id']=='raw'
    monkeypatch.setattr(elevenlabs,'validate_speech',validate)
    async with maker.begin() as db:
        result={'asset_ids':['raw'],'report':{'transcript_asset_id':'raw','audio_asset_ids':['audio']}}
        stage=RecapStage(id='speech',episode_id='episode',revision=1,kind='speech_check',script_id='script',operation_id='job',
            input_json=dump({'script':script,'claims':{'owners':[{'name':'Jaxon'}],'claims':[]}}),input_digest='input',policy_digest='policy',generation=2,state='held',result_json=dump(result))
        original=RecapAsset(id='raw',stage_id='speech',generation=1,digest=sha,size=len(payload),media_type='application/json',storage_key='raw')
        audio=RecapAsset(id='audio',stage_id='narration',generation=1,digest='audio-digest',size=10,media_type='audio/mpeg',storage_key='audio')
        db.add_all([stage,original,audio]);await db.flush()
        bound=await listening.binding(db,stage,allow_fenced=True)
        args=dict(stage_id=stage.id,expected_binding_digest=digest(bound),edits=edits,actor_id='owner',reason='Publish supplied recording',approval_evidence='a'*64)
        with pytest.raises(Held,match='admin_permission_removed'):await op.approve(db,**{**args,'actor_id':'worker'})
        audio.digest='changed'
        with pytest.raises(Held,match='publication_recording_changed'):await op.approve(db,**args)
        audio.digest='audio-digest'
        release=await op.approve(db,**args)
        assert stage.state=='succeeded' and original.generation==1 and objects['raw']==payload
        assert await op.approve(db,**args)==release
        with pytest.raises(Held,match='publication_acceptance_changed'):
            await op.approve(db,**{**args,'approval_evidence':'b'*64})
        assert len((await db.scalars(select(RecapRecovery))).all())==1
        assert len(objects)==2 and release['new_provider_calls']==0
        assert (await db.scalar(select(RecapRecovery))).action=='operator_transcript_approved'
        assert json.loads(stage.result_json)['report']['audio_asset_ids']==['audio']
