import copy
import pytest
from tests.test_recap_audio import transcript
from media.reviewed_speech import review_digest, review_speech


def fixture():
    script={'segments':[{'id':'s','text':'Jaxon won by fourteen points.', 'spoken_numbers':[{'spoken':'fourteen'}]}]}
    raw=transcript('Jackson won by fourteen points.')
    raw['words'][3]['probability']=.6
    review={'version':'human-listening-v1','script_digest':review_digest(script),'transcript_digest':review_digest(raw),
        'edits':[{'start':0,'end':1,'before':'Jackson','after':'Jaxon'}],
        'listening_evidence':'a'*64,'approved_issues':['content_mismatch','speech_confidence_low']}
    return script,raw,review


def test_review_preserves_original_audio_evidence_and_word_timing():
    # Mutation: reviewed spelling is ignored or overwrites original ASR confidence/timing.
    script,raw,review=fixture(); original=copy.deepcopy(raw)
    result=review_speech(script,raw,review=review)
    assert result['passed'] and result['verifier_revision']=='human-listening-v1'
    assert raw==original
    assert result['timeline_transcript']['words'][0]['word']=='Jaxon'
    assert result['timeline_transcript']['words'][3]['probability']==.6
    assert result['timeline_transcript']['words'][0]['start']==raw['words'][0]['start']
    assert not review_speech(script,raw)['passed']


@pytest.mark.parametrize('change',['script','transcript','evidence','number','result'])
def test_review_cannot_transfer_or_waive_semantic_errors(change):
    # Mutation: an old listening approval or a critical semantic mismatch can pass.
    script,raw,review=fixture()
    if change=='script': script['segments'][0]['text']='Jaxon lost by fourteen points.'
    if change=='transcript': raw['words'][0]['end']+=.01
    if change=='evidence': review['listening_evidence']=''
    if change in ('number','result'):
        raw=transcript('Jackson '+('lost' if change=='result' else 'won')+' by '+('forty' if change=='number' else 'fourteen')+' points.')
        review['transcript_digest']=review_digest(raw)
    with pytest.raises(ValueError): review_speech(script,raw,review=review)


def test_multiword_review_retains_outer_timestamps_and_requires_complete_alignment():
    # Mutation: merging word spans invents times or permits omitted content.
    script={'segments':[{'id':'s','text':'Smith Njigba won.'}]};raw=transcript('Smith and Jigba won.')
    review={'version':'human-listening-v1','script_digest':review_digest(script),'transcript_digest':review_digest(raw),
        'edits':[{'start':1,'end':3,'before':'and Jigba','after':'Njigba'}],
        'listening_evidence':'b'*64,'approved_issues':['content_mismatch']}
    result=review_speech(script,raw,review=review)
    assert result['passed']
    assert result['timeline_transcript']['words'][1]['start']==raw['words'][1]['start']
    assert result['timeline_transcript']['words'][1]['end']==raw['words'][2]['end']
    review['edits'][0]['after']=''
    with pytest.raises(ValueError): review_speech(script,raw,review=review)


@pytest.mark.asyncio
async def test_api_review_is_bound_to_assets_input_and_admin(maker,monkeypatch):
    # Mutation: worker-embedded review or changed audio acquires listening authority.
    from app.services.recap_video import listening
    from app.services.generation.recap_models import RecapStage,RecapAsset,RecapRecovery
    from app.services.generation.store import dump,Held,digest
    async def admin(db,actor):
        if actor!='owner': raise Held('admin_permission_removed')
    monkeypatch.setattr(listening,'require_admin_actor',admin)
    async with maker.begin() as db:
        stage=RecapStage(id='speech',episode_id='episode',revision=1,kind='speech_check',script_id='script',operation_id='job',
            input_json='{}',input_digest='input',policy_digest='policy',generation=1,result_json=dump({'report':{'transcript_asset_id':'raw','audio_asset_ids':['audio']}}))
        db.add(stage)
        for ident in ('raw','audio'):
            db.add(RecapAsset(id=ident,stage_id='speech' if ident=='raw' else 'narration',generation=1,digest=ident,size=10,media_type='application/json',storage_key=ident))
        await db.flush()
        assert await listening.approved_review(db,stage) is None
        proof=RecapRecovery(episode_id='episode',stage_id='speech',action='human_listening_approved',actor_id='owner',reason='Heard exact saved recording',
            before_json=dump({'binding':await listening.binding(db,stage),'review':{'exact':'review'}}))
        db.add(proof);await db.flush()
        stage.evidence_json=dump({'listening_review_digest':digest({'exact':'review'})})
        assert await listening.approved_review(db,stage)=={'exact':'review'}
        asset=await db.get(RecapAsset,'audio');asset.digest='different'
        with pytest.raises(Held,match='listening_recording_changed'): await listening.approved_review(db,stage)
        asset.digest='audio';proof.actor_id='worker'
        with pytest.raises(Held,match='admin_permission_removed'): await listening.approved_review(db,stage)
