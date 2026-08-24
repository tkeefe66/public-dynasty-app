from __future__ import annotations

from app.services.aggregations import _latest_trades
from tests.helpers import minimal_chain_cache_entry


def _entry(grade: dict | None) -> object:
    """A two-side trade between Alice and Bob, with `grade` as its grade blob."""
    return minimal_chain_cache_entry(
        owners={
            "u_alice": {"owner_name": "Alice"},
            "u_bob": {"owner_name": "Bob"},
        },
        grades={"tx1": {"trade_id": "tx1", **grade}} if grade is not None else {},
    )


def _trade(sides: dict | None = None) -> dict:
    return {
        "trade": {
            "transaction_id": "tx1", "league_id": "L", "season": 2026,
            "week": 2, "traded_at": "2025-08-29T00:00:00+00:00", "sides": {},
        },
        "sides": sides if sides is not None else {
            "u_alice": {"user_id": "u_alice", "received": [{"name": "Barkley", "player_id": "p1"}], "given": []},
            "u_bob": {"user_id": "u_bob", "received": [{"name": "Montgomery", "player_id": "p2"}], "given": []},
        },
    }


def test_winners_agree_when_one_side_leads_both_lenses():
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
        "production_total": {"u_alice": 179.8, "u_bob": 58.3},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.value_winner is not None and t.value_winner.owner_name == "Alice"
    assert t.production_winner is not None and t.production_winner.owner_name == "Alice"
    # Ordered by the VALUE winner, so the left number is always the same person.
    assert t.production_split == (179.8, 58.3)


def test_winners_can_disagree_and_the_split_still_leads_with_the_value_winner():
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
        "production_total": {"u_alice": 58.3, "u_bob": 179.8},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.value_winner.owner_name == "Alice"
    assert t.production_winner.owner_name == "Bob"
    assert t.production_split == (58.3, 179.8)


def test_three_way_trade_has_winners_but_no_split():
    sides = {
        f"u_{n}": {"user_id": f"u_{n}", "received": [], "given": []}
        for n in ("alice", "bob", "carol")
    }
    entry = minimal_chain_cache_entry(
        owners={f"u_{n}": {"owner_name": n.title()} for n in ("alice", "bob", "carol")},
        grades={"tx1": {
            "trade_id": "tx1",
            "snapshot_value_swing": {"u_alice": 900.0, "u_bob": -400.0, "u_carol": -500.0},
            "production_total": {"u_alice": 10.0, "u_bob": 20.0, "u_carol": 5.0},
        }},
    )
    (t,) = _latest_trades(entry, [_trade(sides)])
    assert t.value_winner.owner_name == "Alice"
    assert t.production_winner.owner_name == "Bob"
    assert t.production_split is None


def test_missing_grade_blob_leaves_every_new_field_none():
    (t,) = _latest_trades(_entry(None), [_trade()])
    assert t.value_winner is None
    assert t.production_winner is None
    assert t.production_split is None


def test_existing_swing_fields_are_unchanged():
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
        "production_total": {"u_alice": 179.8, "u_bob": 58.3},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.swing_ktc == 1450.0
    assert t.swing_prod == 179.8 - 58.3


def test_exactly_one_graded_side_leaves_all_three_fields_none():
    # A partial/corrupted grade blob with a single graded uid has no opponent
    # to have "won" against — every derived field must stay None.
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 1450.0},
        "production_total": {"u_alice": 179.8},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.value_winner is None
    assert t.production_winner is None
    assert t.production_split is None


def test_nobody_scored_yet_has_no_production_winner_but_still_splits():
    # The common offseason / pre-week-1 case: both sides at 0.0. `max` would
    # hand the win to whichever uid the dict happened to list first, and the
    # lead would claim a field winner three lines above a POINTS cell reading
    # "—". A winner requires a strict lead.
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
        "production_total": {"u_alice": 0.0, "u_bob": 0.0},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.value_winner.owner_name == "Alice"
    assert t.production_winner is None
    # The split is a factual pair of totals — it survives the tie, and the
    # frontend renders a 0-0 pair as unscored.
    assert t.production_split == (0.0, 0.0)


def test_equal_nonzero_production_totals_have_no_winner():
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
        "production_total": {"u_alice": 88.5, "u_bob": 88.5},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.production_winner is None
    assert t.production_split == (88.5, 88.5)


def test_a_wash_on_the_value_swing_has_no_value_winner():
    # A zero-sum swing where both sides land on the same number is a wash, not
    # a win — symmetrical with the production rule.
    entry = _entry({
        "snapshot_value_swing": {"u_alice": 0.0, "u_bob": 0.0},
        "production_total": {"u_alice": 179.8, "u_bob": 58.3},
    })
    (t,) = _latest_trades(entry, [_trade()])
    assert t.value_winner is None
    assert t.production_winner.owner_name == "Alice"
    # Ordering falls back to the argmax, so the split is still emitted.
    assert t.production_split is not None
    assert sorted(t.production_split) == [58.3, 179.8]


def test_a_tie_for_second_still_leaves_the_strict_leader_the_winner():
    # Three sides, two tied behind a clear leader: the leader still won.
    sides = {
        f"u_{n}": {"user_id": f"u_{n}", "received": [], "given": []}
        for n in ("alice", "bob", "carol")
    }
    entry = minimal_chain_cache_entry(
        owners={f"u_{n}": {"owner_name": n.title()} for n in ("alice", "bob", "carol")},
        grades={"tx1": {
            "trade_id": "tx1",
            "snapshot_value_swing": {"u_alice": 900.0, "u_bob": -450.0, "u_carol": -450.0},
            "production_total": {"u_alice": 40.0, "u_bob": 20.0, "u_carol": 20.0},
        }},
    )
    (t,) = _latest_trades(entry, [_trade(sides)])
    assert t.value_winner.owner_name == "Alice"
    assert t.production_winner.owner_name == "Alice"


def test_value_and_production_dicts_disagree_on_which_uids_are_present():
    # snapshot_value_swing and production_total are normally keyed off the
    # same graded sides, but if they ever disagree, the value winner (u_alice)
    # isn't even present in production_total — production_winner and
    # production_split must fall back sanely rather than crash.
    entry = minimal_chain_cache_entry(
        owners={
            "u_alice": {"owner_name": "Alice"},
            "u_bob": {"owner_name": "Bob"},
            "u_carol": {"owner_name": "Carol"},
        },
        grades={"tx1": {
            "trade_id": "tx1",
            "snapshot_value_swing": {"u_alice": 1450.0, "u_bob": -1450.0},
            "production_total": {"u_bob": 100.0, "u_carol": 50.0},
        }},
    )
    (t,) = _latest_trades(entry, [_trade()])
    assert t.value_winner.owner_name == "Alice"
    assert t.production_winner.owner_name == "Bob"
    assert t.production_split is None
