"""Fix 2: IR players absent from players[] during injury weeks must still count as missed.

Sleeper drops IR-placed players from the weekly `players` array, so the old
`_owned_played` (which gated ownership on `pid in entry["players"]`) never saw
those weeks as owned -> misses were silently skipped.

The fix derives ownership from the player's tenure span (trade week -> terminal),
so an injury-flagged week is counted even when the player isn't in `players[]`.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_resolved_dicts(*, trade_week: int = 4, season: int = 2024,
                         league_id: str = "L1",
                         tx: str = "tx1",
                         uid_recv: str = "u1",
                         pid_recv: str = "p1") -> list[dict]:
    """One trade: uid_recv received pid_recv on trade_week."""
    trade_dict = {
        "transaction_id": tx,
        "league_id": league_id,
        "season": season,
        "week": trade_week,
        "traded_at": f"{season}-10-01T00:00:00+00:00",
    }
    sides_dict = {
        uid_recv: {
            "received": [{"player_id": pid_recv, "name": "Player One", "via_pick": None}],
            "given":    [{"player_id": "p2",     "name": "Player Two", "via_pick": None}],
        },
        "u2": {
            "received": [{"player_id": "p2",     "name": "Player Two", "via_pick": None}],
            "given":    [{"player_id": pid_recv, "name": "Player One", "via_pick": None}],
        },
    }
    return [{"trade": trade_dict, "sides": sides_dict}]


def _make_matchups(*, pid: str = "p1", uid: str = "u1", season: int = 2024,
                   league_id: str = "L1",
                   uid_rid: int = 1, other_rid: int = 2) -> dict:
    """
    Week 5: pid in players AND players_points (played normally).
    Week 6: pid NOT in players AND NOT in players_points (on IR — dropped from array).
             uid still has a roster entry for week 6 (key exists, p1 just absent).
    """
    return {
        (league_id, 5, uid_rid): {
            "players": [pid],
            "starters": [pid],
            "players_points": {pid: 20.0},
        },
        # Week 6: uid has a matchup entry but p1 is absent (IR drop)
        (league_id, 6, uid_rid): {
            "players": [],          # p1 dropped from array by Sleeper
            "starters": [],
            "players_points": {},
        },
        # Other team's entries (needed so matchup iteration doesn't break)
        (league_id, 5, other_rid): {
            "players": ["p2"],
            "starters": ["p2"],
            "players_points": {"p2": 10.0},
        },
        (league_id, 6, other_rid): {
            "players": ["p2"],
            "starters": ["p2"],
            "players_points": {"p2": 12.0},
        },
    }


# ---------------------------------------------------------------------------
# Test: IR week counted even when absent from players[]
# ---------------------------------------------------------------------------

def test_ir_week_counted_even_when_absent_from_players_list():
    """An injury-flagged week where p1 is NOT in players[] must still register
    as a missed game, because the tenure span covers it."""
    from app.services.grader import compute_injury_payload

    tx = "tx1"
    resolved_dicts = _make_resolved_dicts(trade_week=4, season=2024,
                                          league_id="L1", tx=tx,
                                          uid_recv="u1", pid_recv="p1")
    matchups = _make_matchups(pid="p1", uid="u1", season=2024,
                              league_id="L1", uid_rid=1, other_rid=2)

    # p1 is held (still with u1 at current_holders).
    # Week 6: injury-flagged in injury_map — the ONLY signal for a missed game.
    injury_map = {
        ("p1", 2024, 6): {"missed": True, "confidence": "high", "source": "roster_ir:R01"},
    }

    payload = compute_injury_payload(
        resolved_dicts=resolved_dicts,
        matchups=matchups,
        roster_to_user_by_league={"L1": {1: "u1", 2: "u2"}},
        league_season_by_id={"L1": 2024},
        current_holders={"p1": "u1", "p2": "u2"},
        drop_index={},
        phase_by_lwr={},
        playoff_week_start_by_league={"L1": 15},
        injury_map=injury_map,
        raw_players={},   # no live status — only the historical IR miss matters
    )

    inj = payload["trade_injury"][tx]["u1"]["p1"]
    assert inj["games_missed"]["regular"] == 1, (
        "week 6 IR miss should count even though p1 absent from players[]"
    )
    assert inj["missed_weeks"] == [[2024, 6, "high"]]


# ---------------------------------------------------------------------------
# Test: IR week present in players_points as 0.0 must still count (real prod case)
# ---------------------------------------------------------------------------

def test_ir_week_counted_when_present_as_zero_points():
    """The real prod case: Sleeper keeps the IR player in `players` AND in
    `players_points` as 0.0 (just not in `starters`). A presence-based "played"
    check wrongly excludes it; "played" must mean SCORED > 0."""
    from app.services.grader import compute_injury_payload

    tx = "tx1"
    resolved_dicts = _make_resolved_dicts(trade_week=4, season=2024,
                                          league_id="L1", tx=tx,
                                          uid_recv="u1", pid_recv="p1")
    matchups = {
        ("L1", 5, 1): {"players": ["p1"], "starters": ["p1"], "players_points": {"p1": 20.0}},
        # Week 6: IR — present in players + players_points as 0.0, NOT a starter
        ("L1", 6, 1): {"players": ["p1"], "starters": [], "players_points": {"p1": 0.0}},
        ("L1", 5, 2): {"players": ["p2"], "starters": ["p2"], "players_points": {"p2": 10.0}},
        ("L1", 6, 2): {"players": ["p2"], "starters": ["p2"], "players_points": {"p2": 12.0}},
    }
    injury_map = {
        ("p1", 2024, 6): {"missed": True, "confidence": "high", "source": "roster_ir:R01"},
    }

    payload = compute_injury_payload(
        resolved_dicts=resolved_dicts, matchups=matchups,
        roster_to_user_by_league={"L1": {1: "u1", 2: "u2"}},
        league_season_by_id={"L1": 2024},
        current_holders={"p1": "u1", "p2": "u2"}, drop_index={},
        phase_by_lwr={}, playoff_week_start_by_league={"L1": 15},
        injury_map=injury_map, raw_players={},
    )

    inj = payload["trade_injury"][tx]["u1"]["p1"]
    assert inj["games_missed"]["regular"] == 1, (
        "week 6 IR miss must count even though p1 is in players_points as 0.0"
    )
    assert inj["missed_weeks"] == [[2024, 6, "high"]]


# ---------------------------------------------------------------------------
# Guard: pre-trade injury week is NOT counted
# ---------------------------------------------------------------------------

def test_pre_trade_injury_week_not_counted():
    """An injury flag for the week BEFORE the trade must not be attributed."""
    from app.services.grader import compute_injury_payload

    tx = "tx1"
    resolved_dicts = _make_resolved_dicts(trade_week=4, season=2024,
                                          league_id="L1", tx=tx,
                                          uid_recv="u1", pid_recv="p1")
    matchups = _make_matchups(pid="p1", uid="u1", season=2024,
                              league_id="L1", uid_rid=1, other_rid=2)
    # Add a week-3 entry where p1 played (pre-trade)
    matchups[("L1", 3, 1)] = {
        "players": ["p1"],
        "starters": ["p1"],
        "players_points": {"p1": 15.0},
    }

    # Week 3 is injury-flagged (pre-trade) — should NOT count
    # Week 6 is NOT injury-flagged — should also NOT count
    injury_map = {
        ("p1", 2024, 3): {"missed": True, "confidence": "high", "source": "roster_ir:R01"},
    }

    payload = compute_injury_payload(
        resolved_dicts=resolved_dicts,
        matchups=matchups,
        roster_to_user_by_league={"L1": {1: "u1", 2: "u2"}},
        league_season_by_id={"L1": 2024},
        current_holders={"p1": "u1", "p2": "u2"},
        drop_index={},
        phase_by_lwr={},
        playoff_week_start_by_league={"L1": 15},
        injury_map=injury_map,
        raw_players={},
    )

    # No missed games after the trade, no live injury -> omitted entirely
    assert payload["trade_injury"] == {}, (
        "pre-trade injury week must not appear in the payload"
    )
