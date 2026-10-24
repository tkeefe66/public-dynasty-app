"""Read exact delivered editions and current source evidence, never HTTP-200 guesses."""
import json
from datetime import datetime

from sqlalchemy import select

from app.services.generation.models import (ArtifactHead, ContentArtifact,
    GenerationOperation, GenerationOutbox, ProviderAttempt)
from app.services.generation.store import digest


def game_gate(expected, observed, now):
    expected_ids = [g['event_id'] for g in expected]
    observed_ids = [g['event_id'] for g in observed]
    if (not expected_ids or len(set(expected_ids)) != len(expected_ids)
            or set(expected_ids) != set(observed_ids) or len(set(observed_ids)) != len(observed_ids)):
        return dict(status='help', reason='schedule_inventory_incomplete',
                    action='Review qualified schedule and completion evidence')
    by_id = {g['event_id']: g for g in expected}
    if any(any(g.get(k) != by_id[g['event_id']].get(k) for k in ('home', 'away')) for g in observed):
        return dict(status='help', reason='schedule_identity_conflict', action='Review changed game identities')
    unfinished = [g for g in observed if not (g.get('completed') is True and
                  g.get('status') in ('STATUS_FINAL', 'STATUS_FINAL_OVERTIME'))]
    if unfinished:
        # Finish estimates are scheduling hints only. A later check must reprove FINAL.
        finishes = [int(datetime.fromisoformat(g['kickoff'].replace('Z', '+00:00')).timestamp()) + 4*3600 for g in unfinished]
        return dict(status='waiting', reason='games_unfinished', gate=max(now + 3600, max(finishes)))
    return dict(status='ready')


def review_approved(attempts):
    reviews = []
    for attempt in attempts:
        if attempt.state != 'received' or not attempt.receipt_json or attempt.usage_state != 'known' or attempt.error_code:
            return False
        receipt = json.loads(attempt.receipt_json)
        body = receipt.get('body', {})
        if isinstance(body, str):
            body = json.loads(body)
        for block in body.get('content', []):
            if block.get('type') == 'tool_use' and block.get('name') == 'submit_recap_review':
                reviews.append(block.get('input', {}).get('approved'))
    return bool(reviews and reviews[-1] is True)


async def publication_proof(db, cache_dir, league_id, season, week):
    from app.routes.analyst import analyst_archive
    # Same member-serving handler, including database publication/withdrawal gates.
    served = await analyst_archive(league_id, db)
    editions = [e for e in served['editions'] if e['season'] == season and e['week'] == week
                and e.get('edition_type') == 'roast' and e.get('markdown', '').strip()]
    if len(editions) != 1:
        return None
    artifacts = (await db.scalars(select(ContentArtifact).join(ArtifactHead,
        ArtifactHead.artifact_id == ContentArtifact.id).where(ContentArtifact.league_id == league_id,
        ContentArtifact.feature == 'analyst', ArtifactHead.hold == ''))).all()
    for artifact in artifacts:
        payload = json.loads(artifact.payload_json)
        if (payload.get('season'), payload.get('week')) != (season, week):
            continue
        job = await db.get(GenerationOperation, artifact.operation_id) if artifact.operation_id else None
        outbox = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + artifact.id))
        if not job or job.state != 'succeeded' or not outbox or not outbox.delivered:
            continue
        attempts = (await db.scalars(select(ProviderAttempt).where(
            ProviderAttempt.operation_id == job.id).order_by(ProviderAttempt.stage))).all()
        # The public archive adds original_markdown while loading revisions.
        comparable = {k: editions[0].get(k) for k in payload if k != 'original_markdown'}
        canonical = {k: v for k, v in payload.items() if k != 'original_markdown'}
        if (digest(payload) != artifact.digest or digest(comparable) != digest(canonical)
                or not review_approved(attempts)):
            continue
        return dict(artifact_id=artifact.id, job_id=job.id, reviewed=True, delivered=True,
                    member_serving_readable=True, text_chars=len(editions[0]['markdown']))
    return None


async def job_evidence(db, league_id, season, week):
    rows = (await db.scalars(select(GenerationOperation).where(
        GenerationOperation.league_id == league_id, GenerationOperation.feature == 'analyst',
        GenerationOperation.kind == 'generation').order_by(GenerationOperation.created_at.desc()))).all()
    related = [r for r in rows if (json.loads(r.payload_json).get('season'),
                json.loads(r.payload_json).get('week')) == (season, week)]
    job = next((r for r in related if r.state not in ('cancelled', 'superseded')), None)
    if not job:
        job = await db.scalar(select(GenerationOperation).where(
            GenerationOperation.league_id == league_id, GenerationOperation.kind == 'analyst_refresh'
        ).order_by(GenerationOperation.created_at.desc()).limit(1))
    attempts = (await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id.in_([r.id for r in related])))).all() if related else []
    return job, dict(settled_microusd=sum(a.cost_microusd or 0 for a in attempts),
                     unknown_cost_count=sum(a.cost_microusd is None for a in attempts))


async def requires_recovery(db, job):
    if job.state in ('held', 'needs_attention'):
        return True
    if job.kind != 'generation' or job.state != 'succeeded' or not job.artifact_id:
        return False
    delivery = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + job.artifact_id))
    return bool(delivery and not delivery.delivered and delivery.error)
