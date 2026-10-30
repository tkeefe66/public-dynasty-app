"""Explicit zero-provider editorial authority; paid receipts remain immutable."""
import json
from types import SimpleNamespace

from sqlalchemy import func, select

from app.config import get_settings
from app.services.generation.models import (ArtifactHead, ContentArtifact, GenerationAudit,
    GenerationOperation, ProviderAttempt, stamp)
from app.services.generation.store import Held, digest, dump, lock_control
from app.services.recap_video.qualification import require_admin_actor

TTL = 900


async def _receipts(db, job):
    rows = list((await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id == job.id).order_by(ProviderAttempt.stage, ProviderAttempt.id))).all())
    if len(rows) != job.calls or not rows or any(r.state != 'received' or r.usage_state != 'known'
            or r.cost_microusd is None or not r.receipt_json for r in rows):
        raise Held('recap_editorial_receipts_unsettled')
    values = [dict(id=r.id, stage=r.stage, generation=r.generation, request_digest=r.request_digest,
        request_json=r.request_json, receipt_json=r.receipt_json, cost_microusd=r.cost_microusd,
        usage_state=r.usage_state, state=r.state, provider=r.provider, account_key=r.account_key,
        model=r.model, usage_json=r.usage_json, pricing_json=r.pricing_json, provider_request_id=r.provider_request_id,
        status_code=r.status_code, error_code=r.error_code, settled_at=r.settled_at) for r in rows]
    return rows, digest(values)


async def _context(db, operation_id, actor_id):
    from app.services.recap_video.script_replacement import require_failed_script
    from app.services.recap_video.contracts import require_script_inputs
    from app.services.recap_video.workflow import require_media_preflight
    from app.services.generation.commands import require_actor
    from app.services.generation.store import resolve_policy
    await require_admin_actor(db, actor_id)
    job = await db.get(GenerationOperation, operation_id)
    if not job:
        raise Held('recap_editorial_original_missing')
    episode, cost = await require_failed_script(db, job)
    latest = await db.scalar(select(GenerationOperation.id).where(GenerationOperation.subject == job.subject,
        GenerationOperation.kind == 'generation').order_by(GenerationOperation.created_at.desc(), GenerationOperation.id.desc()).limit(1))
    if latest != job.id:
        raise Held('recap_editorial_original_changed')
    await require_actor(db, SimpleNamespace(kind='generation', actor_id=actor_id, league_id=job.league_id,
        connection_generation=job.connection_generation))
    original_saved = json.loads(job.payload_json)
    if digest(original_saved) != job.request_digest:
        raise Held('recap_editorial_original_changed')
    saved = {**original_saved, 'media_qualification_digest': digest(await require_media_preflight(db, episode.episode_id))}
    await require_script_inputs(db, job.series_id, job.league_id, saved)
    control = await lock_control(db)
    if (get_settings().generation_emergency_pause or control.hold or not control.epoch
            or job.epoch != control.epoch or get_settings().generation_execution_epoch != control.epoch):
        raise Held('recap_editorial_execution_held')
    policy = await resolve_policy(db, job.series_id)
    feature = policy['policy']['features']['recap_video']
    if policy['blocked_by'] or feature['paused'] or feature['mode'] == 'disabled':
        raise Held('recap_editorial_policy_held')
    from app.services.generation.models import LeagueSeason
    from app.services.generation.policy import paid_capabilities, supports_feature
    season = await db.get(LeagueSeason, job.league_id)
    if not season or not season.verified_at or not supports_feature(
            paid_capabilities(json.loads(season.capabilities_json)), season.provider, job.feature):
        raise Held('capability_unknown_or_unsupported')
    receipts, receipt_digest = await _receipts(db, job)
    return job, episode, saved, receipts, dict(original_id=job.id, original_generation=job.generation,
        original_state=job.state, original_request_digest=job.request_digest, original_source_digest=digest(original_saved),
        source_digest=digest(saved),
        receipt_digest=receipt_digest, prior_cost_microusd=cost, actor_id=actor_id,
        epoch=control.epoch, policy_digest=digest(policy))


async def get_editorial_source(db, *, operation_id, actor_id):
    job, episode, saved, receipts, fence = await _context(db, operation_id, actor_id)
    script, review = None, None
    for receipt in reversed(receipts):
        try:
            body = json.loads(json.loads(receipt.receipt_json)['body'])
            blocks = [b for b in body['content'] if b.get('type') == 'tool_use']
            if len(blocks) == 1:
                if blocks[0].get('name') == 'submit_script' and script is None:
                    from sleeper_dynasty.llm.recap_video_writer import Script
                    script = Script.model_validate(blocks[0]['input']).model_dump(exclude_unset=True)
                if blocks[0].get('name') == 'review_script' and review is None:
                    review = blocks[0]['input']
        except (KeyError, ValueError, TypeError):
            continue
    if script is None:
        raise Held('recap_editorial_saved_script_missing')
    return dict(operation_id=job.id, episode_id=episode.episode_id, source=saved, script=script,
        claims=saved['claims'], review=review, fence=fence)


def _validate(script, review, saved, *, require_renderable=True):
    from sleeper_dynasty.llm.recap_video_writer import Script, Review
    from sleeper_dynasty.engine.recap_video_claims import validate_script
    from sleeper_dynasty.engine.recap_narration import narration_chunks
    try:
        normalized = Script.model_validate(script).model_dump(exclude_unset=True)
        # Do not silently normalize a reviewed payload into different content.
        if normalized != script or len(dump(review)) > 64000:
            raise ValueError()
        approval = Review.model_validate({k: review[k] for k in
            ('approved', 'issues', 'checked_segment_ids', 'checks')}).model_dump()
        if (review.get('reviewer_kind') not in ('delegated_ai_editorial_reviewer', 'human_editorial_reviewer')
                or not isinstance(review.get('reviewer_identity'), str) or not review['reviewer_identity'].strip()
                or len(review['reviewer_identity']) > 300
                or review.get('script_sha256') != digest(normalized)
                or review.get('article_digest') != saved['published_article']['digest']
                or not approval['approved'] or approval['issues'] or not all(approval['checks'].values())
                or set(approval['checked_segment_ids']) != {'opening', 'closing', *[s['id'] for s in script['segments']]}
                or len(approval['checked_segment_ids']) != len(script['segments']) + 2
                or validate_script(normalized, saved['claims'], saved['published_article'])):
            raise ValueError()
        narration_chunks(normalized)
        from media.timeline import scene_plan
        if require_renderable:
            scene_plan(normalized, saved['claims'])
        normalize = lambda value: ' '.join(value.casefold().split())
        prior = {normalize(p['premise']) for episode in saved.get('recent_premises', []) for p in episode['premises']}
        if any(normalize(p['premise']) in prior and not p.get('callback_reason', '').strip() for p in normalized['premises']):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise Held('recap_editorial_review_invalid') from None
    return normalized


async def _budget(db, job):
    from app.services.recap_video.narration_budget import envelope_allocation
    from app.services.generation import recap_budget as budget
    from app.services.generation.recap_models import RecapBudgetPolicy
    from datetime import UTC
    allocation = await envelope_allocation(db, job)
    now = stamp()
    policy = await db.get(RecapBudgetPolicy, job.series_id)
    rows = await budget._obligations(db)
    if any(r['episode'] == json.loads(job.payload_json)['episode_id'] and (r['unknown'] or r['outcome_unknown']) for r in rows):
        raise Held('recap_provider_outcome_unknown')
    proposed = rows + [dict(series=job.series_id, episode=json.loads(job.payload_json)['episode_id'], category='video',
        known=0, reserved=allocation['max_microusd'], month=budget.month_key(now), app_month=budget.month_key(now, UTC),
        unknown=False, unbounded=False)]
    budget._check_balances(proposed, job.series_id, json.loads(job.payload_json)['episode_id'], budget._caps(policy), now)
    await budget._check_app(db, proposed, now)
    # Bind caps and prices, not moving usage totals. Apply checks capacity anew.
    return allocation, dict(caps=budget._caps(policy).model_dump(), caps_revision=policy.revision if policy else 0,
        narration_maximum_microusd=allocation['max_microusd'], rate_snapshot=allocation['rate_snapshot'])


async def preview_editorial(db, *, operation_id, script, semantic_review, actor_id, reason):
    if not reason.strip():
        raise Held('recap_editorial_reason_required')
    job, episode, saved, receipts, fence = await _context(db, operation_id, actor_id)
    script = _validate(script, semantic_review, saved)
    _, budget = await _budget(db, job)
    manifest = dict(operation_id=operation_id, fence=fence, script=script, semantic_review=semantic_review, budget=budget,
        created_at=stamp(), expires_at=stamp()+TTL)
    row = GenerationAudit(actor_id=actor_id, action='recap_editorial_preview', target=job.id,
        reason=reason, after_json=dump(manifest))
    db.add(row)
    await db.flush()
    return dict(preview_id=row.id, digest=digest(manifest), script_digest=digest(script),
        narration_maximum_microusd=budget['narration_maximum_microusd'], prior_cost_microusd=fence['prior_cost_microusd'],
        expires_at=manifest['expires_at'], new_writer_calls=0)


async def apply_editorial(db, *, preview_id, preview_digest, actor_id, reason):
    await require_admin_actor(db, actor_id)
    await lock_control(db)
    preview = await db.get(GenerationAudit, preview_id)
    if not preview or preview.action != 'recap_editorial_preview' or preview.actor_id != actor_id or not reason.strip():
        raise Held('recap_editorial_preview_invalid')
    manifest = json.loads(preview.after_json)
    if digest(manifest) != preview_digest:
        raise Held('recap_editorial_preview_changed')
    existing = await db.scalar(select(GenerationOperation).where(GenerationOperation.authorization_key == 'editorial:'+preview_id))
    if existing:
        artifact = await db.get(ContentArtifact, existing.artifact_id)
        await require_editorial_artifact(db, artifact)
        return dict(artifact_id=artifact.id, operation_id=existing.id, new_writer_calls=0)
    if manifest['expires_at'] <= stamp():
        raise Held('recap_editorial_preview_expired')
    old, episode, saved, receipts, fence = await _context(db, preview.target, actor_id)
    script = _validate(manifest['script'], manifest['semantic_review'], saved)
    _, budget = await _budget(db, old)
    if fence != manifest['fence'] or budget != manifest['budget']:
        raise Held('recap_editorial_preview_changed')
    authority = GenerationAudit(actor_id=actor_id, action='recap_editorial_approved', target=old.id,
        reason=reason, after_json=dump(dict(preview_id=preview_id, preview_digest=preview_digest)))
    db.add(authority)
    await db.flush()
    job = GenerationOperation(kind='recap_editorial', feature='recap_video', league_id=old.league_id,
        series_id=old.series_id, subject=old.subject, actor_id=actor_id, actor_kind='admin',
        state='succeeded', active_key=None, authorization_key='editorial:'+preview_id,
        request_digest=digest(saved), payload_json=dump(saved), policy_json=old.policy_json,
        connection_generation=old.connection_generation, epoch=fence['epoch'], calls=0, max_calls=0,
        reason='editorial_reviewed')
    db.add(job)
    await db.flush()
    payload = dict(script=script, claims=saved['claims'], episode_id=episode.episode_id,
        article_digest=saved['published_article']['digest'], source_digest=saved['source_digest'],
        recap_facts_digest=saved['recap_facts_digest'], editorial_authority_id=authority.id, original_operation_id=old.id)
    revision = (await db.scalar(select(func.max(ContentArtifact.revision)).where(ContentArtifact.subject == old.subject)) or 0) + 1
    artifact = ContentArtifact(operation_id=job.id, series_id=old.series_id, league_id=old.league_id,
        feature='recap_video', subject=old.subject, revision=revision, payload_json=dump(payload), digest=digest(payload),
        facts_json=dump(saved), provenance='editorial_reviewed')
    db.add(artifact)
    await db.flush()
    job.artifact_id = artifact.id
    db.add(ArtifactHead(subject=old.subject, artifact_id=artifact.id, revision=artifact.revision))
    authority.after_json = dump(dict(preview_id=preview_id, preview_digest=preview_digest,
        artifact_id=artifact.id, artifact_digest=artifact.digest, operation_id=job.id,
        source_digest=digest(saved), original_operation_id=old.id))
    from app.services.recap_video.editorial_envelope import preview_original_envelope_release, reconcile_original_envelope
    release = await preview_original_envelope_release(db,artifact_id=artifact.id,actor_id=actor_id)
    await reconcile_original_envelope(db,artifact_id=artifact.id,preview_digest=release['digest'],actor_id=actor_id,
        reason='Accepted editorial script supersedes original unused narration reservation')
    from app.services.recap_video.narration_budget import envelope_allocation
    from app.services.generation.recap_budget import reserve_plan
    allocation = await envelope_allocation(db, job)
    await reserve_plan(db, episode.episode_id, old.series_id, 'operation:'+job.id, [allocation], stamp())
    await db.flush()
    return dict(artifact_id=artifact.id, operation_id=job.id, new_writer_calls=0)


async def require_editorial_artifact(db, artifact, *, require_renderable=True, require_preflight=True):
    """Exact durable alternate authority, never a broad managed-provenance bypass."""
    if not artifact or artifact.provenance != 'editorial_reviewed' or artifact.feature != 'recap_video':
        raise Held('recap_editorial_authority_invalid')
    payload = json.loads(artifact.payload_json)
    authority = await db.get(GenerationAudit, payload.get('editorial_authority_id', ''))
    if authority and authority.action == 'recap_editorial_retake_approved':
        from app.services.recap_video.editorial_retake import require_retake_artifact
        return await require_retake_artifact(db, artifact, require_renderable=require_renderable,
            require_preflight=require_preflight)
    job = await db.get(GenerationOperation, artifact.operation_id)
    if not authority or authority.action != 'recap_editorial_approved' or not job:
        raise Held('recap_editorial_authority_invalid')
    proof = json.loads(authority.after_json)
    preview = await db.get(GenerationAudit, proof.get('preview_id', ''))
    if not preview or preview.action != 'recap_editorial_preview':
        raise Held('recap_editorial_authority_invalid')
    manifest = json.loads(preview.after_json)
    saved = json.loads(job.payload_json)
    old = await db.get(GenerationOperation, proof.get('original_operation_id', ''))
    if not old:
        raise Held('recap_editorial_authority_invalid')
    _, receipt_digest = await _receipts(db, old)
    if (digest(manifest) != proof.get('preview_digest') or digest(payload) != artifact.digest
            or proof.get('artifact_id') != artifact.id or proof.get('artifact_digest') != artifact.digest
            or proof.get('operation_id') != job.id or job.artifact_id != artifact.id
            or job.kind != 'recap_editorial' or job.state != 'succeeded' or job.calls != 0 or job.max_calls != 0
            or job.active_key is not None or job.authorization_key != 'editorial:'+preview.id
            or job.actor_id != authority.actor_id or preview.actor_id != authority.actor_id
            or old.id != authority.target or old.id != preview.target or payload.get('original_operation_id') != old.id
            or digest(saved) != proof.get('source_digest') or digest(saved) != manifest['fence']['source_digest']
            or job.request_digest != digest(saved) or json.loads(artifact.facts_json) != saved
            or receipt_digest != manifest['fence']['receipt_digest']
            or old.state != manifest['fence']['original_state'] or old.generation != manifest['fence']['original_generation']
            or digest(json.loads(old.payload_json)) != manifest['fence']['original_source_digest']
            or {**json.loads(old.payload_json), 'media_qualification_digest': saved.get('media_qualification_digest')} != saved
            or old.request_digest != manifest['fence']['original_request_digest']
            or (job.subject, job.series_id, job.league_id) != (old.subject, old.series_id, old.league_id)
            or (artifact.subject, artifact.series_id, artifact.league_id) != (job.subject, job.series_id, job.league_id)
            or payload.get('script') != manifest['script'] or payload.get('claims') != saved['claims']
            or payload.get('episode_id') != saved['episode_id'] or payload.get('source_digest') != saved['source_digest']
            or payload.get('recap_facts_digest') != saved['recap_facts_digest']
            or payload.get('article_digest') != saved['published_article']['digest']):
        raise Held('recap_editorial_authority_changed')
    await require_admin_actor(db, job.actor_id)
    from app.services.generation.commands import require_actor
    await require_actor(db, SimpleNamespace(kind='generation', actor_id=job.actor_id, league_id=job.league_id,
        connection_generation=job.connection_generation))
    head = await db.get(ArtifactHead, artifact.subject)
    if not head or head.artifact_id != artifact.id or head.revision != artifact.revision or head.hold:
        raise Held('recap_editorial_head_changed')
    from app.services.recap_video.contracts import require_script_inputs
    from app.services.recap_video.workflow import require_script_preflight
    from app.services.generation.store import resolve_policy
    control = await lock_control(db)
    policy = await resolve_policy(db, job.series_id)
    if (get_settings().generation_emergency_pause or control.hold or job.epoch != manifest['fence']['epoch']
            or control.epoch != job.epoch or get_settings().generation_execution_epoch != job.epoch
            or digest(policy) != manifest['fence']['policy_digest']):
        raise Held('recap_editorial_execution_changed')
    await require_script_inputs(db, job.series_id, job.league_id, saved)
    if require_preflight:
        try:
            await require_script_preflight(db, saved)
        except Held as exc:
            if exc.code != 'media_qualification_changed':
                raise
            from app.services.recap_video.pronunciation import require_pronunciation_preflight
            await require_pronunciation_preflight(db,artifact)
    _validate(payload['script'], manifest['semantic_review'], saved, require_renderable=require_renderable)
    return job
