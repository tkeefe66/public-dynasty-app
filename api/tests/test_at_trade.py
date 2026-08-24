from __future__ import annotations

from datetime import date, datetime, timezone

from app.services.at_trade import compute_at_trade, BACKFILL_CUTOFF
from app.services.ktc_snapshot_store import KtcSnapshotStore
from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.models.trade import (
    PickAsset, PlayerAsset, ResolvedTrade, Trade, TradeSide,
)


def _rt(tx_id, traded_at, received_by_uid, given_by_uid):
    sides = {uid: TradeSide(uid, list(received_by_uid[uid]), list(given_by_uid[uid]))
             for uid in received_by_uid}
    t = Trade(transaction_id=tx_id, league_id="L", season=2026, week=1,
              traded_at=traded_at, sides=sides)
    return ResolvedTrade(trade=t, sides=sides)


def _store_with_today(tmp_path, d):
    store = KtcSnapshotStore(cache_dir=tmp_path)
    store.capture({
        "josh allen": KTCValue(name="Josh Allen", normalized_name="josh allen",
                               position="QB", superflex_value=8000, one_qb_value=7900),
        "2026 early 1st": KTCValue(name="2026 Early 1st", normalized_name="2026 early 1st",
                                   position="PICK", superflex_value=5000, one_qb_value=4800),
    }, d)
    return store


def _players():
    return {"p_allen": {"full_name": "Josh Allen", "position": "QB"}}


def test_backfilled_trade_values_player_and_picks(tmp_path):
    store = _store_with_today(tmp_path, date(2026, 5, 31))
    rt = _rt("tx1", datetime(2026, 5, 3, tzinfo=timezone.utc),
             received_by_uid={"u1": [PlayerAsset("p_allen", "Josh Allen")], "u2": []},
             given_by_uid={"u1": [], "u2": [PlayerAsset("p_allen", "Josh Allen")]})
    out = compute_at_trade([rt], _players(), store)
    g = out["tx1"]
    assert g["at_trade_approx"] is True            # before first capture, post-cutoff
    assert g["at_trade_snapshot_date"] == "2026-05-31"
    assert g["at_trade_value_swing"]["u1"] == 8000.0


def test_pick_valued_as_pick_not_drafted_player(tmp_path):
    store = _store_with_today(tmp_path, date(2026, 5, 31))
    # A pick annotated with a drafted player; at-trade must use the pick table.
    rt = _rt("tx2", datetime(2026, 5, 10, tzinfo=timezone.utc),
             received_by_uid={
                 "u1": [PickAsset(season=2026, round=1, original_owner_user_id="u1",
                                  drafted_player_id="p_allen", drafted_player_name="Josh Allen")],
                 "u2": []},
             given_by_uid={
                 "u1": [],
                 "u2": [PickAsset(season=2026, round=1, original_owner_user_id="u1",
                                  drafted_player_id="p_allen", drafted_player_name="Josh Allen")]})
    out = compute_at_trade([rt], _players(), store)
    assert out["tx2"]["at_trade_value_swing"]["u1"] == 5000.0   # pick table, not 8000


def test_pre_cutoff_trade_is_blank(tmp_path):
    store = _store_with_today(tmp_path, date(2026, 5, 31))
    rt = _rt("tx3", datetime(2026, 3, 1, tzinfo=timezone.utc),
             received_by_uid={"u1": [PlayerAsset("p_allen", "Josh Allen")], "u2": []},
             given_by_uid={"u1": [], "u2": [PlayerAsset("p_allen", "Josh Allen")]})
    out = compute_at_trade([rt], _players(), store)
    assert out["tx3"]["at_trade_value_swing"] is None
    assert out["tx3"]["at_trade_approx"] is False
