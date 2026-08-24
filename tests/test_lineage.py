# tests/test_lineage.py
from sleeper_dynasty.models.lineage import LineageNode


def test_node_to_dict_nests_children():
    leaf = LineageNode(label="Bhayshul Tuten", kind="player", flipped_at=None,
                       terminal_state="on_roster", became_player=None, children=[])
    root = LineageNode(label="Saquon Barkley", kind="player", flipped_at="2025-08-29",
                       terminal_state=None, became_player=None, children=[leaf])
    d = root.to_dict()
    assert d["label"] == "Saquon Barkley" and d["flipped_at"] == "2025-08-29"
    assert d["children"][0]["terminal_state"] == "on_roster"


from sleeper_dynasty.engine.lineage import build_trade_lineage, terminal_assets

from tests.helpers import trade_player_asset as _player
from tests.helpers import trade_pick_asset as _pick


def _trade(tx, date, sides):
    return {"trade": {"transaction_id": tx, "traded_at": date}, "sides": sides}


def test_kept_player_terminal_on_roster_vs_dropped():
    # u_a received Jacobs in t1 and never moved him.
    trades = [_trade("t1", "2025-08-20T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [_player("12493", "Josh Jacobs")], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [_player("12493", "Josh Jacobs")]},
    })]
    out = build_trade_lineage(trades, "t1", current_holders={"12493": "u_a"})
    n = out["u_a"][0]
    assert n.label == "Josh Jacobs" and n.flipped_at is None
    assert n.terminal_state == "on_roster" and n.children == []
    # if u_a no longer holds him -> dropped
    out2 = build_trade_lineage(trades, "t1", current_holders={})
    assert out2["u_a"][0].terminal_state == "dropped"


def test_flip_produces_children_package():
    # u_a got Barkley in t1, flipped him in t2 for a 2026 2nd + Calvin Austin.
    barkley = _player("4866", "Saquon Barkley")
    pick = _pick(2026, 2, "u_x", drafted_id="99", drafted_name="Bhayshul Tuten")
    austin = _player("777", "Calvin Austin")
    trades = [
        _trade("t1", "2025-08-20T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [barkley], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [barkley]}}),
        _trade("t2", "2025-08-29T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [pick, austin], "given": [barkley]},
            "u_c": {"user_id": "u_c", "received": [barkley], "given": [pick, austin]}}),
    ]
    out = build_trade_lineage(trades, "t1", current_holders={"99": "u_a", "777": "u_a"})
    root = out["u_a"][0]
    assert root.label == "Saquon Barkley" and root.flipped_at == "2025-08-29"
    kids = {c.label: c for c in root.children}
    assert kids["Calvin Austin"].terminal_state == "on_roster"
    pick_kid = next(c for c in root.children if c.kind == "pick")
    assert pick_kid.became_player == "Bhayshul Tuten" and pick_kid.terminal_state == "on_roster"


def test_undrafted_pick_terminal():
    fut = _pick(2027, 1, "u_z")  # no drafted player
    trades = [_trade("t1", "2025-08-20T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [fut], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [fut]}})]
    out = build_trade_lineage(trades, "t1", current_holders={})
    assert out["u_a"][0].kind == "pick" and out["u_a"][0].terminal_state == "undrafted"


def test_via_pick_player_labels_origin():
    # u_a received a pick that they drafted into Makai Lemon (via_pick player).
    vp = _player("13294", "Makai Lemon", via_pick={"season": 2026, "round": 1, "original_owner_user_id": "u_a"})
    trades = [_trade("t1", "2025-08-20T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [vp], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [vp]}})]
    out = build_trade_lineage(trades, "t1", current_holders={"13294": "u_a"})
    n = out["u_a"][0]
    assert n.kind == "pick" and n.became_player == "Makai Lemon"
    assert "Makai Lemon" in n.label and n.terminal_state == "on_roster"


def test_received_player_one_flip_then_terminal():
    # A received; A -> flip -> B(player) + P1(pick). B is terminal; if B is later
    # flipped, we do NOT follow it.
    A = _player("A", "Player A"); B = _player("B", "Player B")
    P1 = _pick(2026, 1, "u_x", drafted_id="C", drafted_name="Player C")
    later = _player("Z", "Player Z")
    trades = [
        _trade("t1", "2025-01-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [A], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [A]}}),
        _trade("t2", "2025-02-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [B, P1], "given": [A]},
            "u_c": {"user_id": "u_c", "received": [A], "given": [B, P1]}}),
        # u_a later flips B -> Z. Must NOT be followed (B is a derived player).
        _trade("t3", "2025-03-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [later], "given": [B]},
            "u_c": {"user_id": "u_c", "received": [B], "given": [later]}}),
    ]
    out = build_trade_lineage(trades, "t1", current_holders={})
    root = out["u_a"][0]
    assert root.flipped_at == "2025-02-01"
    kids = {c.label: c for c in root.children}
    assert kids["Player B"].children == []          # derived player: terminal, NOT followed
    assert kids["Player B"].flipped_at is None
    # P1 is a pick -> followed -> drafted into Player C (terminal player)
    pick_kid = next(c for c in root.children if c.kind == "pick")
    assert pick_kid.became_player == "Player C"


def test_pick_followed_through_multiple_flips():
    # P1 flipped -> C(player, terminal) + P2(pick) ; P2 flipped -> D(player) + nothing.
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
    out = build_trade_lineage(trades, "t1", current_holders={})
    root = out["u_a"][0]                 # P1
    labels = {c.label for c in root.children}
    assert any("Player C" in l for l in labels)         # C terminal
    p2 = next(c for c in root.children if c.kind == "pick" and c.children)
    assert any(gc.label == "Player D" for gc in p2.children)  # P2 followed -> D terminal


def test_terminal_assets_collects_terminal_players():
    # Same multi-hop pick chain: P1 -> C(player) + P2(pick) ; P2 -> D(player).
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
    terms = terminal_assets(trades, "t1")
    pids = {a["player_id"] for a in terms["u_a"] if a["kind"] == "player"}
    assert pids == {"C", "D"}            # the terminal players for u_a
    assert all(a["kind"] == "player" for a in terms["u_a"])  # no undrafted picks left


def test_root_pick_drafted_player_flip_is_followed():
    # u_a received a pick, drafted Player C from it, then traded C onward.
    # The node must read as a FLIP (like a root received player's one flip),
    # not "dropped" — mirroring realized_received_values, which prices this
    # exact flip at its date.
    P1 = _pick(2024, 1, "u_x", drafted_id="C", drafted_name="Player C")
    D = _player("D", "Player D")
    C = _player("C", "Player C")
    trades = [
        _trade("t1", "2024-01-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [P1], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [P1]}}),
        # u_a flips the drafted player (not the pick) to u_c for Player D.
        _trade("t2", "2024-10-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [D], "given": [C]},
            "u_c": {"user_id": "u_c", "received": [C], "given": [D]}}),
    ]
    out = build_trade_lineage(trades, "t1", current_holders={"D": "u_a"})
    n = out["u_a"][0]
    assert n.flipped_at == "2024-10-01"
    assert n.flip_trade_id == "t2"
    assert n.terminal_state is None          # flipped, not dropped
    assert [c.label for c in n.children] == ["Player D"]
    assert n.children[0].terminal_state == "on_roster"


def test_terminal_assets_follow_drafted_player_flip():
    # Same shape: the became-grade terminal set must be the flip package (D),
    # not the drafted player (C) the owner no longer has.
    P1 = _pick(2024, 1, "u_x", drafted_id="C", drafted_name="Player C")
    D = _player("D", "Player D")
    C = _player("C", "Player C")
    trades = [
        _trade("t1", "2024-01-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [P1], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [P1]}}),
        _trade("t2", "2024-10-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [D], "given": [C]},
            "u_c": {"user_id": "u_c", "received": [C], "given": [D]}}),
    ]
    terms = terminal_assets(trades, "t1")
    assert {a["player_id"] for a in terms["u_a"]} == {"D"}


def test_root_pick_drafted_player_kept_stays_terminal():
    # Drafted player never moved: unchanged behavior (on_roster / dropped).
    P1 = _pick(2024, 1, "u_x", drafted_id="C", drafted_name="Player C")
    trades = [_trade("t1", "2024-01-01T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [P1], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [P1]}})]
    out = build_trade_lineage(trades, "t1", current_holders={"C": "u_a"})
    assert out["u_a"][0].terminal_state == "on_roster"
    out2 = build_trade_lineage(trades, "t1", current_holders={})
    assert out2["u_a"][0].terminal_state == "dropped"


def test_flipped_as_pick_marks_flipped_as_pick_flag():
    # u_a received a pick annotated with the slot's eventual draftee (Makai
    # Lemon), but flipped the PICK to u_c before the draft. u_a never realized
    # Makai Lemon, so the node must be marked flipped_as_pick so the receipt
    # row drops the misleading "(Makai Lemon)" annotation.
    pick = _pick(2026, 1, "u_x", drafted_id="ML", drafted_name="Makai Lemon")
    swap = _pick(2026, 1, "u_y", drafted_id="JP", drafted_name="Jadarian Price")
    trades = [
        _trade("t1", "2025-11-07T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [pick], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [pick]}}),
        _trade("t2", "2026-05-02T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [swap], "given": [pick]},
            "u_c": {"user_id": "u_c", "received": [pick], "given": [swap]}}),
    ]
    out = build_trade_lineage(trades, "t1", current_holders={})
    n = out["u_a"][0]
    assert n.flipped_at == "2026-05-02"
    assert n.flipped_as_pick is True
    assert n.became_player == "Makai Lemon"  # slot draftee still carried, not realized


def test_drafted_player_flip_is_not_flipped_as_pick():
    # u_a drafted Player C from the pick, then flipped the PLAYER. u_a DID
    # realize the draftee, so the annotation stays (flipped_as_pick False).
    P1 = _pick(2024, 1, "u_x", drafted_id="C", drafted_name="Player C")
    D = _player("D", "Player D")
    C = _player("C", "Player C")
    trades = [
        _trade("t1", "2024-01-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [P1], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [P1]}}),
        _trade("t2", "2024-10-01T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [D], "given": [C]},
            "u_c": {"user_id": "u_c", "received": [C], "given": [D]}}),
    ]
    out = build_trade_lineage(trades, "t1", current_holders={"D": "u_a"})
    assert out["u_a"][0].flipped_as_pick is False


def test_pick_flipped_in_its_resolution_trade_is_flipped_as_pick():
    # Real-data shape: when the flip IS the pick's resolution trade (the last
    # trade it was received in), the resolver models the flipped asset as the
    # drafted PLAYER carrying via_pick — NOT as a bare pick. u_a still only
    # flipped the pick rights (never rostered the player), so flipped_as_pick
    # must be True even though the flip matches via the drafted-player id.
    pick = _pick(2024, 1, "u_x", drafted_id="MH", drafted_name="Marvin Harrison")
    mh_via_pick = _player("MH", "Marvin Harrison", via_pick=_pick(2024, 1, "u_x"))
    bijan = _player("BJ", "Bijan Robinson")
    trades = [
        _trade("t1", "2023-08-09T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [pick], "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [pick]}}),
        _trade("t2", "2023-11-18T00:00:00", {
            "u_a": {"user_id": "u_a", "received": [bijan], "given": [mh_via_pick]},
            "u_c": {"user_id": "u_c", "received": [mh_via_pick], "given": [bijan]}}),
    ]
    out = build_trade_lineage(trades, "t1", current_holders={"BJ": "u_a"})
    n = out["u_a"][0]
    assert n.flipped_at == "2023-11-18"
    assert n.flipped_as_pick is True  # never realized Marvin Harrison
    assert [c.label for c in n.children] == ["Bijan Robinson"]


def test_terminal_assets_undrafted_pick():
    fut = _pick(2027, 1, "u_z")          # never drafted -> terminal pick
    trades = [_trade("t1", "2025-08-20T00:00:00", {
        "u_a": {"user_id": "u_a", "received": [fut], "given": []},
        "u_b": {"user_id": "u_b", "received": [], "given": [fut]}})]
    terms = terminal_assets(trades, "t1")
    assert terms["u_a"] == [{"kind": "pick", "season": 2027, "round": 1,
                             "label": "2027 1st pick"}]


def test_terminal_assets_includes_player_name_for_pick_draftee():
    from sleeper_dynasty.engine.lineage import terminal_assets
    dicts = [{
        "trade": {"transaction_id": "t1", "traded_at": "2025-11-07T00:00:00"},
        "sides": {
            "u_a": {"user_id": "u_a", "received": [{
                "season": 2026, "round": 1, "original_owner_user_id": "u_x",
                "drafted_player_id": "ML", "drafted_player_name": "Makai Lemon"}],
                "given": []},
            "u_b": {"user_id": "u_b", "received": [], "given": [{
                "season": 2026, "round": 1, "original_owner_user_id": "u_x",
                "drafted_player_id": "ML", "drafted_player_name": "Makai Lemon"}]},
        },
    }]
    terms = terminal_assets(dicts, "t1")
    player = next(t for t in terms["u_a"] if t["kind"] == "player")
    assert player["player_id"] == "ML"
    assert player["name"] == "Makai Lemon"   # the draftee, not "2026 1st pick"
