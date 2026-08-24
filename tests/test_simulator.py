import numpy as np

from sleeper_dynasty.engine.simulator import (
    get_cv,
    sample_weekly_points,
    simulate_season,
    SimulationResult,
)
from sleeper_dynasty.models.league import League, Roster, Matchup


def test_cv_by_position():
    assert get_cv("QB") == 0.20
    assert get_cv("RB") == 0.30
    assert get_cv("WR") == 0.30
    assert get_cv("TE") == 0.35
    assert get_cv("K") == 0.40
    assert get_cv("DEF") == 0.45


def test_sample_weekly_points_respects_distribution():
    rng = np.random.default_rng(42)
    samples = [sample_weekly_points(20.0, "QB", rng) for _ in range(10000)]
    mean = np.mean(samples)
    std = np.std(samples)
    assert abs(mean - 20.0) < 0.5  # mean should be ~20
    assert abs(std - 4.0) < 0.5  # std should be ~20*0.20=4.0


def test_sample_weekly_points_floor_for_low_projection():
    rng = np.random.default_rng(42)
    samples = [sample_weekly_points(2.0, "WR", rng) for _ in range(1000)]
    assert all(s >= 0 for s in samples)


def test_simulate_season_returns_results():
    league = League(
        league_id="test",
        name="Test League",
        season=2026,
        total_rosters=2,
        roster_positions=["QB", "RB", "WR", "TE"],
        scoring_settings={"pass_td": 4.0, "rec": 1.0},
        playoff_week_start=15,
        num_playoff_teams=2,
        status="in_season",
    )
    rosters = [
        Roster(roster_id=1, owner_id="a", owner_name="Alice", players=["qb1", "rb1", "wr1", "te1"],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
        Roster(roster_id=2, owner_id="b", owner_name="Bob", players=["qb2", "rb2", "wr2", "te2"],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
    ]
    matchups_by_week = {
        w: [Matchup(week=w, roster_id_1=1, roster_id_2=2, points_1=None, points_2=None)]
        for w in range(1, 15)
    }
    player_projections = {
        "qb1": ("QB", 22.0), "rb1": ("RB", 15.0), "wr1": ("WR", 16.0), "te1": ("TE", 10.0),
        "qb2": ("QB", 20.0), "rb2": ("RB", 14.0), "wr2": ("WR", 15.0), "te2": ("TE", 9.0),
    }

    result = simulate_season(
        league=league,
        rosters=rosters,
        matchups_by_week=matchups_by_week,
        player_projections=player_projections,
        start_week=1,
        num_sims=100,
    )

    assert isinstance(result, SimulationResult)
    assert 1 in result.team_results
    assert 2 in result.team_results
    # Alice has better players, should win more often
    assert result.team_results[1].avg_wins > result.team_results[2].avg_wins
    assert 0.0 <= result.team_results[1].playoff_pct <= 100.0
    assert 0.0 <= result.team_results[1].championship_pct <= 100.0
