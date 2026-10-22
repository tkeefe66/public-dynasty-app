"""Explicit, receipt-only recovery of false live-roster withdrawals.

This incident recovery does not adopt legacy media into the generation pipeline,
change sharing consent, or authorize any provider request. The caller owns the
transaction. File/media verification remains enforced by the normal read path.
"""
import json

from sqlalchemy import select

from app.services.generation.models import (ArtifactHead, ContentArtifact, GenerationAudit,
    GenerationOperation, GenerationOutbox, ProviderAttempt, stamp)
from app.services.generation.recap_models import (RecapAttention, RecapEpisode,
    RecapObservation, RecapPublication, RecapShareDecision, RecapStage)
from app.services.generation.store import Held, audit, digest, lock_control
from app.services.recap_video.publication import legacy_episode_id, public_article, serving_gate
from app.services.recap_video.qualification import require_admin_actor
from app.services.recap_video.readiness import competitive_digest, evaluate_readiness


async def recover_false_withdrawal(db, episode_id, *, expected_revision, artifact_id,
                                   actor_id, reason, apply=False, expected_digest=None):
    """Preview/apply one exact imported edition; never perform paid work.

    Run the preview in a read-only transaction when operationally possible. Apply
    rechecks every proof under the generation control lock and requires its digest.
    The report deliberately does not claim the API filesystem has been verified.
    """
    if not reason.strip():
        raise Held('recovery_reason_required')
    if apply:
        await lock_control(db)
    await require_admin_actor(db, actor_id)
    gate = await serving_gate(db)
    episode = await db.get(RecapEpisode, episode_id, populate_existing=True)
    if (not episode or episode.admitted_at or episode.article_digest
            or episode.lifecycle != 'correction' or episode.hold != 'recap_facts_changed'):
        raise Held('legacy_false_withdrawal_episode_required')
    legacy_id = legacy_episode_id(episode.league_id, episode.season, episode.week)
    row = await db.get(RecapPublication, legacy_id, populate_existing=True)
    if (not row or row.article_id or not row.withdrawn or row.hold
            or row.authority_revision != expected_revision or row.epoch != gate.epoch):
        raise Held('legacy_withdrawal_authority_changed')
    if await db.scalar(select(RecapStage.id).where(RecapStage.episode_id == episode_id).limit(1)):
        raise Held('legacy_recovery_has_canonical_media')
    withdrawals = (await db.scalars(select(GenerationAudit).where(
        GenerationAudit.target == legacy_id, GenerationAudit.action == 'recap_publication_withdrawn')
        .order_by(GenerationAudit.created_at))).all()
    if (len(withdrawals) != 1 or withdrawals[0].reason != 'recap_facts_changed'
            or withdrawals[0].actor_id != 'api-observer'):
        raise Held('legacy_false_withdrawal_audit_required')
    withdrawal = withdrawals[0]

    artifact = await db.get(ContentArtifact, artifact_id, populate_existing=True)
    if (not artifact or artifact.feature != 'analyst' or artifact.league_id != episode.league_id
            or artifact.series_id != episode.series_id or artifact.created_at > row.published_at):
        raise Held('legacy_original_artifact_required')
    data = json.loads(artifact.payload_json)
    head = await db.get(ArtifactHead, artifact.subject, populate_existing=True)
    projection = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + artifact.id))
    if (not head or head.hold or head.artifact_id != artifact.id or head.revision != artifact.revision
            or digest(data) != artifact.digest or data.get('revision') != artifact.revision
            or data.get('season') != episode.season or data.get('week') != episode.week
            or digest(public_article(data)) != row.article_digest
            or digest(json.loads(row.article_json)) != row.article_digest
            or not projection or not projection.delivered or projection.error or projection.kind != 'artifact'
            or json.loads(projection.payload_json).get('artifact_id') != artifact.id):
        raise Held('legacy_original_article_changed')
    operation = await db.get(GenerationOperation, artifact.operation_id, populate_existing=True) if artifact.operation_id else None
    if (not operation or operation.state != 'succeeded' or operation.artifact_id != artifact.id
            or operation.league_id != episode.league_id or operation.feature != 'analyst'):
        raise Held('legacy_original_operation_required')
    receipts = (await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == operation.id))).all()
    if (not receipts or len(receipts) != operation.calls or any(
            r.state != 'received' or r.usage_state != 'known' or r.cost_microusd is None or not r.receipt_json
            for r in receipts)):
        raise Held('legacy_original_receipts_unsettled')
    if await db.scalar(select(GenerationOperation.id).where(
            GenerationOperation.subject == artifact.subject,
            GenerationOperation.id != operation.id,
            GenerationOperation.created_at >= withdrawal.created_at).limit(1)):
        raise Held('legacy_recovery_has_new_generation')

    observations = (await db.scalars(select(RecapObservation).where(
        RecapObservation.episode_id == episode_id).order_by(RecapObservation.observed_at))).all()
    baseline = None
    valid = []
    for observation in observations:
        source = json.loads(observation.snapshot_json)
        if digest(source) != observation.snapshot_digest:
            raise Held('legacy_observation_integrity_failed')
        if evaluate_readiness(source, None, stamp()).code not in ('ready', 'facts_unstable', 'release_not_due'):
            continue  # An incomplete fetch is not evidence of a changed score.
        valid.append((observation, source))
        if baseline is None and row.published_at <= observation.observed_at < withdrawal.created_at:
            baseline = (observation, source)
    if not baseline or not valid or valid[-1][0].id != episode.latest_observation_id:
        raise Held('legacy_recovery_current_evidence_required')
    canonical = competitive_digest(baseline[1])
    # Continuity since import does not prove a pre-import article was correct.
    # Require the complete period evidence sealed inside that original approved
    # artifact. Named legacy prose facts alone cannot prove player/lineup/rules
    # identity, and a caller-supplied review assertion is not a substitute.
    approved_source = (data.get('facts') or {}).get('source_snapshot')
    if not isinstance(approved_source, dict) or competitive_digest(approved_source) != canonical:
        raise Held('legacy_original_source_equivalence_unproven')
    relevant = [(o, s) for o, s in valid if o.observed_at >= baseline[0].observed_at]
    if any(competitive_digest(source) != canonical for _, source in relevant):
        raise Held('legacy_recovery_competitive_facts_changed')
    if relevant[-1][0].observed_at - baseline[0].observed_at < 3600:
        raise Held('legacy_recovery_stable_evidence_required')
    shares = (await db.scalars(select(RecapShareDecision).where(RecapShareDecision.scope.in_(
        ['edition:' + legacy_id, 'edition:' + episode_id, 'series:' + episode.series_id]))
        .order_by(RecapShareDecision.scope))).all()
    proof = dict(episode_id=episode_id, publication_id=legacy_id, expected_revision=expected_revision,
        article_id=artifact.id, article_digest=artifact.digest, imported_article_digest=row.article_digest,
        withdrawal_id=withdrawal.id, baseline_observation_id=baseline[0].id,
        latest_observation_id=episode.latest_observation_id, competitive_digest=canonical,
        approved_source_digest=digest(approved_source),
        observation_digests=[(o.id, o.snapshot_digest) for o in observations],
        media_digest=digest([row.media_id, row.media_json]), enabled=row.enabled,
        shares=[(s.scope, s.revision, s.allowed, s.opted_out, s.token_digest) for s in shares],
        receipt_digests=sorted((r.id, digest([r.receipt_json, r.cost_microusd])) for r in receipts),
        serving_epoch=gate.epoch)
    fingerprint = digest(proof)
    report = dict(digest=fingerprint, applied=False, episode_id=episode_id,
        publication_id=legacy_id, authority_revision=row.authority_revision,
        artifact_id=artifact.id, media_id=row.media_id, competitive_digest=canonical,
        provider_requests=0, added_cost_microusd=0, filesystem_verified=False)
    if not apply:
        return report
    if expected_digest != fingerprint:
        raise Held('recovery_preview_changed')
    # This restores only the exact approved imported authority. Immutable content,
    # media metadata and share tombstones remain byte-for-byte unchanged.
    row.withdrawn = False
    row.authority_revision += 1
    row.projected_revision = row.authority_revision
    episode.lifecycle, episode.hold = 'held', 'historical_approval_required'
    for attention in (await db.scalars(select(RecapAttention).where(
            RecapAttention.episode_id == episode_id, RecapAttention.reason == 'recap_facts_changed'))).all():
        attention.state = 'resolved'
    audit(db, actor_id, 'recap_false_withdrawal_recovered', legacy_id, reason,
        before={'withdrawn': True, 'authority_revision': expected_revision},
        after={'withdrawn': False, 'authority_revision': row.authority_revision, 'proof_digest': fingerprint,
               'artifact_id': artifact.id, 'competitive_digest': canonical})
    return {**report, 'applied': True, 'authority_revision': row.authority_revision}
