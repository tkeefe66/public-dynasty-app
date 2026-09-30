"""Positional scoring ranks count every player's production, regardless of roster."""

import pytest


def test_totals_use_league_scoring_and_completed_weeks_for_every_player():
    # Mutation: use pts_ppr, rank by PPG, or include the in-progress fourth week.
    from sleeper_dynasty.engine.scoring_leaders import build_scoring_rows

    players = {
        "a": {"full_name": "Alpha Receiver", "position": "WR", "team": "SEA"},
        "b": {"full_name": "Beta Receiver", "position": "WR", "team": "DEN"},
        "c": {"full_name": "Gamma Tight End", "position": "TE", "team": "KC"},
    }
    weeks = {
        1: {"a": {"gp": 1, "rec": 5, "rec_yd": 50, "pts_ppr": 10},
            "b": {"gp": 1, "rec": 1, "rec_yd": 100, "pts_ppr": 11},
            "c": {"gp": 1, "rec": 4, "rec_yd": 40}},
        2: {"a": {"gp": 1, "rec": 3, "rec_yd": 30},
            "c": {"gp": 1, "rec": 2, "rec_yd": 20}},
        3: {"a": {"gp": 1, "rec": 0, "rec_yd": 0}},
        4: {"b": {"gp": 1, "rec_yd": 1000}},
    }
    rows = build_scoring_rows(weeks, players, {"rec": 2, "rec_yd": .1, "bonus_rec_te": 1}, 3)
    by_id = {r["player_id"]: r for r in rows}
    assert by_id["a"]["points"] == 24
    assert by_id["a"]["rank"] == 1
    assert by_id["a"]["games"] == 3
    assert by_id["a"]["points_per_game"] == 8
    assert by_id["b"]["points"] == 12
    assert by_id["b"]["rank"] == 2
    assert by_id["b"]["points_per_game"] == 12
    assert by_id["c"]["points"] == 24
    assert by_id["c"]["rank"] == 1


def test_ties_share_competition_rank_and_negative_games_count():
    # Mutation: enumerate tied ranks, drop negative scorers, or count inactive weeks.
    from sleeper_dynasty.engine.scoring_leaders import build_scoring_rows

    players = {p: {"full_name": p, "position": "QB"} for p in "abcd"}
    rows = build_scoring_rows({1: {
        "a": {"gp": 1, "pass_td": 1}, "b": {"gp": 1, "pass_td": 1},
        "c": {"gp": 1, "pass_int": 1}, "d": {"gms_active": 0},
    }}, players, {"pass_td": 6, "pass_int": -2}, 1)
    assert [(r["player_id"], r["rank"], r["points"]) for r in rows] == [
        ("a", 1, 6), ("b", 1, 6), ("c", 3, -2),
    ]
    assert rows[2]["games"] == 1
    assert rows[2]["points_per_game"] == -2


def test_positional_bonus_is_not_double_counted_when_in_raw_stats():
    # Mutation: add a derived TE bonus on top of the source's own bonus_rec_te.
    from sleeper_dynasty.engine.scoring_leaders import build_scoring_rows

    rows = build_scoring_rows({1: {"te": {"gp": 1, "rec": 4, "bonus_rec_te": 4}}},
                              {"te": {"position": "TE", "full_name": "Test TE"}},
                              {"rec": 1, "bonus_rec_te": .5}, 1)
    assert rows[0]["points"] == 6


def test_active_roster_placeholders_are_not_games_played():
    # Mutation: use gms_active=1 as a fallback for missing gp, inflating the PPG denominator.
    # Shape captured live: gp-absent records contain ranks and sometimes TEAM snaps only.
    from sleeper_dynasty.engine.scoring_leaders import build_scoring_rows

    weeks = {1: {"qb": {"gp": 1, "pass_td": 2}, "idle": {"gms_active": 1}},
             2: {"qb": {"gms_active": 1, "pos_rank_ppr": 999, "tm_off_snp": 64}}}
    rows = build_scoring_rows(weeks, {"qb": {"position": "QB"}, "idle": {"position": "QB"}},
                              {"pass_td": 6}, 2)
    assert len(rows) == 1
    assert rows[0]["games"] == 1
    assert rows[0]["points_per_game"] == 12


def test_captured_kicker_stat_shape_uses_league_rules():
    # Mutation: use the source's default 10 points instead of this league's 11.
    # Captured from Sleeper's public Week 3 response; only the player id is replaced.
    from sleeper_dynasty.engine.scoring_leaders import build_scoring_rows

    stats = {"fg_blkd": 1.0, "fga": 4.0, "fgm": 3.0, "fgm_20_29": 2.0,
             "fgm_30_39": 1.0, "fgmiss": 1.0, "fgmiss_50p": 1.0,
             "gms_active": 1.0, "gp": 1.0, "pts_ppr": 10.0,
             "pts_half_ppr": 10.0, "pts_std": 10.0, "xpa": 2.0, "xpm": 2.0}
    rows = build_scoring_rows({1: {"k": stats}}, {"k": {"position": "K"}},
                              {"fgm_20_29": 3, "fgm_30_39": 3, "xpm": 1}, 1)
    assert rows[0]["points"] == 11


@pytest.mark.parametrize("state, season, expected", [
    ({"season": "2026", "season_type": "regular", "week": 4}, 2026, 3),
    ({"season": "2026", "season_type": "regular", "week": 1}, 2026, 0),
    ({"season": "2026", "season_type": "pre", "week": 3}, 2026, 0),
    ({"season": "2026", "season_type": "post", "week": 1}, 2026, 18),
    ({"season": "2026", "season_type": "regular", "week": 4}, 2025, 18),
    ({"season": "2026", "season_type": "regular", "week": 4}, 2020, 17),
    ({"season": "2026", "season_type": "regular", "week": 4}, 2027, 0),
])
def test_completed_week_boundary(state, season, expected):
    # Mutation: include current week, confuse NFL postseason with regular weeks, or assume 18 pre-2021.
    from sleeper_dynasty.engine.scoring_leaders import completed_week

    assert completed_week(season, state) == expected


@pytest.mark.parametrize("state", [None, {}, {"season": "2026", "season_type": "unknown"},
                                  {"season": "2026", "season_type": "regular", "week": "bad"}])
def test_unknown_state_is_an_error_not_an_empty_leaderboard(state):
    # Mutation: convert missing or malformed state to zero completed weeks.
    from sleeper_dynasty.engine.scoring_leaders import completed_week

    with pytest.raises(ValueError, match="NFL season state"):
        completed_week(2026, state)
