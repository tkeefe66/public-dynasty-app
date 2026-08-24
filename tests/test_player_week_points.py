"""Tests for the player_week_points helper extracted from _points_while_owned."""
from datetime import datetime, timezone

import pytest

from sleeper_dynasty.engine.trade_grader import player_week_points
from sleeper_dynasty.models.trade import (
    PlayerAsset,
    ResolvedTrade,
    Trade,
    TradeSide,
)


def _make_rt(league_id: str, season: int, week: int, uid: str) -> ResolvedTrade:
    """Minimal ResolvedTrade with a single side for ``uid``."""
    sides = {uid: TradeSide(uid, [PlayerAsset("p1", "P1")], [])}
    base = Trade(
        transaction_id="t1",
        league_id=league_id,
        season=season,
        week=week,
        traded_at=datetime(season, 9, 1, tzinfo=timezone.utc),
        sides=sides,
    )
    return ResolvedTrade(trade=base, sides=sides)


def _matchups() -> dict:
    # (league_id, week, roster_id) -> entry. Player "p1" on roster 1 (user "u1").
    return {
        ("L1", 5, 1): {"players": ["p1"], "starters": ["p1"], "players_points": {"p1": 10.0}},
        ("L1", 6, 1): {"players": ["p1"], "starters": [],      "players_points": {"p1": 7.0}},  # benched
    }


@pytest.fixture
def make_rt_week4_L1_u1() -> ResolvedTrade:
    """A ResolvedTrade in L1 week 4, season 2024, side u1.

    _is_post_trade will return True for weeks 5 and 6 of L1 (season 2024)
    because those are strictly after trade week 4 in the same season.
    """
    return _make_rt("L1", 2024, 4, "u1")


def test_player_week_points_returns_per_week_started_and_total(make_rt_week4_L1_u1):
    rt = make_rt_week4_L1_u1
    r2u = {"L1": {1: "u1"}}
    total = player_week_points(
        "p1", "u1",
        matchups=_matchups(),
        roster_to_user_by_league=r2u,
        rt=rt,
        league_season_by_id={"L1": 2024},
        starters_only=False,
    )
    assert total == {(2024, 5): 10.0, (2024, 6): 7.0}

    started = player_week_points(
        "p1", "u1",
        matchups=_matchups(),
        roster_to_user_by_league=r2u,
        rt=rt,
        league_season_by_id={"L1": 2024},
        starters_only=True,
    )
    assert started == {(2024, 5): 10.0}  # week 6 benched -> omitted
