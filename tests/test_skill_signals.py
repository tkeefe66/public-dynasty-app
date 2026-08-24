from sleeper_dynasty.engine.skill_signals import lineup_skill_signals
from sleeper_dynasty.engine.skill_signals import trade_skill_signals


def test_lineup_efficiency_perfect_and_imperfect():
    # One league "L", QB + FLEX slots. Two owners.
    # Owner A (roster 1) started optimally; Owner B (roster 2) benched their stud.
    roster_positions = ["QB", "FLEX", "BN"]
    matchups = {
        ("L", 1, 1): {
            "starters": ["qb1", "rb1"], "players": ["qb1", "rb1", "wr_bench"],
            "players_points": {"qb1": 20.0, "rb1": 15.0, "wr_bench": 5.0},
        },
        ("L", 1, 2): {
            # Started qb2 + the weak WR; benched the 18-pt RB. Optimal = 25+18=43,
            # actual = 25+4 = 29 -> efficiency 29/43.
            "starters": ["qb2", "wr_weak"], "players": ["qb2", "wr_weak", "rb_bench"],
            "players_points": {"qb2": 25.0, "wr_weak": 4.0, "rb_bench": 18.0},
        },
    }
    out = lineup_skill_signals(
        matchups=matchups,
        roster_positions_by_league={"L": roster_positions},
        positions={"qb1": "QB", "rb1": "RB", "wr_bench": "WR",
                   "qb2": "QB", "wr_weak": "WR", "rb_bench": "RB"},
        roster_to_user_by_league={"L": {1: "A", 2: "B"}},
        owners=["A", "B"],
    )
    assert out["A"]["lineup_skill"] == 1.0           # 35/35 optimal
    assert abs(out["B"]["lineup_skill"] - 29.0 / 43.0) < 1e-9
    # An owner with no games scores 0.0 (no division by zero).
    out2 = lineup_skill_signals(
        matchups={}, roster_positions_by_league={}, positions={},
        roster_to_user_by_league={}, owners=["C"])
    assert out2["C"]["lineup_skill"] == 0.0


def test_lineup_efficiency_never_exceeds_one_on_edge_cases():
    # A started player with an UNKNOWN position must not inflate efficiency past 1.0,
    # and a week with no roster_positions must be skipped (not counted as actual-only).
    matchups = {
        ("L", 1, 1): {  # ghost starter "mystery" has no position entry
            "starters": ["qb1", "mystery"], "players": ["qb1", "mystery"],
            "players_points": {"qb1": 20.0, "mystery": 99.0},
        },
        ("L2", 2, 1): {  # week in a league with empty rpos -> must be skipped
            "starters": ["qb1"], "players": ["qb1"],
            "players_points": {"qb1": 10.0},
        },
    }
    out = lineup_skill_signals(
        matchups=matchups,
        roster_positions_by_league={"L": ["QB", "BN"], "L2": []},
        positions={"qb1": "QB"},  # "mystery" intentionally absent
        roster_to_user_by_league={"L": {1: "A"}, "L2": {1: "A"}},
        owners=["A"],
    )
    # Wk1 optimal = qb1(20); actual counts only positioned starters = qb1(20) -> 1.0.
    # "mystery" (99) is excluded from BOTH, so efficiency stays 1.0, not 5.95.
    # L2 wk2 has empty rpos -> opt_total 0 -> skipped, never counted as actual-only.
    assert out["A"]["lineup_skill"] == 1.0
    assert out["A"]["lineup_skill"] <= 1.0


def test_trade_skill_zero_sum_and_shrinkage():
    # A fleeces B once: +30 value, A's haul produced 80 vs B's 20.
    trades = [{
        "value_swing": {"A": 30.0, "B": -30.0},
        "production": {"A": 80.0, "B": 20.0},
    }]
    out = trade_skill_signals(trades, owners=["A", "B", "C"], k=2.0)
    # n=1 -> shrink = 1/(1+2) = 1/3. value avg = swing itself.
    assert abs(out["A"]["trade_value"] - 30.0 / 3.0) < 1e-9
    assert abs(out["B"]["trade_value"] - (-30.0 / 3.0)) < 1e-9
    # production recentered: mean=50 -> A:+30, B:-30; avg over 1 trade, shrink 1/3.
    assert abs(out["A"]["trade_production"] - 30.0 / 3.0) < 1e-9
    assert abs(out["B"]["trade_production"] - (-30.0 / 3.0)) < 1e-9
    # Non-trader C sits exactly neutral.
    assert out["C"] == {"trade_value": 0.0, "trade_production": 0.0}


def test_trade_skill_averages_not_sums_volume():
    # Owner X makes the SAME +30 winning trade twice. Averaging => mean swing 30,
    # shrunk by 2/(2+2)=0.5 => 15. A summing bug would give 60*0.5=30. The assert
    # on 15 (and the != 30 guard) is what distinguishes average from sum.
    win = {"value_swing": {"X": 30.0, "Z": -30.0}, "production": {"X": 70.0, "Z": 10.0}}
    out = trade_skill_signals([win, win], owners=["X", "Z"], k=2.0)
    assert abs(out["X"]["trade_value"] - 15.0) < 1e-9   # avg(30,30)=30 * 0.5
    assert out["X"]["trade_value"] != 30.0              # would be 30.0 if summed
    # production recentered per trade: mean=40 -> X:+30 each; avg 30 * 0.5 = 15.
    assert abs(out["X"]["trade_production"] - 15.0) < 1e-9
