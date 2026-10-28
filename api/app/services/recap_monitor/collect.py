"""Schedule-first inspection. All external calls are free provider reads."""
import json
import logging
from datetime import datetime, time, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db.models import LeagueMembership, User
from app.services.generation.models import LeagueSeason, LeagueSeries
from app.services.generation.recap_budget import get_budget_view
from app.services.generation.store import digest, resolve_policy
from app.services.platform_client import connected_client
from app.services.recap_monitor.evidence import game_gate, job_evidence, publication_proof, requires_recovery, workflow_evidence
from app.services.recap_monitor.state import ZONE
from app.services.recap_video.periods import scoring_period
from sleeper_dynasty.api.nfl_inventory import fetch_inventory
from sleeper_dynasty.api.nfl_schedule import fetch_week_evidence
from sleeper_dynasty.api.sleeper import SleeperClient

log = logging.getLogger(__name__)


def current_week(games, now):
    due = []
    for week in {g['week'] for g in games}:
        first = min(datetime.fromisoformat(g['kickoff'].replace('Z', '+00:00')).astimezone(ZONE)
                    for g in games if g['week'] == week)
        monday = first.date() + timedelta(days=(0 - first.weekday()) % 7)
        if datetime.combine(monday, time(22, 30), ZONE).timestamp() <= now:
            due.append(week)
    return max(due, default=0)


async def owner(maker, config):
    async with maker() as db:
        user = await db.get(User, config.owner_id)
        if not user or not user.is_admin or user.email.lower() not in get_settings().admin_email_list:
            raise ValueError('monitor_owner_authority_missing')
        return user


async def collect(config, maker, cache_dir, now, previous):
    await owner(maker, config)
    sleeper = SleeperClient()
    try:
        state = await sleeper.get_nfl_state()
    finally:
        await sleeper.close()
    year = int(state['season'])
    if year < config.first_season or state.get('season_type') not in ('regular', 'post'):
        return []
    inventory = await fetch_inventory(year)
    week = current_week(inventory['games'], now)
    if not week or (year, week) < (config.first_season, config.first_week):
        return []
    scoreboard = {}
    async def completed(period):
        observed = []
        for w in period['nfl_weeks']:
            if w not in scoreboard:
                scoreboard[w] = (await fetch_week_evidence(year, w))['games']
            observed.extend(scoreboard[w])
        return game_gate([g for g in inventory['games'] if g['week'] in period['nfl_weeks']], observed, now)
    observations = []
    for series_id in config.series_ids:
        base = dict(key=series_id + ':' + str(year) + ':' + str(week), series_id=series_id,
                    season=year, week=week, status='pending')
        try:
            async with maker() as db:
                series = await db.get(LeagueSeries, series_id)
                seasons = (await db.scalars(select(LeagueSeason).where(
                    LeagueSeason.series_id == series_id, LeagueSeason.season == year,
                    LeagueSeason.verified_at > 0))).all()
                if not series or len(seasons) != 1:
                    raise ValueError('verified_league_series_mapping_required')
                season = seasons[0]
                base.update(league_id=season.league_id, league_name=series.name)
                member = await db.scalar(select(LeagueMembership.id).where(
                    LeagueMembership.user_id == config.owner_id, LeagueMembership.league_id == season.league_id))
                # Existing app guard permits admin GETs for Sleeper; Yahoo
                # always requires actual membership plus the owner's grant.
                if not member and season.provider == 'yahoo':
                    raise ValueError('monitor_owner_membership_required')
            # Metadata is free; use exactly the configured real owner's connection.
            async with maker() as db:
                client = await connected_client(season.league_id, db=db, user_id=config.owner_id)
            try:
                league, _ = await client.get_league(season.league_id)
                bracket = {'ok': True, 'winners': [], 'losers': []}
                if week >= league.playoff_week_start:
                    bracket.update(winners=await client.get_winners_bracket(season.league_id),
                                   losers=await client.get_losers_bracket(season.league_id))
                try:
                    period = scoring_period(week, dict(playoff_week_start=league.playoff_week_start,
                        playoff_round_type=league.playoff_round_type, num_playoff_teams=league.num_playoff_teams), bracket)
                except ValueError as exc:
                    if str(exc) != 'season_finished':
                        raise
                    period = None
            finally:
                await client.close()
            periods = {period['period_id']: period} if period else {}
            for old in previous.values():
                if old.get('series_id') == series_id and old.get('season') == year and old.get('status') != 'inactive' and old.get('period'):
                    periods.setdefault(old['period']['period_id'], old['period'])
            if not periods:
                observations.append({**base, 'status': 'inactive', 'reason': 'season_finished'})
            for period in periods.values():
                item = {**base, 'period': period, 'week': period['week'],
                        'key': series_id + ':' + str(year) + ':' + period['period_id']}
                if (year, period['week']) < (config.first_season, config.first_week):
                    continue
                old = previous.get(item['key'], {})
                item.update(recovery_attempts=old.get('recovery_attempts', 0))
                gate = await completed(period)
                if gate['status'] != 'ready':
                    observations.append({**item, **gate, 'progress': digest(gate)})
                    continue  # Never audit unfinished scoring periods.
                item['first_games_complete_at'] = old.get('first_games_complete_at', now)
                async with maker() as db:
                    proof = await publication_proof(db, cache_dir, season.league_id, year, period['week'])
                    if proof:
                        observations.append({**item, 'status': 'complete', 'proof': proof,
                                             'progress': digest(proof)})
                        continue
                    policy = await resolve_policy(db, series_id)
                    budget = await get_budget_view(db, series_id, None, now)
                    feature = policy['policy']['features']['analyst']
                    if feature['max_calls'] > 6 or budget['caps']['combined_episode_microusd'] > 5_000_000 or budget['caps']['combined_month_microusd'] > 25_000_000:
                        raise ValueError('monitor_authorization_ceiling_changed')
                    job, costs = await job_evidence(db, season.league_id, year, period['week'])
                    item.update(costs)
                    if job:
                        item.update(job_id=job.id, calls_used=job.calls, max_calls=job.max_calls,
                                    job_kind=job.kind, job_reason=job.reason,
                                    readiness_week=json.loads(job.progress_json).get('week'),
                                    remaining_calls=max(0, job.max_calls-job.calls),
                                    last_progress_at=job.updated_at,
                                    recoverable=await requires_recovery(db, job))
                        if job.kind == 'generation':
                            item['first_ready_observed_at'] = old.get('first_ready_observed_at', now)
                            item['generation_created_at'] = job.created_at
                    gates = [job.next_attempt_at] if job and job.next_attempt_at > now else []
                    from app.services.generation.recap_models import RecapEpisode
                    episode = await db.scalar(select(RecapEpisode).where(RecapEpisode.series_id == series_id,
                        RecapEpisode.season == year, RecapEpisode.period_id == period['period_id']))
                    item.update(workflow_evidence(job, episode, now))
                    if episode and episode.eligible_at > now:
                        gates.append(episode.eligible_at)
                    if episode and episode.hold == 'facts_unstable' and episode.stable_since + 3600 > now:
                        gates.append(episode.stable_since + 3600)
                    from app.services.generation.recap_models import ProviderAccountControl
                    account = await db.get(ProviderAccountControl, ('anthropic', get_settings().anthropic_account_alias))
                    if account and account.cooldown_until > now:
                        gates.append(account.cooldown_until)
                    if gates and item['status'] != 'help':
                        item.update(status='waiting', gate=max(gates), recoverable=False)
                    observations.append(item)
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == 'season_finished':
                observations.append({**base, 'status': 'inactive', 'reason': 'season_finished'})
            else:
                # Retry source/access failures before escalating a persistent problem.
                log.warning('Recap monitor source failed type=%s', type(exc).__name__)
                reason = str(exc) if isinstance(exc, ValueError) and str(exc) in (
                    'monitor_owner_membership_required', 'verified_league_series_mapping_required',
                    'monitor_authorization_ceiling_changed') else 'source_or_authority_unavailable'
                observations.append({**base, 'reason': reason, 'progress': reason,
                                     'recoverable': False,
                                     'action': 'Review source access or league mapping; no replacement writing authorized'})
    return observations
