from datetime import datetime, timezone

import pytest

from sleeper_dynasty.models.trade import (
    FaabAsset,
    OwnerTradeRecord,
    PickAsset,
    PlayerAsset,
    ResolvedTrade,
    Trade,
    TradeGrade,
    TradeSide,
)


def test_player_asset_holds_id_and_name():
    a = PlayerAsset(player_id="123", name="Bijan Robinson")
    assert a.player_id == "123"
    assert a.name == "Bijan Robinson"


def test_pick_asset_carries_season_round_and_original_owner():
    p = PickAsset(season=2025, round=1, original_owner_user_id="u1")
    assert p.season == 2025
    assert p.round == 1
    assert p.original_owner_user_id == "u1"


def test_faab_asset_holds_amount():
    f = FaabAsset(amount=25)
    assert f.amount == 25


def test_trade_side_holds_received_and_given_lists():
    side = TradeSide(
        user_id="u1",
        received=[PlayerAsset("123", "A")],
        given=[PlayerAsset("456", "B")],
    )
    assert side.user_id == "u1"
    assert len(side.received) == 1
    assert len(side.given) == 1


def test_trade_holds_sides_and_metadata():
    when = datetime(2024, 9, 12, tzinfo=timezone.utc)
    trade = Trade(
        transaction_id="tx_001",
        league_id="league_2024",
        season=2024,
        week=2,
        traded_at=when,
        sides={
            "u1": TradeSide("u1", [PlayerAsset("123", "A")], [PlayerAsset("456", "B")]),
            "u2": TradeSide("u2", [PlayerAsset("456", "B")], [PlayerAsset("123", "A")]),
        },
    )
    assert trade.transaction_id == "tx_001"
    assert trade.season == 2024
    assert set(trade.sides.keys()) == {"u1", "u2"}


def test_resolved_trade_wraps_a_trade_with_resolved_sides():
    base = Trade(
        transaction_id="tx_002",
        league_id="league_2024",
        season=2024,
        week=2,
        traded_at=datetime(2024, 9, 12, tzinfo=timezone.utc),
        sides={},
    )
    resolved = ResolvedTrade(trade=base, sides={})
    assert resolved.trade.transaction_id == "tx_002"


def test_trade_grade_holds_all_views_per_side():
    g = TradeGrade(
        trade_id="tx_001",
        snapshot_value_swing={"u1": 1450.0, "u2": -1450.0},
        production_total={"u1": 387.4, "u2": -387.4},
        production_regular={"u1": 300.0, "u2": -300.0},
        production_playoff={"u1": 95.0, "u2": -95.0},
        production_toilet={"u1": 10.0, "u2": -10.0},
    )
    assert g.snapshot_value_swing["u1"] == 1450.0
    assert g.production_regular["u1"] == 300.0
    assert g.production_playoff["u1"] == 95.0
    assert g.production_toilet["u1"] == 10.0


def test_owner_trade_record_defaults_to_zero():
    r = OwnerTradeRecord(user_id="u1", display_name="Tom")
    assert r.trades == 0
    assert r.net_ktc == 0.0
    assert r.production_total == 0.0
    assert r.production_regular == 0.0
    assert r.production_playoff == 0.0
    assert r.production_toilet == 0.0
    assert r.best_trade_id is None
    assert r.worst_trade_id is None


def test_player_asset_via_pick_defaults_to_none():
    a = PlayerAsset(player_id="x", name="X")
    assert a.via_pick is None


def test_player_asset_can_carry_via_pick():
    pick = PickAsset(season=2024, round=1, original_owner_user_id="u_orig")
    a = PlayerAsset(player_id="x", name="X", via_pick=pick)
    assert a.via_pick is pick
    assert a.via_pick.season == 2024


def test_pick_asset_carries_optional_drafted_player():
    from sleeper_dynasty.models.trade import PickAsset

    # Defaults: a bare pick knows nothing about a drafted player.
    bare = PickAsset(season=2025, round=1, original_owner_user_id="u_alice")
    assert bare.drafted_player_id is None
    assert bare.drafted_player_name is None

    # Annotated: a non-resolution pick records what it became, for valuation.
    annotated = PickAsset(
        season=2024,
        round=1,
        original_owner_user_id="u_alice",
        drafted_player_id="p_jayden",
        drafted_player_name="Jayden Daniels",
    )
    assert annotated.drafted_player_id == "p_jayden"
    assert annotated.drafted_player_name == "Jayden Daniels"
