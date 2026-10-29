"""Member text authority is independent of media, with exact source evidence."""
import json

from sqlalchemy import select

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationAudit, GenerationOperation, GenerationOutbox, ProviderAttempt
from app.services.generation.store import Held, digest
from app.services.generation.recap_models import RecapObservation
from app.services.recap_video.readiness import competitive_facts, evaluate_readiness


def text_source_digest(edition, source):
    facts = competitive_facts(source)
    if period_local(edition):
        from sleeper_dynasty.llm.recap_packet import period_text_source
        facts = period_text_source(facts)
    return digest(facts)


def period_local(edition):
    from sleeper_dynasty.llm.recap_packet import period_local_facts
    return period_local_facts(edition.get('facts', {})) and not edition.get('outlook') and not edition.get('lore')


async def reviewed_article(db, episode):
    """Canonical head + delivered projection + original review receipts."""
    rows = (await db.scalars(select(ContentArtifact).join(ArtifactHead,
        ArtifactHead.artifact_id == ContentArtifact.id).where(
        ContentArtifact.feature == 'analyst', ContentArtifact.series_id == episode.series_id,
        ContentArtifact.league_id == episode.league_id, ArtifactHead.hold == ''))).all()
    matching = [r for r in rows if (json.loads(r.payload_json).get('season'),
        json.loads(r.payload_json).get('week')) == (episode.season, episode.week)]
    if len(matching) != 1:
        raise Held('recap_text_article_missing')
    artifact = matching[0]
    if episode.article_digest and episode.article_digest != artifact.digest:
        raise Held('recap_text_article_unprojected')
    payload = json.loads(artifact.payload_json)
    head = await db.get(ArtifactHead, artifact.subject)
    outbox = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + artifact.id))
    if (digest(payload) != artifact.digest or payload.get('edition_type') != 'roast'
            or (payload.get('season'), payload.get('week')) != (episode.season, episode.week)
            or head.revision != artifact.revision or not outbox or not outbox.delivered or outbox.error
            or json.loads(outbox.payload_json).get('artifact_id') != artifact.id):
        raise Held('recap_text_article_changed')
    if artifact.provenance == 'operator_reviewed_correction':
        from app.services.recap_video.editorial_revision import verify_review
        proof = await verify_review(db, episode, artifact)
        original = await db.get(ContentArtifact, proof['original_artifact_id'])
        job = await db.get(GenerationOperation, original.operation_id)
        if not job or job.state != 'succeeded' or job.artifact_id != original.id or job.subject != artifact.subject:
            raise Held('editorial_revision_original_review_changed')
        return artifact, payload, job
    if artifact.provenance == 'reviewed_receipt_only_correction':
        proof = json.loads(artifact.facts_json).get('recovery_proof', {})
        from app.services.recap_video.publication import serving_gate
        gate = await serving_gate(db)
        original = await db.get(ContentArtifact, proof.get('article_id', ''))
        baseline = await db.get(RecapObservation, proof.get('baseline_observation_id', ''))
        if (proof.get('corrected_digest') != artifact.digest or not proof.get('editorial_review')
                or not proof.get('legacy_claim_proof') or proof.get('serving_epoch') != gate.epoch
                or not original or original.digest != proof.get('article_digest')
                or digest(json.loads(original.payload_json)) != original.digest
                or original.subject != artifact.subject or not original.operation_id
                or not baseline or baseline.episode_id != episode.episode_id
                or [baseline.id, baseline.snapshot_digest] not in proof.get('observation_digests', [])
                or digest(json.loads(baseline.snapshot_json)) != baseline.snapshot_digest):
            raise Held('recap_text_legacy_proof_changed')
        receipts = list((await db.scalars(select(ProviderAttempt).where(
            ProviderAttempt.operation_id == original.operation_id))).all())
        if (not receipts or any(r.cost_microusd is None for r in receipts)
                or sorted([r.id, digest([r.receipt_json, r.cost_microusd])] for r in receipts) != proof.get('receipt_digests')):
            raise Held('recap_text_legacy_receipts_changed')
        return artifact, payload, None
    job = await db.get(GenerationOperation, artifact.operation_id) if artifact.operation_id else None
    if not job or job.state != 'succeeded' or job.artifact_id != artifact.id or job.subject != artifact.subject:
        raise Held('recap_text_original_review_required')
    attempts = list((await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id == job.id).order_by(ProviderAttempt.stage))).all())
    from app.services.generation.analyst_review_recovery import publication_attempts
    from app.services.recap_monitor.evidence import review_approved
    attempts = await publication_attempts(db, job, payload, attempts)
    if not attempts or not review_approved(attempts):
        raise Held('recap_text_original_review_required')
    return artifact, payload, job


async def current_source(db, episode, *, last_valid=False):
    observation = await db.get(RecapObservation, episode.latest_observation_id)
    source = json.loads(observation.snapshot_json) if observation else {}
    if (not observation or observation.episode_id != episode.episode_id
            or digest(source) != observation.snapshot_digest or episode.source_digest != observation.snapshot_digest):
        raise Held('recap_text_source_integrity')
    if evaluate_readiness(source, None, episode.observed_at).code not in ('ready', 'facts_unstable', 'release_not_due'):
        if last_valid:
            observations = (await db.scalars(select(RecapObservation).where(
                RecapObservation.episode_id == episode.episode_id,
                RecapObservation.observed_at <= episode.observed_at).order_by(
                RecapObservation.observed_at.desc()))).all()
            for previous in observations:
                candidate = json.loads(previous.snapshot_json)
                if digest(candidate) != previous.snapshot_digest:
                    raise Held('recap_text_source_integrity')
                if evaluate_readiness(candidate, None, previous.observed_at).code in ('ready', 'facts_unstable', 'release_not_due'):
                    return candidate
        raise Held('recap_text_source_unavailable')
    return source


async def automatic_withdrawal(db, publication):
    if publication.hold:
        return False
    if not publication.withdrawn:
        return True
    query = select(GenerationAudit).where(
        GenerationAudit.target == publication.episode_id,
        GenerationAudit.action == 'recap_publication_withdrawn').order_by(
        GenerationAudit.created_at.desc())
    rows = list((await db.scalars(query)).all())
    exact = [r for r in rows if json.loads(r.after_json).get('authority_revision') == publication.authority_revision]
    latest = exact if exact else [r for r in rows if r.created_at == rows[0].created_at] if rows else []
    return bool(latest and all((r.actor_id, r.reason) in (
        ('api-observer', 'recap_facts_changed'), ('api-observer', 'recap_dependency_changed'),
        ('api-observer', 'recap_dependency_inventory_changed'),
        ('api-projector', 'Article revision requires reviewed media reattachment')) for r in latest))


async def requires_text_proof(db, episode):
    rows = (await db.scalars(select(ContentArtifact).join(ArtifactHead,
        ArtifactHead.artifact_id == ContentArtifact.id).where(ContentArtifact.feature == 'analyst',
        ContentArtifact.league_id == episode.league_id, ContentArtifact.series_id == episode.series_id))).all()
    return any(((row.operation_id and json.loads(row.payload_json).get('facts', {}).get('source_snapshot'))
        or (row.provenance == 'operator_reviewed_correction')
        or (row.provenance == 'reviewed_receipt_only_correction'
            and json.loads(row.facts_json).get('recovery_proof'))) and (json.loads(row.payload_json).get('season'),
        json.loads(row.payload_json).get('week')) == (episode.season, episode.week) for row in rows)


async def member_text_current(db, episode, edition):
    """No mutations on read; media and sharing retain their separate gates."""
    from app.services.recap_video.publication import edition_row, serving_gate
    try:
        gate = await serving_gate(db)
        artifact, payload, job = await reviewed_article(db, episode)
        comparable = {k: edition.get(k) for k in payload if k != 'original_markdown'}
        if digest(comparable) != digest({k: v for k, v in payload.items() if k != 'original_markdown'}):
            return False
        row = await edition_row(db, episode.league_id, episode.season, episode.week)
        if row and (row.epoch != gate.epoch or not await automatic_withdrawal(db, row)):
            return False
        if not row and job:
            from app.config import get_settings
            from app.services.generation.models import GenerationControl
            control = await db.get(GenerationControl, 'global')
            if (not control or control.hold == 'restore_reconciled' or job.epoch != control.epoch
                    or job.epoch != get_settings().generation_execution_epoch):
                return False
        # Legacy cross-period prose cannot waive dependency invalidation.
        if (episode.hold.startswith('recap_dependency')
                and not period_local(payload)):
            return False
        original = payload.get('facts', {}).get('source_snapshot')
        if not original and artifact.provenance == 'reviewed_receipt_only_correction':
            proof = json.loads(artifact.facts_json)['recovery_proof']
            baseline = await db.get(RecapObservation, proof['baseline_observation_id'])
            original = json.loads(baseline.snapshot_json)
        return bool(original and text_source_digest(payload, original) ==
                    text_source_digest(payload, await current_source(db, episode, last_valid=True)))
    except (Held, ValueError, TypeError, KeyError):
        return False
