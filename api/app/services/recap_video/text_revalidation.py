"""Explicit review of unchanged member text after an unused bench-score correction.

Does not clear episode/media holds, rewrite artifacts, resume jobs, or grant sharing.
An audit binds the exact article and competitive evidence; any later change expires it.
"""
import copy
import json
import re
from decimal import Decimal

from sqlalchemy import select

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationAudit, GenerationOperation, GenerationOutbox, ProviderAttempt
from app.services.generation.recap_models import RecapEpisode, RecapObservation
from app.services.generation.store import Held, audit, digest, lock_control
from app.services.recap_video.publication import edition_row, serving_gate
from app.services.recap_video.readiness import competitive_digest, competitive_facts, source_ready

ACTION = 'recap_member_text_revalidated'


def bench_changes(edition, current):
    original = edition.get('facts', {}).get('source_snapshot')
    if not isinstance(original, dict):
        raise Held('text_revalidation_original_source_required')
    before, after = competitive_facts(original), competitive_facts(current)
    comparable = copy.deepcopy(after)
    changes = []
    try:
        for week, rows in before['scores'].items():
            for index, row in enumerate(rows):
                other = comparable['scores'][week][index]
                for player, value in row['players_points'].items():
                    new = other['players_points'][player]
                    if value == new:
                        continue
                    if (player in row['starters'] or player in other['starters']
                            or not Decimal(str(value)).is_finite() or not Decimal(str(new)).is_finite()):
                        raise Held('text_revalidation_material_change')
                    changes.append({'week': week, 'roster_id': row['roster_id'], 'player_id': player,
                                    'before': value, 'after': new})
                    other['players_points'][player] = value
        if not changes or comparable != before:
            raise Held('text_revalidation_material_change')
        text = edition['markdown']
        if (re.search(r'\b(bench|benched|optimal|regret|substitution)\b', text, re.I)
                or edition['facts'].get('bench_regret')
                or any(str(change[key]) in text for change in changes for key in ('before', 'after'))):
            raise Held('text_revalidation_bench_claim_requires_correction')
    except (KeyError, TypeError, IndexError, ArithmeticError, ValueError) as exc:
        raise Held('text_revalidation_evidence_incomplete') from exc
    return changes


async def evidence(db, episode):
    from app.services.recap_monitor.evidence import review_approved
    from app.services.generation.analyst_review_recovery import publication_attempts
    if (not episode or not episode.admitted_at or episode.lifecycle != 'correction'
            or episode.hold != 'recap_facts_changed'
            or await edition_row(db, episode.league_id, episode.season, episode.week)):
        raise Held('text_revalidation_unpublished_media_free_edition_required')
    artifact = await db.scalar(select(ContentArtifact).where(
        ContentArtifact.league_id == episode.league_id, ContentArtifact.series_id == episode.series_id,
        ContentArtifact.feature == 'analyst', ContentArtifact.digest == episode.article_digest))
    if not artifact:
        raise Held('text_revalidation_article_missing')
    payload = json.loads(artifact.payload_json)
    head = await db.get(ArtifactHead, artifact.subject)
    outbox = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + artifact.id))
    job = await db.get(GenerationOperation, artifact.operation_id) if artifact.operation_id else None
    observation = await db.get(RecapObservation, episode.latest_observation_id)
    source = json.loads(observation.snapshot_json) if observation else {}
    if (not head or head.hold or head.artifact_id != artifact.id or head.revision != artifact.revision
            or digest(payload) != artifact.digest or payload.get('edition_type') != 'roast'
            or (payload.get('season'), payload.get('week')) != (episode.season, episode.week)
            or not outbox or not outbox.delivered or outbox.error
            or json.loads(outbox.payload_json).get('artifact_id') != artifact.id
            or not job or job.state != 'succeeded' or job.artifact_id != artifact.id
            or job.feature != 'analyst' or job.league_id != episode.league_id
            or not observation or observation.episode_id != episode.episode_id
            or digest(source) != observation.snapshot_digest or observation.snapshot_digest != episode.source_digest
            or not source_ready(episode, source)):
        raise Held('text_revalidation_evidence_changed')
    attempts = list((await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id == job.id).order_by(ProviderAttempt.stage))).all())
    attempts = await publication_attempts(db, job, payload, attempts)
    if not review_approved(attempts):
        raise Held('text_revalidation_original_review_required')
    changes = bench_changes(payload, source)
    gate = await serving_gate(db)
    return {'episode_id': episode.episode_id, 'artifact_id': artifact.id, 'article_digest': artifact.digest,
            'source_facts_digest': competitive_digest(source), 'changes': changes, 'serving_epoch': gate.epoch}, payload


async def revalidate(db, episode_id, *, actor_id, reviewer, reason, apply=False, expected_digest=None):
    from app.services.recap_video.qualification import require_admin_actor
    if apply:
        await lock_control(db)
    await require_admin_actor(db, actor_id)
    if not reviewer.strip() or not reason.strip():
        raise Held('text_revalidation_independent_review_required')
    proof, _ = await evidence(db, await db.get(RecapEpisode, episode_id, populate_existing=True))
    proof.update(reviewer=reviewer, reason=reason, review_kind='operator_assisted_text_review')
    fingerprint = digest(proof)
    if apply:
        if expected_digest != fingerprint:
            raise Held('text_revalidation_preview_changed')
        audit(db, actor_id, ACTION, episode_id, reason, after=proof)
        await db.flush()
    return {'digest': fingerprint, 'applied': apply, 'changes': proof['changes'], 'provider_requests': 0}


async def member_text_revalidated(db, episode_id, edition):
    row = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == ACTION,
        GenerationAudit.target == episode_id).order_by(GenerationAudit.created_at.desc()).limit(1))
    if not row:
        return False
    try:
        proof, payload = await evidence(db, await db.get(RecapEpisode, episode_id))
        saved = json.loads(row.after_json)
        comparable = {key: edition.get(key) for key in payload if key != 'original_markdown'}
        return (all(saved.get(key) == value for key, value in proof.items())
                and digest(comparable) == digest({k: v for k, v in payload.items() if k != 'original_markdown'}))
    except (Held, ValueError, KeyError, TypeError):
        return False
