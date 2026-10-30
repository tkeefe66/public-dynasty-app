"""One explicitly approved rewritten narration; old artifacts and charges survive."""
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.config import get_settings
from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationAudit, GenerationOperation, stamp
from app.services.generation.recap_models import RecapEpisode, RecapProviderAttempt
from app.services.generation.store import Held, digest, dump, lock_control, resolve_policy
from app.services.recap_video.qualification import require_admin_actor


async def source_proof(db, artifact):
    from app.services.recap_video.editorial import _receipts
    payload = json.loads(artifact.payload_json)
    job = await db.get(GenerationOperation, artifact.operation_id)
    original = await db.get(GenerationOperation, payload['original_operation_id'])
    authority = await db.get(GenerationAudit, payload['editorial_authority_id'])
    if not job or not original or not authority or authority.action != 'recap_editorial_approved':
        raise Held('retake_original_authority_required')
    _, receipts = await _receipts(db, original)
    media = (await db.scalars(select(RecapProviderAttempt).where(
        RecapProviderAttempt.operation_id == job.id).order_by(RecapProviderAttempt.id))).all()
    if not media or any(a.state != 'received' or a.cost_microusd is None or a.error_code or not a.receipt_json for a in media):
        raise Held('retake_original_receipts_unsettled')
    return dict(artifact_id=artifact.id, artifact_digest=artifact.digest, payload_digest=digest(payload),
        facts_digest=digest(json.loads(artifact.facts_json)), operation_id=job.id,
        job_digest=digest([job.payload_json,job.request_digest,job.state,job.calls,job.max_calls,job.epoch]),
        authority_digest=digest([authority.actor_id,authority.after_json]), writer_receipts=receipts,
        original_job_digest=digest([original.payload_json,original.request_digest,original.state,original.generation,original.calls]),
        media_receipts=digest([[a.id,a.stage_id,a.state,a.cost_microusd,a.receipt_json,a.request_digest,
            a.request_json,a.pricing_json,a.identity_json,a.error_code] for a in media]))


async def context(db, artifact_id, actor_id):
    from app.services.recap_video.editorial import require_editorial_artifact
    from app.services.recap_video.admin_actions import active_stages
    await require_admin_actor(db, actor_id)
    await lock_control(db)
    artifact = await db.get(ContentArtifact, artifact_id)
    job = await require_editorial_artifact(db, artifact)
    payload = json.loads(artifact.payload_json)
    episode = await db.get(RecapEpisode, payload['episode_id'])
    rows = await active_stages(db, episode.episode_id)
    if (not rows or any(r.script_id != artifact.id or r.state == 'running' for r in rows)
            or any(r.state != 'succeeded' for r in rows if r.kind == 'narrate')
            or not any(r.kind == 'narrate' for r in rows)):
        raise Held('retake_finished_narration_required')
    from app.services.recap_video.publication import authority_for_episode
    public = await authority_for_episode(db, episode)
    if public and public.media_id:
        raise Held('retake_published_video_requires_separate_review')
    attempts = (await db.scalars(select(RecapProviderAttempt).where(RecapProviderAttempt.episode_id == episode.episode_id))).all()
    if any(a.state != 'received' or a.cost_microusd is None or a.error_code for a in attempts):
        raise Held('retake_original_receipts_unsettled')
    proof = await source_proof(db, artifact)
    proof['stages'] = [[r.id,r.generation,r.state,r.input_digest] for r in rows]
    policy = await resolve_policy(db,artifact.series_id)
    proof['policy_digest'] = digest(policy)
    return artifact, job, episode, rows, proof


async def quote(db, episode_id, script, maximum):
    from app.services.recap_video.elevenlabs import qualification, validate_request, MODEL
    from sleeper_dynasty.engine.recap_narration import narration_chunks
    if type(maximum) is not int or not 0 < maximum <= 250000:
        raise Held('retake_approval_ceiling_invalid')
    chunks = narration_chunks(script)
    if len(chunks) != 1:
        raise Held('retake_one_narration_required')
    approved = await qualification(db, episode_id)
    request = dict(model_id=MODEL,inputs=[dict(voice_id=approved['config']['voice_id'],text=chunks[0]['text'])],
        settings=approved['config']['settings'])
    try:
        price = validate_request(request, approved['rate_snapshot'], maximum)
    except ValueError:
        raise Held('retake_approval_ceiling_exceeded') from None
    return dict(request=request,rate_snapshot=approved['rate_snapshot'],max_microusd=price)


async def preview_retake(db, *, artifact_id, script, semantic_review, maximum_microusd, actor_id, reason):
    from app.services.recap_video.editorial import _validate
    if not reason.strip(): raise Held('retake_reason_required')
    artifact, job, episode, _, proof = await context(db,artifact_id,actor_id)
    saved = json.loads(job.payload_json)
    script = _validate(script,semantic_review,saved)
    paid = await quote(db,episode.episode_id,script,maximum_microusd)
    manifest = dict(source=proof,script=script,semantic_review=semantic_review,saved=saved,paid=paid,
        episode_id=episode.episode_id,maximum_microusd=maximum_microusd,expires_at=stamp()+900)
    row = GenerationAudit(actor_id=actor_id,action='recap_editorial_retake_preview',target=artifact.id,
        reason=reason,after_json=dump(manifest))
    db.add(row); await db.flush()
    return dict(preview_id=row.id,digest=digest(manifest),requests=1,maximum_microusd=paid['max_microusd'],new_writer_calls=0)


async def apply_retake(db, *, preview_id, preview_digest, actor_id, reason):
    from app.services.recap_video.editorial import _validate
    from app.services.recap_video.workflow import start_media
    from app.services.generation.recap_budget import reserve_plan
    await require_admin_actor(db,actor_id); await lock_control(db)
    preview = await db.get(GenerationAudit,preview_id)
    if (not preview or preview.action != 'recap_editorial_retake_preview' or preview.actor_id != actor_id
            or not reason.strip()): raise Held('retake_preview_invalid')
    manifest = json.loads(preview.after_json)
    if digest(manifest) != preview_digest: raise Held('retake_preview_changed')
    existing = await db.scalar(select(GenerationOperation).where(GenerationOperation.authorization_key == 'retake:'+preview_id))
    if existing:
        artifact = await db.get(ContentArtifact,existing.artifact_id)
        await require_retake_artifact(db,artifact)
        return result(artifact,manifest)
    if manifest['expires_at'] <= stamp(): raise Held('retake_preview_expired')
    old, old_job, episode, rows, proof = await context(db,preview.target,actor_id)
    if proof != manifest['source'] or json.loads(old_job.payload_json) != manifest['saved']:
        raise Held('retake_preview_changed')
    script = _validate(manifest['script'],manifest['semantic_review'],manifest['saved'])
    if await quote(db,episode.episode_id,script,manifest['maximum_microusd']) != manifest['paid']:
        raise Held('retake_price_changed')
    authority = GenerationAudit(actor_id=actor_id,action='recap_editorial_retake_approved',target=old.id,
        reason=reason,after_json=dump(dict(preview_id=preview_id,preview_digest=preview_digest)))
    db.add(authority); await db.flush()
    job = GenerationOperation(kind='recap_editorial',feature='recap_video',league_id=old.league_id,
        series_id=old.series_id,subject=old.subject,actor_id=actor_id,actor_kind='admin',state='succeeded',
        authorization_key='retake:'+preview_id,request_digest=digest(manifest['saved']),payload_json=dump(manifest['saved']),
        policy_json=old_job.policy_json,connection_generation=old_job.connection_generation,epoch=old_job.epoch,
        calls=0,max_calls=0,reason='editorial_retake_reviewed')
    db.add(job); await db.flush()
    payload = {**json.loads(old.payload_json),'script':script,'editorial_authority_id':authority.id}
    artifact = ContentArtifact(operation_id=job.id,series_id=old.series_id,league_id=old.league_id,
        feature=old.feature,subject=old.subject,revision=old.revision+1,payload_json=dump(payload),digest=digest(payload),
        facts_json=dump(manifest['saved']),provenance='editorial_reviewed')
    db.add(artifact); await db.flush(); job.artifact_id=artifact.id
    head = await db.get(ArtifactHead,old.subject)
    head.artifact_id,head.revision=artifact.id,artifact.revision
    authority.after_json=dump(dict(preview_id=preview_id,preview_digest=preview_digest,artifact_id=artifact.id,
        artifact_digest=artifact.digest,operation_id=job.id))
    fresh = await start_media(db,artifact.id)
    narration = [r for r in fresh if r.kind=='narrate']
    if len(narration)!=1 or json.loads(narration[0].input_json)['paid']!=manifest['paid']:
        raise Held('retake_request_changed')
    await reserve_plan(db,episode.episode_id,old.series_id,'media:'+artifact.id,[dict(key=narration[0].id,
        category='video',operation_id=narration[0].id,max_microusd=manifest['paid']['max_microusd'],
        rate_snapshot=manifest['paid']['rate_snapshot'])],stamp())
    from app.services.generation.recap_models import RecapRecovery
    for row in rows:
        if row.state != 'succeeded':
            db.add(RecapRecovery(episode_id=episode.episode_id,stage_id=row.id,action='editorial_retake_superseded',
                actor_id=actor_id,reason=reason,before_json=dump(dict(approval_id=authority.id,state=row.state,generation=row.generation))))
            row.state,row.reason,row.lease_until='cancelled','editorial_retake_superseded',0
            row.generation+=1
    episode.lifecycle='narration'
    await db.flush()
    return result(artifact,manifest)


def result(artifact,manifest):
    return dict(artifact_id=artifact.id,operation_id=artifact.operation_id,requests=1,
        maximum_microusd=manifest['paid']['max_microusd'],new_writer_calls=0)


async def require_retake_artifact(db, artifact, *, require_renderable=True, require_preflight=True):
    from app.services.recap_video.editorial import _validate
    from app.services.generation.commands import require_actor
    from app.services.recap_video.contracts import require_script_inputs
    from app.services.recap_video.workflow import require_script_preflight
    payload=json.loads(artifact.payload_json)
    authority=await db.get(GenerationAudit,payload['editorial_authority_id'])
    if not authority or authority.action!='recap_editorial_retake_approved': raise Held('retake_authority_invalid')
    proof=json.loads(authority.after_json)
    preview=await db.get(GenerationAudit,proof.get('preview_id',''))
    job=await db.get(GenerationOperation,artifact.operation_id)
    if not preview or not job: raise Held('retake_authority_invalid')
    manifest=json.loads(preview.after_json)
    old=await db.get(ContentArtifact,authority.target)
    if not old: raise Held('retake_authority_invalid')
    source=await source_proof(db,old)
    expected={k:v for k,v in manifest['source'].items() if k not in ('stages','policy_digest')}
    expected_payload={**json.loads(old.payload_json),'script':manifest['script'],'editorial_authority_id':authority.id}
    head=await db.get(ArtifactHead,artifact.subject)
    if (source!=expected or preview.action!='recap_editorial_retake_preview' or preview.target!=old.id
            or preview.actor_id!=authority.actor_id or job.actor_id!=authority.actor_id
            or digest(manifest)!=proof.get('preview_digest') or proof.get('artifact_id')!=artifact.id
            or proof.get('artifact_digest')!=artifact.digest or proof.get('operation_id')!=job.id
            or payload!=expected_payload or digest(payload)!=artifact.digest or artifact.provenance!='editorial_reviewed'
            or artifact.revision!=old.revision+1 or artifact.feature!='recap_video'
            or job.kind!='recap_editorial' or job.state!='succeeded' or job.calls!=0 or job.max_calls!=0
            or job.artifact_id!=artifact.id or job.active_key is not None or job.authorization_key!='retake:'+preview.id
            or json.loads(job.payload_json)!=manifest['saved'] or job.request_digest!=digest(manifest['saved'])
            or json.loads(artifact.facts_json)!=manifest['saved']
            or (artifact.subject,artifact.series_id,artifact.league_id)!=(old.subject,old.series_id,old.league_id)
            or (job.subject,job.series_id,job.league_id)!=(old.subject,old.series_id,old.league_id)
            or not head or head.artifact_id!=artifact.id or head.revision!=artifact.revision or head.hold):
        raise Held('retake_authority_changed')
    await require_admin_actor(db,job.actor_id)
    await require_actor(db,SimpleNamespace(kind='generation',actor_id=job.actor_id,league_id=job.league_id,
        connection_generation=job.connection_generation))
    control=await lock_control(db)
    if (get_settings().generation_emergency_pause or control.hold or not control.epoch or job.epoch!=control.epoch
            or get_settings().generation_execution_epoch!=control.epoch
            or digest(await resolve_policy(db,job.series_id))!=manifest['source']['policy_digest']):
        raise Held('retake_execution_changed')
    await require_script_inputs(db,job.series_id,job.league_id,manifest['saved'])
    if require_preflight: await require_script_preflight(db,manifest['saved'])
    _validate(payload['script'],manifest['semantic_review'],manifest['saved'],require_renderable=require_renderable)
    if await quote(db,manifest['episode_id'],payload['script'],manifest['maximum_microusd'])!=manifest['paid']:
        raise Held('retake_price_changed')
    return job


async def require_retake_stage(db,stage,artifact):
    """One approved request remains exact even if a stage digest is recomputed."""
    authority=await db.get(GenerationAudit,json.loads(artifact.payload_json).get('editorial_authority_id',''))
    if not authority or authority.action!='recap_editorial_retake_approved': return
    proof=json.loads(authority.after_json)
    preview=await db.get(GenerationAudit,proof['preview_id'])
    manifest=json.loads(preview.after_json)
    if stage.execution_revision!=1: raise Held('retake_request_changed')
    if stage.kind=='narrate' and (stage.chunk!=0 or json.loads(stage.input_json).get('paid')!=manifest['paid']):
        raise Held('retake_request_changed')
