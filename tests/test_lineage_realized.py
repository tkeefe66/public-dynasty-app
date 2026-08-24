from sleeper_dynasty.engine.lineage import realized_received_values

from tests.helpers import trade_pick_asset as _pick


def _trade(tx, when, sides):
    return {"trade": {"transaction_id": tx, "traded_at": when,
                      "league_id": "L", "season": 2026, "week": 1},
            "sides": sides}


def _player(pid, name):
    return {"player_id": pid, "name": name}


# Price providers: today = lookup in TODAY; dated = lookup in DATED[date].
TODAY = {"B": 5000.0, "C": 4800.0, "X": 1500.0}
DATED = {"2027-09-01": {"C": 6000.0, "B": 5000.0}}


def price_player(pid, d_iso):
    table = TODAY if d_iso is None else DATED.get(d_iso[:10], TODAY)
    return float(table.get(pid, 0.0))


def price_pick(season, rnd, d_iso):
    return 0.0  # picks priced separately in dedicated tests below


def test_held_player_valued_at_today():
    # A receives C and still holds it -> today's KTC.
    trades = [_trade("t1", "2026-01-01T00:00:00", {
        "A": {"received": [_player("C", "C")], "given": [_player("B", "B")]},
        "D": {"received": [_player("B", "B")], "given": [_player("C", "C")]},
    })]
    out = realized_received_values(trades, "t1", {"C": "A", "B": "D"},
                                   price_player, price_pick)
    assert out["A"] == [4800.0]   # C today
    assert out["D"] == [5000.0]   # B today


def test_flipped_player_valued_at_flip_date():
    # A receives C, then flips C away on 2027-09-01 -> C's KTC at flip date (6000).
    trades = [
        _trade("t1", "2026-01-01T00:00:00", {
            "A": {"received": [_player("C", "C")], "given": [_player("B", "B")]},
            "D": {"received": [_player("B", "B")], "given": [_player("C", "C")]},
        }),
        _trade("t2", "2027-09-01T00:00:00", {
            "A": {"received": [_player("Z", "Z")], "given": [_player("C", "C")]},
            "E": {"received": [_player("C", "C")], "given": [_player("Z", "Z")]},
        }),
    ]
    out = realized_received_values(trades, "t1", {"C": "E", "B": "D"},
                                   price_player, price_pick)
    assert out["A"] == [6000.0]   # C frozen at flip date, NOT today's 4800


def test_dropped_player_is_zero():
    # A receives C, never flips it, not on current roster -> dropped -> 0.
    trades = [_trade("t1", "2026-01-01T00:00:00", {
        "A": {"received": [_player("C", "C")], "given": [_player("B", "B")]},
        "D": {"received": [_player("B", "B")], "given": [_player("C", "C")]},
    })]
    out = realized_received_values(trades, "t1", {"B": "D"},  # C absent from holders
                                   price_player, price_pick)
    assert out["A"] == [0.0]


def test_two_received_assets_preserve_order():
    # A receives [C (held), B (flipped 2027-09-01)]; the returned list must be
    # [C_today (4800), B_flipdate (DATED 2027-09-01 = 5000)] in received order.
    trades = [
        _trade("t1", "2026-01-01T00:00:00", {
            "A": {"received": [_player("C", "C"), _player("B", "B")],
                  "given": [_player("X", "X")]},
            "D": {"received": [_player("X", "X")],
                  "given": [_player("C", "C"), _player("B", "B")]},
        }),
        _trade("t2", "2027-09-01T00:00:00", {
            "A": {"received": [_player("Y", "Y")], "given": [_player("B", "B")]},
            "E": {"received": [_player("B", "B")], "given": [_player("Y", "Y")]},
        }),
    ]
    # C held by A (today 4800); B flipped on 2027-09-01 (DATED price 5000).
    out = realized_received_values(trades, "t1", {"C": "A"},
                                   price_player, price_pick)
    assert out["A"] == [4800.0, 5000.0]


PICK_TODAY = {(2027, 1): 900.0}
PICK_DATED = {"2028-09-01": {(2027, 1): 700.0}}


def _pp_today(pid, d_iso):
    return float(TODAY.get(pid, 0.0))


def _pp_pick(season, rnd, d_iso):
    table = PICK_TODAY if d_iso is None else PICK_DATED.get(d_iso[:10], PICK_TODAY)
    return float(table.get((season, rnd), 0.0))


def test_pick_flipped_before_draft_uses_flip_date_pick_value():
    trades = [
        _trade("t1", "2026-01-01T00:00:00", {
            "A": {"received": [_pick(2027, 1, "A")], "given": [_player("B", "B")]},
            "D": {"received": [_player("B", "B")], "given": [_pick(2027, 1, "A")]},
        }),
        _trade("t2", "2028-09-01T00:00:00", {
            "A": {"received": [_player("Z", "Z")], "given": [_pick(2027, 1, "A")]},
            "E": {"received": [_pick(2027, 1, "A")], "given": [_player("Z", "Z")]},
        }),
    ]
    out = realized_received_values(trades, "t1", {}, _pp_today, _pp_pick)
    assert out["A"] == [700.0]   # pick frozen at flip date


def test_pick_drafted_and_held_uses_drafted_player_today():
    # Pick received, drafted to player C, still held -> today's C.
    trades = [_trade("t1", "2026-01-01T00:00:00", {
        "A": {"received": [_pick(2027, 1, "A", drafted_id="C", drafted_name="C")],
              "given": [_player("B", "B")]},
        "D": {"received": [_player("B", "B")],
              "given": [_pick(2027, 1, "A", drafted_id="C", drafted_name="C")]},
    })]
    out = realized_received_values(trades, "t1", {"C": "A"}, _pp_today, _pp_pick)
    assert out["A"] == [4800.0]   # today's C, not the pick table


def test_pick_drafted_then_player_flipped_uses_flip_date():
    # Pick received in t1, drafted to player C, then C flipped away on 2027-09-01
    # -> realized at C's flip-date price (6000), not today's 4800 and not the pick table.
    trades = [
        _trade("t1", "2026-01-01T00:00:00", {
            "A": {"received": [_pick(2027, 1, "A", drafted_id="C", drafted_name="C")],
                  "given": [_player("B", "B")]},
            "D": {"received": [_player("B", "B")],
                  "given": [_pick(2027, 1, "A", drafted_id="C", drafted_name="C")]},
        }),
        _trade("t2", "2027-09-01T00:00:00", {
            "A": {"received": [_player("Z", "Z")], "given": [_player("C", "C")]},
            "E": {"received": [_player("C", "C")], "given": [_player("Z", "Z")]},
        }),
    ]
    # price_player must see flip-date prices: use the module-level `price_player`
    # (TODAY/DATED), and `_pp_pick` for picks.
    out = realized_received_values(trades, "t1", {"C": "E"}, price_player, _pp_pick)
    assert out["A"] == [6000.0]
