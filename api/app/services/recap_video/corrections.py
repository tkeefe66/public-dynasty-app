"""Free observations, edition-first withdrawal and audited free recovery.

No observation, spelling review or recovery can authorize a new paid request.
"""
import json

from sqlalchemy import select

from app.services.generation.models import ContentArtifact, stamp
from app.services.generation.recap_models import (RecapAttention, RecapDependency, RecapEpisode,
    RecapObservation, RecapProviderAttempt, RecapRecovery, RecapStage)
from app.services.generation.store import Conflict, Held, audit, data, digest, dump, lock_control


def qualified_episode_count(approvals: list[dict]) -> int:
    current = {row['episode_id']: row['passed'] for row in approvals}
    return sum(value is True for value in current.values())


async def attention(db, episode, state, reason):
    key = digest([episode, state, reason])
    if not await db.get(RecapAttention, key):
        db.add(RecapAttention(key=key, episode_id=episode, state=state, reason=reason))
        audit(db, 'api-observer', 'recap_attention', episode, reason)


async def bind_dependencies(db, episode):
    """Conservative context rule: all saved earlier periods in the same season.

    Immutable edges retain exactly which prior observation supported context.
    Narrowing is deferred until article/history claims expose typed operands.
    """
    priors = (await db.scalars(select(RecapEpisode).where(RecapEpisode.series_id == episode.series_id,
        RecapEpisode.season == episode.season, RecapEpisode.week < episode.week))).all()
    for prior in priors:
        if not prior.latest_observation_id or not prior.facts_digest:
            continue
        exists = await db.scalar(select(RecapDependency.id).where(RecapDependency.episode_id == episode.episode_id,
            RecapDependency.prior_episode_id == prior.episode_id,
            RecapDependency.observation_id == prior.latest_observation_id))
        if not exists:
            db.add(RecapDependency(episode_id=episode.episode_id, prior_episode_id=prior.episode_id,
                observation_id=prior.latest_observation_id, facts_digest=prior.facts_digest))


async def invalidate_episode(db, episode, reason, *, actor_id='api-observer'):
    from app.services.recap_video.publication import edition_row, withdraw_edition
    public = await edition_row(db, episode.league_id, episode.season, episode.week)
    withdrawn = None
    if public and not public.withdrawn:
        withdrawn = public.episode_id
        await withdraw_edition(db, episode.league_id, episode.season, episode.week,
            expected_revision=public.authority_revision, actor_id=actor_id, reason=reason)
    episode.lifecycle, episode.hold = 'correction', reason
    for stage in (await db.scalars(select(RecapStage).where(RecapStage.episode_id == episode.episode_id))).all():
        if stage.state != 'succeeded':
            stage.generation += 1
            stage.state, stage.reason, stage.lease_until = 'held', reason, 0
    for attempt in (await db.scalars(select(RecapProviderAttempt).where(
            RecapProviderAttempt.episode_id == episode.episode_id, RecapProviderAttempt.state == 'dispatching'))).all():
        attempt.state = 'unknown'
    await attention(db, episode.episode_id, 'correction', reason)
    return withdrawn


async def withdraw_changed(db, episode, snapshot):
    from app.services.recap_video.readiness import competitive_digest, evaluate_readiness
    from app.services.recap_video.publication import edition_row
    if not episode.facts_digest or episode.facts_digest == competitive_digest(snapshot):
        return []
    # Missing/incomplete sources are an evidence hold, not a proved stat correction.
    if evaluate_readiness(snapshot,None,stamp()).code not in ('facts_unstable','release_not_due','ready'):
        return []
    result = []
    public=await edition_row(db,episode.league_id,episode.season,episode.week)
    has_media=await db.scalar(select(RecapStage.id).where(RecapStage.episode_id==episode.episode_id).limit(1))
    changed = await invalidate_episode(db, episode, 'recap_facts_changed') if public or episode.article_digest or has_media else None
    if changed:
        result.append(changed)
    dependent_ids = (await db.scalars(select(RecapDependency.episode_id).where(
        RecapDependency.prior_episode_id == episode.episode_id).distinct())).all()
    for ident in dependent_ids:
        later = await db.get(RecapEpisode, ident)
        if later:
            changed = await invalidate_episode(db, later, 'recap_dependency_changed')
            if changed:
                result.append(changed)
    return result


async def observe_correction(db, episode_id: str, snapshot: dict, now: int) -> dict:
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    await lock_control(db)
    episode = await db.get(RecapEpisode, episode_id)
    if not episode:
        raise Held('recap_episode_missing')
    withdrawn = await withdraw_changed(db, episode, snapshot)
    await observe_period(db, EpisodeKey(episode.series_id, episode.season, episode.period_id), snapshot, now)
    return dict(episode_id=episode_id, withdrawn=withdrawn)


async def resume_free(db, episode_id, *, stage_id, expected_generation, actor_id, reason):
    from app.services.recap_video.qualification import require_admin_actor
    from app.services.recap_video.speech_reviews import bind_reviews
    from app.services.recap_video.workflow import _current
    await lock_control(db)
    await require_admin_actor(db, actor_id)
    row = await db.get(RecapStage, stage_id, populate_existing=True)
    if not row or row.episode_id != episode_id or row.generation != expected_generation:
        raise Conflict('Checkpoint changed. Reload current episode evidence.')
    if row.kind not in ('speech_check', 'render', 'media_check') or row.state not in ('held', 'needs_attention'):
        raise Held('free_recovery_requires_held_free_checkpoint')
    await _current(db, row, now=stamp())
    rows = list((await db.scalars(select(RecapStage).where(RecapStage.script_id == row.script_id,
        RecapStage.execution_revision == row.execution_revision))).all())
    paid = [stage for stage in rows if stage.kind == 'narrate']
    if not paid or any(stage.state != 'succeeded' for stage in paid):
        raise Held('completed_narration_required')
    affected = {row.id}
    while True:
        expanded = affected | {stage.id for stage in rows if stage.predecessor_id in affected}
        if expanded == affected:
            break
        affected = expanded
    binding = await bind_reviews(db, await db.get(ContentArtifact, row.script_id)) if row.kind == 'speech_check' else None
    for stage in rows:
        if stage.id not in affected:
            continue
        if stage.kind == 'narrate':
            raise Held('paid_recovery_not_permitted')
        db.add(RecapRecovery(episode_id=episode_id, stage_id=stage.id, action='resume_free',
            before_json=dump(data(stage)), actor_id=actor_id, reason=reason))
        inputs = json.loads(stage.input_json)
        if binding is not None:
            inputs['speech_review'] = binding
        stage.input_json, stage.input_digest = dump(inputs), digest(inputs)
        stage.generation += 1
        stage.state, stage.reason, stage.result_json = 'queued', '', ''
        stage.evidence_json, stage.lease_until, stage.failures, stage.next_attempt_at = '{}', 0, 0, 0
    audit(db, actor_id, 'recap_free_recovery', row.id, reason)
    return dict(stage_id=row.id, generation=row.generation, state=row.state)


# Public Task10 interfaces live here; larger qualification logic stays focused.
from app.services.recap_video.qualification import qualification_status, record_preview_approval
