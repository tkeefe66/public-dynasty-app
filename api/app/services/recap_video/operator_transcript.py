"""Explicit publication acceptance of a derived transcript, never a listening claim.

Original ASR, audio, and provider receipts remain immutable. Only an administrator
can admit an exact corrected caption transcript; default speech checks still pass.
"""
import asyncio
import copy
import hashlib
import json
import math
import re
import uuid
from difflib import SequenceMatcher

from sqlalchemy import select

from app.services.generation.recap_models import RecapAsset, RecapRecovery, RecapStage
from app.services.generation.store import Held, digest, dump, lock_control
from app.services.generation.models import stamp
from app.services.recap_video.qualification import require_admin_actor


def derive(script, raw, edits, *, name_tokens=()):
    from app.services.recap_video.audio import verify_speech, _tokens, word_text
    original=verify_speech(script,raw)
    if set(original['issues'])-{'content_mismatch','speech_evidence_invalid'}:
        raise ValueError('publication_semantic_or_confidence_failure')
    result=copy.deepcopy(raw);words=result['words'];ownership=[];consumed=0
    for index,segment in enumerate(result.get('segments',[])):
        matches=[last+1 for last in range(consumed,len(words))
            if _tokens(word_text(words[consumed:last+1]))==_tokens(segment['text'])]
        if len(matches)!=1:raise ValueError('publication_segment_ambiguous')
        end=matches[0];group=words[consumed:end]
        for key,value in (('start',group[0]['start']),('end',group[-1]['end'])):
            if type(segment[key]) not in (int,float) or not math.isfinite(segment[key]):
                raise ValueError('publication_segment_invalid')
            if abs(segment[key]-value)>.5:raise ValueError('publication_segment_drift')
            segment[key]=value
        ownership.extend([index]*(end-consumed));consumed=end
    if consumed!=len(words):raise ValueError('publication_segment_incomplete')
    repaired=verify_speech(script,result)
    if set(repaired['issues'])-{'content_mismatch'}:raise ValueError('publication_word_evidence_invalid')
    if not isinstance(edits,list) or len(edits)>16:raise ValueError('publication_edits_invalid')
    previous=0
    for edit in edits:
        if set(edit)!={'start','end','before','after'}:raise ValueError('publication_edit_invalid')
        start,end=edit['start'],edit['end']
        if (type(start)!=int or type(end)!=int or start<previous or not start<end<=len(words)
                or end-start>4 or not isinstance(edit['after'],str)
                or not re.fullmatch(r'[A-Za-z]+(?:[-’\x27 ][A-Za-z]+)*',edit['after'])
                or word_text(words[start:end]).strip()!=edit['before']
                or len(set(ownership[start:end]))!=1):raise ValueError('publication_edit_invalid')
        previous=end
        before_tokens=_tokens(edit['before']);after_tokens=_tokens(edit['after'])
        whitespace_only=''.join(before_tokens)==''.join(after_tokens)
        if not whitespace_only and (end-start!=1 or len(before_tokens)!=1 or len(after_tokens)!=1
                or after_tokens[0] not in name_tokens or before_tokens[0] in name_tokens
                or SequenceMatcher(None,before_tokens[0],after_tokens[0]).ratio()<.5):
            raise ValueError('publication_spelling_not_bound_to_entity')
    for edit in reversed(edits):
        start,end=edit['start'],edit['end'];group=words[start:end]
        words[start:end]=[{**group[0],'word':(' ' if group[0]['word'][:1].isspace() else '')+edit['after'],'end':group[-1]['end'],
            'probability':min(w['probability'] for w in group)}]
        ownership[start:end]=[ownership[start]]
    result['text']=word_text(words)
    for index,segment in enumerate(result['segments']):
        segment['text']=word_text([w for w,owner in zip(words,ownership,strict=True) if owner==index])
    if not verify_speech(script,result)['passed']:raise ValueError('publication_transcript_unresolved')
    return result


async def approve(db, *, stage_id, expected_binding_digest, edits, actor_id, reason, approval_evidence):
    from app.services.recap_video.listening import binding
    from app.services.recap_video.workflow import _current
    from app.services.recap_video.rendering import read
    from app.services.recap_video.elevenlabs import validate_speech
    from app.services.recap_video.storage import configured_store
    await require_admin_actor(db,actor_id)
    if not reason.strip() or not re.fullmatch('[a-f0-9]{64}',approval_evidence):
        raise Held('publication_acceptance_required')
    await lock_control(db)
    stage=await db.get(RecapStage,stage_id)
    if not stage or stage.kind!='speech_check':raise Held('publication_speech_stage_required')
    prior=await db.scalar(select(RecapRecovery).where(RecapRecovery.stage_id==stage_id,
        RecapRecovery.action=='operator_transcript_approved'))
    if prior:
        proof=json.loads(prior.before_json)
        if (proof['binding_digest']!=expected_binding_digest or proof['edits']!=edits
                or prior.actor_id!=actor_id or proof['approval_evidence']!=approval_evidence):
            raise Held('publication_acceptance_changed')
        return dict(review_id=prior.id,stage_id=stage_id,new_provider_calls=0)
    if stage.state!='held':raise Held('publication_held_speech_required')
    await _current(db,stage,now=stamp())
    bound=await binding(db,stage,allow_fenced=True)
    if digest(bound)!=expected_binding_digest:raise Held('publication_recording_changed')
    _,data=await read(db,bound['transcript'][0])
    raw=json.loads(data);inputs=json.loads(stage.input_json)
    from app.services.recap_video.audio import _tokens
    names=[o['name'] for o in inputs['claims']['owners']]
    names.extend(o['name'] for c in inputs['claims']['claims'] for o in c.get('operands',[]) if o.get('name'))
    name_tokens={token for name in names for token in _tokens(name)}
    try:derived=derive(inputs['script'],raw,edits,name_tokens=name_tokens)
    except ValueError as exc:raise Held(str(exc)) from None
    original_result=json.loads(stage.result_json);original_evidence=json.loads(stage.evidence_json)
    proof=dict(binding=bound,binding_digest=expected_binding_digest,edits=edits,
        approval_evidence=approval_evidence,original_result=original_result,original_evidence=original_evidence)
    review=RecapRecovery(episode_id=stage.episode_id,stage_id=stage.id,action='operator_transcript_approved',
        actor_id=actor_id,reason=reason,before_json=dump(proof))
    db.add(review);await db.flush()
    derived['operator_derivation']=dict(review_id=review.id,source_asset_id=bound['transcript'][0],
        source_digest=bound['transcript'][1],kind='publication-acceptance-v1')
    encoded=dump(derived).encode();checksum=hashlib.sha256(encoded).hexdigest();key=str(uuid.uuid4())
    await asyncio.to_thread(configured_store().put_verified,key,encoded,checksum)
    asset=RecapAsset(stage_id=stage.id,generation=stage.generation,digest=checksum,size=len(encoded),
        media_type='application/json',storage_key=key)
    db.add(asset);await db.flush()
    result=copy.deepcopy(original_result);result['asset_ids']=[asset.id]
    result['report']['transcript_asset_id']=asset.id
    await validate_speech(db,stage,result)
    result['status']='ok';result['report']['issues']=[]
    stage.result_json=dump(result);stage.state='succeeded';stage.reason='';stage.lease_until=0
    evidence=json.loads(stage.evidence_json);evidence['operator_derivation']=derived['operator_derivation']
    stage.evidence_json=dump(evidence)
    return dict(review_id=review.id,stage_id=stage.id,new_provider_calls=0)
