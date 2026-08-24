"""Tests for compute_production_series_payload in grader.py."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sleeper_dynasty.models.trade import (
    PlayerAsset,
    Trade,
    TradeSide,
    ResolvedTrade,
)


@pytest.fixture()
def simple_two_team_chain():
    """Minimal two-team chain: one trade, two players, regular-season weeks only."""
    # League L1, season 2024, trade in week 4.  p1 goes to u1, p2 goes to u2.
    t = Trade(
        transaction_id="tx1",
        league_id="L1",
        season=2024,
        week=4,
        traded_at=datetime(2024, 10, 1, tzinfo=timezone.utc),
        sides={
            "u1": TradeSide("u1", received=[PlayerAsset("p1", "Player One")],
                            given=[PlayerAsset("p2", "Player Two")]),
            "u2": TradeSide("u2", received=[PlayerAsset("p2", "Player Two")],
                            given=[PlayerAsset("p1", "Player One")]),
        },
    )
    rt = ResolvedTrade(trade=t, sides=t.sides)

    # Build the serialised dict form (mirroring _to_dict) — but attach "rt" too.
    trade_dict = {
        "transaction_id": "tx1",
        "league_id": "L1",
        "season": 2024,
        "week": 4,
        "traded_at": "2024-10-01T00:00:00+00:00",
    }
    sides_dict = {
        "u1": {
            "received": [{"player_id": "p1", "name": "Player One", "via_pick": None}],
            "given":    [{"player_id": "p2", "name": "Player Two", "via_pick": None}],
        },
        "u2": {
            "received": [{"player_id": "p2", "name": "Player Two", "via_pick": None}],
            "given":    [{"player_id": "p1", "name": "Player One", "via_pick": None}],
        },
    }
    resolved_dicts = [{"trade": trade_dict, "sides": sides_dict, "rt": rt}]

    # matchups: weeks 5 and 6, both regular season (< playoff_week_start=15).
    # Roster 1 → u1, roster 2 → u2.
    matchups = {
        ("L1", 5, 1): {
            "players": ["p1"],
            "starters": ["p1"],
            "players_points": {"p1": 20.0},
        },
        ("L1", 6, 1): {
            "players": ["p1"],
            "starters": ["p1"],
            "players_points": {"p1": 15.0},
        },
        ("L1", 5, 2): {
            "players": ["p2"],
            "starters": ["p2"],
            "players_points": {"p2": 10.0},
        },
        ("L1", 6, 2): {
            "players": ["p2"],
            "starters": ["p2"],
            "players_points": {"p2": 12.0},
        },
    }

    return SimpleNamespace(
        resolved_dicts=resolved_dicts,
        matchups=matchups,
        roster_to_user_by_league={"L1": {1: "u1", 2: "u2"}},
        league_season_by_id={"L1": 2024},
        current_holders={"p1": "u1", "p2": "u2"},
        drop_index={},
        phase_by_lwr={},
        playoff_week_start_by_league={"L1": 15},
        names={"u1": "Owner One", "u2": "Owner Two"},
    )


def test_payload_shapes_and_axis(simple_two_team_chain):
    from app.services.grader import compute_production_series_payload

    f = simple_two_team_chain
    payload = compute_production_series_payload(
        resolved_dicts=f.resolved_dicts,
        matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id,
        current_holders=f.current_holders,
        drop_index=f.drop_index,
        phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league,
        names=f.names,
    )

    # production_week_axis should exist and be non-empty
    assert payload["production_week_axis"]  # [[season, week], ...]

    tx = f.resolved_dicts[0]["trade"]["transaction_id"]

    # u1 received p1; series should be cumulative (non-decreasing) and end > 0
    total_series_u1 = payload["trade_production_series"][tx]["u1"]["total"]
    vals = [v for _s, _w, v in total_series_u1]
    assert vals == sorted(vals), "cumulative series must be non-decreasing"
    assert vals[-1] > 0

    # All five metrics present per side (total, regular, playoff, toilet, started)
    assert set(payload["trade_production_series"][tx]["u1"]) == {"total", "regular", "playoff", "toilet", "started"}

    # Verdict present for the trade
    assert "total" in payload["trade_production_verdict"][tx]

    # Owner series has received + given, each with metrics
    assert set(payload["owner_production_series"]["u1"]) == {"received", "given"}
    assert "total" in payload["owner_production_series"]["u1"]["received"]


def test_cumulative_values_correct(simple_two_team_chain):
    """u1 received p1 who scored 20 in week 5 and 15 in week 6."""
    from app.services.grader import compute_production_series_payload

    f = simple_two_team_chain
    payload = compute_production_series_payload(
        resolved_dicts=f.resolved_dicts,
        matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id,
        current_holders=f.current_holders,
        drop_index=f.drop_index,
        phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league,
        names=f.names,
    )

    tx = "tx1"
    u1_total = payload["trade_production_series"][tx]["u1"]["total"]
    # axis is [(2024,5), (2024,6)] → cumulative [20, 35]
    assert len(u1_total) == 2
    assert u1_total[0] == [2024, 5, 20.0]
    assert u1_total[1] == [2024, 6, 35.0]

    # u2 received p2: 10 + 12 = 22
    u2_total = payload["trade_production_series"][tx]["u2"]["total"]
    assert u2_total[-1][2] == pytest.approx(22.0)


def test_owner_aggregate_received(simple_two_team_chain):
    """Owner-level received aggregate should match per-trade sum."""
    from app.services.grader import compute_production_series_payload

    f = simple_two_team_chain
    payload = compute_production_series_payload(
        resolved_dicts=f.resolved_dicts,
        matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id,
        current_holders=f.current_holders,
        drop_index=f.drop_index,
        phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league,
        names=f.names,
    )

    # u1 received total 35 pts across weeks 5-6
    u1_recv_total = payload["owner_production_series"]["u1"]["received"]["total"]
    assert u1_recv_total[-1][2] == pytest.approx(35.0)

    # owner verdicts present
    assert "total" in payload["owner_production_verdict"]["u1"]


def test_payload_has_per_player_and_per_trade_drill(simple_two_team_chain):
    from app.services.grader import compute_production_series_payload

    f = simple_two_team_chain
    payload = compute_production_series_payload(
        resolved_dicts=f.resolved_dicts, matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id, current_holders=f.current_holders,
        drop_index=f.drop_index, phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league, names=f.names,
    )
    tx = f.resolved_dicts[0]["trade"]["transaction_id"]
    players = payload["trade_production_players"][tx]["u1"]
    assert players and "player_id" in players[0] and "total" in players[0]["byMetric"]
    trades = payload["owner_production_trades"]["u1"]
    assert trades and "trade_id" in trades[0] and "total" in trades[0]["byMetric"]


def test_started_metric_in_payload(simple_two_team_chain):
    """Payload includes a 'started' line: starters-only, no phase filter, all weeks."""
    from app.services.grader import compute_production_series_payload

    f = simple_two_team_chain
    payload = compute_production_series_payload(
        resolved_dicts=f.resolved_dicts,
        matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id,
        current_holders=f.current_holders,
        drop_index=f.drop_index,
        phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league,
        names=f.names,
    )

    tx = f.resolved_dicts[0]["trade"]["transaction_id"]
    # 'started' key must be present per side in the trade series
    assert "started" in payload["trade_production_series"][tx]["u1"]
    assert "started" in payload["trade_production_series"][tx]["u2"]

    # In the fixture, p1 is a starter in both regular-season weeks (5 and 6).
    # started = starters_only=True, phase_filter=None → 20 + 15 = 35.
    # (Same as 'total' here since all fixture players are starters.)
    u1_started = payload["trade_production_series"][tx]["u1"]["started"]
    assert u1_started[-1][2] == pytest.approx(35.0)

    # started ≤ total (starters are a subset of all bench + starters)
    u1_total = payload["trade_production_series"][tx]["u1"]["total"]
    assert u1_started[-1][2] <= u1_total[-1][2] + 0.001

    # started ≥ any single phase (no phase filter means all weeks count)
    u1_regular = payload["trade_production_series"][tx]["u1"]["regular"]
    assert u1_started[-1][2] >= u1_regular[-1][2] - 0.001

    # 'started' also present in owner series
    assert "started" in payload["owner_production_series"]["u1"]["received"]
    assert "started" in payload["owner_production_verdict"]["u1"]
