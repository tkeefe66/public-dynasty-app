from sleeper_dynasty.engine.production_series import (
    METRIC_GATES, week_axis, cumulative, merge_week_points,
)


def test_metric_gates():
    assert METRIC_GATES["total"] == (False, None)
    assert METRIC_GATES["regular"] == (True, "regular")
    assert METRIC_GATES["playoff"] == (True, "playoff")
    assert METRIC_GATES["toilet"] == (True, "toilet")
    # started = starters-only, no phase filter (all weeks)
    assert METRIC_GATES["started"] == (True, None)


def test_week_axis_sorts_across_seasons():
    matchups = {("L1", 17, 1): {}, ("L1", 1, 1): {}, ("L2", 2, 1): {}}
    season = {"L1": 2024, "L2": 2025}
    assert week_axis(matchups, season) == [(2024, 1), (2024, 17), (2025, 2)]


def test_cumulative_runs_and_holds_flat_on_gaps():
    axis = [(2024, 1), (2024, 2), (2024, 3)]
    wp = {(2024, 1): 10.0, (2024, 3): 5.0}  # nothing week 2
    assert cumulative(wp, axis) == [((2024, 1), 10.0), ((2024, 2), 10.0), ((2024, 3), 15.0)]


def test_merge_week_points_adds():
    a = {(2024, 1): 10.0, (2024, 2): 3.0}
    b = {(2024, 2): 4.0, (2024, 3): 1.0}
    assert merge_week_points([a, b]) == {(2024, 1): 10.0, (2024, 2): 7.0, (2024, 3): 1.0}
