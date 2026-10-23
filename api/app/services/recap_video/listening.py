"""Administrator-only adjudication of exact saved speech evidence; never TTS."""
import asyncio
import json
import uuid
from sqlalchemy import select
from app.services.generation.models import stamp
from app.services.generation.recap_models import RecapAsset,RecapRecovery,RecapStage
from app.services.generation.store import Held,digest,dump,lock_control
from app.services.recap_video.qualification import require_admin_actor


async def binding(db,stage,*,allow_fenced=False):
    result=json.loads(stage.result_json)
    identity=result['report']['transcript_asset_id']
    asset=await db.get(RecapAsset,identity)
    allowed={stage.generation}
    if allow_fenced and stage.state=='held': allowed.add(stage.generation-1)
    if not asset or asset.stage_id!=stage.id or asset.generation not in allowed:
        raise Held('listening_transcript_changed')
    audio=[]
    for ident in result['report']['audio_asset_ids']:
        item=await db.get(RecapAsset,ident)
        if not item: raise Held('listening_audio_missing')
        audio.append([item.id,item.digest,item.size,item.stage_id,item.generation])
    return dict(stage_id=stage.id,generation=stage.generation,input_digest=stage.input_digest,
        script_id=stage.script_id,transcript=[asset.id,asset.digest,asset.size],audio=audio)


async def approved_review(db,stage):
    rows=(await db.scalars(select(RecapRecovery).where(RecapRecovery.stage_id==stage.id,
        RecapRecovery.action=='human_listening_approved'))).all()
    if not rows: return None
    if len(rows)!=1: raise Held('listening_review_ambiguous')
    row=rows[0];await require_admin_actor(db,row.actor_id)
    proof=json.loads(row.before_json)
    if proof['binding']!=await binding(db,stage): raise Held('listening_recording_changed')
    evidence=json.loads(stage.evidence_json)
    if evidence.get('listening_review_digest') and evidence['listening_review_digest']!=digest(proof['review']):
        raise Held('listening_review_changed')
    return proof['review']


async def approve_listening(db,*,stage_id,expected_binding_digest,review,actor_id,reason):
    from app.services.recap_video.workflow import _current
    from app.services.recap_video.elevenlabs import validate_speech
    from app.services.recap_video.rendering import read
    from media.reviewed_speech import review_speech
    await require_admin_actor(db,actor_id)
    stage=await db.get(RecapStage,stage_id)
    if not stage or stage.kind!='speech_check' or stage.state!='held' or not reason.strip():
        raise Held('listening_held_speech_required')
    current=await binding(db,stage,allow_fenced=True)
    if digest(current)!=expected_binding_digest: raise Held('listening_recording_changed')
    asset,data=await read(db,current['transcript'][0])
    inputs=json.loads(stage.input_json)
    try: review_speech(inputs['script'],json.loads(data),aliases=inputs['speech_review']['aliases'],review=review)
    except ValueError as exc: raise Held(str(exc)) from None
    await lock_control(db)
    await _current(db,stage,now=stamp())
    if current!=await binding(db,stage,allow_fenced=True) or stage.state!='held': raise Held('listening_recording_changed')
    if await approved_review(db,stage) is not None: raise Held('listening_already_reviewed')
    original_result=json.loads(stage.result_json)
    original_evidence=json.loads(stage.evidence_json)
    if asset.generation!=stage.generation:
        from app.services.recap_video.storage import configured_store
        identity=str(uuid.uuid4());key=str(uuid.uuid4())
        await asyncio.to_thread(configured_store().put_verified,key,data,asset.digest)
        adopted=RecapAsset(id=identity,stage_id=stage.id,generation=stage.generation,
            digest=asset.digest,size=asset.size,media_type=asset.media_type,storage_key=key)
        db.add(adopted);await db.flush()
        result=json.loads(stage.result_json)
        result['asset_ids']=[identity];result['report']['transcript_asset_id']=identity
        stage.result_json=dump(result)
    row=RecapRecovery(episode_id=stage.episode_id,stage_id=stage.id,action='human_listening_approved',
        actor_id=actor_id,reason=reason,before_json=dump(dict(binding=await binding(db,stage),review=review,
            original_binding=current,original_result=original_result,original_evidence=original_evidence)))
    db.add(row);await db.flush()
    result=json.loads(stage.result_json)
    await validate_speech(db,stage,result)
    result['status']='ok';result['report']['issues']=[]
    stage.result_json=dump(result);stage.state='succeeded';stage.reason='';stage.lease_until=0
    return dict(review_id=row.id,stage_id=stage.id,state=stage.state,new_provider_calls=0)
