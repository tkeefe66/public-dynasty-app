"""Monte Carlo season simulator for fantasy football leagues.

Simulates many possible season outcomes by sampling weekly player scores
from a normal distribution parameterized by projections and position-specific
variance. Tracks wins, playoff appearances, and championships across
iterations to produce probabilistic season forecasts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from numpy.random import Generator

from sleeper_dynasty.engine.lineup import solve_optimal_lineup
from sleeper_dynasty.models.league import League, Matchup, Roster

logger = logging.getLogger(__name__)

# Coefficient of variation (std / mean) by position.
# Higher CV = more week-to-week volatility.
POSITION_CV: dict[str, float] = {
    "QB": 0.20,
    "RB": 0.30,
    "WR": 0.30,
    "TE": 0.35,
    "K": 0.40,
    "DEF": 0.45,
}

# Minimum standard deviation for low-projection players to avoid
# degenerate distributions (e.g. a 1-point projection with 0.3 std).
_MIN_STD = 1.0

# Projection threshold below which the minimum std floor is applied.
_LOW_PROJECTION_THRESHOLD = 5.0


def get_cv(position: str) -> float:
    """Return the coefficient of variation for a position.

    Args:
        position: NFL position code (QB, RB, WR, TE, K, DEF).

    Returns:
        CV as a float. Falls back to 0.30 for unknown positions.
    """
    return POSITION_CV.get(position, 0.30)


def sample_weekly_points(projected: float, position: str, rng: Generator) -> float:
    """Sample a single week's fantasy points for a player.

    Draws from N(projected, std) where std = projected * CV, floored at 0.
    For low projections (< 5 pts), uses a minimum std of 1.0 to avoid
    unrealistically tight distributions.

    Args:
        projected: Season-average weekly projection.
        position: NFL position code.
        rng: NumPy random generator instance.

    Returns:
        Non-negative sampled fantasy points.
    """
    cv = get_cv(position)
    std = projected * cv
    if projected < _LOW_PROJECTION_THRESHOLD:
        std = max(std, _MIN_STD)
    raw = rng.normal(projected, std)
    return max(0.0, raw)


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


@dataclass
class TeamSimResult:
    """Aggregated simulation results for a single team."""

    roster_id: int
    avg_wins: float
    avg_losses: float
    win_low: float  # 5th percentile wins
    win_high: float  # 95th percentile wins
    playoff_pct: float  # percentage 0-100
    championship_pct: float  # percentage 0-100
    avg_points_for: float


@dataclass
class MatchupSimResult:
    """Aggregated simulation results for a single weekly matchup."""

    week: int
    roster_id_1: int
    roster_id_2: int
    win_pct_1: float  # percentage 0-100
    win_pct_2: float  # percentage 0-100
    avg_score_1: float
    avg_score_2: float


@dataclass
class SimulationResult:
    """Complete Monte Carlo simulation output."""

    team_results: dict[int, TeamSimResult]
    matchup_results: list[MatchupSimResult]


# ---------------------------------------------------------------------------
# Core simulation logic
# ---------------------------------------------------------------------------


def _simulate_team_week(
    roster: Roster,
    league: League,
    player_projections: dict[str, tuple[str, float]],
    rng: Generator,
) -> float:
    """Simulate one week's score for a roster.

    Samples points for every player on the roster, then uses the optimal
    lineup solver to pick the best starting lineup.

    Args:
        roster: The team's roster.
        league: League configuration (for roster_positions).
        player_projections: player_id -> (position, projected_points).
        rng: NumPy random generator.

    Returns:
        Total optimal lineup score for the week.
    """
    # Build sampled player dict: player_id -> (position, sampled_points)
    sampled_players: dict[str, tuple[str, float]] = {}
    for pid in roster.players:
        if pid in player_projections:
            pos, proj = player_projections[pid]
            pts = sample_weekly_points(proj, pos, rng)
            sampled_players[pid] = (pos, pts)

    if not sampled_players:
        return 0.0

    _, total = solve_optimal_lineup(league.roster_positions, sampled_players)
    return total


def _simulate_playoffs(
    playoff_team_ids: list[int],
    roster_map: dict[int, Roster],
    league: League,
    player_projections: dict[str, tuple[str, float]],
    rng: Generator,
) -> int:
    """Simulate single-elimination playoff bracket.

    Teams are seeded by their order in playoff_team_ids (index 0 = 1-seed).
    Standard bracket: 1v4, 2v3 in semis, winners meet in the final.
    For 2-team playoffs, it's just a single matchup.

    Args:
        playoff_team_ids: Ordered list of team IDs that made the playoffs.
        roster_map: roster_id -> Roster mapping.
        league: League configuration.
        player_projections: player_id -> (position, projected_points).
        rng: NumPy random generator.

    Returns:
        roster_id of the champion.
    """
    if len(playoff_team_ids) == 0:
        return -1
    if len(playoff_team_ids) == 1:
        return playoff_team_ids[0]

    # Build bracket rounds via single elimination.
    # Pair seeds: 1v(last), 2v(second-to-last), etc.
    remaining = list(playoff_team_ids)

    while len(remaining) > 1:
        next_round: list[int] = []
        # Pair from outside in: seed 1 vs seed N, seed 2 vs seed N-1, etc.
        num_matchups = len(remaining) // 2
        for i in range(num_matchups):
            team_a = remaining[i]
            team_b = remaining[len(remaining) - 1 - i]
            score_a = _simulate_team_week(
                roster_map[team_a], league, player_projections, rng
            )
            score_b = _simulate_team_week(
                roster_map[team_b], league, player_projections, rng
            )
            # Tiebreak: higher seed (lower index) wins
            if score_a >= score_b:
                next_round.append(team_a)
            else:
                next_round.append(team_b)
        # If odd number of teams, the middle seed gets a bye
        if len(remaining) % 2 == 1:
            next_round.append(remaining[num_matchups])
        remaining = next_round

    return remaining[0]


def simulate_season(
    league: League,
    rosters: list[Roster],
    matchups_by_week: dict[int, list[Matchup]],
    player_projections: dict[str, tuple[str, float]],
    start_week: int,
    num_sims: int = 10000,
) -> SimulationResult:
    """Run Monte Carlo simulation of the remaining season.

    Args:
        league: League configuration.
        rosters: All rosters in the league.
        matchups_by_week: week_number -> list of Matchup objects.
        player_projections: player_id -> (position, projected_points).
        start_week: First week to simulate (earlier weeks use actual results).
        num_sims: Number of simulation iterations.

    Returns:
        SimulationResult with team and matchup-level aggregations.
    """
    rng = np.random.default_rng(seed=None)

    roster_map: dict[int, Roster] = {r.roster_id: r for r in rosters}
    roster_ids = sorted(roster_map.keys())

    # Determine the regular season weeks to simulate.
    regular_season_end = league.playoff_week_start - 1
    sim_weeks = [w for w in range(start_week, regular_season_end + 1)]

    # Pre-existing record (wins/losses before start_week).
    base_wins: dict[int, int] = {r.roster_id: r.wins for r in rosters}
    base_losses: dict[int, int] = {r.roster_id: r.losses for r in rosters}
    base_points: dict[int, float] = {r.roster_id: r.points_for for r in rosters}

    # Accumulators across sims.
    all_wins: dict[int, list[int]] = {rid: [] for rid in roster_ids}
    all_losses: dict[int, list[int]] = {rid: [] for rid in roster_ids}
    all_points: dict[int, list[float]] = {rid: [] for rid in roster_ids}
    playoff_counts: dict[int, int] = {rid: 0 for rid in roster_ids}
    championship_counts: dict[int, int] = {rid: 0 for rid in roster_ids}

    # Per-matchup accumulators: (week, rid1, rid2) -> (wins_1, wins_2, scores_1, scores_2)
    matchup_keys: list[tuple[int, int, int]] = []
    matchup_wins_1: dict[tuple[int, int, int], int] = {}
    matchup_wins_2: dict[tuple[int, int, int], int] = {}
    matchup_scores_1: dict[tuple[int, int, int], list[float]] = {}
    matchup_scores_2: dict[tuple[int, int, int], list[float]] = {}

    for week in sim_weeks:
        for m in matchups_by_week.get(week, []):
            key = (week, m.roster_id_1, m.roster_id_2)
            if key not in matchup_wins_1:
                matchup_keys.append(key)
                matchup_wins_1[key] = 0
                matchup_wins_2[key] = 0
                matchup_scores_1[key] = []
                matchup_scores_2[key] = []

    logger.info(
        "Starting Monte Carlo simulation: %d sims, weeks %d-%d",
        num_sims,
        start_week,
        regular_season_end,
    )

    for sim in range(num_sims):
        # Per-sim accumulators.
        sim_wins: dict[int, int] = {rid: base_wins[rid] for rid in roster_ids}
        sim_losses: dict[int, int] = {rid: base_losses[rid] for rid in roster_ids}
        sim_points: dict[int, float] = {rid: base_points[rid] for rid in roster_ids}

        for week in sim_weeks:
            for m in matchups_by_week.get(week, []):
                score_1 = _simulate_team_week(
                    roster_map[m.roster_id_1], league, player_projections, rng
                )
                score_2 = _simulate_team_week(
                    roster_map[m.roster_id_2], league, player_projections, rng
                )

                sim_points[m.roster_id_1] += score_1
                sim_points[m.roster_id_2] += score_2

                if score_1 >= score_2:
                    sim_wins[m.roster_id_1] += 1
                    sim_losses[m.roster_id_2] += 1
                else:
                    sim_wins[m.roster_id_2] += 1
                    sim_losses[m.roster_id_1] += 1

                # Track matchup-level results.
                key = (week, m.roster_id_1, m.roster_id_2)
                if score_1 >= score_2:
                    matchup_wins_1[key] += 1
                else:
                    matchup_wins_2[key] += 1
                matchup_scores_1[key].append(score_1)
                matchup_scores_2[key].append(score_2)

        # Record season totals.
        for rid in roster_ids:
            all_wins[rid].append(sim_wins[rid])
            all_losses[rid].append(sim_losses[rid])
            all_points[rid].append(sim_points[rid])

        # Determine playoff teams: sort by wins desc, tiebreak by total points desc.
        standings = sorted(
            roster_ids,
            key=lambda rid: (sim_wins[rid], sim_points[rid]),
            reverse=True,
        )
        playoff_team_ids = standings[: league.num_playoff_teams]
        for rid in playoff_team_ids:
            playoff_counts[rid] += 1

        # Simulate playoffs.
        champion = _simulate_playoffs(
            playoff_team_ids, roster_map, league, player_projections, rng
        )
        if champion >= 0:
            championship_counts[champion] += 1

    # Build team results.
    team_results: dict[int, TeamSimResult] = {}
    for rid in roster_ids:
        wins_arr = np.array(all_wins[rid])
        team_results[rid] = TeamSimResult(
            roster_id=rid,
            avg_wins=float(np.mean(wins_arr)),
            avg_losses=float(np.mean(all_losses[rid])),
            win_low=float(np.percentile(wins_arr, 5)),
            win_high=float(np.percentile(wins_arr, 95)),
            playoff_pct=100.0 * playoff_counts[rid] / num_sims,
            championship_pct=100.0 * championship_counts[rid] / num_sims,
            avg_points_for=float(np.mean(all_points[rid])),
        )

    # Build matchup results.
    matchup_results: list[MatchupSimResult] = []
    for key in matchup_keys:
        week, rid1, rid2 = key
        total_matchups = matchup_wins_1[key] + matchup_wins_2[key]
        if total_matchups == 0:
            continue
        matchup_results.append(
            MatchupSimResult(
                week=week,
                roster_id_1=rid1,
                roster_id_2=rid2,
                win_pct_1=100.0 * matchup_wins_1[key] / total_matchups,
                win_pct_2=100.0 * matchup_wins_2[key] / total_matchups,
                avg_score_1=float(np.mean(matchup_scores_1[key])),
                avg_score_2=float(np.mean(matchup_scores_2[key])),
            )
        )

    logger.info("Simulation complete: %d iterations", num_sims)
    return SimulationResult(team_results=team_results, matchup_results=matchup_results)
