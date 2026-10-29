"""Explicit resume of a first video from an already reviewed current article.

Text-only repair never grants this authority. No provider call, cap adjustment,
old-media reuse, or uncertain receipt replay happens here.
"""
import json

from sqlalchemy import select

from app.services.generation.models import GenerationOperation, GenerationAudit
from app.services.generation.recap_models import RecapEpisode, RecapProviderAttempt, RecapStage
from app.services.generation.store import Held, audit, lock_control


async def resume_video(db, episode_id, *, actor_id, reason):
    from app.services.recap_video.qualification import require_admin_actor, calibration
    from app.services.recap_video.text_authority import current_source, reviewed_article, member_text_current
    from app.services.recap_video.readiness import source_ready, _authority_reason, EpisodeKey
    from app.services.recap_video.publication import edition_row
    from app.services.recap_video.contracts import _published_article

    await lock_control(db)
    await require_admin_actor(db, actor_id)
    episode = await db.get(RecapEpisode, episode_id)
    if (not episode or not episode.admitted_at or episode.hold not in
            ('recap_facts_changed', 'recap_editorial_correction_required')):
        raise Held('recap_video_corrected_article_required')
    denied = await _authority_reason(db, EpisodeKey(episode.series_id, episode.season, episode.period_id),
                                    episode.league_id, media_checkpoint=True)
    if denied:
        raise Held(denied)
    source = await current_source(db, episode)
    if not source_ready(episode, source):
        raise Held('correction_stable_facts_required')
    artifact, edition, _ = await reviewed_article(db, episode)
    if not await member_text_current(db, episode, edition):
        raise Held('recap_video_current_reviewed_article_required')
    await _published_article(db, episode)
    await calibration(db, episode.series_id, episode.season)
    publication = await edition_row(db, episode.league_id, episode.season, episode.week)
    if publication and (publication.media_id or publication.withdrawn or publication.hold):
        raise Held('recap_video_existing_publication_requires_review')
    stages = (await db.scalars(select(RecapStage).where(RecapStage.episode_id == episode_id))).all()
    if (any(s.kind != 'preflight' or s.state not in ('held', 'succeeded') or s.lease_until for s in stages)
            or await db.scalar(select(RecapProviderAttempt.id).where(RecapProviderAttempt.episode_id == episode_id).limit(1))):
        raise Held('recap_video_saved_media_requires_review')
    jobs = (await db.scalars(select(GenerationOperation).where(
        GenerationOperation.league_id == episode.league_id, GenerationOperation.feature == 'recap_video',
        GenerationOperation.kind != 'media_preflight'))).all()
    if any((j.subject == 'recap_video:'+episode_id or json.loads(j.payload_json).get('episode_id') == episode_id)
           and (j.calls or j.artifact_id or j.state not in ('cancelled', 'failed', 'rejected')) for j in jobs):
        raise Held('recap_video_saved_script_requires_review')
    if not reason.strip():
        raise Held('recap_video_resume_reason_required')
    episode.lifecycle, episode.hold = 'ready', ''
    result = dict(episode_id=episode_id, article_id=artifact.id, article_digest=artifact.digest,
                  facts_digest=episode.facts_digest, provider_requests=0, limits_changed=False)
    audit(db, actor_id, 'recap_video_corrected_article_resumed', episode_id, reason, after=result)
    return result


async def first_video_resume_authorized(db, episode, article):
    """A resume binds one corrected article, never future revisions or retakes."""
    from app.services.recap_video.qualification import require_admin_actor
    rows = (await db.scalars(select(GenerationAudit).where(
        GenerationAudit.target == episode.episode_id,
        GenerationAudit.action == 'recap_video_corrected_article_resumed'))).all()
    for row in rows:
        proof = json.loads(row.after_json)
        if (proof.get('article_id') == article['artifact_id'] and proof.get('article_digest') == article['digest']
                and proof.get('facts_digest') == episode.facts_digest):
            await require_admin_actor(db, row.actor_id)
            return True
    return False


async def resume_automatic_articles(db):
    """First-video continuation only for a managed automatic text correction.

    Operator text-only repairs require the explicit resume action; completed or
    uncertain media retains its separate review/recovery path and all receipts.
    """
    from app.services.recap_video.text_authority import reviewed_article
    from app.services.recap_video.qualification import qualification_status
    from app.services.recap_video.workflow import preparation_attention
    episodes = (await db.scalars(select(RecapEpisode).where(RecapEpisode.lifecycle == 'correction',
        RecapEpisode.hold.in_(('recap_facts_changed', 'recap_editorial_correction_required'))).limit(50))).all()
    for episode in episodes:
        try:
            async with db.begin_nested():
                artifact, _, job = await reviewed_article(db, episode)
                if (artifact.provenance != 'managed' or not job or job.kind != 'generation'
                        or not json.loads(job.payload_json).get('automatic_recap_correction')):
                    continue
                status = await qualification_status(db, episode.series_id, episode.season)
                if not status['automatic']:
                    raise Held(status['reason'])
                await resume_video(db, episode.episode_id, actor_id=job.actor_id,
                    reason='Automatic first-video continuation from reviewed corrected article; existing limits retained')
        except Held as exc:
            await preparation_attention(db, episode.episode_id, exc.code)
