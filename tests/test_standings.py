from __future__ import annotations

import pytest

from sleeper_dynasty.engine.standings import (
    StandingRow,
    all_play_win_pct,
    standings_as_of,
    standings_history,
    validate_against_roster,
)
from sleeper_dynasty.models.league import Roster


def _mk(team_points, opp_points):
    return {"team_points": team_points, "opponent_points": opp_points}


# Two-team league, weeks 1-3. r1 beats r2 twice, loses once.
MATCHUPS = {
    ("L", 1, 1): _mk(100.0, 90.0),
    ("L", 1, 2): _mk(90.0, 100.0),
    ("L", 2, 1): _mk(80.0, 110.0),
    ("L", 2, 2): _mk(110.0, 80.0),
    ("L", 3, 1): _mk(120.0, 100.0),
    ("L", 3, 2): _mk(100.0, 120.0),
}
R2U = {1: "ua", 2: "ub"}


def test_through_week_2_counts_one_win_one_loss_each():
    rows = standings_as_of(
        MATCHUPS, league_id="L", through_week=2,
        playoff_week_start=15, roster_to_user=R2U,
    )
    by_owner = {r.owner_id: r for r in rows}
    assert by_owner["ua"].wins == 1 and by_owner["ua"].losses == 1
    assert by_owner["ua"].points_for == 180.0  # 100 + 80
    assert by_owner["ub"].wins == 1 and by_owner["ub"].losses == 1


def test_full_season_ranks_r1_first_by_record():
    rows = standings_as_of(
        MATCHUPS, league_id="L", through_week=3,
        playoff_week_start=15, roster_to_user=R2U,
    )
    assert [r.owner_id for r in rows] == ["ua", "ub"]
    assert rows[0].rank == 1 and rows[1].rank == 2
    assert rows[0].wins == 2 and rows[0].losses == 1


def test_tie_when_equal_points():
    m = {("L", 1, 1): _mk(100.0, 100.0), ("L", 1, 2): _mk(100.0, 100.0)}
    rows = standings_as_of(
        m, league_id="L", through_week=1,
        playoff_week_start=15, roster_to_user={1: "ua", 2: "ub"},
    )
    assert all(r.ties == 1 and r.wins == 0 and r.losses == 0 for r in rows)


def test_playoff_weeks_excluded():
    # Week 15 is a playoff week and must not affect the regular-season record.
    m = dict(MATCHUPS)
    m[("L", 15, 1)] = _mk(200.0, 10.0)
    m[("L", 15, 2)] = _mk(10.0, 200.0)
    rows = standings_as_of(
        m, league_id="L", through_week=15,
        playoff_week_start=15, roster_to_user=R2U,
    )
    by_owner = {r.owner_id: r for r in rows}
    assert by_owner["ua"].wins == 2  # unchanged by the week-15 blowout


def test_unplayed_week_skipped():
    m = {
        ("L", 1, 1): _mk(None, None),
        ("L", 1, 2): _mk(None, None),
        # Week 2 is played; unplayed week 1 must not contaminate it.
        ("L", 2, 1): _mk(100.0, 90.0),
        ("L", 2, 2): _mk(90.0, 100.0),
    }
    rows = standings_as_of(
        m, league_id="L", through_week=5,
        playoff_week_start=15, roster_to_user={1: "ua", 2: "ub"},
    )
    assert len(rows) == 2
    by_owner = {r.owner_id: r for r in rows}
    assert by_owner["ua"].wins == 1 and by_owner["ua"].points_for == 100.0
    assert by_owner["ub"].losses == 1


def test_other_league_rows_ignored():
    m = dict(MATCHUPS)
    m[("OTHER", 1, 1)] = _mk(999.0, 0.0)
    rows = standings_as_of(
        m, league_id="L", through_week=3,
        playoff_week_start=15, roster_to_user=R2U,
    )
    assert all(r.points_for < 500 for r in rows)


# ---------------------------------------------------------------------------
# Task 2: standings_history + validate_against_roster
# ---------------------------------------------------------------------------


def test_standings_history_keys_and_values():
    hist = standings_history(
        MATCHUPS, league_id="L", season=2024,
        playoff_week_start=15, roster_to_user=R2U,
    )
    assert set(hist) == {"2024-01", "2024-02", "2024-03"}
    # By week 3, ua has 2 wins.
    by_owner = {r.owner_id: r for r in hist["2024-03"]}
    assert by_owner["ua"].wins == 2


def _roster(rid, owner, w, l, pf):
    return Roster(
        roster_id=rid, owner_id=owner, owner_name=owner, players=[],
        wins=w, losses=l, ties=0, points_for=pf, points_against=0.0,
    )


def test_validate_matches_returns_empty():
    rows = standings_as_of(
        MATCHUPS, league_id="L", through_week=3,
        playoff_week_start=15, roster_to_user=R2U,
    )
    # ua pf: 100+80+120=300; ub pf: 90+110+100=300
    rosters = [_roster(1, "ua", 2, 1, 300.0), _roster(2, "ub", 1, 2, 300.0)]
    assert validate_against_roster(rows, rosters) == []


def test_validate_reports_record_mismatch():
    rows = standings_as_of(
        MATCHUPS, league_id="L", through_week=3,
        playoff_week_start=15, roster_to_user=R2U,
    )
    rosters = [_roster(1, "ua", 3, 0, 300.0), _roster(2, "ub", 1, 2, 300.0)]
    deltas = validate_against_roster(rows, rosters)
    assert any("roster 1" in d for d in deltas)


# ---------------------------------------------------------------------------
# Task 1: all_play_win_pct
# ---------------------------------------------------------------------------


def test_all_play_win_pct_scores_every_roster_against_every_other():
    # Three rosters, two regular-season weeks. Week 3 is playoffs and must be
    # excluded. A wins both weeks outright; B and C split the rest.
    matchups = {
        ("L", 1, 1): {"team_points": 100.0},
        ("L", 1, 2): {"team_points": 90.0},
        ("L", 1, 3): {"team_points": 80.0},
        ("L", 2, 1): {"team_points": 95.0},
        ("L", 2, 2): {"team_points": 60.0},
        ("L", 2, 3): {"team_points": 70.0},
        ("L", 3, 1): {"team_points": 10.0},   # playoff week, ignored
        ("L", 3, 2): {"team_points": 200.0},
        ("L", 3, 3): {"team_points": 5.0},
    }
    out = all_play_win_pct(
        matchups, league_id="L", playoff_week_start=3,
        roster_to_user={1: "ua", 2: "ub", 3: "uc"})
    assert out == {"ua": 1.0, "ub": 0.25, "uc": 0.25}


def test_all_play_win_pct_ties_count_half():
    matchups = {
        ("L", 1, 1): {"team_points": 100.0},
        ("L", 1, 2): {"team_points": 100.0},
    }
    out = all_play_win_pct(
        matchups, league_id="L", playoff_week_start=2,
        roster_to_user={1: "ua", 2: "ub"})
    assert out == {"ua": 0.5, "ub": 0.5}


def test_all_play_denominator_is_the_rosters_that_actually_played():
    # Roster 3 has no score in week 2 (bye, or a dropped pair). Week 2 must be
    # scored out of ONE opponent, not two — using league size here would
    # silently mark everyone down.
    matchups = {
        ("L", 1, 1): {"team_points": 100.0},
        ("L", 1, 2): {"team_points": 90.0},
        ("L", 1, 3): {"team_points": 80.0},
        ("L", 2, 1): {"team_points": 100.0},
        ("L", 2, 2): {"team_points": 90.0},
    }
    out = all_play_win_pct(
        matchups, league_id="L", playoff_week_start=3,
        roster_to_user={1: "ua", 2: "ub", 3: "uc"})
    # ua: 2/2 + 1/1 = 3/3;  ub: 1/2 + 0/1 = 1/3;  uc: 0/2 = 0/2
    assert out["ua"] == 1.0
    assert out["ub"] == pytest.approx(1 / 3)
    assert out["uc"] == 0.0


def test_all_play_win_pct_skips_rosters_with_no_played_weeks():
    out = all_play_win_pct(
        {}, league_id="L", playoff_week_start=15, roster_to_user={1: "ua"})
    assert out == {}
