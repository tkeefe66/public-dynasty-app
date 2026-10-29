"""Explicit operator-reviewed article revisions. No generation or provider calls.

This operator service is not a scheduler fallback: a full editorial review of the
exact text and current source must precede application of its preview fingerprint.
Original artifacts and paid receipts remain immutable and separately attributed.
"""
import json

from sqlalchemy import func, select

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationOperation, GenerationOutbox, ProviderAttempt
from app.services.generation.recap_models import RecapEpisode, RecapObservation, RecapProviderAttempt, RecapStage
from app.services.generation.store import Held, audit, digest, dump, lock_control
from app.services.recap_video.publication import edition_row, serving_gate
from app.services.recap_video.qualification import require_admin_actor
from app.services.recap_video.text_authority import current_source, reviewed_article


async def receipt_binding(db, operation_id):
    rows = list((await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == operation_id))).all())
    if not rows or any(r.state != 'received' or r.usage_state != 'known' or r.cost_microusd is None
                       or not r.receipt_json or r.error_code for r in rows):
        raise Held('editorial_revision_receipts_unsettled')
    return sorted([r.id, digest([r.receipt_json, r.cost_microusd])] for r in rows)


async def verify_review(db, episode, artifact):
    proof = json.loads(artifact.facts_json).get('operator_review', {})
    gate = await serving_gate(db)
    original = await db.get(ContentArtifact, proof.get('original_artifact_id', ''))
    observation = await db.get(RecapObservation, proof.get('observation_id', ''))
    if (not proof.get('reviewer') or not proof.get('review_notes') or not proof.get('actor_id')
            or proof.get('corrected_digest') != artifact.digest or proof.get('serving_epoch') != gate.epoch
            or not original or original.subject != artifact.subject or not original.operation_id
            or original.digest != proof.get('original_digest') or digest(json.loads(original.payload_json)) != original.digest
            or not observation or observation.episode_id != episode.episode_id
            or observation.snapshot_digest != proof.get('source_digest')
            or digest(json.loads(observation.snapshot_json)) != observation.snapshot_digest
            or await receipt_binding(db, original.operation_id) != proof.get('receipts')):
        raise Held('editorial_revision_review_changed')
    return proof


async def revise(db, episode_id, *, artifact_id, actor_id, cache_dir, edits, reviewer,
                 review_notes, reason, apply=False, expected_digest=None):
    if apply:
        await lock_control(db)
    await require_admin_actor(db, actor_id)
    gate = await serving_gate(db)
    episode = await db.get(RecapEpisode, episode_id, populate_existing=True)
    if not episode or not episode.admitted_at or episode.hold not in ('recap_facts_changed', 'recap_editorial_correction_required'):
        raise Held('editorial_revision_hold_required')
    if await edition_row(db, episode.league_id, episode.season, episode.week):
        raise Held('editorial_revision_media_requires_separate_review')
    original, data, job = await reviewed_article(db, episode)
    if original.id != artifact_id or not job:
        raise Held('editorial_revision_original_head_required')
    receipts = await receipt_binding(db, job.id)
    source = await current_source(db, episode)
    # This explicit full-article review repairs prose about existing results.
    # It may rebind fresh player details without waiting for the scheduler's
    # one-hour quiet window, but cannot authorize changed outcomes or lineups.
    prior_source = data.get('facts', {}).get('source_snapshot') or {}
    if (not prior_source.get('pairings') or prior_source.get('pairings') != source.get('pairings')
            or prior_source.get('starters') != source.get('starters')
            or any(prior_source.get(key) != source.get(key) for key in ('season', 'week', 'period_id', 'roster_positions'))):
        raise Held('editorial_revision_results_or_lineups_changed')
    stages = list((await db.scalars(select(RecapStage).where(RecapStage.episode_id == episode_id))).all())
    if (any(s.kind != 'preflight' or s.state not in ('held', 'succeeded') or s.lease_until for s in stages)
            or await db.scalar(select(RecapProviderAttempt.id).where(RecapProviderAttempt.episode_id == episode_id).limit(1))):
        raise Held('editorial_revision_media_started')
    for other in (await db.scalars(select(GenerationOperation).where(GenerationOperation.league_id == episode.league_id))).all():
        if other.id != job.id and other.subject == original.subject and other.state not in ('succeeded', 'cancelled', 'failed', 'rejected'):
            raise Held('editorial_revision_generation_active')
        if (other.feature == 'recap_video' and other.kind != 'media_preflight'
                and json.loads(other.payload_json).get('episode_id') == episode_id
                and (other.calls or other.state not in ('cancelled', 'failed', 'rejected'))):
            raise Held('editorial_revision_media_started')
    if not all(isinstance(v, str) and v.strip() for v in (reviewer, review_notes, reason)) or not edits:
        raise Held('editorial_revision_full_review_required')
    text = data['markdown']
    for edit in edits:
        if (set(edit) != {'before', 'after'} or not isinstance(edit['before'], str)
                or not edit['before'] or not isinstance(edit['after'], str) or text.count(edit['before']) != 1):
            raise Held('editorial_revision_exact_anchor_required')
        text = text.replace(edit['before'], edit['after'], 1)
    if not text.strip() or text == data['markdown']:
        raise Held('editorial_revision_empty')
    from app.services.analyst_store import AnalystEdition
    from app.services.recap_video.collector import edition_from_snapshot
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket
    from sleeper_dynasty.llm.recap_writer import require_matchup_coverage, require_scoring_claims
    facts = edition_from_snapshot(source, generated_at=episode.observed_at)['facts']
    facts['league_name'] = data['league_name']
    require_matchup_coverage(text, ArchivedPacket(facts), None)
    require_scoring_claims(text, ArchivedPacket(facts))
    revision = 1 + (await db.scalar(select(func.max(ContentArtifact.revision)).where(ContentArtifact.subject == original.subject)) or 0)
    corrected = AnalystEdition.model_validate({**data, 'markdown': text, 'facts': facts, 'outlook': None,
        'lore': None, 'revision': revision, 'original_markdown': None, 'correction_note': reason}).model_dump()
    proof = dict(original_artifact_id=original.id, original_digest=original.digest,
        corrected_digest=digest(corrected), observation_id=episode.latest_observation_id,
        source_digest=episode.source_digest, serving_epoch=gate.epoch, receipts=receipts,
        reviewer=reviewer, review_notes=review_notes, actor_id=actor_id, edits=edits,
        stages=sorted([s.id, s.generation, s.state, s.input_digest] for s in stages))
    fingerprint = digest(proof)
    report = dict(digest=fingerprint, applied=False, markdown=text, provider_requests=0, added_cost_microusd=0)
    if not apply:
        return report
    if expected_digest != fingerprint:
        raise Held('editorial_revision_preview_changed')
    replacement = ContentArtifact(series_id=original.series_id, league_id=original.league_id, feature='analyst',
        subject=original.subject, revision=revision, payload_json=dump(corrected), digest=digest(corrected),
        facts_json=dump({'operator_review': proof, 'recap_facts_digest': episode.facts_digest}), provenance='operator_reviewed_correction')
    from app.services.generation.publication import project_analyst
    project_analyst(cache_dir, replacement, original)
    db.add(replacement)
    await db.flush()
    head = await db.get(ArtifactHead, original.subject)
    head.artifact_id, head.revision = replacement.id, revision
    # Text authority is independent of media. Preserve the media hold: clearing
    # it would admit paid scripts on the next automatic workflow tick.
    episode.article_digest = replacement.digest
    db.add(GenerationOutbox(key='artifact:' + replacement.id, kind='artifact', delivered=True,
        payload_json=dump({'artifact_id': replacement.id, 'expected_artifact': original.id, 'operator_review_digest': fingerprint})))
    audit(db, actor_id, 'recap_operator_editorial_revision', episode_id, reason,
        before={'artifact_id': original.id, 'digest': original.digest},
        after={'artifact_id': replacement.id, 'digest': replacement.digest, 'review_digest': fingerprint, 'provider_requests': 0})
    return {**report, 'applied': True, 'artifact_id': replacement.id}
