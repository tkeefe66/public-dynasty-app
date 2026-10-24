"""Small allowlist of existing audited commands; never creates approvals."""
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.services.generation import administration, resolution
from app.services.generation.commands import FREE_REFRESH_KINDS, require_actor
from app.services.generation.models import (ArtifactHead, ContentArtifact,
    GenerationOperation, GenerationOutbox, ProviderAttempt)
from app.services.generation.store import Conflict, Held
from app.services.recap_monitor.evidence import review_approved


async def recover(db, item, owner_id, now):
    out = dict(item)
    def help_needed(reason, action='Review saved work in Admin; additional calls require specific approval'):
        return {**out, 'status': 'help', 'reason': reason, 'action': action}
    if item.get('recovery_attempts', 0) >= 2:
        return help_needed('recovery_exhausted')
    job = await db.get(GenerationOperation, item.get('job_id', ''), populate_existing=True)
    if not job or job.actor_id != owner_id:
        return help_needed('job_authority_or_state_changed')
    if job.kind not in (*FREE_REFRESH_KINDS, 'generation') or job.kind == 'generation' and job.feature != 'analyst':
        return help_needed('unsupported_recovery')
    payload = json.loads(job.payload_json)
    if job.league_id != item.get('league_id') or (job.kind == 'generation' and (
            job.series_id != item.get('series_id') or
            (payload.get('season'), payload.get('week')) != (item.get('season'), item.get('week')))):
        return help_needed('job_scope_changed')
    out.update(calls_used=job.calls, max_calls=job.max_calls,
               remaining_calls=max(0, job.max_calls - job.calls))
    if job.state == 'succeeded' and job.artifact_id:
        try:
            await require_actor(db, job)
        except Held:
            return help_needed('recovery_authority_changed')
        artifact = await db.get(ContentArtifact, job.artifact_id)
        head = await db.get(ArtifactHead, job.subject)
        delivery = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + job.artifact_id))
        attempts = (await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == job.id)
            .order_by(ProviderAttempt.stage))).all()
        payload = json.loads(artifact.payload_json) if artifact else {}
        if (artifact and head and not head.hold and head.artifact_id == artifact.id
                and artifact.operation_id == job.id and artifact.provenance == 'managed'
                and (artifact.series_id, artifact.league_id, payload.get('season'), payload.get('week'))
                    == (item.get('series_id'), item.get('league_id'), item.get('season'), item.get('week'))
                and delivery and not delivery.delivered and delivery.error
                and len(attempts) == job.calls and all(a.cost_microusd is not None for a in attempts)
                and review_approved(attempts)):
            await administration.retry_projection(db, delivery.id, SimpleNamespace(
                expected_error=delivery.error, reason='Cloud recap monitor: replay reviewed saved publication; no AI calls'), owner_id)
            return {**out, 'status': 'pending', 'recovery_attempts': item.get('recovery_attempts', 0) + 1}
        return help_needed('saved_publication_requires_review')
    if job.state not in ('held', 'needs_attention'):
        return help_needed('job_authority_or_state_changed')
    saved_attempts = (await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == job.id)
        .order_by(ProviderAttempt.stage))).all()
    replay_only = (job.reason == 'provider_outcome_unknown' and job.calls == job.max_calls
        and len(saved_attempts) == job.calls and review_approved(saved_attempts))
    if job.kind == 'generation' and (job.max_calls > 4 or job.calls >= job.max_calls and not replay_only):
        return help_needed('attempt_allowance_exhausted')
    related = select(GenerationOperation.id).where(GenerationOperation.subject == job.subject) if job.subject else select(GenerationOperation.id).where(GenerationOperation.id == job.id)
    attempts = (await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id.in_(related)))).all()
    if any(a.state in ('dispatching', 'unknown', 'abandoned') or a.cost_microusd is None for a in attempts):
        return help_needed('provider_outcome_unknown')
    try:
        await require_actor(db, job)
        guidance = await resolution.resolution(db, job)
        action = guidance['action']
        if action in ('resume', 'retry_refresh'):
            # Command rechecks original actor/grant, generation/state and receipts.
            await administration.job_action(db, job.id, SimpleNamespace(action='resume',
                expected_generation=job.generation, expected_state=job.state,
                reason='Owner-authorized cloud recap monitor: bounded same-job recovery'), owner_id)
        elif action == 'retry_publication':
            await administration.retry_projection(db, guidance['outbox_id'], SimpleNamespace(
                expected_error=guidance['expected_error'],
                reason='Owner-authorized cloud recap monitor: replay saved publication'), owner_id)
        elif action in ('wait', 'related', 'saved'):
            return {**out, 'status': 'pending'}
        else:
            return help_needed('recovery_requires_review')
    except (Held, Conflict):
        return help_needed('recovery_authority_changed')
    return {**out, 'status': 'pending', 'recovery_attempts': item.get('recovery_attempts', 0) + 1,
            'last_recovery_at': now}
