from sleeper_dynasty.engine.trade_history import build_drop_index

from tests.helpers import load_fixture


def test_build_drop_index_captures_drop_and_waiver_legs():
    txs = load_fixture("transactions_with_drops.json")
    roster_to_user = {1: "u_alice", 2: "u_bob"}
    idx = build_drop_index(txs, roster_to_user)
    # 1726185600000 ms = 2024-09-13 UTC; 8888 dropped by roster 1 (alice)
    assert idx[("u_alice", "8888")] == "2024-09-13"
    # waiver drop of 9999 by roster 2 (bob)
    assert idx[("u_bob", "9999")] == "2024-09-14"
    # trade drops are NOT in the drop index (trades handled separately)
    assert ("u_bob", "5555") not in idx


def test_build_drop_index_keeps_earliest_date():
    txs = [
        {"type": "drop", "status": "complete", "created": 1726358400000,
         "drops": {"8888": 1}},
        {"type": "drop", "status": "complete", "created": 1726185600000,
         "drops": {"8888": 1}},
    ]
    idx = build_drop_index(txs, {1: "u_alice"})
    assert idx[("u_alice", "8888")] == "2024-09-13"  # earlier of the two
