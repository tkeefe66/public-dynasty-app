"""League participation, independent of app access and historical identity.

Read existing provider-neutral snapshots; never infer departure from activity,
names, missing outlooks, or an incomplete roster response.
"""
from __future__ import annotations

from app.services.chain_cache import ChainCacheEntry


def season_membership(entry: ChainCacheEntry, year: int) -> dict[str, str]:
    """Positive evidence admits a participant; missing evidence never ranks one.

    Current membership and membership in a selected year are separate facts.
    A complete season roster establishes absence, but trades/played records
    retain managers who left before that snapshot.
    """
    aliases = entry.owner_aliases or {}
    def canonical(uid):
        return aliases.get(uid, uid)

    seasons = dict(entry.league_season_by_id)
    leagues = {lg["league_id"]: lg for lg in entry.chain if lg.get("league_id")}
    seasons.update({lid: int(lg["season"]) for lid, lg in leagues.items() if lg.get("season")})
    lids = [lid for lid, season in seasons.items() if int(season) == year]
    active = set()
    complete = bool(lids)
    for lid in lids:
        roster = entry.roster_to_user_by_league.get(lid) or {}
        members = {canonical(uid) for uid in roster.values() if uid}
        active.update(members)
        expected = leagues.get(lid, {}).get("total_rosters")
        complete = complete and bool(expected) and len(roster) == expected and len(members) == expected and members.issubset(entry.owners)
    for trade in entry.resolved_trades:
        if (trade.get("trade") or {}).get("season") == year:
            active.update(canonical(uid) for uid in (trade.get("sides") or {}))
    # A played season record is positive evidence. Empty/zero placeholder
    # records and prior-year career records cannot establish participation.
    records = (entry.season_records or {}).get(str(year), {})
    for uid, record in records.items():
        if sum(record.get(key, 0) or 0 for key in ("wins", "losses", "ties")) > 0:
            active.add(canonical(uid))
    return {uid: "active" if canonical(uid) in active else
            "inactive" if complete else "unverified" for uid in entry.owners}


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
                  if any(canonical(u) == uid and
                         sum(record.get(key, 0) or 0 for key in ("wins", "losses", "ties")) > 0
                         for u, record in records.items()))
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
    # A unique current assignment proves presence even when another team is
    # vacant. Completeness is needed to prove absence, not presence.
    assignments = [canonical(u) for u in roster.values() if u]
    if uid in entry.owners and assignments.count(uid) == 1:
        result["membership_status"] = "current"
        return result
    if (not expected or len(roster) != expected or len(members) != expected
            or not members.issubset(entry.owners)):
        return result
    if played:
        result["membership_status"] = "former"
    return result
