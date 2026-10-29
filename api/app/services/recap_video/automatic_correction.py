"""Source-bound correction work under the original call and monetary ceilings."""
import json
import logging

from sqlalchemy import select

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationAudit, GenerationCandidate, GenerationOperation, GenerationOutbox, ProviderAttempt, stamp
from app.services.generation.store import Held, audit, digest, dump, resolve_policy
from app.services.recap_video.text_authority import current_source, reviewed_article, text_source_digest

log = logging.getLogger(__name__)
KEY = 'automatic_recap_correction'
EXTRA_CALLS = 'recap_correction_extra_calls_approved'


async def approve_extra_pair(db, root_id, *, actor_id, authorization_key, reason):
    """Explicit one-time operator approval; never invoked by automatic recovery.

    Preserves the original job and standing policies. Each unique human approval
    adds exactly one draft/review pair to this subject's lifetime accounting.
    """
    from app.services.generation.store import lock_control
    from app.services.recap_video.qualification import require_admin_actor
    control = await lock_control(db)
    await require_admin_actor(db, actor_id)
    root = await db.get(GenerationOperation, root_id)
    if (not root or root.feature != 'analyst' or root.state != 'succeeded'
            or KEY in json.loads(root.payload_json) or not authorization_key.strip() or not reason.strip()
            or root.epoch != control.epoch):
        raise Held('recap_correction_approval_invalid')
    # Recheck complete, settled accounting and external epoch before extending.
    await allowance(db, root.subject, root.id)
    previous = (await db.scalars(select(GenerationAudit).where(
        GenerationAudit.action == EXTRA_CALLS, GenerationAudit.target == root.id))).all()
    for row in previous:
        if json.loads(row.after_json).get('authorization_key') == authorization_key:
            return authorization_key
    audit(db, actor_id, EXTRA_CALLS, root.id, reason, after={
        'authorization_key': authorization_key, 'root_digest': digest(json.loads(root.payload_json)),
        'epoch': root.epoch, 'subject': root.subject, 'additional_calls': 2})
    await db.flush()
    return authorization_key


async def retire_unprojected(db, episode, source):
    """Detach a superseded, never-delivered successor; retain its paid evidence."""
    rows = (await db.scalars(select(ContentArtifact).join(ArtifactHead,
        ArtifactHead.artifact_id == ContentArtifact.id).where(ContentArtifact.series_id == episode.series_id,
        ContentArtifact.league_id == episode.league_id, ContentArtifact.feature == 'analyst',
        ArtifactHead.hold == ''))).all()
    for row in rows:
        saved = json.loads(row.facts_json)
        edition = saved.get('edition', {})
        if (edition.get('season'), edition.get('week')) != (episode.season, episode.week):
            continue
        original = edition.get('facts', {}).get('source_snapshot')
        if not original or text_source_digest(edition, original) == text_source_digest(edition, source):
            continue
        outbox = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + row.id))
        job = await db.get(GenerationOperation, row.operation_id) if row.operation_id else None
        previous = await db.get(ContentArtifact, job.expected_artifact) if job and job.expected_artifact else None
        if (not job or job.state != 'succeeded' or job.artifact_id != row.id
                or not outbox or outbox.delivered or not previous or previous.subject != row.subject
                or (episode.article_digest and previous.digest != episode.article_digest)
                or (not episode.article_digest and json.loads(previous.payload_json).get('edition_type') != 'results')):
            continue
        head = await db.get(ArtifactHead, row.subject)
        head.artifact_id, head.revision = previous.id, previous.revision
        outbox.error = 'recap_correction_source_superseded'
        audit(db, 'api-observer', 'recap_unprojected_correction_superseded', row.id,
              'Source changed before delivery; retained artifact and receipts, restored delivered predecessor',
              after={'predecessor': previous.id})


async def unpublished_base(db, episode):
    """Continue an interrupted first recap, without resetting its allowance."""
    jobs = list((await db.scalars(select(GenerationOperation).where(
        GenerationOperation.series_id == episode.series_id, GenerationOperation.league_id == episode.league_id,
        GenerationOperation.feature == 'analyst').order_by(GenerationOperation.created_at))).all())
    for root in jobs:
        saved = json.loads(root.payload_json)
        if (saved.get('season'), saved.get('week')) != (episode.season, episode.week) or saved.get(KEY):
            continue
        if root.state not in ('held', 'succeeded', 'cancelled'):
            continue
        if root.state in ('held', 'cancelled') and root.reason not in ('recap_facts_changed', 'recap_source_superseded'):
            continue
        head = await db.get(ArtifactHead, root.subject)
        base = await db.get(ContentArtifact, head.artifact_id) if head and not head.hold else None
        if not base or base.id != root.expected_artifact or digest(json.loads(base.payload_json)) != base.digest:
            continue
        old = json.loads(base.payload_json)
        if old.get('edition_type') != 'results' or not saved.get('edition', {}).get('facts', {}).get('source_snapshot'):
            continue
        if root.state == 'held':
            receipts = list((await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == root.id))).all())
            if any(a.state in ('dispatching', 'unknown', 'abandoned') or a.cost_microusd is None for a in receipts):
                raise Held('recap_provider_outcome_unknown')
            from app.services.generation.commands import cancel
            await cancel(db, root.id, 'api-observer', 'First recap source superseded; retain original call allowance')
            root.reason = 'recap_source_superseded'
        return base, saved['edition'], root
    raise Held('recap_text_article_missing')


async def allowance(db, subject, root_id, *, current_job=None):
    """All physical attempts count, including cancelled/failed correction work."""
    root = await db.get(GenerationOperation, root_id)
    if not root or root.subject != subject or root.feature != 'analyst' or KEY in json.loads(root.payload_json):
        raise Held('recap_correction_root_invalid')
    from app.config import get_settings
    if not root.epoch or root.epoch != get_settings().generation_execution_epoch:
        raise Held('recap_correction_root_epoch_changed')
    policy = await resolve_policy(db, root.series_id)
    jobs = list((await db.scalars(select(GenerationOperation).where(
        GenerationOperation.subject == subject, GenerationOperation.feature == 'analyst'))).all())
    attempts = list((await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id.in_([job.id for job in jobs])))).all())
    if any(a.state in ('dispatching', 'unknown', 'abandoned') or a.cost_microusd is None for a in attempts):
        raise Held('recap_provider_outcome_unknown')
    if any(job.id != current_job and job.state in ('queued', 'running', 'held', 'needs_attention') for job in jobs):
        raise Held('recap_correction_work_pending')
    if sum(job.calls for job in jobs) != len(attempts):
        raise Held('recap_correction_accounting_incomplete')
    ceiling = min(root.max_calls, policy['policy']['features']['analyst']['max_calls'])
    approvals = (await db.scalars(select(GenerationAudit).where(
        GenerationAudit.action == EXTRA_CALLS, GenerationAudit.target == root.id))).all()
    keys = set()
    for approval in approvals:
        proof = json.loads(approval.after_json)
        key = proof.get('authorization_key')
        if (key and key not in keys and proof.get('root_digest') == digest(json.loads(root.payload_json))
                and proof.get('epoch') == root.epoch and proof.get('subject') == subject
                and proof.get('additional_calls') == 2):
            ceiling += 2
            keys.add(key)
    return max(0, ceiling - len(attempts))


async def require_correction(db, episode, payload):
    """Shared by admission, dispatch, artifact save, and projection."""
    proof = payload[KEY]
    from app.services.recap_video.publication import edition_row
    from app.services.recap_video.text_authority import automatic_withdrawal
    public = await edition_row(db, episode.league_id, episode.season, episode.week)
    if public and not await automatic_withdrawal(db, public):
        raise Held('recap_correction_explicit_withdrawal')
    source = await current_source(db, episode)
    base = await db.get(ContentArtifact, payload.get('correction_base', ''))
    # Admission already proved stability for this exact text source. Irrelevant
    # bench changes may reset full-source stability without changing that proof.
    if (not episode.admitted_at
            or proof.get('episode_id') != episode.episode_id
            or proof.get('source_digest') != text_source_digest(payload['edition'], source)
            or not base or base.digest != proof.get('base_digest')
            or base.series_id != episode.series_id or base.league_id != episode.league_id):
        raise Held('recap_correction_source_changed')
    head = await db.get(ArtifactHead, base.subject)
    if not head or head.hold:
        raise Held('recap_correction_head_changed')
    if head.artifact_id != base.id:
        # Projection happens after artifact CAS; accept only this exact successor.
        successor = await db.get(ContentArtifact, head.artifact_id)
        job = await db.get(GenerationOperation, successor.operation_id) if successor else None
        if (not job or job.state != 'succeeded' or job.artifact_id != successor.id
                or job.expected_artifact != base.id
                or json.loads(job.payload_json) != {k: v for k, v in payload.items() if k != '_validation'}):
            raise Held('recap_correction_head_changed')
    if episode.hold.startswith('recap_dependency'):
        raise Held('recap_correction_history_unproven')
    return episode


async def collect_correction(db, episode):
    """Idempotent free reconciliation; creating a candidate never calls a provider."""
    from app.services.recap_video.readiness import source_ready, _authority_reason, EpisodeKey
    from app.services.recap_video.collector import edition_from_snapshot
    if not episode.admitted_at:
        return
    try:
        source = await current_source(db, episode)
        if not source_ready(episode, source):
            return
        await retire_unprojected(db, episode, source)
        try:
            artifact, old, original_job = await reviewed_article(db, episode)
        except Held:
            if episode.article_digest:
                raise
            artifact, old, original_job = await unpublished_base(db, episode)
        if original_job is None:
            return  # Reviewed legacy recovery authorizes no new paid requests.
        from app.services.recap_video.text_revalidation import member_text_revalidated
        if await member_text_revalidated(db, episode.episode_id, old):
            return  # Exact existing independent review already proves this text.
        from app.services.recap_video.publication import edition_row
        from app.services.recap_video.text_authority import automatic_withdrawal
        public = await edition_row(db, episode.league_id, episode.season, episode.week)
        if public and not await automatic_withdrawal(db, public):
            raise Held('recap_correction_explicit_withdrawal')
        if episode.hold.startswith('recap_dependency'):
            raise Held('recap_correction_history_unproven')
        reason = await _authority_reason(db, EpisodeKey(episode.series_id, episode.season, episode.period_id),
                                        episode.league_id, automatic=True)
        if reason:
            raise Held(reason)
        root_id = json.loads(original_job.payload_json).get(KEY, {}).get('root_operation_id', original_job.id)
        pending = list((await db.scalars(select(GenerationOperation).where(
            GenerationOperation.subject == artifact.subject,
            GenerationOperation.state.in_(('queued', 'held', 'needs_attention'))))).all())
        for job in pending:
            saved = json.loads(job.payload_json)
            if saved.get(KEY) and saved[KEY]['source_digest'] != text_source_digest(saved['edition'], source):
                attempts = list((await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == job.id))).all())
                if any(a.state in ('dispatching', 'unknown', 'abandoned') or a.cost_microusd is None for a in attempts):
                    raise Held('recap_provider_outcome_unknown')
                from app.services.generation.commands import cancel
                await cancel(db, job.id, 'api-observer', 'Superseded correction source; spent calls remain charged')
                job.reason = 'recap_source_superseded'
        original = old.get('facts', {}).get('source_snapshot')
        if not original or (json.loads(artifact.payload_json).get('edition_type') == 'roast'
                            and text_source_digest(old, original) == text_source_digest(old, source)):
            return
        retired = list((await db.scalars(select(GenerationOperation.id).where(
            GenerationOperation.subject == artifact.subject, GenerationOperation.state == 'cancelled',
            GenerationOperation.reason == 'recap_source_superseded').order_by(GenerationOperation.id))).all())
        # Only a demonstrably source-superseded job permits a new attempt at a
        # previously seen source. Owner cancellation never creates permission.
        edition = edition_from_snapshot(source, generated_at=episode.observed_at, facts_digest=episode.facts_digest)
        event = 'source-correction:' + digest([artifact.id, text_source_digest(edition, source), retired])
        key = digest([artifact.subject, event])
        if await db.get(GenerationCandidate, key):
            return
        remaining = await allowance(db, artifact.subject, root_id)
        if remaining < 2:
            raise Held('recap_correction_allowance_exhausted')
        payload = {'edition': edition, 'facts': edition['facts'], 'season': episode.season,
            'week': episode.week, 'period_id': episode.period_id, 'recap_facts_digest': episode.facts_digest,
            'source_snapshot': edition['facts']['source_snapshot'], 'event_at': episode.observed_at,
            'correction_base': artifact.id, 'previous_content': old,
            'correction_reason': 'Official scoring evidence changed. This recap was automatically corrected and fact-checked.',
            KEY: {'episode_id': episode.episode_id, 'root_operation_id': root_id,
                  'base_digest': artifact.digest, 'source_digest': text_source_digest(edition, source)}}
        db.add(GenerationCandidate(key=key, series_id=episode.series_id, league_id=episode.league_id,
            feature='analyst', subject=artifact.subject, event=event, payload_json=dump(payload),
            digest=digest(payload), eligible_at=stamp(), hold=''))
        audit(db, 'api-observer', 'recap_automatic_correction_prepared', episode.episode_id,
              'Stable changed facts; original call ceiling and monetary caps retained',
              after={'candidate': key, 'root_operation_id': root_id, 'remaining_calls': remaining})
        await db.flush()
    except Held as exc:
        log.info('Recap correction deferred episode=%s reason=%s', episode.episode_id, exc.code)
