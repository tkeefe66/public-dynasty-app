"""Outlook engine: previews, byes, weather assembly, and playoff stakes for
the UPCOMING week. Pure functions over data fetched by the CLI.
"""

from __future__ import annotations

import logging

from sleeper_dynasty.engine.lineup import solve_optimal_lineup
from sleeper_dynasty.models.league import MatchupResult, Roster
from sleeper_dynasty.models.player import Player
from sleeper_dynasty.models.recap import (
    ByeTrouble, MatchupPreview, OutlookFacts, PlayoffStake, WeatherNote,
)

logger = logging.getLogger(__name__)


def _pair_by_matchup(
    pairings: list[MatchupResult],
) -> list[tuple[MatchupResult, MatchupResult]]:
    by_mid: dict[int | None, list[MatchupResult]] = {}
    for r in pairings:
        by_mid.setdefault(r.matchup_id, []).append(r)
    return [tuple(e) for e in by_mid.values() if len(e) == 2]


def build_matchup_previews(
    pairings: list[MatchupResult],
    owner_by_roster: dict[int, str],
    team_projected: dict[int, float],
) -> list[MatchupPreview]:
    """Build previews with projected scores and a favorite/spread."""
    previews = []
    for a, b in _pair_by_matchup(pairings):
        a_proj = round(team_projected.get(a.roster_id, 0.0), 1)
        b_proj = round(team_projected.get(b.roster_id, 0.0), 1)
        a_name = owner_by_roster.get(a.roster_id, "Unknown")
        b_name = owner_by_roster.get(b.roster_id, "Unknown")
        fav = a_name if a_proj >= b_proj else b_name
        previews.append(MatchupPreview(
            home=a_name, away=b_name,
            home_projected=a_proj, away_projected=b_proj,
            favorite=fav, spread=round(abs(a_proj - b_proj), 1),
        ))
    return previews


def build_playoff_stakes(
    rosters: list[Roster],
    num_playoff_teams: int,
    weeks_remaining: int,
) -> list[PlayoffStake]:
    """Crude stakes from current standings.

    - eliminated: cannot mathematically reach the cutoff team's win total even
      winning out (wins + weeks_remaining < cutoff_wins).
    - can-clinch: at/above the cutoff with a >1-game cushion over the bubble.
    - must-win: within one game of the cutoff in either direction.
    - in-the-hunt: everything else above water.
    """
    ordered = sorted(rosters, key=lambda r: (r.wins, r.points_for), reverse=True)
    if len(ordered) < num_playoff_teams:
        return [PlayoffStake(r.owner_name, "in-the-hunt") for r in ordered]

    cutoff_wins = ordered[num_playoff_teams - 1].wins
    stakes = []
    for idx, r in enumerate(ordered):
        max_wins = r.wins + weeks_remaining
        if max_wins < cutoff_wins:
            status = "eliminated"
        elif idx < num_playoff_teams and (r.wins - cutoff_wins) >= 1:
            status = "can-clinch"
        elif abs(r.wins - cutoff_wins) <= 1:
            status = "must-win"
        else:
            status = "in-the-hunt"
        stakes.append(PlayoffStake(r.owner_name, status))
    return stakes


def _label(pid: str, players: dict[str, Player]) -> str:
    p = players.get(pid)
    if p is None:
        return pid
    return f"{p.full_name} ({p.position or '?'}, {p.team or 'FA'})"


def build_bye_trouble(
    rosters: list[Roster],
    owner_by_roster: dict[int, str],
    players: dict[str, Player],
    byes: set[str],
    roster_positions: list[str],
    projections: dict[str, float],
) -> list[ByeTrouble]:
    """Find managers whose projected starters are on bye, and guess the
    (likely worse) replacement the optimizer would slot in instead.

    Requires ``byes`` and ``projections``: without projections every player
    scores 0.0, so the optimizer's "ideal starters" are arbitrary and the
    resulting beats are noise. In that case we omit bye trouble entirely
    (best-effort degradation, consistent with how busts are skipped when
    projections are unavailable).
    """
    if not byes or not projections:
        return []

    troubles = []
    for roster in rosters:
        # Players on this roster whose NFL team is on bye.
        on_bye = [
            pid for pid in roster.players
            if (players.get(pid) and players[pid].team in byes)
        ]
        if not on_bye:
            continue

        # Would-be-optimal starters if NOBODY were on bye.
        full_map = {
            pid: (players[pid].position or "", projections.get(pid, 0.0))
            for pid in roster.players if pid in players
        }
        ideal_starters, _ = solve_optimal_lineup(roster_positions, full_map)
        affected = [pid for pid in on_bye if pid in ideal_starters]
        if not affected:
            continue

        # Optimal lineup with bye players removed -> the replacements.
        avail_map = {
            pid: v for pid, v in full_map.items()
            if players[pid].team not in byes
        }
        repl_starters, _ = solve_optimal_lineup(roster_positions, avail_map)
        # The best NEW starter not in the ideal lineup = the replacement.
        new_in = [pid for pid in repl_starters if pid not in ideal_starters]
        replacement = max(
            new_in, key=lambda p: projections.get(p, 0.0), default=None
        )

        troubles.append(ByeTrouble(
            owner=owner_by_roster.get(roster.roster_id, "Unknown"),
            players_on_bye=[_label(p, players) for p in affected],
            likely_replacement=_label(replacement, players) if replacement else None,
            replacement_projected=(
                round(projections.get(replacement, 0.0), 1)
                if replacement else None
            ),
        ))
    return troubles


def build_weather_notes(
    games: list[dict],
    weather_by_home: dict[str, dict],
) -> list[WeatherNote]:
    """Assemble weather notes for games that have fetched conditions.

    ``weather_by_home`` maps home-team abbr -> {wind_mph, temp_f, precip}.
    Only games with notable conditions (wind >= 15 or precip != none or
    temp <= 32) are kept — calm dome-like days aren't funny.
    """
    notes = []
    for g in games:
        wx = weather_by_home.get(g["home"])
        if not wx:
            continue
        notable = (
            (wx.get("wind_mph") or 0) >= 15
            or wx.get("precip") not in (None, "none")
            or (wx.get("temp_f") is not None and wx["temp_f"] <= 32)
        )
        if not notable:
            continue
        notes.append(WeatherNote(
            game=f"{g['away']} @ {g['home']}",
            wind_mph=wx.get("wind_mph"),
            temp_f=wx.get("temp_f"),
            precip=wx.get("precip"),
            affected_players=[],
        ))
    return notes


def build_outlook_facts(
    week: int,
    pairings: list[MatchupResult],
    owner_by_roster: dict[int, str],
    team_projected: dict[int, float],
    rosters: list[Roster],
    players: dict[str, Player],
    byes: set[str],
    roster_positions: list[str],
    projections: dict[str, float],
    games: list[dict],
    weather_by_home: dict[str, dict],
    num_playoff_teams: int,
    weeks_remaining: int,
) -> OutlookFacts:
    """Assemble the full outlook facts packet."""
    return OutlookFacts(
        week=week,
        matchups=build_matchup_previews(
            pairings, owner_by_roster, team_projected
        ),
        byes=build_bye_trouble(
            rosters, owner_by_roster, players, byes,
            roster_positions, projections,
        ),
        weather=build_weather_notes(games, weather_by_home),
        playoff_stakes=build_playoff_stakes(
            rosters, num_playoff_teams, weeks_remaining
        ),
    )
