"""Per-week recap for the dashboard's in-season lead (followup A2).

Figures are hand-computed here and asserted exactly: the lead publishes a high
score, a blowout margin, and a traded-points tally, and a number in the lead
that doesn't reconcile with the standings on the same page is the one failure
this feature can't ship with.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.week_recap import (
    derive_week_recap,
    latest_completed_regular_week,
    traded_pids_by_user,
)

_SEASONS = {"LG": 2026}
_ROSTERS = {"LG": {1: "u_tom", 2: "u_mike", 3: "u_amir", 4: "u_joey"}}


def _entry(team: float, opp: float, opp_rid: int, *, starters=None, points=None) -> dict:
    return {
        "starters": list(starters or []),
        "players": list(starters or []),
        "players_points": dict(points or {}),
        "team_points": team,
        "opponent_points": opp,
        "opponent_roster_id": opp_rid,
    }


def _week(week: int) -> dict:
    """Two games. Tom 120.5 beats Mike 100.25 (margin 20.25); Amir 140.0 beats
    Joey 90.0 (margin 50.0) — so Amir owns both the high score and the blowout."""
    return {
        ("LG", week, 1): _entry(120.5, 100.25, 2),
        ("LG", week, 2): _entry(100.25, 120.5, 1),
        ("LG", week, 3): _entry(140.0, 90.0, 4),
        ("LG", week, 4): _entry(90.0, 140.0, 3),
    }


# --------------------------------------------------------------------------
# latest_completed_regular_week — never an in-progress week
# --------------------------------------------------------------------------


def test_picks_the_last_week_before_the_current_one():
    matchups = {**_week(3), **_week(4), **_week(5)}
    got = latest_completed_regular_week(
        matchups=matchups, league_season_by_id=_SEASONS,
        playoff_start_by_season={2026: 15},
        nfl_state={"season_type": "regular", "season": "2026", "week": 5},
    )
    # Week 5 is the current week — in progress or not yet kicked off, never
    # "completed" — so the recap is week 4.
    assert got == (2026, 4)


def test_none_outside_the_regular_season():
    for season_type in ("post", "off", "pre", ""):
        assert latest_completed_regular_week(
            matchups=_week(3), league_season_by_id=_SEASONS,
            playoff_start_by_season={2026: 15},
            nfl_state={"season_type": season_type, "season": "2026", "week": 5},
        ) is None


def test_none_in_week_one_and_on_missing_state():
    assert latest_completed_regular_week(
        matchups=_week(1), league_season_by_id=_SEASONS,
        playoff_start_by_season={2026: 15},
        nfl_state={"season_type": "regular", "season": "2026", "week": 1},
    ) is None
    assert latest_completed_regular_week(
        matchups=_week(1), league_season_by_id=_SEASONS,
        playoff_start_by_season={2026: 15}, nfl_state=None,
    ) is None


def test_bracket_weeks_are_never_the_recap_week():
    # Week 15 is the league's playoff start: a bracket game, not a recap week.
    matchups = {**_week(14), **_week(15)}
    got = latest_completed_regular_week(
        matchups=matchups, league_season_by_id=_SEASONS,
        playoff_start_by_season={2026: 15},
        nfl_state={"season_type": "regular", "season": "2026", "week": 16},
    )
    assert got == (2026, 14)


def test_ignores_other_seasons_in_the_chain():
    matchups = {**_week(9)}
    matchups[("OLD", 12, 1)] = _entry(200.0, 10.0, 2)
    got = latest_completed_regular_week(
        matchups=matchups,
        league_season_by_id={"LG": 2026, "OLD": 2025},
        playoff_start_by_season={2026: 15, 2025: 15},
        nfl_state={"season_type": "regular", "season": "2026", "week": 10},
    )
    assert got == (2026, 9)


# --------------------------------------------------------------------------
# traded_pids_by_user — trade week excluded, pick-derived players counted
# --------------------------------------------------------------------------


@dataclass
class _Asset:
    player_id: str


@dataclass
class _Side:
    received: list
    given: list


@dataclass
class _Trade:
    league_id: str
    season: int
    week: int


@dataclass
class _RT:
    trade: _Trade
    sides: dict


def _resolved(week: int, *, uid="u_tom", pid="p1", season=2026) -> dict:
    return {
        "trade": {"transaction_id": f"tx{week}"},
        "rt": _RT(
            trade=_Trade(league_id="LG", season=season, week=week),
            sides={uid: _Side(received=[_Asset(pid)], given=[])},
        ),
    }


def test_trade_week_itself_is_excluded():
    # Sleeper trades take effect the following week (trade_grader._is_post_trade).
    same_week = traded_pids_by_user(
        [_resolved(4)], season=2026, week=4, league_season_by_id=_SEASONS,
    )
    assert same_week == {}
    later = traded_pids_by_user(
        [_resolved(3)], season=2026, week=4, league_season_by_id=_SEASONS,
    )
    assert later == {"u_tom": {"p1"}}


def test_a_later_week_in_the_same_season_is_excluded():
    assert traded_pids_by_user(
        [_resolved(9)], season=2026, week=4, league_season_by_id=_SEASONS,
    ) == {}


def test_season_comes_from_the_chain_map_not_the_trade_record():
    """A trade's season is resolved through ``league_season_by_id`` (the chain's
    league→season map), which is how every other rollup dates a trade. A trade
    in next season's league is excluded from this season's recap; an earlier
    season's is included."""
    next_season = _resolved(1, pid="p_next")
    next_season["rt"].trade.league_id = "LG27"
    prior_season = _resolved(1, pid="p_prior")
    prior_season["rt"].trade.league_id = "LG25"
    seasons = {"LG": 2026, "LG27": 2027, "LG25": 2025}
    got = traded_pids_by_user(
        [next_season, prior_season], season=2026, week=4, league_season_by_id=seasons,
    )
    assert got == {"u_tom": {"p_prior"}}


def test_rows_without_a_resolved_trade_are_skipped():
    assert traded_pids_by_user(
        [{"trade": {"transaction_id": "tx"}}], season=2026, week=4,
        league_season_by_id=_SEASONS,
    ) == {}


# --------------------------------------------------------------------------
# derive_week_recap — the published figures
# --------------------------------------------------------------------------

_DERIVE = dict(
    roster_to_user_by_league=_ROSTERS,
    league_season_by_id=_SEASONS,
    season=2026,
    week=4,
)


def test_high_score_and_blowout_are_the_hand_computed_figures():
    got = derive_week_recap(matchups=_week(4), traded_pids={}, **_DERIVE)
    assert got["season"] == "2026"
    assert got["week"] == 4
    assert got["high_score"] == {"user_id": "u_amir", "points": 140.0}
    assert got["blowout"] == {
        "winner_user_id": "u_amir", "loser_user_id": "u_joey", "margin": 50.0,
    }
    assert got["traded_points"] is None


def test_blowout_margin_reconciles_with_the_two_scores():
    got = derive_week_recap(matchups=_week(4), traded_pids={}, **_DERIVE)
    # Self-consistency: the margin is exactly winner points minus loser points,
    # both of which are in the same matchup entries the standings read.
    assert got["blowout"]["margin"] == 140.0 - 90.0


def test_traded_points_counts_only_started_trade_acquired_players():
    matchups = _week(4)
    # Tom started p1 (acquired by trade, 22.5) and p2 (drafted, 30.0); p3 was
    # acquired by trade but benched, so it must not count.
    matchups[("LG", 4, 1)] = _entry(
        120.5, 100.25, 2,
        starters=["p1", "p2"],
        points={"p1": 22.5, "p2": 30.0, "p3": 99.0},
    )
    got = derive_week_recap(
        matchups=matchups, traded_pids={"u_tom": {"p1", "p3"}}, **_DERIVE,
    )
    assert got["traded_points"] == {"user_id": "u_tom", "points": 22.5}


def test_traded_points_picks_the_biggest_tally():
    matchups = _week(4)
    matchups[("LG", 4, 1)] = _entry(
        120.5, 100.25, 2, starters=["p1"], points={"p1": 10.0},
    )
    matchups[("LG", 4, 3)] = _entry(
        140.0, 90.0, 4, starters=["p7", "p8"], points={"p7": 12.0, "p8": 9.5},
    )
    got = derive_week_recap(
        matchups=matchups,
        traded_pids={"u_tom": {"p1"}, "u_amir": {"p7", "p8"}},
        **_DERIVE,
    )
    assert got["traded_points"] == {"user_id": "u_amir", "points": 21.5}


def test_none_when_the_week_has_no_matchups():
    assert derive_week_recap(matchups=_week(9), traded_pids={}, **_DERIVE) is None


def test_none_when_no_game_produced_a_winner():
    tie = {
        ("LG", 4, 1): _entry(100.0, 100.0, 2),
        ("LG", 4, 2): _entry(100.0, 100.0, 1),
    }
    # A high score exists but no blowout — a half-populated lead is worse than
    # the placeholder, so the whole recap is withheld.
    assert derive_week_recap(matchups=tie, traded_pids={}, **_DERIVE) is None


def test_unmapped_rosters_are_skipped():
    got = derive_week_recap(
        matchups=_week(4),
        roster_to_user_by_league={"LG": {3: "u_amir", 4: "u_joey"}},
        league_season_by_id=_SEASONS, season=2026, week=4, traded_pids={},
    )
    assert got["high_score"]["user_id"] == "u_amir"
    assert got["blowout"]["winner_user_id"] == "u_amir"
