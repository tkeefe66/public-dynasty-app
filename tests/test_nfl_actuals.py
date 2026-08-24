from sleeper_dynasty.engine.nfl_actuals import (
    score_week, next_n_weeks, points_after_drop,
)


def test_score_week_applies_league_scoring():
    raw = {
        "p1": {"rec": 5.0, "rec_yd": 80.0, "rec_td": 1.0},
        "p2": {"rush_yd": 100.0},
        "p3": {},          # empty stats -> skipped
    }
    scoring = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "rush_yd": 0.1}
    pts = score_week(raw, scoring)
    assert pts["p1"] == 19.0      # 5 + 8 + 6
    assert pts["p2"] == 10.0      # 100*0.1
    assert "p3" not in pts and len(pts) == 2


def test_next_n_weeks_rolls_over_season_boundary():
    assert next_n_weeks((2024, 16), 3) == [(2024, 17), (2024, 18), (2025, 1)]
    assert len(next_n_weeks((2024, 5), 10)) == 10
    assert next_n_weeks((2024, 5), 10)[-1] == (2024, 15)


def test_points_after_drop_sums_only_the_window():
    nfl = {
        (2024, 9): {"p1": 20.0, "x": 5.0},
        (2024, 10): {"p1": 18.0},
        (2025, 1): {"p1": 99.0},   # 11th week from (2024,8) — just OUTSIDE window=10
    }
    total = points_after_drop("p1", (2024, 8), nfl, window=10)
    assert total == 38.0          # 20 + 18; (2025,1) is the 11th week, excluded
    # a player with no data in the window -> 0
    assert points_after_drop("ghost", (2024, 8), nfl, window=10) == 0.0
