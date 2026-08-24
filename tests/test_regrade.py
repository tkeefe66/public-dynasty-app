# tests/test_regrade.py
"""Tests for the became-grade (engine/regrade.py).

Fixtures mirror tests/test_lineage.py's dict-form trades and the matchup /
KTC shapes the production grader consumes.
"""
from sleeper_dynasty.engine.regrade import build_became_grade
from sleeper_dynasty.models.player import KTCValue

from tests.helpers import trade_player_asset as _player
from tests.helpers import trade_pick_asset as _pick


def _trade(tx, date, sides, *, league_id="L", season=2025, week=1):
    return {"trade": {"transaction_id": tx, "traded_at": date, "league_id": league_id,
                      "season": season, "week": week},
            "sides": sides}


def _ktc(value):
    return KTCValue(name="x", normalized_name="x", position="RB", superflex_value=value)


def _matchup(players, starters, points):
    return {"players": players, "starters": starters, "players_points": points}


# u_a receives B in a single trade and keeps him. roster 1 = u_a in league L.
ROSTER_MAP = {"L": {1: "u_a", 2: "u_b"}}


def test_kept_terminal_player_value_plus_production():
    B = _player("B", "Player B")
    trades = [_trade("t1", "2025-01-01T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [B], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [B]}})]
    # Player B scores 10 in week 2 (post-trade), on u_a's roster (rid 1).
    matchups = {("L", 2, 1): _matchup(["B"], ["B"], {"B": 10.0})}
    out = build_became_grade(
        trades[0], trades, matchups=matchups,
        roster_to_user_by_league=ROSTER_MAP,
        phase_by_lwr={},
        playoff_week_start_by_league={"L": 15},
        league_season_by_id={"L": 2025},
        ktc_values={"B": _ktc(5000)}, pick_values={})
    g = out["u_a"]
    assert g["ktc"] == 5000.0
    assert g["production"] == 10.0
    assert g["regular"] == 10.0
    assert g["playoff"] == 0.0           # week 2 is not a playoff week
    assert "Player B" in g["terminal_labels"]


def test_player_flipped_immediately_keeps_market_zero_production():
    # A -> flip -> B(terminal). B never scores for u_a (flipped on, no ownership weeks).
    A = _player("A", "Player A"); B = _player("B", "Player B")
    trades = [
        _trade("t1", "2025-01-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [A], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [A]}}),
        _trade("t2", "2025-02-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [B], "given": [A]},
            "u_b": {"user_id": "u_b", "received": [A], "given": [B]}}),
    ]
    # B scores, but only on u_b's roster (rid 2) — u_a never owned him on a roster.
    matchups = {("L", 3, 2): _matchup(["B"], ["B"], {"B": 20.0})}
    out = build_became_grade(
        trades[0], trades, matchups=matchups,
        roster_to_user_by_league=ROSTER_MAP,
        phase_by_lwr={},
        playoff_week_start_by_league={"L": 15},
        league_season_by_id={"L": 2025},
        ktc_values={"B": _ktc(3000)}, pick_values={})
    g = out["u_a"]
    assert g["ktc"] == 3000.0            # still B's market value
    assert g["production"] == 0.0


def test_undrafted_pick_terminal_value_only():
    fut = _pick(2027, 1, "u_z")          # never drafted -> terminal pick
    trades = [_trade("t1", "2025-01-01T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [fut], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [fut]}})]
    out = build_became_grade(
        trades[0], trades, matchups={},
        roster_to_user_by_league=ROSTER_MAP,
        phase_by_lwr={},
        playoff_week_start_by_league={"L": 15},
        league_season_by_id={"L": 2025},
        ktc_values={}, pick_values={(2027, 1): _ktc(1200)})
    g = out["u_a"]
    assert g["ktc"] == 1200.0
    assert g["production"] == 0.0
    assert g["regular"] == 0.0
    assert g["playoff"] == 0.0
    assert g["toilet"] == 0.0


def test_pick_chain_sums_terminal_players():
    # P1 -> C(player) + P2(pick) ; P2 -> D(player). Became = C + D.
    P1 = _pick(2026, 1, "u_x"); C = _player("C", "Player C")
    P2 = _pick(2027, 1, "u_x"); D = _player("D", "Player D")
    trades = [
        _trade("t1", "2025-01-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [P1], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [P1]}}),
        _trade("t2", "2025-02-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [C, P2], "given": [P1]},
            "u_b": {"user_id": "u_b", "received": [P1], "given": [C, P2]}}),
        _trade("t3", "2025-03-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [D], "given": [P2]},
            "u_b": {"user_id": "u_b", "received": [P2], "given": [D]}}),
    ]
    # Both C and D score for u_a (rid 1) post the root trade.
    matchups = {("L", 5, 1): _matchup(["C", "D"], ["C", "D"], {"C": 7.0, "D": 3.0})}
    out = build_became_grade(
        trades[0], trades, matchups=matchups,
        roster_to_user_by_league=ROSTER_MAP,
        phase_by_lwr={},
        playoff_week_start_by_league={"L": 15},
        league_season_by_id={"L": 2025},
        ktc_values={"C": _ktc(2000), "D": _ktc(1000)}, pick_values={})
    g = out["u_a"]
    assert g["ktc"] == 3000.0            # C + D market
    assert g["production"] == 10.0       # 7 + 3
    labels = g["terminal_labels"]
    assert any("Player C" in l for l in labels)
    assert any("Player D" in l for l in labels)


def test_phase_taxonomy_regular_playoff_toilet():
    """Terminal player's points are attributed to the correct phase bucket."""
    B = _player("B", "Player B")
    trades = [_trade("t1", "2025-01-01T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [B], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [B]}})]
    # week 5: regular season, started -> regular bucket
    # week 16: playoff week, in playoff bracket -> playoff bucket
    # week 17: playoff week, in toilet bracket -> toilet bucket
    # week 18: playoff week, absent from phase_by_lwr -> "dropped", not counted in any phase_filter
    matchups = {
        ("L", 5, 1):  _matchup(["B"], ["B"], {"B": 10.0}),
        ("L", 16, 1): _matchup(["B"], ["B"], {"B": 20.0}),
        ("L", 17, 1): _matchup(["B"], ["B"], {"B": 5.0}),
        ("L", 18, 1): _matchup(["B"], ["B"], {"B": 3.0}),
    }
    phase_by_lwr = {
        ("L", 16, 1): "playoff",
        ("L", 17, 1): "toilet",
        # ("L", 18, 1) absent => "dropped"
    }
    out = build_became_grade(
        trades[0], trades, matchups=matchups,
        roster_to_user_by_league=ROSTER_MAP,
        phase_by_lwr=phase_by_lwr,
        playoff_week_start_by_league={"L": 15},
        league_season_by_id={"L": 2025},
        ktc_values={"B": _ktc(100)}, pick_values={})
    g = out["u_a"]
    # production = all weeks bench-inclusive = 10 + 20 + 5 + 3
    assert g["production"] == 38.0
    # regular = started, week < 15: only week 5
    assert g["regular"] == 10.0
    # playoff = started, phase=="playoff": only week 16
    assert g["playoff"] == 20.0
    # toilet = started, phase=="toilet": only week 17
    assert g["toilet"] == 5.0


def test_playoff_and_started_gates():
    B = _player("B", "Player B")
    trades = [_trade("t1", "2025-01-01T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [B], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [B]}})]
    matchups = {
        # week 5: benched (not in starters), regular season
        ("L", 5, 1): _matchup(["B"], [], {"B": 8.0}),
        # week 16: started, playoff week
        ("L", 16, 1): _matchup(["B"], ["B"], {"B": 12.0}),
    }
    phase_by_lwr = {("L", 16, 1): "playoff"}
    out = build_became_grade(
        trades[0], trades, matchups=matchups,
        roster_to_user_by_league=ROSTER_MAP,
        phase_by_lwr=phase_by_lwr,
        playoff_week_start_by_league={"L": 15},
        league_season_by_id={"L": 2025},
        ktc_values={"B": _ktc(100)}, pick_values={})
    g = out["u_a"]
    assert g["production"] == 20.0       # both weeks, bench included
    assert g["regular"] == 0.0           # week 5 benched -> not in starters
    assert g["playoff"] == 12.0          # started + playoff week
    assert g["toilet"] == 0.0


def test_became_breakdown_rows_sum_to_totals():
    B = _player("B", "Player B")
    C = _player("C", "Player C")
    trades = [_trade("t1", "2025-01-01T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [B, C], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [B, C]}})]
    matchups = {
        ("L", 2, 1): _matchup(["B", "C"], ["B", "C"], {"B": 10.0, "C": 6.0}),
    }
    out = build_became_grade(
        trades[0], trades, matchups=matchups,
        roster_to_user_by_league=ROSTER_MAP, phase_by_lwr={},
        playoff_week_start_by_league={"L": 15},
        league_season_by_id={"L": 2025},
        ktc_values={"B": _ktc(5000), "C": _ktc(3000)}, pick_values={})
    g = out["u_a"]
    rows = g["breakdown"]
    assert {r["player_id"] for r in rows} == {"B", "C"}
    b = next(r for r in rows if r["player_id"] == "B")
    assert b["kind"] == "player" and b["label"] == "Player B"
    assert b["ktc"] == 5000.0 and b["production_total"] == 10.0
    # Rows sum to the side totals.
    assert g["ktc"] == sum(r["ktc"] for r in rows)
    assert g["production"] == sum(r["production_total"] for r in rows)
    assert g["regular"] == sum(r["production_regular"] for r in rows)
