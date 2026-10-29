"""Read-only, member-safe explanation for an edition without authorized media."""
from sqlalchemy import select

from app.services.generation.models import LeagueSeason
from app.services.generation.recap_models import RecapAttention, RecapEpisode, RecapStage
from app.services.generation.store import resolve_policy


def state(status, reason, message, enabled=True):
    return dict(status=status, reason=reason, message=message, enabled=enabled)


async def video_status(db, league_id: str, season: int, week: int) -> dict:
    """Never grants playback authority, creates work, or exposes raw error text."""
    league = await db.get(LeagueSeason, league_id)
    if not league or league.season != season:
        return state('unavailable', 'no_video', 'No video is available for this edition.', False)
    config = await resolve_policy(db, league.series_id)
    feature = config['policy']['features'].get('recap_video', {})
    if not feature or feature.get('mode') == 'disabled':
        return state('disabled', 'video_disabled', 'Video recaps are not enabled for this league.', False)
    episode = await db.scalar(select(RecapEpisode).where(
        RecapEpisode.series_id == league.series_id, RecapEpisode.league_id == league_id,
        RecapEpisode.season == season, RecapEpisode.week == week))
    if episode and episode.lifecycle == 'video_skipped':
        return state('unavailable', 'no_video', 'No video is available for this edition.', False)
    if not episode:
        return state('unavailable', 'no_video', 'No video is available for this edition.')
    if config['blocked_by'] or feature.get('paused'):
        return state('blocked', 'policy_paused', 'Video preparation is paused. The written recap is available below.')
    if episode.hold:
        return state('blocked', 'source_review', 'Video is waiting for source verification. The written recap is available below.')
    attention = await db.scalar(select(RecapAttention.key).where(
        RecapAttention.episode_id == episode.episode_id,
        RecapAttention.state == 'needs_attention').limit(1))
    if attention:
        return state('blocked', 'preparation_review', 'Video preparation needs review before it can continue. The written recap is available below.')
    stages = (await db.scalars(select(RecapStage).where(
        RecapStage.episode_id == episode.episode_id, RecapStage.kind != 'preflight'))).all()
    if stages:
        latest = max((row.revision, row.execution_revision) for row in stages)
        current = [row for row in stages if (row.revision, row.execution_revision) == latest]
        if any(row.state in ('held', 'failed', 'unknown', 'needs_attention', 'cancelled') for row in current):
            return state('blocked', 'preparation_review', 'Video preparation needs review before it can continue. The written recap is available below.')
    return state('pending', 'preparing', 'Video is not published yet. The written recap is available below.')
