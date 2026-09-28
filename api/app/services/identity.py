from __future__ import annotations

from app.models.common import OwnerRef
from app.services.chain_cache import ChainCacheEntry


def owner_name(entry: ChainCacheEntry, uid: str) -> str:
    """The owner's handle, falling back to the raw user_id."""
    uid = getattr(entry, "owner_aliases", {}).get(uid, uid)
    return (entry.owners.get(uid) or {}).get("owner_name") or uid


def owner_ref(entry: ChainCacheEntry, uid: str) -> OwnerRef:
    uid = getattr(entry, "owner_aliases", {}).get(uid, uid)
    o = entry.owners.get(uid) or {}
    return OwnerRef(
        user_id=uid,
        owner_name=o.get("owner_name") or uid,
        team_name=o.get("team_name"),
        franchise_name=o.get("franchise_name"),
        avatar_url=o.get("avatar_url"),
    )


def apply_name_overrides(entry: ChainCacheEntry, overrides: dict[str, str]) -> None:
    """Mutate entry.owners in place, applying display name overrides.

    Only touches uids present in both overrides and entry.owners.
    Called once after reading ChainCache, so all downstream services
    (aggregations, trade_view, owner_view, leaderboard) see friendly names.
    """
    for uid, name in overrides.items():
        uid = getattr(entry, "owner_aliases", {}).get(uid, uid)
        if uid in entry.owners:
            entry.owners[uid] = {**(entry.owners[uid] or {}), "owner_name": name}
            if entry.owners[uid].get("franchise_name"):
                entry.owners[uid]["franchise_name"] = name
