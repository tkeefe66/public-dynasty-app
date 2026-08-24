"""Build a 'what this trade became' tree from cached dict-form trades.

Owner-anchored, forward in time: for each asset a side received, follow that
owner's later flips; a moved asset's children are the full package the owner got
back. Pure; operates on the same dicts trade_view reads from the cache.
"""

from __future__ import annotations

from typing import Callable

from sleeper_dynasty.models.lineage import LineageNode

_ORD = {1: "1st", 2: "2nd", 3: "3rd"}


def _ordinal(n: int) -> str:
    return _ORD.get(n, f"{n}th")


def _asset_id(a: dict):
    """Stable identity for matching an asset across trades, or None to skip."""
    if a.get("player_id"):
        return ("player", a["player_id"])
    if a.get("season") is not None and a.get("round") is not None:
        return ("pick", a.get("original_owner_user_id"), a["season"], a["round"])
    return None  # faab / unknown


def _given_index(trades: list[dict]) -> dict[tuple, list[dict]]:
    """(owner, asset_id) -> trades (date-ordered) where that owner GAVE the asset."""
    idx: dict[tuple, list[dict]] = {}
    ordered = sorted(trades, key=lambda r: r["trade"]["traded_at"])
    for r in ordered:
        for uid, side in (r.get("sides") or {}).items():
            for a in side.get("given") or []:
                aid = _asset_id(a)
                if aid:
                    idx.setdefault((uid, aid), []).append(r)
    return idx


def build_trade_lineage(
    resolved_trades: list[dict],
    root_trade_id: str,
    current_holders: dict[str, str],
) -> dict[str, list[LineageNode]]:
    trades = sorted(resolved_trades, key=lambda r: r["trade"]["traded_at"])
    given_index = _given_index(trades)

    def _label_kind_became(asset: dict):
        """(display label, kind, became_player) for an asset."""
        is_player = _asset_id(asset)[0] == "player"
        vp = asset.get("via_pick")
        if is_player and vp:
            return (f'{vp["season"]} {_ordinal(vp["round"])} -> {asset.get("name")}',
                    "pick", asset.get("name"))
        if is_player:
            return (asset.get("name") or asset["player_id"], "player", None)
        return (f'{asset["season"]} {_ordinal(asset["round"])} pick', "pick",
                asset.get("drafted_player_name"))

    def _first_flip(owner: str, aid, since: str) -> dict | None:
        """Earliest flip strictly after acquisition, or None."""
        flips = [r for r in given_index.get((owner, aid), [])
                 if r["trade"]["traded_at"] > since]
        return flips[0] if flips else None

    def _flip_node(asset: dict, owner: str, flip: dict, label, kind, became,
                   *, as_pick: bool = False) -> LineageNode:
        got = flip["sides"][owner].get("received") or []
        children = [walk_derived(c, owner, flip["trade"]["traded_at"])
                    for c in got if _asset_id(c)]
        others = [u for u in (flip.get("sides") or {}) if u != owner]
        return LineageNode(label=label, kind=kind,
                           flipped_at=flip["trade"]["traded_at"][:10],
                           terminal_state=None, became_player=became, children=children,
                           flip_trade_id=flip["trade"].get("transaction_id"),
                           flip_league_id=flip["trade"].get("league_id"),
                           flip_counterparty_uid=(others[0] if others else None),
                           flipped_as_pick=as_pick)

    def _terminal_node(asset: dict, owner: str, label, kind, became) -> LineageNode:
        is_player = _asset_id(asset)[0] == "player"
        held_id = asset["player_id"] if is_player else asset.get("drafted_player_id")
        if held_id:
            state = "on_roster" if current_holders.get(held_id) == owner else "dropped"
            return LineageNode(label, kind, None, state, became, [],
                               terminal_player_id=held_id)
        return LineageNode(label, "pick", None, "undrafted", None, [],
                           terminal_pick=(asset["season"], asset["round"]))

    def walk_pick(asset: dict, owner: str, since: str) -> LineageNode:
        """A pick is always followed through every flip/draft until it
        resolves to players (which are then terminal)."""
        label, kind, became = _label_kind_became(asset)
        flip = _first_flip(owner, _asset_id(asset), since)
        if flip:
            return _flip_node(asset, owner, flip, label, kind, became, as_pick=True)
        # No pick-keyed flip. The pick may still have been flipped *as a pick*
        # in its resolution trade — the resolver models that flipped asset as
        # the drafted PLAYER (carrying via_pick), so it matches by drafted id,
        # not pick id. Follow that flip (mirrors realized_received_values, which
        # prices it at its date). It's a real pick-flip only when the owner gave
        # the asset *as a pick* (via_pick set); if they gave the bare drafted
        # player, they rostered him first, so the draftee annotation stays.
        dpid = asset.get("drafted_player_id")
        if dpid:
            flip = _first_flip(owner, ("player", dpid), since)
            if flip:
                given = (flip.get("sides", {}).get(owner) or {}).get("given") or []
                as_pick = any(
                    g.get("player_id") == dpid and g.get("via_pick")
                    for g in given
                )
                return _flip_node(asset, owner, flip, label, kind, became,
                                  as_pick=as_pick)
        return _terminal_node(asset, owner, label, kind, became)

    def walk_derived(asset: dict, owner: str, since: str) -> LineageNode:
        """A child of a flip: a derived PLAYER is terminal (never followed);
        a derived PICK keeps following."""
        if _asset_id(asset)[0] == "player":
            label, kind, became = _label_kind_became(asset)
            return _terminal_node(asset, owner, label, kind, became)
        return walk_pick(asset, owner, since)

    def walk_root(asset: dict, owner: str, since: str) -> LineageNode:
        """A root received asset: a PLAYER follows exactly one flip (its
        result players are terminal); a PICK follows like any pick."""
        if _asset_id(asset)[0] == "pick":
            return walk_pick(asset, owner, since)
        label, kind, became = _label_kind_became(asset)
        flip = _first_flip(owner, _asset_id(asset), since)
        if flip:
            return _flip_node(asset, owner, flip, label, kind, became)
        return _terminal_node(asset, owner, label, kind, became)

    root = next(r for r in trades if r["trade"]["transaction_id"] == root_trade_id)
    out: dict[str, list[LineageNode]] = {}
    for uid, side in (root.get("sides") or {}).items():
        out[uid] = [walk_root(a, uid, root["trade"]["traded_at"])
                    for a in (side.get("received") or []) if _asset_id(a)]
    return out


def terminal_assets(
    resolved_trades: list[dict],
    root_trade_id: str,
) -> dict[str, list[dict]]:
    """Per side: the terminal players + undrafted picks from the bounded walk.

    Reuses ``build_trade_lineage`` (the one bounded walk) and reads the
    terminal-leaf identities off the tree, so the tree and the became-grade
    tell the same story. ``current_holders`` is irrelevant here (the walk
    bounds terminals, not current holdings), so an empty map is passed.
    """
    tree = build_trade_lineage(resolved_trades, root_trade_id, current_holders={})

    def collect(node: LineageNode, acc: list[dict]) -> None:
        if not node.children:
            if node.terminal_player_id:
                acc.append({"kind": "player", "player_id": node.terminal_player_id,
                            "label": node.label,
                            "name": node.became_player or node.label})
            elif node.terminal_pick:
                acc.append({"kind": "pick", "season": node.terminal_pick[0],
                            "round": node.terminal_pick[1], "label": node.label})
        for c in node.children:
            collect(c, acc)

    out: dict[str, list[dict]] = {}
    for uid, nodes in tree.items():
        acc: list[dict] = []
        for n in nodes:
            collect(n, acc)
        out[uid] = acc
    return out


def realized_received_values(
    resolved_trades: list[dict],
    root_trade_id: str,
    current_holders: dict[str, str],
    price_player: Callable[[str, str | None], float],
    price_pick: Callable[[int, int, str | None], float],
) -> dict[str, list[float]]:
    """Realized value of each side's received haul, frozen at the owner's
    relinquish boundary.

    Per received asset (held → today / flipped → flip date / dropped → 0):
      - ``price_player(player_id, date_iso | None)`` returns the player's KTC at
        the dated snapshot (None = today).
      - ``price_pick(season, round, date_iso | None)`` returns the round-level
        pick value (None = today).

    Returns ``{user_id: [value, ...]}`` index-aligned to that side's ``received``
    assets that carry an ``_asset_id`` (same filter ``build_asset_breakdown``
    uses), so breakdown rows and these values line up by index.
    """
    idx = _given_index(resolved_trades)

    def _first_flip_date(owner: str, aid, since: str) -> str | None:
        flips = [r for r in idx.get((owner, aid), [])
                 if r["trade"]["traded_at"] > since]
        return flips[0]["trade"]["traded_at"][:10] if flips else None

    def _player_value(pid: str, owner: str, since: str) -> float:
        flip_date = _first_flip_date(owner, ("player", pid), since)
        if flip_date is not None:
            return price_player(pid, flip_date)          # flipped → flip-date KTC
        if current_holders.get(pid) == owner:
            return price_player(pid, None)               # held → today
        return 0.0                                       # dropped

    def _asset_value(a: dict, owner: str, since: str) -> float:
        aid = _asset_id(a)
        if aid[0] == "player":
            return _player_value(a["player_id"], owner, since)
        # pick
        flip_date = _first_flip_date(owner, aid, since)
        if flip_date is not None:
            return price_pick(a["season"], a["round"], flip_date)  # flipped as a pick
        dpid = a.get("drafted_player_id")
        if dpid:
            # Drafted player resolves under this owner; reuse the root-trade date
            # as the acquisition floor — any flip of the drafted player is
            # necessarily after it (the player didn't exist before the draft).
            return _player_value(dpid, owner, since)
        return price_pick(a["season"], a["round"], None)  # undrafted future pick, held

    root = next(
        (r for r in resolved_trades
         if r["trade"]["transaction_id"] == root_trade_id),
        None,
    )
    if root is None:
        raise ValueError(f"trade {root_trade_id!r} not found in resolved_trades")
    since = root["trade"]["traded_at"]
    out: dict[str, list[float]] = {}
    for uid, side in (root.get("sides") or {}).items():
        out[uid] = [_asset_value(a, uid, since)
                    for a in (side.get("received") or []) if _asset_id(a)]
    return out


def _player_tenure(pid, owner, since, idx, current_holders, drop_index):
    """Terminal state for a received PLAYER: flipped (first flip after `since`),
    else held (still on roster), else dropped (real date if known, else None)."""
    from sleeper_dynasty.engine.value_series import AssetTenure

    flips = [r for r in idx.get((owner, ("player", pid)), [])
             if r["trade"]["traded_at"] > since]
    if flips:
        return AssetTenure("player", pid, None, None, "flipped",
                           flips[0]["trade"]["traded_at"][:10])
    if current_holders.get(pid) == owner:
        return AssetTenure("player", pid, None, None, "held", None)
    return AssetTenure("player", pid, None, None, "dropped",
                       drop_index.get((owner, pid)))


def side_value_tenures(
    resolved_trades: list[dict],
    root_trade_id: str,
    owner_uid: str,
    *,
    which: str,                 # "received" | "given"
    current_holders: dict[str, str],
    drop_index: dict[tuple[str, str], str],
) -> list:
    """Build the AssetTenure list for one side of one trade.

    ``received`` assets carry their real terminal state (held/flipped/dropped);
    ``given`` assets are the counterfactual — priced as if the owner had kept
    them, so every one is ``held``. Picks resolve to their drafted player when
    known (mirrors ``realized_received_values``); a flipped-as-a-pick stays a
    pick locked at the flip date.
    """
    from sleeper_dynasty.engine.value_series import AssetTenure

    idx = _given_index(resolved_trades)
    root = next(
        (r for r in resolved_trades
         if r["trade"]["transaction_id"] == root_trade_id),
        None,
    )
    if root is None:
        raise ValueError(f"trade {root_trade_id!r} not found in resolved_trades")
    since = root["trade"]["traded_at"]
    side = (root.get("sides") or {}).get(owner_uid) or {}

    out = []
    for a in (side.get(which) or []):
        aid = _asset_id(a)
        if aid is None:
            continue  # faab / unknown
        if which == "given":
            # Counterfactual: price as if held. Resolve a drafted pick to its player.
            if aid[0] == "player":
                out.append(AssetTenure("player", a["player_id"], None, None, "held", None))
            elif a.get("drafted_player_id"):
                out.append(AssetTenure("player", a["drafted_player_id"], None, None, "held", None))
            else:
                out.append(AssetTenure("pick", None, a["season"], a["round"], "held", None))
            continue
        # received side
        if aid[0] == "player":
            out.append(_player_tenure(a["player_id"], owner_uid, since, idx,
                                      current_holders, drop_index))
            continue
        # pick: flipped as a pick first, else resolve to drafted player, else held pick
        flips = [r for r in idx.get((owner_uid, aid), [])
                 if r["trade"]["traded_at"] > since]
        if flips:
            out.append(AssetTenure("pick", None, a["season"], a["round"], "flipped",
                                   flips[0]["trade"]["traded_at"][:10]))
        elif a.get("drafted_player_id"):
            out.append(_player_tenure(a["drafted_player_id"], owner_uid, since, idx,
                                      current_holders, drop_index))
        else:
            out.append(AssetTenure("pick", None, a["season"], a["round"], "held", None))
    return out
