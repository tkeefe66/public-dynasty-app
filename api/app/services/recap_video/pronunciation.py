"""Explicit narration-only amendments; canonical editorial text never changes."""
import json
from datetime import UTC

from sqlalchemy import select

from app.services.generation.models import ContentArtifact, GenerationAudit, stamp
from app.services.generation.recap_models import RecapStage, RecapRecovery, RecapProviderAttempt, RecapBudgetPolicy, RecapBudgetAllocation
from app.services.generation.store import Held, Conflict, digest, dump, lock_control, resolve_policy
from app.services.recap_video.qualification import require_admin_actor, evidence_hashes


def dictionary_binding(dictionary):
    if (not isinstance(dictionary,dict) or set(dictionary)!={'pronunciation_dictionary_id','version_id','rules'}
            or not isinstance(dictionary['rules'],list) or not 1<=len(dictionary['rules'])<=64):
        raise Held('pronunciation_dictionary_invalid')
    from app.services.recap_video.elevenlabs import identifier
    for key in ('pronunciation_dictionary_id','version_id'):
        identifier(dictionary[key])
    seen=set()
    for rule in dictionary['rules']:
        if (not isinstance(rule,dict) or set(rule)!={'grapheme','alphabet','phoneme'} or rule['alphabet']!='ipa'
                or any(not isinstance(rule[k],str) or not 0<len(rule[k])<=200 for k in ('grapheme','phoneme'))
                or rule['grapheme'] in seen):
            raise Held('pronunciation_dictionary_invalid')
        seen.add(rule['grapheme'])
    return dict(dictionary=dictionary,content_digest=digest(dictionary['rules']))


async def _continuity(db,artifact):
    """Only current requalification of the same account/voice/settings/rate."""
    from app.services.recap_video.elevenlabs import qualification
    from app.services.recap_video.workflow import require_media_preflight
    payload=json.loads(artifact.payload_json)
    authority=await db.get(GenerationAudit,payload['editorial_authority_id'])
    proof=json.loads(authority.after_json)
    preview=await db.get(GenerationAudit,proof['preview_id'])
    old=json.loads(preview.after_json)['budget']['rate_snapshot']['qualification']
    current=await qualification(db,payload['episode_id'])
    if any(old[key]!=current[key] for key in ('config','metadata','rate_snapshot')):
        raise Held('pronunciation_base_voice_changed')
    evidence=await require_media_preflight(db,payload['episode_id'])
    return dict(qualification=current,preflight=evidence)


async def preview_pronunciation(db,*,episode_id,dictionary,actor_id,reason):
    await require_admin_actor(db,actor_id)
    await lock_control(db)
    if not reason.strip(): raise Held('pronunciation_reason_required')
    binding=dictionary_binding(dictionary)
    from app.services.recap_video.admin_actions import active_stages
    from app.services.recap_video.editorial import require_editorial_artifact
    from app.services.recap_video.elevenlabs import validate_request
    rows=await active_stages(db,episode_id)
    paid=sorted((r for r in rows if r.kind=='narrate'),key=lambda r:r.chunk)
    if not paid or any(r.state=='running' for r in rows):
        raise Held('pronunciation_stop_active_media_first')
    artifact=await db.get(ContentArtifact,paid[0].script_id)
    await require_editorial_artifact(db,artifact,require_preflight=False)
    continuity=await _continuity(db,artifact)
    attempts=(await db.scalars(select(RecapProviderAttempt).where(RecapProviderAttempt.episode_id==episode_id))).all()
    if any(a.state!='received' or a.cost_microusd is None for a in attempts):
        raise Held('pronunciation_original_requests_unsettled')
    locator={k:dictionary[k] for k in ('pronunciation_dictionary_id','version_id')}
    requests=[]
    for row in paid:
        old=json.loads(row.input_json)['paid']
        request={**old['request'],'pronunciation_dictionary_locators':[locator]}
        maximum=validate_request(request,old['rate_snapshot'],old['max_microusd'])
        requests.append(dict(stage_id=row.id,request=request,rate_snapshot=old['rate_snapshot'],max_microusd=maximum))
    from app.services.generation import recap_budget as budget
    budget_rows=await budget._obligations(db)
    await budget.require_episode_budget(db,episode_id,artifact.series_id,stamp())
    caps=await db.get(RecapBudgetPolicy,artifact.series_id)
    proposed=budget_rows+[dict(series=artifact.series_id,episode=episode_id,category='video',known=0,
        reserved=sum(r['max_microusd'] for r in requests),month=budget.month_key(stamp()),app_month=budget.month_key(stamp(),UTC),
        unknown=False,outcome_unknown=False,unbounded=False)]
    budget._check_balances(proposed,artifact.series_id,episode_id,budget._caps(caps),stamp())
    await budget._check_app(db,proposed,stamp())
    manifest=dict(episode_id=episode_id,script_id=artifact.id,script_digest=artifact.digest,
        execution_revision=paid[0].execution_revision+1,source_stages=[[r.id,r.generation,r.state,r.input_digest] for r in rows],
        dictionary=binding,continuity=continuity,requests=requests,maximum_microusd=sum(r['max_microusd'] for r in requests),
        prior_cost_microusd=sum(a.cost_microusd for a in attempts),new_writer_calls=0,
        expires_at=stamp()+900)
    row=GenerationAudit(actor_id=actor_id,action='recap_pronunciation_preview',target=episode_id,reason=reason,after_json=dump(manifest))
    db.add(row);await db.flush()
    return dict(preview_id=row.id,digest=digest(manifest),**manifest)


async def approve_pronunciation(db,*,preview_id,preview_digest,actor_id,reason,sample_evidence):
    await require_admin_actor(db,actor_id);await lock_control(db)
    evidence_hashes(sample_evidence,('dictionary_readback','sample_request','sample_audio','human_listening_review'))
    row=await db.get(GenerationAudit,preview_id)
    if not row or row.action!='recap_pronunciation_preview' or row.actor_id!=actor_id or not reason.strip():
        raise Held('pronunciation_preview_invalid')
    manifest=json.loads(row.after_json)
    if digest(manifest)!=preview_digest or manifest['expires_at']<=stamp():
        raise Conflict('Pronunciation preview changed or expired. Prepare a fresh preview.')
    if sample_evidence['dictionary_readback']!=manifest['dictionary']['content_digest']:
        raise Held('pronunciation_dictionary_readback_changed')
    from app.services.recap_video.admin_actions import active_stages
    from app.services.recap_video.editorial import require_editorial_artifact
    artifact=await db.get(ContentArtifact,manifest['script_id'])
    await require_editorial_artifact(db,artifact,require_preflight=False)
    old=await active_stages(db,row.target)
    if (artifact.digest!=manifest['script_digest'] or await _continuity(db,artifact)!=manifest['continuity']
            or [[r.id,r.generation,r.state,r.input_digest] for r in old]!=manifest['source_stages']):
        raise Held('pronunciation_preview_changed')
    attempts=(await db.scalars(select(RecapProviderAttempt).where(RecapProviderAttempt.episode_id==row.target))).all()
    if any(a.state!='received' or a.cost_microusd is None for a in attempts):
        raise Held('pronunciation_original_requests_unsettled')
    policy=await resolve_policy(db,artifact.series_id)
    pd=digest([policy['policy']['features']['recap_video'],policy['revisions'],manifest['continuity']['preflight']])
    proof=GenerationAudit(actor_id=actor_id,action='recap_pronunciation_approved',target=row.target,reason=reason,
        after_json=dump(dict(preview_id=preview_id,preview_digest=preview_digest,sample_evidence=sample_evidence)))
    db.add(proof);await db.flush()
    order={'narrate':0,'speech_check':1,'render':2,'media_check':3};old.sort(key=lambda r:(order[r.kind],r.chunk))
    requests={r['stage_id']:r for r in manifest['requests']};previous='';allocations=[]
    for source in old:
        inputs=json.loads(source.input_json)
        if source.kind=='narrate':
            item=requests[source.id];inputs['paid']={k:item[k] for k in ('request','rate_snapshot','max_microusd')}
        fresh=RecapStage(episode_id=row.target,revision=source.revision,execution_revision=manifest['execution_revision'],
            kind=source.kind,chunk=source.chunk,script_id=source.script_id,operation_id=source.operation_id,
            predecessor_id=previous,input_json=dump(inputs),input_digest=digest(inputs),policy_digest=pd,epoch=source.epoch)
        db.add(fresh);await db.flush();previous=fresh.id
        db.add(RecapRecovery(episode_id=row.target,stage_id=fresh.id,action='pronunciation_amendment_authority',
            actor_id=actor_id,reason=reason,before_json=dump(dict(approval_id=proof.id,source_stage_id=source.id,input_digest=fresh.input_digest))))
        if fresh.kind=='narrate':
            allocations.append(dict(key=fresh.id,category='video',operation_id=fresh.id,max_microusd=inputs['paid']['max_microusd'],rate_snapshot=inputs['paid']['rate_snapshot']))
            db.add(RecapRecovery(episode_id=row.target,stage_id=fresh.id,action='bounded_replacement_authority',actor_id=actor_id,
                reason=reason,before_json=dump(dict(input_digest=fresh.input_digest,script_id=artifact.id,execution_revision=fresh.execution_revision,
                    dispositioned=[],maximum_microusd=manifest['maximum_microusd'],evidence='Explicit pronunciation correction; original requests retained'))))
        if source.state!='succeeded':
            source.state='cancelled';source.reason='pronunciation_replaced';source.generation+=1;source.lease_until=0
    from app.services.generation.recap_budget import _reserve, release_unsubmitted, settle_allocation
    for source in old:
        if source.state=='cancelled' and source.reason=='pronunciation_replaced':
            await release_unsubmitted(db,source.id,'pronunciation_replaced')
    # Initial narration may still own an unbound envelope rather than chunk
    # allocations. Every old checkpoint has now been replaced; only never-bound
    # exposure may move into the new exact reservation.
    envelopes=(await db.scalars(select(RecapBudgetAllocation).where(
        RecapBudgetAllocation.operation_id==artifact.operation_id,RecapBudgetAllocation.key=='narration-envelope',
        RecapBudgetAllocation.attempt_id.is_(None),RecapBudgetAllocation.actual_microusd.is_(None)))).all()
    for envelope in envelopes:
        await settle_allocation(db,envelope.id,0,dict(non_submission='pronunciation_replaced',approval_id=proof.id))
    await _reserve(db,row.target,artifact.series_id,'media:'+artifact.id+':'+str(manifest['execution_revision']),allocations,stamp())
    await db.flush()
    return dict(approval_id=proof.id,requests=len(requests),maximum_microusd=manifest['maximum_microusd'],new_writer_calls=0)


async def require_pronunciation_stage(db,stage):
    authority=await db.scalar(select(RecapRecovery).where(RecapRecovery.stage_id==stage.id,RecapRecovery.action=='pronunciation_amendment_authority'))
    locators=json.loads(stage.input_json).get('paid',{}).get('request',{}).get('pronunciation_dictionary_locators')
    if not authority:
        if locators: raise Held('pronunciation_authority_required')
        return None
    value=json.loads(authority.before_json)
    approval=await db.get(GenerationAudit,value['approval_id'])
    if not approval or approval.action!='recap_pronunciation_approved' or approval.target!=stage.episode_id:
        raise Held('pronunciation_authority_changed')
    approved=json.loads(approval.after_json);preview=await db.get(GenerationAudit,approved['preview_id'])
    evidence_hashes(approved.get('sample_evidence'),('dictionary_readback','sample_request','sample_audio','human_listening_review'))
    manifest=json.loads(preview.after_json)
    await require_admin_actor(db,approval.actor_id)
    artifact=await db.get(ContentArtifact,stage.script_id)
    source=await db.get(RecapStage,value['source_stage_id'])
    expected=json.loads(source.input_json)
    if stage.kind=='narrate':
        request=next((r for r in manifest['requests'] if r['stage_id']==source.id),None)
        if not request: raise Held('pronunciation_authority_changed')
        expected['paid']={k:request[k] for k in ('request','rate_snapshot','max_microusd')}
    if (preview.action!='recap_pronunciation_preview' or preview.actor_id!=approval.actor_id
            or digest(manifest)!=approved['preview_digest'] or manifest['script_id']!=stage.script_id
            or approved['sample_evidence']['dictionary_readback']!=manifest['dictionary']['content_digest']
            or manifest['script_digest']!=artifact.digest or manifest['execution_revision']!=stage.execution_revision
            or value['input_digest']!=stage.input_digest or digest(expected)!=stage.input_digest):
        raise Held('pronunciation_authority_changed')
    current=await _continuity(db,artifact)
    if current!=manifest['continuity']:
        renewals=(await db.scalars(select(RecapRecovery).where(RecapRecovery.stage_id==stage.id,
            RecapRecovery.action=='pronunciation_free_requalified').order_by(RecapRecovery.created_at.desc(),RecapRecovery.id.desc()))).all()
        if not renewals: raise Held('pronunciation_authority_changed')
        renewal=renewals[0];await require_admin_actor(db,renewal.actor_id)
        renewed=json.loads(renewal.before_json)
        if (renewed['approval_id']!=approval.id or renewed['input_digest']!=stage.input_digest
                or renewed['continuity']!=current or renewed['script_digest']!=artifact.digest):
            raise Held('pronunciation_authority_changed')
    return current['preflight']


async def require_pronunciation_preflight(db,artifact):
    from app.services.recap_video.admin_actions import active_stages
    rows=await active_stages(db,json.loads(artifact.payload_json)['episode_id'])
    if not rows or any(row.script_id!=artifact.id for row in rows):
        raise Held('media_qualification_changed')
    for stage in rows:
        if await require_pronunciation_stage(db,stage) is None:
            raise Held('media_qualification_changed')


async def renew_finished_preflight(db,*,episode_id,actor_id,reason):
    """Renew free verification of retained paid audio; no new request authority."""
    from app.services.recap_video.admin_actions import active_stages
    await require_admin_actor(db,actor_id);await lock_control(db)
    rows=await active_stages(db,episode_id)
    paid=[r for r in rows if r.kind=='narrate']
    if not reason.strip() or not paid or any(r.state!='succeeded' for r in paid) or any(r.state=='running' for r in rows):
        raise Held('finished_narration_required')
    artifact=await db.get(ContentArtifact,paid[0].script_id)
    current=await _continuity(db,artifact)
    policy=await resolve_policy(db,artifact.series_id)
    pd=digest([policy['policy']['features']['recap_video'],policy['revisions'],current['preflight']])
    for stage in rows:
        authority=await db.scalar(select(RecapRecovery).where(RecapRecovery.stage_id==stage.id,
            RecapRecovery.action=='pronunciation_amendment_authority'))
        if not authority: raise Held('pronunciation_authority_required')
        value=json.loads(authority.before_json)
        if value['input_digest']!=stage.input_digest: raise Held('pronunciation_authority_changed')
        db.add(RecapRecovery(episode_id=episode_id,stage_id=stage.id,action='pronunciation_free_requalified',
            actor_id=actor_id,reason=reason,before_json=dump(dict(approval_id=value['approval_id'],input_digest=stage.input_digest,
                script_digest=artifact.digest,continuity=current,previous_policy_digest=stage.policy_digest))))
        stage.policy_digest=pd
    await db.flush()
    for stage in rows: await require_pronunciation_stage(db,stage)
    return dict(stages=len(rows),new_provider_calls=0)
