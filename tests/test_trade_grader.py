from datetime import datetime, timezone

import pytest

from sleeper_dynasty.engine.trade_grader import grade_hindsight_production, grade_snapshot_value, grade_trade
from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.models.trade import (
    FaabAsset,
    PickAsset,
    PlayerAsset,
    ResolvedTrade,
    Trade,
    TradeSide,
)


def _stub_resolved_trade(received_by_uid, given_by_uid):
    """Make a minimal ResolvedTrade with two sides."""
    sides = {
        uid: TradeSide(uid, list(received_by_uid[uid]), list(given_by_uid[uid]))
        for uid in received_by_uid
    }
    base = Trade(
        transaction_id="t1",
        league_id="L",
        season=2024,
        week=2,
        traded_at=datetime(2024, 9, 12, tzinfo=timezone.utc),
        sides=sides,
    )
    return ResolvedTrade(trade=base, sides=sides)


def test_snapshot_value_swing_two_player_trade():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_bijan", "Bijan")],
            "u2": [PlayerAsset("p_adams", "Adams")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_adams", "Adams")],
            "u2": [PlayerAsset("p_bijan", "Bijan")],
        },
    )
    ktc = {
        "p_bijan": KTCValue(
            name="Bijan", normalized_name="bijan", position="RB",
            superflex_value=7500, one_qb_value=7400,
        ),
        "p_adams": KTCValue(
            name="Adams", normalized_name="adams", position="WR",
            superflex_value=6050, one_qb_value=6000,
        ),
    }
    swings = grade_snapshot_value(rt, ktc, fmt="superflex")
    assert swings["u1"] == pytest.approx(7500 - 6050)  # +1450
    assert swings["u2"] == pytest.approx(6050 - 7500)  # -1450


def test_snapshot_value_unknown_player_counts_as_zero():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("missing", "?")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("missing", "?")]},
    )
    swings = grade_snapshot_value(rt, ktc_values={}, fmt="superflex")
    assert swings["u1"] == 0.0
    assert swings["u2"] == 0.0


def test_snapshot_value_faab_is_zero():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [FaabAsset(amount=25)], "u2": []},
        given_by_uid={"u1": [], "u2": [FaabAsset(amount=25)]},
    )
    swings = grade_snapshot_value(rt, ktc_values={}, fmt="superflex")
    assert swings["u1"] == 0.0
    assert swings["u2"] == 0.0


def test_snapshot_value_future_pick_uses_pick_table():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PickAsset(season=2030, round=1, original_owner_user_id="u1")],
            "u2": [],
        },
        given_by_uid={
            "u1": [],
            "u2": [PickAsset(season=2030, round=1, original_owner_user_id="u1")],
        },
    )
    pick_values = {
        (2030, 1): KTCValue(
            name="2030 Round 1", normalized_name="2030 round 1", position="PICK",
            superflex_value=5000, one_qb_value=4800,
        )
    }
    swings = grade_snapshot_value(rt, ktc_values={}, fmt="superflex",
                                  pick_values=pick_values)
    assert swings["u1"] == pytest.approx(5000)
    assert swings["u2"] == pytest.approx(-5000)


def test_snapshot_value_future_pick_zero_without_table():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PickAsset(season=2030, round=1, original_owner_user_id="u1")],
            "u2": [],
        },
        given_by_uid={
            "u1": [],
            "u2": [PickAsset(season=2030, round=1, original_owner_user_id="u1")],
        },
    )
    swings = grade_snapshot_value(rt, ktc_values={}, fmt="superflex")
    assert swings["u1"] == 0.0
    assert swings["u2"] == 0.0


def test_snapshot_value_drafted_but_flipped_pick_uses_player_value():
    # A pick annotated with its drafted player (non-resolution trade) is valued
    # at that player's CURRENT KTC, so it telescopes against the resolution trade.
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PickAsset(season=2024, round=1, original_owner_user_id="u_a",
                             drafted_player_id="p_jayden",
                             drafted_player_name="Jayden Daniels")],
            "u2": [],
        },
        given_by_uid={
            "u1": [],
            "u2": [PickAsset(season=2024, round=1, original_owner_user_id="u_a",
                             drafted_player_id="p_jayden",
                             drafted_player_name="Jayden Daniels")],
        },
    )
    ktc = {
        "p_jayden": KTCValue(
            name="Jayden Daniels", normalized_name="jayden daniels", position="QB",
            superflex_value=8000, one_qb_value=7900,
        )
    }
    swings = grade_snapshot_value(rt, ktc_values=ktc, fmt="superflex")
    assert swings["u1"] == pytest.approx(8000)
    assert swings["u2"] == pytest.approx(-8000)


def test_hindsight_sums_post_trade_points_for_receiver():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_bijan", "Bijan")],
            "u2": [PlayerAsset("p_adams", "Adams")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_adams", "Adams")],
            "u2": [PlayerAsset("p_bijan", "Bijan")],
        },
    )
    # u1 -> roster 1; u2 -> roster 2 in 2024 league.
    roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    # Trade was week 2; weeks 3+ count.
    matchups = {
        ("L", 3, 1): {
            "starters": [], "players": ["p_bijan"],
            "players_points": {"p_bijan": 20.0}, "team_points": 100.0,
        },
        ("L", 3, 2): {
            "starters": [], "players": ["p_adams"],
            "players_points": {"p_adams": 15.0}, "team_points": 90.0,
        },
        ("L", 4, 1): {
            "starters": [], "players": ["p_bijan"],
            "players_points": {"p_bijan": 25.0}, "team_points": 105.0,
        },
        ("L", 4, 2): {
            "starters": [], "players": ["p_adams"],
            "players_points": {"p_adams": 10.0}, "team_points": 85.0,
        },
    }
    swings = grade_hindsight_production(
        rt,
        matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
    )
    # Received-only: u1 counts Bijan (20+25=45); u2 counts Adams (15+10=25).
    assert swings["u1"] == pytest.approx(45.0)
    assert swings["u2"] == pytest.approx(25.0)


def test_hindsight_ignores_weeks_before_trade():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_x", "X")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_x", "X")]},
    )
    # Trade week is 2 (per _stub_resolved_trade). Week 1 should not count.
    matchups = {
        ("L", 1, 1): {
            "starters": [], "players": ["p_x"],
            "players_points": {"p_x": 99.0}, "team_points": 100.0,
        },
        ("L", 3, 1): {
            "starters": [], "players": ["p_x"],
            "players_points": {"p_x": 10.0}, "team_points": 100.0,
        },
    }
    swings = grade_hindsight_production(
        rt,
        matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
    )
    assert swings["u1"] == pytest.approx(10.0)


def test_hindsight_started_only_counts_starter_weeks():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_x", "X")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_x", "X")]},
    )
    # Trade week is 2. Week 3 player started; week 4 benched.
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 20.0}, "team_points": 100.0,
        },
        ("L", 4, 1): {
            "starters": [], "players": ["p_x"],
            "players_points": {"p_x": 12.0}, "team_points": 100.0,
        },
    }
    roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    total = grade_hindsight_production(
        rt, matchups=matchups, roster_to_user_by_league=roster_to_user_by_league,
    )
    started = grade_hindsight_production(
        rt, matchups=matchups, roster_to_user_by_league=roster_to_user_by_league,
        starters_only=True,
    )
    # Total counts both weeks (bench included); started counts only week 3.
    assert total["u1"] == pytest.approx(32.0)
    assert started["u1"] == pytest.approx(20.0)


def test_hindsight_playoff_only_counts_started_playoff_weeks():
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_x", "X")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_x", "X")]},
    )
    # Trade week is 2. Playoffs start week 15. Mix of started/benched and
    # regular-season/playoff weeks.
    matchups = {
        ("L", 3, 1): {   # started, regular season
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 20.0}, "team_points": 100.0,
        },
        ("L", 15, 1): {  # started, playoff winners-bracket week → counts
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 30.0}, "team_points": 100.0,
        },
        ("L", 16, 1): {  # benched, playoff week → excluded (started gate)
            "starters": [], "players": ["p_x"],
            "players_points": {"p_x": 40.0}, "team_points": 100.0,
        },
    }
    roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    # Mark week 15 as playoff (winners bracket), week 16 as dropped (benched).
    phase_by_lwr = {("L", 15, 1): "playoff"}
    playoff_week_start_by_league = {"L": 15}
    started = grade_hindsight_production(
        rt, matchups=matchups, roster_to_user_by_league=roster_to_user_by_league,
        starters_only=True,
    )
    playoff = grade_hindsight_production(
        rt, matchups=matchups, roster_to_user_by_league=roster_to_user_by_league,
        starters_only=True, phase_filter="playoff",
        phase_by_lwr=phase_by_lwr,
        playoff_week_start_by_league=playoff_week_start_by_league,
    )
    # Started (no phase filter) counts all post-trade started weeks: 3 + 15 = 50.
    assert started["u1"] == pytest.approx(50.0)
    # Playoff-started counts only week 15 (winners bracket) = 30.
    assert playoff["u1"] == pytest.approx(30.0)


def test_production_is_received_only_not_swing():
    """Production is received-only: a given-away player scoring on the OTHER
    roster must NOT subtract from the trader's metric (the phantom-bug fix)."""
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_r", "R")], "u2": [PlayerAsset("p_g", "G")]},
        given_by_uid={"u1": [PlayerAsset("p_g", "G")], "u2": [PlayerAsset("p_r", "R")]},
    )
    roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    # Week 3 (regular, started): R scores 50 on u1's roster; G scores 40 on u2's roster.
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_r"], "players": ["p_r"],
            "players_points": {"p_r": 50.0}, "team_points": 100.0,
        },
        ("L", 3, 2): {
            "starters": ["p_g"], "players": ["p_g"],
            "players_points": {"p_g": 40.0}, "team_points": 90.0,
        },
    }
    reg = grade_hindsight_production(
        rt, matchups=matchups, roster_to_user_by_league=roster_to_user_by_league,
        starters_only=True, phase_filter="regular",
        phase_by_lwr={}, playoff_week_start_by_league={"L": 15},
    )
    # Received-only: u1 counts only R (50), NOT 50 - 40(phantom G) = 10.
    assert reg["u1"] == pytest.approx(50.0)
    assert reg["u2"] == pytest.approx(40.0)


from sleeper_dynasty.engine.trade_grader import aggregate_owner_records, grade_trade
from sleeper_dynasty.models.trade import TradeGrade


def test_hindsight_excludes_prior_season_matchups():
    """Regression: a 2026 trade should NOT be credited with 2024 season matchups."""
    sides = {
        "u1": TradeSide("u1", received=[PlayerAsset("p_bijan", "Bijan")], given=[]),
        "u2": TradeSide("u2", received=[], given=[PlayerAsset("p_bijan", "Bijan")]),
    }
    t = Trade(
        transaction_id="t1",
        league_id="L2026",
        season=2026,
        week=2,
        traded_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        sides=sides,
    )
    rt = ResolvedTrade(trade=t, sides=sides)

    # Matchups span 2024, 2025 leagues — both PRIOR seasons, should NOT count.
    matchups = {
        ("L2024", 5, 1): {  # 2024 — PRIOR season, should NOT count
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 100.0},
            "team_points": 150.0, "opponent_points": 100.0,
        },
        ("L2025", 8, 1): {  # 2025 — PRIOR season, should NOT count
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 200.0},
            "team_points": 150.0, "opponent_points": 100.0,
        },
        # No 2026 matchups (season hasn't started in our scenario).
    }
    league_season_by_id = {"L2024": 2024, "L2025": 2025, "L2026": 2026}
    swings = grade_hindsight_production(
        rt, matchups, {"L2024": {1: "u1"}, "L2025": {1: "u1"}, "L2026": {1: "u1"}},
        league_season_by_id=league_season_by_id,
    )
    # u1 received Bijan but no post-trade weeks exist yet → 0.0.
    assert swings["u1"] == 0.0
    assert swings["u2"] == 0.0


def test_grade_trade_combines_all_views():
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_bijan", "Bijan")],
            "u2": [PlayerAsset("p_adams", "Adams")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_adams", "Adams")],
            "u2": [PlayerAsset("p_bijan", "Bijan")],
        },
    )
    ktc = {
        "p_bijan": KTCValue(
            name="Bijan", normalized_name="b", position="RB",
            superflex_value=7500, one_qb_value=7400,
        ),
        "p_adams": KTCValue(
            name="Adams", normalized_name="a", position="WR",
            superflex_value=6050, one_qb_value=6000,
        ),
    }
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 20.0},
            "team_points": 100.0, "opponent_points": 80.0,
        },
        ("L", 3, 2): {
            "starters": ["p_adams"], "players": ["p_adams"],
            "players_points": {"p_adams": 15.0},
            "team_points": 90.0, "opponent_points": 95.0,
        },
    }
    grade = grade_trade(
        rt,
        ktc_values=ktc,
        matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_week_start_by_league={"L": 15},
        fmt="superflex",
    )
    assert grade.trade_id == "t1"
    assert grade.snapshot_value_swing["u1"] == pytest.approx(1450.0)
    assert grade.production_total["u1"] == pytest.approx(20.0)
    # Week 3 is regular season → regular-started counts; playoff-started is 0.
    assert grade.production_regular["u1"] == pytest.approx(20.0)
    assert grade.production_playoff["u1"] == pytest.approx(0.0)
    assert grade.production_toilet.get("u1", 0.0) == pytest.approx(0.0)


def test_aggregate_owner_records_sums_across_trades():
    g1 = TradeGrade(
        trade_id="t1",
        snapshot_value_swing={"u1": 1000.0, "u2": -1000.0},
        production_total={"u1": 50.0, "u2": -50.0},
        production_regular={"u1": 40.0, "u2": -40.0},
        production_playoff={"u1": 15.0, "u2": -15.0},
        production_toilet={"u1": 5.0, "u2": -5.0},
    )
    g2 = TradeGrade(
        trade_id="t2",
        snapshot_value_swing={"u1": -500.0, "u3": 500.0},
        production_total={"u1": -10.0, "u3": 10.0},
        production_regular={"u1": -8.0, "u3": 8.0},
        production_playoff={"u1": -3.0, "u3": 3.0},
        production_toilet={"u1": -1.0, "u3": 1.0},
    )
    display_names = {"u1": "Alice", "u2": "Bob", "u3": "Carol"}
    records = aggregate_owner_records([g1, g2], display_names=display_names)
    a = records["u1"]
    assert a.trades == 2
    assert a.net_ktc == pytest.approx(500.0)
    assert a.production_total == pytest.approx(40.0)
    assert a.production_regular == pytest.approx(32.0)   # 40 - 8
    assert a.production_playoff == pytest.approx(12.0)   # 15 - 3
    assert a.production_toilet == pytest.approx(4.0)     # 5 - 1
    # Best trade for u1 is t1 (+1000 ktc); worst is t2 (-500 ktc).
    assert a.best_trade_id == "t1"
    assert a.worst_trade_id == "t2"
    # u3 only participated in t2.
    c = records["u3"]
    assert c.trades == 1
    assert c.net_ktc == pytest.approx(500.0)
    assert c.best_trade_id == "t2"


def test_flipped_pick_telescopes_and_credits_only_real_ownership():
    # B receives a pick in A<->B and flips it in B<->C. The pick's drafted
    # player ("p_x") is rostered only by C. Grade both trades and confirm:
    #  - snapshot: B's pick nets to ~0 across the two trades
    #  - production: B earns 0 from the pick (never rostered p_x)
    ktc = {
        "p_x": KTCValue(name="X", normalized_name="x", position="WR",
                        superflex_value=6000, one_qb_value=5900),
    }

    # A<->B: B receives an annotated (flipped) pick worth p_x's KTC.
    ab = _stub_resolved_trade(
        received_by_uid={
            "u_b": [PickAsset(season=2024, round=1, original_owner_user_id="u_a",
                              drafted_player_id="p_x", drafted_player_name="X")],
            "u_a": [],
        },
        given_by_uid={
            "u_b": [],
            "u_a": [PickAsset(season=2024, round=1, original_owner_user_id="u_a",
                              drafted_player_id="p_x", drafted_player_name="X")],
        },
    )
    # B<->C: the resolution trade. B gives the resolved player; C receives it.
    bc = _stub_resolved_trade(
        received_by_uid={
            "u_c": [PlayerAsset("p_x", "X")],
            "u_b": [],
        },
        given_by_uid={
            "u_c": [],
            "u_b": [PlayerAsset("p_x", "X")],
        },
    )

    ab_swings = grade_snapshot_value(ab, ktc, fmt="superflex")
    bc_swings = grade_snapshot_value(bc, ktc, fmt="superflex")

    # B: +6000 (received pick in A<->B) then -6000 (gave p_x in B<->C) = 0 net.
    assert ab_swings["u_b"] + bc_swings["u_b"] == pytest.approx(0.0)
    # A gave the pick: -6000. C received p_x: +6000.
    assert ab_swings["u_a"] == pytest.approx(-6000)
    assert bc_swings["u_c"] == pytest.approx(6000)

    # Production: p_x scores 20 pts in week 5, rostered by C (roster 3).
    matchups = {
        ("L", 5, 3): {
            "players": ["p_x"], "players_points": {"p_x": 20.0},
            "starters": ["p_x"], "team_points": 100.0, "opponent_points": 90.0,
        },
    }
    roster_to_user = {"L": {3: "u_c"}}
    # In A<->B, B received the pick (a PickAsset) -> no production for B.
    ab_prod = grade_hindsight_production(ab, matchups, roster_to_user)
    assert ab_prod["u_b"] == pytest.approx(0.0)


def test_ignore_drafted_player_values_pick_via_table():
    # A pick annotated with its drafted player. With ignore_drafted_player=True
    # it must use the pick table, NOT the player's KTC.
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PickAsset(season=2026, round=1, original_owner_user_id="u_a",
                             drafted_player_id="p_x", drafted_player_name="X")],
            "u2": [],
        },
        given_by_uid={
            "u1": [],
            "u2": [PickAsset(season=2026, round=1, original_owner_user_id="u_a",
                             drafted_player_id="p_x", drafted_player_name="X")],
        },
    )
    ktc = {"p_x": KTCValue(name="X", normalized_name="x", position="WR",
                           superflex_value=9000, one_qb_value=8900)}
    pick_values = {(2026, 1): KTCValue(name="2026 R1", normalized_name="2026 r1",
                                       position="PICK", superflex_value=5000, one_qb_value=4800)}
    swings = grade_snapshot_value(rt, ktc, fmt="superflex", pick_values=pick_values,
                                  ignore_drafted_player=True)
    assert swings["u1"] == pytest.approx(5000)   # pick-table value, not 9000
    assert swings["u2"] == pytest.approx(-5000)


# ---------------------------------------------------------------------------
# Phase-filter tests (Step B)
# ---------------------------------------------------------------------------

def test_phase_filter_playoff_counts_only_playoff_week():
    """phase_filter='playoff' gates on phase_by_lwr; regular-season weeks excluded."""
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_x", "X")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_x", "X")]},
    )
    # Trade week 2; playoff starts week 15; week 3 regular, week 15 is playoff.
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 20.0},
        },
        ("L", 15, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 30.0},
        },
    }
    roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    phase_by_lwr = {("L", 15, 1): "playoff"}
    playoff_week_start_by_league = {"L": 15}

    playoff = grade_hindsight_production(
        rt,
        matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        starters_only=True,
        phase_filter="playoff",
        phase_by_lwr=phase_by_lwr,
        playoff_week_start_by_league=playoff_week_start_by_league,
    )
    # Only week 15 (playoff) counts; week 3 is regular and excluded.
    assert playoff["u1"] == pytest.approx(30.0)


def test_phase_filter_regular_counts_only_pre_playoff_weeks():
    """phase_filter='regular' counts only weeks before playoff_week_start."""
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_x", "X")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_x", "X")]},
    )
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 20.0},
        },
        ("L", 15, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 30.0},
        },
    }
    roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    phase_by_lwr = {("L", 15, 1): "playoff"}
    playoff_week_start_by_league = {"L": 15}

    regular = grade_hindsight_production(
        rt,
        matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        starters_only=True,
        phase_filter="regular",
        phase_by_lwr=phase_by_lwr,
        playoff_week_start_by_league=playoff_week_start_by_league,
    )
    # Only week 3 (regular) counts; week 15 (playoff) excluded.
    assert regular["u1"] == pytest.approx(20.0)


def test_phase_filter_toilet_counts_losers_bracket_weeks():
    """phase_filter='toilet' counts only losers-bracket weeks."""
    rt = _stub_resolved_trade(
        received_by_uid={"u1": [PlayerAsset("p_x", "X")], "u2": []},
        given_by_uid={"u1": [], "u2": [PlayerAsset("p_x", "X")]},
    )
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 20.0},
        },
        ("L", 15, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 30.0},
        },
        ("L", 16, 1): {
            "starters": ["p_x"], "players": ["p_x"],
            "players_points": {"p_x": 10.0},
        },
    }
    roster_to_user_by_league = {"L": {1: "u1", 2: "u2"}}
    # Week 15: playoff winners bracket; week 16: losers bracket (toilet).
    phase_by_lwr = {("L", 15, 1): "playoff", ("L", 16, 1): "toilet"}
    playoff_week_start_by_league = {"L": 15}

    toilet = grade_hindsight_production(
        rt,
        matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        starters_only=True,
        phase_filter="toilet",
        phase_by_lwr=phase_by_lwr,
        playoff_week_start_by_league=playoff_week_start_by_league,
    )
    # Only week 16 (toilet) counts.
    assert toilet["u1"] == pytest.approx(10.0)


def test_grade_trade_produces_three_phase_started_fields():
    """grade_trade returns hindsight_started_{regular,playoff,toilet}_swing and NOT hindsight_started_swing."""
    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_bijan", "Bijan")],
            "u2": [PlayerAsset("p_adams", "Adams")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_adams", "Adams")],
            "u2": [PlayerAsset("p_bijan", "Bijan")],
        },
    )
    ktc = {
        "p_bijan": KTCValue(name="Bijan", normalized_name="b", position="RB",
                            superflex_value=7500, one_qb_value=7400),
        "p_adams": KTCValue(name="Adams", normalized_name="a", position="WR",
                            superflex_value=6050, one_qb_value=6000),
    }
    matchups = {
        ("L", 3, 1): {
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 20.0},
        },
        ("L", 15, 1): {
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 35.0},
        },
        ("L", 3, 2): {
            "starters": ["p_adams"], "players": ["p_adams"],
            "players_points": {"p_adams": 15.0},
        },
    }
    phase_by_lwr = {("L", 15, 1): "playoff"}
    grade = grade_trade(
        rt,
        ktc_values=ktc,
        matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_week_start_by_league={"L": 15},
        phase_by_lwr=phase_by_lwr,
        fmt="superflex",
    )
    assert grade.trade_id == "t1"
    # Three phase fields must exist.
    assert hasattr(grade, "production_regular")
    assert hasattr(grade, "production_playoff")
    assert hasattr(grade, "production_toilet")
    # Old field must NOT exist.
    assert not hasattr(grade, "hindsight_started_swing")
    # u1 regular = received-only week3 bijan (20).
    assert grade.production_regular["u1"] == pytest.approx(20.0)
    # u1 playoff = week15 bijan (35); received-only, no phantom.
    assert grade.production_playoff["u1"] == pytest.approx(35.0)
    # No toilet weeks → 0.
    assert grade.production_toilet.get("u1", 0.0) == pytest.approx(0.0)


def test_direct_breakdown_per_player_and_pick():
    from sleeper_dynasty.engine.trade_grader import build_asset_breakdown

    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_bijan", "Bijan"),
                   PickAsset(season=2027, round=1, original_owner_user_id="u1")],
            "u2": [PlayerAsset("p_adams", "Adams")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_adams", "Adams")],
            "u2": [PlayerAsset("p_bijan", "Bijan"),
                   PickAsset(season=2027, round=1, original_owner_user_id="u1")],
        },
    )
    ktc = {
        "p_bijan": KTCValue(name="Bijan", normalized_name="b", position="RB",
                            superflex_value=7500, one_qb_value=7400),
        "p_adams": KTCValue(name="Adams", normalized_name="a", position="WR",
                            superflex_value=6050, one_qb_value=6000),
    }
    matchups = {
        ("L", 3, 1): {"starters": ["p_bijan"], "players": ["p_bijan"],
                      "players_points": {"p_bijan": 20.0}},
        ("L", 3, 2): {"starters": ["p_adams"], "players": ["p_adams"],
                      "players_points": {"p_adams": 15.0}},
    }
    rows = build_asset_breakdown(
        rt, ktc_values=ktc, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_week_start_by_league={"L": 15}, fmt="superflex",
    )
    u1 = rows["u1"]
    bijan = next(r for r in u1 if r.player_id == "p_bijan")
    assert bijan.kind == "player"
    assert bijan.ktc == 7500.0
    assert bijan.production_total == 20.0
    assert bijan.production_regular == 20.0
    pick = next(r for r in u1 if r.kind == "pick")
    assert pick.production_total == 0.0
    assert "2027" in pick.label

    assert bijan.from_pick is None  # a directly-traded player has no pick origin

    g = grade_trade(rt, ktc_values=ktc, matchups=matchups,
                    roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
                    playoff_week_start_by_league={"L": 15}, fmt="superflex")
    assert g.production_total["u1"] == pytest.approx(sum(r.production_total for r in u1))
    assert g.received_ktc["u1"] == pytest.approx(sum(r.ktc for r in u1))
    assert g.breakdown["u1"] == u1


def test_breakdown_player_via_pick_carries_provenance():
    """A drafted pick resolves to a PlayerAsset(via_pick=...); the breakdown row
    records where it came from so the UI can show 'Player · from 2024 2nd'."""
    from sleeper_dynasty.engine.trade_grader import build_asset_breakdown

    rt = _stub_resolved_trade(
        received_by_uid={
            "u1": [PlayerAsset("p_franklin", "Troy Franklin",
                               via_pick=PickAsset(season=2024, round=2,
                                                  original_owner_user_id="u2"))],
            "u2": [PlayerAsset("p_jacobs", "Josh Jacobs")],
        },
        given_by_uid={
            "u1": [PlayerAsset("p_jacobs", "Josh Jacobs")],
            "u2": [PlayerAsset("p_franklin", "Troy Franklin")],
        },
    )
    ktc = {
        "p_franklin": KTCValue(name="Troy Franklin", normalized_name="tf",
                               position="WR", superflex_value=2000, one_qb_value=2000),
        "p_jacobs": KTCValue(name="Josh Jacobs", normalized_name="jj",
                             position="RB", superflex_value=4000, one_qb_value=4000),
    }
    rows = build_asset_breakdown(
        rt, ktc_values=ktc, matchups={},
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_week_start_by_league={"L": 15}, fmt="superflex",
    )
    franklin = next(r for r in rows["u1"] if r.player_id == "p_franklin")
    assert franklin.kind == "player"
    assert franklin.from_pick == "2024 2nd"
    assert franklin.from_pick_owner_uid == "u2"


def _started_trade():
    # Mike receives p1 (week-1 trade, league L season 2024, roster 1 = Mike).
    player = PlayerAsset(player_id="p1", name="Bijan Robinson")
    pick = PickAsset(season=2025, round=1, original_owner_user_id="u_mike")
    mike = TradeSide("u_mike", received=[player], given=[pick])
    tom = TradeSide("u_tom", received=[pick], given=[player])
    t = Trade("t1", "L", 2024, 1, datetime(2024, 9, 1),
              {"u_mike": mike, "u_tom": tom})
    return ResolvedTrade(trade=t, sides={"u_mike": mike, "u_tom": tom})


def test_production_after_drop_uses_nfl_actuals_window():
    # Mike rosters p1 weeks 5-6, then no longer; p1's NFL actuals after wk6 (the
    # 10-week window 7..16) are summed regardless of any league roster.
    rt = _started_trade()
    matchups = {
        ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 10.0},
                      "team_points": 100.0, "opponent_points": 90.0},
        ("L", 6, 1): {"players": ["p1"], "starters": [],
                      "players_points": {"p1": 4.0},
                      "team_points": 100.0, "opponent_points": 90.0},
    }
    nfl_points = {
        (2024, 7): {"p1": 18.0},
        (2024, 8): {"p1": 22.0},
        (2024, 17): {"p1": 50.0},   # outside the 10-week window (7..16) -> excluded
    }
    grade = grade_trade(
        rt, ktc_values={}, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_week_start_by_league={"L": 15}, phase_by_lwr={},
        league_season_by_id={"L": 2024}, nfl_points=nfl_points,
    )
    line = grade.breakdown["u_mike"][0]
    assert line.production_after_drop == 40.0   # 18 + 22; wk17 excluded
    # no nfl_points -> 0 (CLI/back-compat path)
    g2 = grade_trade(
        rt, ktc_values={}, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_week_start_by_league={"L": 15}, phase_by_lwr={},
        league_season_by_id={"L": 2024},
    )
    assert g2.breakdown["u_mike"][0].production_after_drop == 0.0


def test_production_started_counts_all_started_weeks_incl_placement():
    rt = _started_trade()
    matchups = {
        # regular started: 10
        ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                      "players_points": {"p1": 10.0},
                      "team_points": 100.0, "opponent_points": 90.0},
        # playoff started (winners bracket): 20
        ("L", 15, 1): {"players": ["p1"], "starters": ["p1"],
                       "players_points": {"p1": 20.0},
                       "team_points": 100.0, "opponent_points": 90.0},
        # placement game started (3rd-place; neither winners nor losers bracket): 7
        ("L", 16, 1): {"players": ["p1"], "starters": ["p1"],
                       "players_points": {"p1": 7.0},
                       "team_points": 100.0, "opponent_points": 90.0},
        # benched regular week: 4 (counts toward total, not started)
        ("L", 6, 1): {"players": ["p1"], "starters": [],
                      "players_points": {"p1": 4.0},
                      "team_points": 100.0, "opponent_points": 90.0},
    }
    phase_by_lwr = {("L", 15, 1): "playoff", ("L", 16, 1): "placement"}
    grade = grade_trade(
        rt, ktc_values={}, matchups=matchups,
        roster_to_user_by_league={"L": {1: "u_mike"}},
        playoff_week_start_by_league={"L": 15},
        phase_by_lwr=phase_by_lwr,
        league_season_by_id={"L": 2024},
    )
    started = grade.production_started["u_mike"]
    phases = (grade.production_regular["u_mike"]
              + grade.production_playoff["u_mike"]
              + grade.production_toilet["u_mike"])
    assert started == 37.0            # 10 + 20 + 7 (all started weeks)
    assert phases == 30.0             # 10 + 20 (placement excluded from phases)
    assert started > phases           # the metric is NOT the phase sum
    assert grade.production_total["u_mike"] == 41.0   # +4 benched
    # per-asset line carries it too
    line = grade.breakdown["u_mike"][0]
    assert line.production_started == 37.0
