"""FactsBuilder: turn raw league data into the recap facts packet.

Every comedy-relevant number is computed here so the LLM writer never has
to (and can never invent one). Pure functions, fully unit-testable against
real past-week Sleeper data.
"""

from __future__ import annotations

import logging

from sleeper_dynasty.engine.lineup import solve_optimal_lineup
from sleeper_dynasty.models.league import MatchupResult, Roster
from sleeper_dynasty.models.player import Player
from sleeper_dynasty.models.recap import (
    BenchRegret, LuckNote, MatchupRecap, PlayerLine, RecapFacts,
)

logger = logging.getLogger(__name__)

# Type alias for readability: roster_id -> owner display/team name.
OWNER_BY_ROSTER = dict  # documentation marker; callers pass dict[int, str]

BLOWOUT_MARGIN = 40.0
NAILBITER_MARGIN = 5.0

TOP_N = 3
BUST_PROJECTION_MIN = 10.0
BUST_RATIO = 0.5


def _pair_results(
    results: list[MatchupResult],
) -> list[tuple[MatchupResult, MatchupResult]]:
    """Group MatchupResults into opponent pairs by matchup_id.

    Skips unplayed weeks: Sleeper returns placeholder entries for upcoming
    weeks with points=0 on both sides. Two real NFL fantasy lineups totaling
    exactly 0 is functionally impossible, so both-zero is the unplayed
    sentinel (mirrors cli._assemble_played_matchups).
    """
    by_mid: dict[int | None, list[MatchupResult]] = {}
    for r in results:
        by_mid.setdefault(r.matchup_id, []).append(r)
    pairs = []
    for entries in by_mid.values():
        if len(entries) != 2:
            continue
        a, b = entries
        if (a.points or 0.0) == 0.0 and (b.points or 0.0) == 0.0:
            continue
        pairs.append((a, b))
    return pairs


def build_matchup_recaps(
    results: list[MatchupResult],
    owner_by_roster: dict[int, str],
) -> tuple[list[MatchupRecap], dict | None, dict | None]:
    """Build per-matchup recaps plus the week's high and low scorer.

    Returns ``(recaps, high_scorer, low_scorer)`` where the scorer dicts are
    ``{"owner": str, "points": float}`` or ``None`` if no games were played.
    """
    pairs = _pair_results(results)
    recaps: list[MatchupRecap] = []
    all_scores: list[tuple[str, float]] = []

    for a, b in pairs:
        a_pts, b_pts = a.points or 0.0, b.points or 0.0
        winner_r, loser_r = (a, b) if a_pts >= b_pts else (b, a)
        w_pts, l_pts = winner_r.points or 0.0, loser_r.points or 0.0
        margin = round(w_pts - l_pts, 2)
        recaps.append(MatchupRecap(
            winner=owner_by_roster.get(winner_r.roster_id, "Unknown"),
            loser=owner_by_roster.get(loser_r.roster_id, "Unknown"),
            winner_points=w_pts,
            loser_points=l_pts,
            margin=margin,
            blowout=margin >= BLOWOUT_MARGIN,
            nailbiter=margin <= NAILBITER_MARGIN,
        ))
        all_scores.append((owner_by_roster.get(a.roster_id, "Unknown"), a_pts))
        all_scores.append((owner_by_roster.get(b.roster_id, "Unknown"), b_pts))

    if not all_scores:
        return recaps, None, None

    high = max(all_scores, key=lambda x: x[1])
    low = min(all_scores, key=lambda x: x[1])
    return (
        recaps,
        {"owner": high[0], "points": high[1]},
        {"owner": low[0], "points": low[1]},
    )


def build_bench_regret(
    result: MatchupResult,
    roster_positions: list[str],
    positions_by_player: dict[str, str],
    owner: str,
    min_points: float = 1.0,
) -> BenchRegret | None:
    """Compute points left on the bench for one roster-week.

    Feeds the week's ACTUAL ``players_points`` to the optimal-lineup solver
    as if they were projections, then diffs the optimal starter total against
    the lineup the manager actually started. Returns None if the manager was
    already optimal (or within ``min_points``).
    """
    # Build (position, actual_points) for every rostered player we can place.
    player_map: dict[str, tuple[str, float]] = {}
    for pid in result.players:
        pos = positions_by_player.get(pid)
        if not pos:
            continue
        player_map[pid] = (pos, result.players_points.get(pid, 0.0))

    _, optimal_total = solve_optimal_lineup(roster_positions, player_map)

    actual_total = sum(
        result.players_points.get(pid, 0.0) for pid in result.starters
    )
    left = round(optimal_total - actual_total, 2)
    if left < min_points:
        return None

    started = [
        (pid, result.players_points.get(pid, 0.0)) for pid in result.starters
    ]
    benched = [
        (pid, result.players_points.get(pid, 0.0))
        for pid in result.players
        if pid not in set(result.starters)
    ]
    if not started or not benched:
        return None

    hero_pid, hero_pts = max(benched, key=lambda x: x[1])
    dud_pid, dud_pts = min(started, key=lambda x: x[1])

    return BenchRegret(
        owner=owner,
        points_left_on_bench=left,
        benched_hero=PlayerLine(
            player=hero_pid, owner=owner, points=hero_pts,
            position=positions_by_player.get(hero_pid),
        ),
        started_dud=PlayerLine(
            player=dud_pid, owner=owner, points=dud_pts,
            position=positions_by_player.get(dud_pid),
        ),
    )


def build_luck_notes(
    results: list[MatchupResult],
    owner_by_roster: dict[int, str],
) -> tuple[list[LuckNote], list[LuckNote]]:
    """Flag the lucky (lowest-scoring winner) and unlucky (highest-scoring
    loser) owners of the week. Returns ``(lucky, unlucky)``.
    """
    pairs = _pair_results(results)
    if not pairs:
        return [], []

    winners: list[tuple[str, float]] = []
    losers: list[tuple[str, float]] = []
    for a, b in pairs:
        a_pts, b_pts = a.points or 0.0, b.points or 0.0
        w, l = (a, b) if a_pts >= b_pts else (b, a)
        winners.append((owner_by_roster.get(w.roster_id, "Unknown"),
                        w.points or 0.0))
        losers.append((owner_by_roster.get(l.roster_id, "Unknown"),
                       l.points or 0.0))

    lucky: list[LuckNote] = []
    unlucky: list[LuckNote] = []

    lowest_winner = min(winners, key=lambda x: x[1])
    lucky.append(LuckNote(
        owner=lowest_winner[0],
        note=(f"won with the lowest winning score of the week "
              f"({lowest_winner[1]:.1f}) — backed into it"),
    ))

    highest_loser = max(losers, key=lambda x: x[1])
    unlucky.append(LuckNote(
        owner=highest_loser[0],
        note=(f"put up {highest_loser[1]:.1f} — the highest score of any "
              f"loser this week — and still lost"),
    ))
    return lucky, unlucky


def build_player_beats(
    results: list[MatchupResult],
    owner_by_roster: dict[int, str],
    positions_by_player: dict[str, str],
    projections: dict[str, float],
) -> tuple[list[PlayerLine], list[PlayerLine], list[PlayerLine]]:
    """League-wide heroes, goats, and busts among STARTED players.

    - heroes: top ``TOP_N`` started performances by actual points.
    - goats: bottom ``TOP_N`` started performances by actual points.
    - busts: started players whose projection was >= ``BUST_PROJECTION_MIN``
      but who scored <= ``BUST_RATIO`` of it, worst-ratio first.

    ``projections`` maps player_id -> weekly projected points (may be empty;
    then busts is empty). Only played weeks contribute (both-zero pairs are
    excluded upstream by the caller passing played results, but we also skip
    rosters whose points are 0).
    """
    started_lines: list[PlayerLine] = []
    bust_candidates: list[tuple[PlayerLine, float]] = []

    for r in results:
        if (r.points or 0.0) == 0.0:
            continue
        owner = owner_by_roster.get(r.roster_id, "Unknown")
        for pid in r.starters:
            pts = r.players_points.get(pid, 0.0)
            line = PlayerLine(
                player=pid, owner=owner, points=pts,
                position=positions_by_player.get(pid),
            )
            started_lines.append(line)
            proj = projections.get(pid)
            if proj and proj >= BUST_PROJECTION_MIN and pts <= BUST_RATIO * proj:
                bust_line = PlayerLine(
                    player=pid, owner=owner, points=pts,
                    position=positions_by_player.get(pid), projected=proj,
                )
                bust_candidates.append((bust_line, pts / proj))

    heroes = sorted(started_lines, key=lambda p: p.points, reverse=True)[:TOP_N]
    goats = sorted(started_lines, key=lambda p: p.points)[:TOP_N]
    busts = [bl for bl, _ in sorted(bust_candidates, key=lambda x: x[1])][:TOP_N]
    return heroes, goats, busts


def build_standings(rosters: list[Roster]) -> list[dict]:
    """Standings snapshot sorted by wins desc, then points_for desc."""
    ordered = sorted(
        rosters, key=lambda r: (r.wins, r.points_for), reverse=True
    )
    return [
        {
            "owner": r.owner_name,
            "wins": r.wins,
            "losses": r.losses,
            "ties": r.ties,
            "points_for": round(r.points_for, 1),
        }
        for r in ordered
    ]


def _player_label(pid: str, players: dict[str, Player]) -> str:
    p = players.get(pid)
    if p is None:
        return pid
    team = p.team or "FA"
    pos = p.position or "?"
    return f"{p.full_name} ({pos}, {team})"


def _resolve_line(line: PlayerLine, players: dict[str, Player]) -> PlayerLine:
    line.player = _player_label(line.player, players)
    return line


def build_recap_facts(
    week: int,
    league_name: str,
    results: list[MatchupResult],
    rosters: list[Roster],
    owner_by_roster: dict[int, str],
    players: dict[str, Player],
    roster_positions: list[str],
    weekly_projections: dict[str, float],
) -> RecapFacts:
    """Assemble the full recap facts packet, resolving player IDs to names.

    ``weekly_projections`` maps player_id -> projected points for the week
    (used for busts); pass {} to skip bust detection.
    """
    positions_by_player = {
        pid: (p.position or "") for pid, p in players.items()
    }

    matchups, high, low = build_matchup_recaps(results, owner_by_roster)
    lucky, unlucky = build_luck_notes(results, owner_by_roster)
    heroes, goats, busts = build_player_beats(
        results, owner_by_roster, positions_by_player, weekly_projections
    )
    standings = build_standings(rosters)

    # Bench regret per played roster.
    regrets = []
    played_rosters = {
        r.roster_id for r in results if (r.points or 0.0) != 0.0
    }
    for r in results:
        if r.roster_id not in played_rosters:
            continue
        regret = build_bench_regret(
            r, roster_positions, positions_by_player,
            owner_by_roster.get(r.roster_id, "Unknown"),
        )
        if regret is not None:
            regrets.append(regret)
    # Most egregious first; keep the worst few.
    regrets.sort(key=lambda b: b.points_left_on_bench, reverse=True)
    regrets = regrets[:TOP_N]

    # Resolve all player IDs to readable labels.
    for line in heroes + goats + busts:
        _resolve_line(line, players)
    for reg in regrets:
        _resolve_line(reg.benched_hero, players)
        _resolve_line(reg.started_dud, players)

    return RecapFacts(
        week=week,
        league_name=league_name,
        standings=standings,
        matchups=matchups,
        high_scorer=high,
        low_scorer=low,
        bench_regret=regrets,
        lucky=lucky,
        unlucky=unlucky,
        heroes=heroes,
        goats=goats,
        busts=busts,
    )
