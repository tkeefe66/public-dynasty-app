"""Tests for compute_injury_payload in grader.py."""
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
def injury_two_team_chain():
    """Two-team chain for injury testing.

    One trade (tx1), league L1, season 2024, week 4.
    u1 received p1; p1 is rostered for weeks 5 AND 6, but only played week 5.
    Week 6 p1 is on roster (in 'players') but absent from 'players_points'
    (simulating a missed game). Week 6 classifies as regular (< playoff_week_start=15).
    The injury_map passed to compute_injury_payload flags (p1, 2024, 6) as missed.
    """
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

    # Week 5: p1 is rostered and played (has players_points).
    # Week 6: p1 is rostered (in 'players') but did NOT play (absent from players_points).
    matchups = {
        ("L1", 5, 1): {
            "players": ["p1"],
            "starters": ["p1"],
            "players_points": {"p1": 20.0},
        },
        ("L1", 6, 1): {
            "players": ["p1"],      # rostered — owned_weeks includes (2024, 6)
            "starters": ["p1"],
            "players_points": {},   # NOT in players_points — played_weeks excludes (2024, 6)
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
    )


def test_injury_payload_shape(injury_two_team_chain):
    from app.services.grader import compute_injury_payload

    f = injury_two_team_chain
    payload = compute_injury_payload(
        resolved_dicts=f.resolved_dicts,
        matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id,
        current_holders=f.current_holders,
        drop_index=f.drop_index,
        phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league,
        injury_map={
            ("p1", 2024, 6): {
                "missed": True,
                "confidence": "high",
                "source": "roster_status:RES",
            }
        },
        raw_players={
            "p1": {
                "injury_status": "Out",
                "injury_body_part": "Knee",
                "injury_start_date": "2024-10-01",
            }
        },
    )

    tx = f.resolved_dicts[0]["trade"]["transaction_id"]
    inj = payload["trade_injury"][tx]["u1"]["p1"]

    # p1 missed 1 regular-season game (week 6 is < playoff_week_start=15)
    assert inj["games_missed"]["regular"] == 1
    assert inj["games_missed"]["playoff"] == 0
    assert inj["games_missed"]["toilet"] == 0

    # Live status: p1 is currently out
    assert inj["currently_out"] is True
    assert inj["out_detail"] is not None
    assert "Out" in inj["out_detail"]

    # missed_weeks: [[season, week, confidence]]
    assert inj["missed_weeks"] == [[2024, 6, "high"]]


def test_injury_payload_omits_healthy_players(injury_two_team_chain):
    """Players with no missed games and not currently out are omitted from the payload."""
    from app.services.grader import compute_injury_payload

    f = injury_two_team_chain
    payload = compute_injury_payload(
        resolved_dicts=f.resolved_dicts,
        matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id,
        current_holders=f.current_holders,
        drop_index=f.drop_index,
        phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league,
        injury_map={},       # no injuries flagged
        raw_players={},      # no live status
    )
    # With no injuries and no live-out status, trade_injury should be empty
    assert payload["trade_injury"] == {}


def test_injury_payload_currently_out_without_missed_games(injury_two_team_chain):
    """A player currently out (live status) but with no historical missed games
    still appears in the payload."""
    from app.services.grader import compute_injury_payload

    f = injury_two_team_chain
    payload = compute_injury_payload(
        resolved_dicts=f.resolved_dicts,
        matchups=f.matchups,
        roster_to_user_by_league=f.roster_to_user_by_league,
        league_season_by_id=f.league_season_by_id,
        current_holders=f.current_holders,
        drop_index=f.drop_index,
        phase_by_lwr=f.phase_by_lwr,
        playoff_week_start_by_league=f.playoff_week_start_by_league,
        injury_map={},  # no historical missed games
        raw_players={
            "p1": {
                "injury_status": "IR",
                "injury_body_part": "Shoulder",
                "injury_start_date": "2024-11-01",
            }
        },
    )
    tx = f.resolved_dicts[0]["trade"]["transaction_id"]
    inj = payload["trade_injury"][tx]["u1"]["p1"]
    assert inj["currently_out"] is True
    assert inj["games_missed"] == {"regular": 0, "playoff": 0, "toilet": 0}
    assert inj["missed_weeks"] == []
