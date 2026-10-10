"""Audited free history retrieval. Never constructs paid dispatch authority."""
from sqlalchemy import select

from app.config import get_settings
from app.services.generation.models import GenerationOperation, stamp
from app.services.generation.recap_models import RecapProviderAttempt, RecapRecoveryRequest
from app.services.generation.store import Held, OwnershipLost, audit, dump, lock_control
from app.services.generation.commands import require_actor
from app.services.generation.provider_control import account_control, record_failure
from app.services.recap_video.qualification import require_admin_actor
from app.services.recap_video.workflow import _identity


async def recovered_audio_plan(db, episode_id, *, verify_bytes=False):
    """All incomplete chunks need exact recovered bytes; no partial paid retry."""
    import asyncio
    import hashlib
    import json
    from app.services.generation.recap_models import RecapAsset
    from app.services.generation.store import data, digest
    from app.services.recap_video.admin_actions import active_stages
    from app.services.recap_video.storage import configured_store
    rows = await active_stages(db,episode_id)
    plan = []
    for stage in [row for row in rows if row.kind == 'narrate' and row.state != 'succeeded']:
        attempt = await db.scalar(select(RecapProviderAttempt).where(RecapProviderAttempt.stage_id==stage.id))
        receipt = json.loads(attempt.recovery_receipt_json or '{}') if attempt else {}
        asset = await db.get(RecapAsset,receipt.get('asset',{}).get('asset_id',''))
        if (not attempt or attempt.state in ('dispatching','abandoned') or stage.state not in ('held','needs_attention')
                or receipt.get('outcome') != 'recovered' or receipt.get('request_digest') != attempt.request_digest
                or receipt.get('identity') != _identity(attempt) or not all(_identity(attempt).get(k) for k in ('request_id','history_item_id'))
                or not asset or asset.stage_id != stage.id or asset.generation != attempt.generation
                or asset.media_type != 'audio/mpeg' or not 0 < asset.size <= 64*1024*1024
                or receipt.get('audio_sha256') != asset.digest or receipt.get('audio_size') != asset.size
                or receipt.get('asset') != {'asset_id':asset.id,'digest':asset.digest,'size':asset.size}):
            raise Held('recovered_audio_exact_chunk_evidence_required')
        if verify_bytes:
            try:
                raw = await asyncio.to_thread(configured_store().read_range,asset.storage_key,0,asset.size-1)
            except (OSError,ValueError):
                raise Held('recovered_audio_unavailable') from None
            if len(raw) != asset.size or hashlib.sha256(raw).hexdigest() != asset.digest:
                raise Held('recovered_audio_hash_mismatch')
        plan.append({'stage_id':stage.id,'asset_id':asset.id,'binding':digest([data(stage),data(attempt),data(asset)])})
    if not plan:
        raise Held('recovered_audio_pending_chunks_required')
    return plan


async def adopt_recovered_audio(db,episode_id,verified,*,actor_id,reason):
    from app.services.generation.recap_models import RecapStage,RecapRecovery
    from app.services.generation.store import Conflict,data
    from app.services.recap_video.admin_actions import active_stages
    from app.services.recap_video.corrections import resume_free
    from app.services.recap_video.workflow import _current
    if verified != await recovered_audio_plan(db,episode_id):
        raise Conflict('Recovered audio changed. Reload exact saved evidence.')
    for item in verified:
        stage = await db.get(RecapStage,item['stage_id'])
        await _current(db,stage,now=stamp())
        db.add(RecapRecovery(episode_id=episode_id,stage_id=stage.id,action='adopt_recovered_audio',
            before_json=dump({'stage':data(stage),'verified_binding':item}),actor_id=actor_id,reason=reason))
        stage.generation += 1
        stage.state,stage.reason,stage.lease_until = 'succeeded','',0
        stage.result_json=dump({'status':'ok','asset_ids':[item['asset_id']],'report':{'recovery_binding':item['binding']}})
        stage.evidence_json=dump({'recovered_audio_binding':item['binding'],'requires_independent_speech_timing':True})
    speech = next((row for row in await active_stages(db,episode_id) if row.kind=='speech_check'),None)
    if not speech or speech.state=='running':
        raise Held('recovered_audio_speech_checkpoint_required')
    db.add(RecapRecovery(episode_id=episode_id,stage_id=speech.id,action='recovered_audio_speech_reset',
        before_json=dump(data(speech)),actor_id=actor_id,reason=reason))
    speech.state='held'
    return await resume_free(db,episode_id,stage_id=speech.id,expected_generation=speech.generation,actor_id=actor_id,reason=reason)


async def enqueue_recovery(db, attempt_id, *, actor_id, reason):
    control = await lock_control(db)
    await require_admin_actor(db, actor_id)
    attempt = await db.get(RecapProviderAttempt, attempt_id)
    if not attempt or attempt.state == 'dispatching':
        raise Held('recovery_request_still_active')
    identity = _identity(attempt)
    if not all(identity.get(key) for key in ('request_id','history_item_id')):
        raise Held('recovery_exact_request_and_history_ids_required')
    pending = await db.scalar(select(RecapRecoveryRequest).where(RecapRecoveryRequest.attempt_id == attempt_id,
        RecapRecoveryRequest.state.in_(('pending','running'))))
    if pending:
        if pending.state == 'running' and pending.lease_until <= stamp():
            pending.state, pending.error = 'held', 'recovery_lease_expired_review_before_retry'
        else:
            return pending
    row = RecapRecoveryRequest(attempt_id=attempt_id,worker_id=attempt.worker_id,actor_id=actor_id,
        identity_json=dump(identity),request_digest=attempt.request_digest,epoch=control.epoch,reason=reason)
    db.add(row)
    await db.flush()
    audit(db,actor_id,'recap_exact_history_recovery',attempt_id,reason,after={'recovery_id':row.id,'worker_id':row.worker_id})
    return row


async def claim_recovery(db, worker_id, now):
    control = await lock_control(db)
    settings = get_settings()
    if settings.generation_emergency_pause or control.hold or not control.epoch or settings.generation_execution_epoch != control.epoch:
        return None
    rows = (await db.scalars(select(RecapRecoveryRequest).where(RecapRecoveryRequest.worker_id == worker_id,
        RecapRecoveryRequest.state.in_(('pending','running'))).order_by(RecapRecoveryRequest.created_at))).all()
    for row in rows:
        if row.state == 'running':
            if row.lease_until <= now:
                row.state, row.error = 'held', 'recovery_lease_expired_review_before_retry'
            continue
        attempt = await db.get(RecapProviderAttempt,row.attempt_id)
        try:
            await require_admin_actor(db,row.actor_id)
            if (not attempt or attempt.worker_id != worker_id or attempt.state == 'dispatching'
                    or row.epoch != control.epoch or row.request_digest != attempt.request_digest
                    or row.identity_json != dump(_identity(attempt))):
                raise Held('recovery_identity_changed')
            job = await db.get(GenerationOperation,attempt.operation_id)
            if not job:
                raise Held('recovery_operation_missing')
            await require_actor(db,job)
            provider = await account_control(db,attempt.provider,attempt.account_key)
            if provider.hold and provider.hold != 'accounting_attention':
                raise Held(provider.hold)
            if provider.cooldown_until > now:
                raise Held('provider_cooldown')
        except Held as exc:
            row.state, row.error = 'held', exc.code
            continue
        row.state, row.lease_until = 'running', now + 600
        return {'recovery_id':row.id,'attempt_id':row.attempt_id,'generation':row.generation}
    return None


async def complete_recovery(db, recovery_id, generation, *, worker_id, error='', status=0):
    await lock_control(db)
    row = await db.get(RecapRecoveryRequest,recovery_id)
    if not row or row.worker_id != worker_id or row.state != 'running' or row.generation != generation or row.lease_until <= stamp():
        raise OwnershipLost('Exact recovery lease is no longer current')
    attempt = await db.get(RecapProviderAttempt,row.attempt_id)
    # Receipt routes separately retain late financial evidence. This completion
    # only acknowledges a lookup; neither old nor new media can be selected here.
    if error:
        row.state, row.error = 'held', error
        await record_failure(db,attempt.provider,attempt.account_key,status,stamp())
    elif not attempt.recovery_receipt_json:
        raise Held('recovery_receipt_missing')
    else:
        row.state, row.error = 'finished', 'recovered_evidence_requires_review'
    row.lease_until = 0
    audit(db,row.actor_id,'recap_history_recovery_finished',row.attempt_id,row.error)
    return {'state':row.state,'reason':row.error}
