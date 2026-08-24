"""Trade-history engine.

Fetches and normalizes trades across the full dynasty league chain, then
resolves traded picks into the players actually drafted with them.

The public entry points are:
  - normalize_trade(raw_tx, roster_to_user, league_id, season) -> Trade
  - build_trade_history(client, current_league_id, cache) -> list[Trade]
  - resolve_assets(trades, drafts_by_season, draft_picks_by_draft_id,
                   user_to_slot_by_season, player_names,
                   resolution_by_identity) -> list[ResolvedTrade]

Stable owner identity: every roster_id reference in a raw Sleeper trade
transaction is mapped to its Sleeper user_id at the time of the trade,
using that league-season's roster table. Owners who left the league are
graded under an "Owner #<roster_id>" fallback string.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sleeper_dynasty.models.trade import (
    FaabAsset,
    PickAsset,
    PlayerAsset,
    ResolvedTrade,
    Trade,
    TradeSide,
)

log = logging.getLogger(__name__)

# Transaction IDs that must NEVER surface in the report. Hardcoded
# because these are known-junk Sleeper records (e.g., canceled trades
# the API still returns).
BLACKLISTED_TRANSACTION_IDS = frozenset({
    "1094079897179373568",
    "1031422536271220736",
})


def _identity_for(
    roster_id: int, roster_to_user: dict[int, str]
) -> str:
    """Return stable identity for a roster_id; fall back to a placeholder."""
    if roster_id in roster_to_user:
        return roster_to_user[roster_id]
    log.warning(
        "No user mapping for roster_id=%d; using fallback identity",
        roster_id,
    )
    return f"Owner #{roster_id}"


def compute_pick_resolution_map(
    trades: list[Trade],
) -> dict[tuple[str, int, int], str]:
    """Map each pick identity to the transaction_id of its resolution trade.

    A pick's identity is ``(original_owner_user_id, season, round)``. The
    resolution trade is the chronologically last trade in which that pick was
    *received* — i.e., the one that delivered it to whoever ultimately held it
    (and therefore drafted with it). Ties on ``traded_at`` break by
    transaction_id for determinism.
    """
    # identity -> (sort_key, transaction_id) of the current best (latest) candidate.
    best: dict[tuple[str, int, int], tuple[tuple[datetime, str], str]] = {}
    for trade in trades:
        for side in trade.sides.values():
            for asset in side.received:
                if not isinstance(asset, PickAsset):
                    continue
                identity = (
                    asset.original_owner_user_id, asset.season, asset.round,
                )
                sort_key = (trade.traded_at, trade.transaction_id)
                current = best.get(identity)
                if current is None or sort_key > current[0]:
                    best[identity] = (sort_key, trade.transaction_id)
    return {identity: tx_id for identity, (_k, tx_id) in best.items()}


def normalize_trade(
    raw_tx: dict,
    roster_to_user: dict[int, str],
    league_id: str,
    season: int,
) -> Trade:
    """Convert a raw Sleeper trade transaction into a Trade model.

    ``roster_to_user`` is THIS league-season's roster_id → user_id mapping
    (from ``SleeperClient.get_rosters`` + ``get_users``). Used to attach
    stable owner identity to every asset in the trade.
    """
    # Build a per-identity TradeSide skeleton.
    sides: dict[str, TradeSide] = {}
    for rid in raw_tx.get("roster_ids", []):
        ident = _identity_for(rid, roster_to_user)
        sides.setdefault(ident, TradeSide(user_id=ident, received=[], given=[]))

    # Player adds/drops.
    for player_id, dest_roster_id in (raw_tx.get("adds") or {}).items():
        ident = _identity_for(dest_roster_id, roster_to_user)
        sides.setdefault(ident, TradeSide(user_id=ident, received=[], given=[]))
        sides[ident].received.append(PlayerAsset(player_id=player_id, name=""))
    for player_id, src_roster_id in (raw_tx.get("drops") or {}).items():
        ident = _identity_for(src_roster_id, roster_to_user)
        sides.setdefault(ident, TradeSide(user_id=ident, received=[], given=[]))
        sides[ident].given.append(PlayerAsset(player_id=player_id, name=""))

    # Draft picks. A pick is GIVEN by previous_owner_id (prior holder before
    # this tx) and RECEIVED by owner_id (new owner after this tx). roster_id
    # is the ORIGINAL drafting team (whose end-of-season standings set the
    # pick slot) — used as metadata, NOT as a side participant.
    for pick in raw_tx.get("draft_picks") or []:
        prior_rid = pick["previous_owner_id"]   # prior holder — the giver
        new_rid = pick["owner_id"]               # new owner — the receiver
        original_rid = pick["roster_id"]         # original drafter — metadata only
        giver = _identity_for(prior_rid, roster_to_user)
        receiver = _identity_for(new_rid, roster_to_user)
        original_owner_user_id = _identity_for(original_rid, roster_to_user)
        sides.setdefault(giver, TradeSide(user_id=giver, received=[], given=[]))
        sides.setdefault(receiver, TradeSide(user_id=receiver, received=[], given=[]))
        asset = PickAsset(
            season=int(pick["season"]),
            round=int(pick["round"]),
            original_owner_user_id=original_owner_user_id,
        )
        sides[giver].given.append(asset)
        sides[receiver].received.append(asset)

    # FAAB transfers.
    for fb in raw_tx.get("waiver_budget") or []:
        sender = _identity_for(fb["sender"], roster_to_user)
        receiver = _identity_for(fb["receiver"], roster_to_user)
        sides.setdefault(sender, TradeSide(user_id=sender, received=[], given=[]))
        sides.setdefault(receiver, TradeSide(user_id=receiver, received=[], given=[]))
        amount = int(fb["amount"])
        sides[sender].given.append(FaabAsset(amount=amount))
        sides[receiver].received.append(FaabAsset(amount=amount))

    return Trade(
        transaction_id=str(raw_tx["transaction_id"]),
        league_id=league_id,
        season=season,
        week=int(raw_tx.get("leg", 0)),
        traded_at=datetime.fromtimestamp(
            int(raw_tx["created"]) / 1000.0, tz=timezone.utc
        ),
        sides=sides,
    )


_DROP_TX_TYPES = ("drop", "waiver", "free_agent")


def build_drop_index(
    raw_txs: list[dict],
    roster_to_user: dict[int, str],
) -> dict[tuple[str, str], str]:
    """Map ``(owner_user_id, player_id) -> earliest ISO drop date`` from the
    drop legs of drop/waiver/free-agent transactions. Trade drops are excluded
    (trades are handled by the lineage walk).
    """
    out: dict[tuple[str, str], str] = {}
    for tx in raw_txs:
        if tx.get("status") != "complete":
            continue
        if tx.get("type") not in _DROP_TX_TYPES:
            continue
        drops = tx.get("drops") or {}
        if not drops:
            continue
        d_iso = datetime.fromtimestamp(
            int(tx["created"]) / 1000.0, tz=timezone.utc
        ).date().isoformat()
        for player_id, src_roster_id in drops.items():
            owner = roster_to_user.get(src_roster_id)
            if owner is None:
                continue
            key = (owner, str(player_id))
            if key not in out or d_iso < out[key]:
                out[key] = d_iso
    return out


def _resolve_one_asset(
    asset,
    trade_id: str,
    resolution_by_identity: dict[tuple[str, int, int], str],
    drafts_by_season: dict[int, dict],
    draft_picks_by_draft_id: dict[str, list[dict]],
    user_to_slot_by_season: dict[int, dict[str, int]],
    player_names: dict[str, str],
):
    """Resolve a single asset.

    A PickAsset whose draft is complete and whose drafted player is known is
    EITHER upgraded to a PlayerAsset (only in its resolution trade) OR returned
    as a PickAsset annotated with the drafted player (every other trade). A
    pick whose draft hasn't happened (or whose slot/player can't be found) is
    returned unchanged.
    """
    if not isinstance(asset, PickAsset):
        return asset
    draft = drafts_by_season.get(asset.season)
    if draft is None or draft.get("status") != "complete":
        return asset  # draft hasn't happened yet
    slot_map = user_to_slot_by_season.get(asset.season, {})
    slot = slot_map.get(asset.original_owner_user_id)
    if slot is None:
        log.warning(
            "No draft slot for user=%s in season=%d; leaving pick unresolved",
            asset.original_owner_user_id, asset.season,
        )
        return asset
    rows = draft_picks_by_draft_id.get(draft["draft_id"], [])
    player_id = None
    for row in rows:
        if row.get("round") == asset.round and row.get("draft_slot") == slot:
            player_id = row.get("player_id")
            break
    if not player_id:
        log.warning(
            "Draft %s has no drafted player for round=%d slot=%d (user=%s); "
            "pick stays unresolved",
            draft["draft_id"], asset.round, slot, asset.original_owner_user_id,
        )
        return asset

    player_name = player_names.get(player_id, player_id)
    identity = (asset.original_owner_user_id, asset.season, asset.round)
    is_resolution_trade = resolution_by_identity.get(identity) == trade_id
    if is_resolution_trade:
        return PlayerAsset(player_id=player_id, name=player_name, via_pick=asset)
    # Non-resolution trade: keep the pick, annotate it for snapshot valuation.
    return PickAsset(
        season=asset.season,
        round=asset.round,
        original_owner_user_id=asset.original_owner_user_id,
        drafted_player_id=player_id,
        drafted_player_name=player_name,
    )


def _resolve_side(
    side: TradeSide,
    trade_id: str,
    resolution_by_identity: dict[tuple[str, int, int], str],
    drafts_by_season: dict[int, dict],
    draft_picks_by_draft_id: dict[str, list[dict]],
    user_to_slot_by_season: dict[int, dict[str, int]],
    player_names: dict[str, str],
) -> TradeSide:
    def _resolve(a):
        return _resolve_one_asset(
            a, trade_id, resolution_by_identity, drafts_by_season,
            draft_picks_by_draft_id, user_to_slot_by_season, player_names,
        )

    return TradeSide(
        user_id=side.user_id,
        received=[_resolve(a) for a in side.received],
        given=[_resolve(a) for a in side.given],
    )


def resolve_assets(
    trades: list[Trade],
    drafts_by_season: dict[int, dict],
    draft_picks_by_draft_id: dict[str, list[dict]],
    user_to_slot_by_season: dict[int, dict[str, int]],
    player_names: dict[str, str],
    resolution_by_identity: dict[tuple[str, int, int], str] | None = None,
) -> list[ResolvedTrade]:
    """Resolve traded picks.

    ``resolution_by_identity`` (from ``compute_pick_resolution_map``) decides
    which single trade may upgrade each pick to a PlayerAsset. When omitted,
    no pick is upgraded — every drafted pick is annotated instead. Callers that
    want resolution MUST pass the map.
    """
    resolution_by_identity = resolution_by_identity or {}
    resolved: list[ResolvedTrade] = []
    for trade in trades:
        new_sides = {
            uid: _resolve_side(
                side,
                trade.transaction_id,
                resolution_by_identity,
                drafts_by_season,
                draft_picks_by_draft_id,
                user_to_slot_by_season,
                player_names,
            )
            for uid, side in trade.sides.items()
        }
        resolved.append(ResolvedTrade(trade=trade, sides=new_sides))
    return resolved


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _derive_user_slot_map(
    draft: dict,
    draft_picks: list[dict],
    roster_to_user: dict[int, str],
) -> dict[str, int]:
    """Build the user_id → draft_slot map for one season's draft.

    Preferred path: read ``draft.draft_order`` directly (Sleeper's
    authoritative mapping). Falls back to the round-1-pick heuristic
    when ``draft_order`` is absent — for that fallback the picker's
    roster_id is taken as the original slot owner, which is only
    correct for untraded round-1 picks.
    """
    order = draft.get("draft_order")
    if isinstance(order, dict) and order:
        # Sleeper's authoritative mapping: user_id -> slot.
        # Values come back as int strings sometimes — normalize.
        out: dict[str, int] = {}
        for uid, slot in order.items():
            try:
                out[str(uid)] = int(slot)
            except (TypeError, ValueError):
                continue
        return out

    # Fallback heuristic.
    user_to_slot: dict[str, int] = {}
    for row in draft_picks:
        if row.get("round") != 1:
            continue
        rid = row.get("roster_id")
        slot = row.get("draft_slot")
        if rid in roster_to_user and slot is not None:
            user_to_slot.setdefault(roster_to_user[rid], slot)
    return user_to_slot


async def _fetch_league_season_data(
    client,
    league,
    league_cache=None,
) -> dict:
    """Pull everything we need for one league-season.

    Returns a dict bundling users, roster_to_user, raw transactions (trades,
    drops, and the unfiltered roster-transaction feed), drafts, and
    draft_picks_by_draft_id, plus the ``league`` object.

    When ``league_cache`` is provided and the league is sealed
    (``status == "complete"``), the bundle (minus the League object) is loaded
    from / stored in the cache, avoiding all network fetches for that season.
    The current/incomplete season is always fetched and never cached.
    """
    sealed = league_cache is not None and getattr(league, "status", None) == "complete"
    if sealed:
        cached = league_cache.read_trade_bundle(league.league_id)
        if cached is not None:
            return {"league": league, **cached}

    users = await client.get_users(league.league_id)
    rosters = await client.get_rosters(league.league_id)
    roster_to_user = {r.roster_id: r.owner_id for r in rosters}

    raw_trades: list[dict] = []
    for tx in await client.get_trade_transactions(league.league_id):
        tx_id = str(tx.get("transaction_id", ""))
        if tx_id in BLACKLISTED_TRANSACTION_IDS:
            log.info("Skipping blacklisted transaction %s", tx_id)
            continue
        raw_trades.append(tx)
    raw_drops = await client.get_drop_transactions(league.league_id)
    raw_roster_txs = await client.get_roster_transactions(league.league_id)

    drafts = await client.get_drafts(league.league_id)
    draft_picks_by_draft_id: dict[str, list[dict]] = {}
    for d in drafts:
        if d.get("status") == "complete":
            picks = await client.get_draft_picks(d["draft_id"])
            draft_picks_by_draft_id[d["draft_id"]] = picks

    bundle = {
        "users": users,
        "roster_to_user": roster_to_user,
        "raw_trades": raw_trades,
        "raw_drops": raw_drops,
        "raw_roster_txs": raw_roster_txs,
        "drafts": drafts,
        "draft_picks_by_draft_id": draft_picks_by_draft_id,
    }
    if sealed:
        league_cache.write_trade_bundle(league.league_id, bundle)
    return {"league": league, **bundle}


async def build_trade_history(
    client,
    current_league_id: str,
    player_names: dict[str, str],
    league_cache=None,
    return_drops: bool = False,
) -> list[ResolvedTrade]:
    """Walk the league chain and return all trades, resolved, newest-first.

    Args:
        client: A SleeperClient (or test double exposing the same async
            methods).
        current_league_id: The starting league. We walk back from here.
        player_names: player_id → display name (from Sleeper's players
            blob). Used to label resolved picks.
        league_cache: Optional, duck-typed cache (exposing
            ``read_trade_bundle`` / ``write_trade_bundle``) used to skip
            network fetches for sealed seasons.

    Returns:
        ResolvedTrade list, newest first.
    """
    chain = await client.walk_league_history(current_league_id)
    log.info("Trade chain length: %d seasons", len(chain))

    async def _logged_fetch(league):
        log.info("Fetching trades for season %d (%s)", league.season, league.name)
        return await _fetch_league_season_data(client, league, league_cache)

    bundles = await asyncio.gather(*(_logged_fetch(lg) for lg in chain))

    # Aggregate drafts + picks across all seasons for resolution.
    drafts_by_season: dict[int, dict] = {}
    draft_picks_by_draft_id: dict[str, list[dict]] = {}
    user_to_slot_by_season: dict[int, dict[str, int]] = {}
    for bundle in bundles:
        season = bundle["league"].season
        for d in bundle["drafts"]:
            if d.get("status") == "complete":
                drafts_by_season[int(d.get("season", season))] = d
        draft_picks_by_draft_id.update(bundle["draft_picks_by_draft_id"])
        # Derive slot map: prefer the FIRST completed draft for this season
        # (most leagues have one; startup leagues with two drafts use the
        # rookie draft for current-season picks, but startup data is messy
        # enough that we accept some degradation).
        completed = [d for d in bundle["drafts"] if d.get("status") == "complete"]
        if completed:
            first = completed[0]
            picks_for_first = bundle["draft_picks_by_draft_id"].get(first["draft_id"], [])
            user_to_slot_by_season[season] = _derive_user_slot_map(
                first, picks_for_first, bundle["roster_to_user"]
            )
        else:
            user_to_slot_by_season[season] = {}

    # Normalize every trade.
    trades: list[Trade] = []
    for bundle in bundles:
        for raw_tx in bundle["raw_trades"]:
            trades.append(
                normalize_trade(
                    raw_tx,
                    roster_to_user=bundle["roster_to_user"],
                    league_id=bundle["league"].league_id,
                    season=bundle["league"].season,
                )
            )

    # Backfill player names for PlayerAssets created during normalize_trade.
    # normalize_trade constructs PlayerAsset(player_id=X, name="") from raw
    # adds/drops — the Sleeper API doesn't embed names in transaction payloads.
    # We fill the gap here using the players blob rather than changing
    # normalize_trade's signature (which is independently unit-tested).
    for trade in trades:
        for side in trade.sides.values():
            for asset_list in (side.received, side.given):
                for asset in asset_list:
                    if isinstance(asset, PlayerAsset) and not asset.name:
                        asset.name = player_names.get(asset.player_id, asset.player_id)

    # Resolve picks. The resolution map ensures each traded pick upgrades to a
    # PlayerAsset in exactly one trade (the one that delivered it to its final
    # holder); elsewhere it stays an annotated pick.
    resolution_by_identity = compute_pick_resolution_map(trades)
    resolved = resolve_assets(
        trades,
        drafts_by_season=drafts_by_season,
        draft_picks_by_draft_id=draft_picks_by_draft_id,
        user_to_slot_by_season=user_to_slot_by_season,
        player_names=player_names,
        resolution_by_identity=resolution_by_identity,
    )

    # Newest first.
    resolved.sort(key=lambda rt: rt.trade.traded_at, reverse=True)

    if not return_drops:
        return resolved

    drop_index: dict[tuple[str, str], str] = {}
    for bundle in bundles:
        season_idx = build_drop_index(
            bundle.get("raw_drops", []), bundle["roster_to_user"]
        )
        for key, d_iso in season_idx.items():
            if key not in drop_index or d_iso < drop_index[key]:
                drop_index[key] = d_iso
    return resolved, drop_index
