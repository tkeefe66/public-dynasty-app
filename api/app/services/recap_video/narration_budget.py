"""Pre-script exposure and atomic concrete-chunk binding; no provider I/O."""
import json

from sqlalchemy import select

from app.services.generation.recap_models import RecapBudgetAllocation, RecapBudgetPlan
from app.services.generation.store import Held, digest, dump, lock_control
from sleeper_dynasty.engine.recap_narration import MAX_SUBMITTED_CHARACTERS, MAX_CHUNK_CHARACTERS, MAX_CHUNKS

ENVELOPE_KEY = 'narration-envelope'


async def envelope_allocation(db, job):
    from app.services.recap_video.elevenlabs import qualification, canonical, validate_request, MODEL
    from app.services.recap_video.workflow import require_media_preflight
    episode = json.loads(job.payload_json)['episode_id']
    evidence = await require_media_preflight(db, episode)
    approved = await qualification(db, episode)
    if (evidence['qualification_revision'] != approved['revision']
            or evidence['voice_digest'] != canonical([approved['config'], approved['metadata']])
            or evidence['rate_digest'] != canonical(approved['rate_snapshot'])):
        raise Held('media_qualification_changed')
    try:
        unit = validate_request({'model_id': MODEL, 'inputs': [{'voice_id': approved['config']['voice_id'], 'text': 'x'}],
            'settings': approved['config']['settings']}, approved['rate_snapshot'], 9_007_199_254_740_991)
    except ValueError:
        raise Held('media_rate_unqualified') from None
    snapshot = dict(envelope_version=1, max_submitted_characters=MAX_SUBMITTED_CHARACTERS,
        max_chunk_characters=MAX_CHUNK_CHARACTERS, max_chunks=MAX_CHUNKS,
        qualification=approved, preflight_digest=digest(evidence))
    return dict(key=ENVELOPE_KEY, category='video', operation_id=job.id,
        max_microusd=MAX_SUBMITTED_CHARACTERS * unit, rate_snapshot=snapshot)


async def bind_chunks(db, script_id, operation_id, episode_id, series_id, allocations, requests, now):
    """Swap envelope for immutable chunks in one savepoint; no gap/double count.

    Existing pre-envelope scripts retain the old exact-plan reservation path.
    Every newly dispatched script obtains its envelope in gateway admission.
    """
    from app.services.generation.recap_budget import reserve_plan, settle_allocation
    await lock_control(db)
    envelope = await db.scalar(select(RecapBudgetAllocation).join(RecapBudgetPlan,
        RecapBudgetPlan.id == RecapBudgetAllocation.plan_id).where(
        RecapBudgetPlan.plan_key == 'operation:' + operation_id,
        RecapBudgetAllocation.key == ENVELOPE_KEY))
    plan_key = 'media:' + script_id
    if envelope is None:
        return await reserve_plan(db, episode_id, series_id, plan_key, allocations, now)
    binding = dict(script_id=script_id, allocations_digest=digest(allocations), requests_digest=digest(requests))
    if envelope.actual_microusd is not None:
        if json.loads(envelope.evidence_json).get('concrete_binding') != binding:
            raise Held('narration_envelope_already_released')
        return await reserve_plan(db, episode_id, series_id, plan_key, allocations, now)
    snapshot = json.loads(envelope.rate_json)
    approved = snapshot['qualification']
    from app.services.recap_video.elevenlabs import validate_request, MODEL
    characters = 0
    if not 1 <= len(requests) <= snapshot['max_chunks']:
        raise Held('narration_exceeds_envelope')
    for allocation, request in zip(allocations, requests, strict=True):
        try:
            text = request['inputs'][0]['text']
            expected = {'model_id': MODEL, 'inputs': [{'voice_id': approved['config']['voice_id'], 'text': text}],
                'settings': approved['config']['settings']}
            if request != expected or allocation['rate_snapshot'] != approved['rate_snapshot']:
                raise ValueError()
            validate_request(request, allocation['rate_snapshot'], allocation['max_microusd'])
            characters += len(text)
        except (ValueError, KeyError, TypeError):
            raise Held('narration_envelope_changed') from None
    if characters > snapshot['max_submitted_characters'] or sum(a['max_microusd'] for a in allocations) > envelope.max_microusd:
        raise Held('narration_exceeds_envelope')
    async with db.begin_nested():
        await settle_allocation(db, envelope.id, 0, {'concrete_binding': binding})
        plan = await reserve_plan(db, episode_id, series_id, plan_key, allocations, now)
        return plan
