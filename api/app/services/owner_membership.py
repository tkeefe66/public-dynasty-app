"""League participation, independent of app access and historical identity.

Read existing provider-neutral snapshots; never infer departure from activity,
names, missing outlooks, or an incomplete roster response.
"""
from __future__ import annotations

from app.services.chain_cache import ChainCacheEntry


def owner_membership(entry: ChainCacheEntry, uid: str) -> dict:
    aliases = entry.owner_aliases or {}
    canonical = lambda value: aliases.get(value, value)
    uid = canonical(uid)
    seasons = dict(entry.league_season_by_id)
    leagues = {lg["league_id"]: lg for lg in entry.chain if lg.get("league_id")}
    seasons.update({lid: int(lg["season"]) for lid, lg in leagues.items() if lg.get("season")})
    played = {
        int(seasons[lid]) for lid, roster in entry.roster_to_user_by_league.items()
        if lid in seasons and uid in {canonical(u) for u in roster.values() if u}
    }
    played.update(int(year) for year, records in entry.season_records.items()
                  if uid in {canonical(u) for u in records})
    for trade in entry.resolved_trades:
        season = (trade.get("trade") or {}).get("season")
        if season and uid in {canonical(u) for u in (trade.get("sides") or {})}:
            played.add(int(season))

    result = {"membership_status": "unverified",
              "last_active_season": max(played) if played else None}
    if not seasons:
        return result
    latest = max(int(s) for s in seasons.values())
    latest_ids = [lid for lid, year in seasons.items() if int(year) == latest]
    # Two distinct leagues at the same cutoff are ambiguous, not evidence of
    # departure. No fallback to an older populated season.
    if len(latest_ids) != 1:
        return result
    lid = latest_ids[0]
    roster = entry.roster_to_user_by_league.get(lid) or {}
    expected = leagues.get(lid, {}).get("total_rosters")
    members = {canonical(u) for u in roster.values() if u}
    if (not expected or len(roster) != expected or len(members) != expected
            or not members.issubset(entry.owners)):
        return result
    if uid in members:
        result["membership_status"] = "current"
    elif played:
        result["membership_status"] = "former"
    return result
