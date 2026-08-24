from sleeper_dynasty.engine.head_to_head import (
    H2HRecord,
    aggregate_head_to_head,
    head_to_head_records,
)


def _entry(opp_rid: int, tp: float, op: float) -> dict:
    return {"opponent_roster_id": opp_rid, "team_points": tp, "opponent_points": op}


# 4 rosters -> users; two regular-season weeks, one playoff week to be excluded.
ROSTER_TO_USER = {1: "a", 2: "b", 3: "c", 4: "d"}
MATCHUPS = {
    # Week 1: a beats b (110-100); d beats c (95-90)
    ("L", 1, 1): _entry(2, 110, 100),
    ("L", 1, 2): _entry(1, 100, 110),
    ("L", 1, 3): _entry(4, 90, 95),
    ("L", 1, 4): _entry(3, 95, 90),
    # Week 2: c beats a (120-80); b ties d (100-100)
    ("L", 2, 1): _entry(3, 80, 120),
    ("L", 2, 3): _entry(1, 120, 80),
    ("L", 2, 2): _entry(4, 100, 100),
    ("L", 2, 4): _entry(2, 100, 100),
    # Week 3: playoff bracket — must NOT count toward H2H.
    ("L", 3, 1): _entry(2, 200, 0),
    ("L", 3, 2): _entry(1, 0, 200),
}


def _records():
    return head_to_head_records(
        MATCHUPS, league_id="L", roster_to_user=ROSTER_TO_USER, playoff_week_start=3,
    )


def test_win_loss_recorded_for_both_sides():
    h = _records()
    assert h["a"]["b"] == H2HRecord("b", wins=1, losses=0, ties=0, points_for=110, points_against=100)
    assert h["b"]["a"] == H2HRecord("a", wins=0, losses=1, ties=0, points_for=100, points_against=110)


def test_tie_recorded():
    h = _records()
    assert h["b"]["d"] == H2HRecord("d", wins=0, losses=0, ties=1, points_for=100, points_against=100)
    assert h["d"]["b"] == H2HRecord("b", wins=0, losses=0, ties=1, points_for=100, points_against=100)


def test_multiple_opponents_per_owner():
    h = _records()
    assert set(h["a"]) == {"b", "c"}
    assert h["a"]["c"] == H2HRecord("c", wins=0, losses=1, ties=0, points_for=80, points_against=120)
    assert h["c"]["a"] == H2HRecord("a", wins=1, losses=0, ties=0, points_for=120, points_against=80)


def test_playoff_weeks_excluded():
    # Week 3 (>= playoff_week_start) would have made a 2-0 over b; it must be ignored.
    h = _records()
    assert h["a"]["b"].wins == 1


def test_missing_points_skipped():
    matchups = {
        ("L", 1, 1): {"opponent_roster_id": 2, "team_points": None, "opponent_points": 100},
        ("L", 1, 2): {"opponent_roster_id": 1, "team_points": 100, "opponent_points": None},
    }
    h = head_to_head_records(
        matchups, league_id="L", roster_to_user={1: "a", 2: "b"}, playoff_week_start=15,
    )
    assert h == {}


def test_other_leagues_ignored():
    matchups = dict(MATCHUPS)
    matchups[("OTHER", 1, 1)] = _entry(2, 999, 0)
    h = head_to_head_records(
        matchups, league_id="L", roster_to_user=ROSTER_TO_USER, playoff_week_start=3,
    )
    assert h["a"]["b"].points_for == 110  # the OTHER-league blowout didn't leak in


# --- chain-wide aggregation across seasons (owner_id stable across leagues) ---


def test_aggregate_sums_records_across_leagues():
    league_a = {
        "a": {"b": H2HRecord("b", wins=1, losses=0, ties=0, points_for=110, points_against=100)},
        "b": {"a": H2HRecord("a", wins=0, losses=1, ties=0, points_for=100, points_against=110)},
    }
    league_b = {
        "a": {"b": H2HRecord("b", wins=0, losses=1, ties=1, points_for=190, points_against=205)},
        "b": {"a": H2HRecord("a", wins=1, losses=0, ties=1, points_for=205, points_against=190)},
    }
    agg = aggregate_head_to_head([league_a, league_b])
    assert agg["a"]["b"] == H2HRecord("b", wins=1, losses=1, ties=1, points_for=300, points_against=305)
    assert agg["b"]["a"] == H2HRecord("a", wins=1, losses=1, ties=1, points_for=305, points_against=300)


def test_aggregate_unions_new_opponents():
    league_a = {"a": {"b": H2HRecord("b", wins=1)}}
    league_b = {"a": {"c": H2HRecord("c", losses=1)}}
    agg = aggregate_head_to_head([league_a, league_b])
    assert set(agg["a"]) == {"b", "c"}


def test_aggregate_empty_input():
    assert aggregate_head_to_head([]) == {}
