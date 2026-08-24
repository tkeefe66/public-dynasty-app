"""Tests for roster_asof: reconstructing an owner's roster as of a date."""

from __future__ import annotations

from datetime import datetime, timezone

from sleeper_dynasty.engine.roster_asof import roster_asof


def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def test_applies_adds_and_drops_in_timestamp_order():
    """p1 is added at t=100 and later dropped at t=200 -- applied in timestamp
    order it ends up gone. The two transactions are handed to roster_asof in
    the *opposite* of timestamp order, so this only passes if the function
    sorts by timestamp rather than trusting input order (applying input
    order would process the drop first as a no-op, then the add, leaving p1
    on the roster)."""
    seed = {"u1": {"p9"}}
    txs = [
        {"status_updated": 200, "adds": None, "drops": {"p1": 1}},
        {"status_updated": 100, "adds": {"p1": 1}, "drops": None},
    ]
    out = roster_asof(seed, txs, {1: "u1"}, as_of=_dt(300))
    assert out["u1"] == {"p9"}


def test_shuffled_input_order_matches_sorted_order():
    """The property the module promises: feeding transactions in any input
    order yields the same result as feeding them already sorted by
    timestamp. Includes an add/drop conflict (p1) and a later flip (p2
    added then dropped in favor of p3) so a broken sort would actually
    change the outcome."""
    seed = {"u1": {"p9"}}
    sorted_txs = [
        {"status_updated": 100, "adds": {"p1": 1}, "drops": None},
        {"status_updated": 150, "adds": {"p2": 1}, "drops": None},
        {"status_updated": 200, "adds": None, "drops": {"p1": 1}},
        {"status_updated": 250, "adds": {"p3": 1}, "drops": {"p2": 1}},
    ]
    shuffled_txs = [sorted_txs[2], sorted_txs[0], sorted_txs[3], sorted_txs[1]]

    expected = roster_asof(seed, sorted_txs, {1: "u1"}, as_of=_dt(300))
    actual = roster_asof(seed, shuffled_txs, {1: "u1"}, as_of=_dt(300))
    assert actual == expected == {"u1": {"p9", "p3"}}


def test_ignores_transactions_after_the_cutoff():
    seed = {"u1": {"p1"}}
    txs = [{"status_updated": 500, "adds": {"p2": 1}, "drops": None}]
    assert roster_asof(seed, txs, {1: "u1"}, as_of=_dt(300))["u1"] == {"p1"}


def test_a_transaction_with_no_timestamp_is_skipped_not_guessed():
    # Measured: 0 of 528 real transactions lack one. Defensive invariant only —
    # do NOT build a skip counter for the UI, it would always render 0.
    seed = {"u1": {"p1"}}
    txs = [{"adds": {"p2": 1}, "drops": None}]
    assert roster_asof(seed, txs, {1: "u1"}, as_of=_dt(300))["u1"] == {"p1"}


def test_is_owner_keyed_not_roster_id_keyed():
    """Roster ids are not stable across a league chain."""
    seed = {"u1": {"p1"}}
    txs = [{"status_updated": 100, "adds": {"p2": 7}, "drops": None}]
    out = roster_asof(seed, txs, {7: "u1"}, as_of=_dt(300))
    assert out["u1"] == {"p1", "p2"}


def test_does_not_mutate_the_seed():
    seed = {"u1": {"p1"}}
    roster_asof(seed, [{"status_updated": 100, "adds": {"p2": 1}, "drops": None}],
                {1: "u1"}, as_of=_dt(300))
    assert seed == {"u1": {"p1"}}


def test_a_transaction_exactly_AT_the_cutoff_is_included():
    """The boundary, which `test_ignores_transactions_after_the_cutoff` does not
    reach: it only proves ts > as_of is excluded, so mutating the guard from
    `>` to `>=` passes that test and the whole suite.

    A draft is stamped at an instant and moves settle on the same instant, so
    off-by-one here silently drops the last transaction before every draft —
    the reconstruction stays plausible and is wrong.
    """
    seed = {"u1": {"p1"}}
    txs = [{"status_updated": 300, "adds": {"p2": 1}, "drops": None}]
    assert roster_asof(seed, txs, {1: "u1"}, as_of=_dt(300))["u1"] == {"p1", "p2"}
