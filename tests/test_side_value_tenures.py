from sleeper_dynasty.engine.lineage import side_value_tenures

# Minimal resolved-trade dicts. Shape mirrors _to_dict(ResolvedTrade): each item
# has "trade" (with transaction_id, traded_at) and "sides" {uid: {received, given}}.
ROOT = {
    "trade": {"transaction_id": "t1", "traded_at": "2026-06-01T00:00:00+00:00"},
    "sides": {
        "alice": {
            "received": [{"player_id": "p_kept", "name": "Kept"},
                         {"player_id": "p_flip", "name": "Flip"},
                         {"player_id": "p_drop", "name": "Drop"}],
            "given": [{"player_id": "p_gave", "name": "Gave"}],
        },
        "bob": {"received": [{"player_id": "p_gave", "name": "Gave"}],
                "given": [{"player_id": "p_kept", "name": "Kept"},
                          {"player_id": "p_flip", "name": "Flip"},
                          {"player_id": "p_drop", "name": "Drop"}]},
    },
}
# Alice later flips p_flip to bob on 2026-06-10.
FLIP = {
    "trade": {"transaction_id": "t2", "traded_at": "2026-06-10T00:00:00+00:00"},
    "sides": {
        "bob": {"received": [{"player_id": "p_flip", "name": "Flip"}], "given": []},
        "alice": {"received": [], "given": [{"player_id": "p_flip", "name": "Flip"}]},
    },
}
TRADES = [ROOT, FLIP]


def test_received_tenures_classify_held_flipped_dropped():
    current_holders = {"p_kept": "alice"}  # only p_kept still on alice's roster
    drop_index = {("alice", "p_drop"): "2026-06-08"}
    tens = side_value_tenures(
        TRADES, "t1", "alice", which="received",
        current_holders=current_holders, drop_index=drop_index,
    )
    by_pid = {t.player_id: t for t in tens}
    assert by_pid["p_kept"].terminal == "held"
    assert by_pid["p_kept"].terminal_date is None
    assert by_pid["p_flip"].terminal == "flipped"
    assert by_pid["p_flip"].terminal_date == "2026-06-10"
    assert by_pid["p_drop"].terminal == "dropped"
    assert by_pid["p_drop"].terminal_date == "2026-06-08"


def test_given_tenures_are_all_held_counterfactual():
    tens = side_value_tenures(
        TRADES, "t1", "alice", which="given",
        current_holders={}, drop_index={},
    )
    assert len(tens) == 1
    assert tens[0].player_id == "p_gave"
    assert tens[0].terminal == "held"
    assert tens[0].terminal_date is None


def test_dropped_player_without_drop_record_still_terminal_zero():
    # p_drop not held, not flipped, and no drop record -> dropped with None date
    tens = side_value_tenures(
        TRADES, "t1", "alice", which="received",
        current_holders={"p_kept": "alice", "p_flip": "alice"}, drop_index={},
    )
    by_pid = {t.player_id: t for t in tens}
    assert by_pid["p_drop"].terminal == "dropped"
    assert by_pid["p_drop"].terminal_date is None
