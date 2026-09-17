"""Best-effort upcoming-week preview, using that week's projections."""
import logging

from sleeper_dynasty.api.nfl_schedule import fetch_week_schedule
from sleeper_dynasty.api.projections import normalize_projection
from sleeper_dynasty.api.weather import fetch_game_weather
from sleeper_dynasty.engine.lineup import solve_optimal_lineup
from sleeper_dynasty.engine.outlook import build_matchup_previews, build_weather_notes
from sleeper_dynasty.models.recap import OutlookFacts

log = logging.getLogger(__name__)


async def upcoming_outlook(client, league, week, rosters, players):
    try:
        raw = await client.get_projections(league.season, week)
        if not raw:
            return None
        projections = {pid: normalize_projection(stats, league.scoring_settings)
                       for pid, stats in raw.items() if isinstance(stats, dict)}
        pairings = await client.get_matchup_results(league.league_id, week)
        names = {r.roster_id: r.owner_name for r in rosters}
        totals = {}
        for roster in rosters:
            available = {pid: (players[pid].position, projections[pid])
                         for pid in roster.players if pid in players and pid in projections}
            if not available:
                return None
            _, total = solve_optimal_lineup(league.roster_positions, available)
            totals[roster.roster_id] = total
        pairings = [r for r in pairings if r.matchup_id is not None and r.roster_id in totals]
        previews = build_matchup_previews(pairings, names, totals)
        if not previews:
            return None
        outlook = OutlookFacts(week=week, matchups=previews, byes=[], weather=[], playoff_stakes=[])
        try:
            games = await fetch_week_schedule(league.season, week)
            # Absence from a scoreboard is not affirmative evidence of a bye:
            # feeds can be partial, and ESPN WSH != Sleeper WAS. Until we have
            # an explicit, season/week-verified bye source, omit these claims.
            weather = {}
            for game in games:
                if not game.get("indoor"):
                    wx = await fetch_game_weather(game["home"], game.get("kickoff") or "")
                    if wx:
                        weather[game["home"]] = wx
            outlook.weather = build_weather_notes(games, weather)
        except Exception:
            log.warning("Analyst schedule/weather unavailable; retaining matchup preview", exc_info=True)
        return outlook
    except Exception:
        log.warning("Analyst upcoming-week preview unavailable; retaining recap", exc_info=True)
        return None
