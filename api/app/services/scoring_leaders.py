"""Read-through scoring cache: shared NFL stats, league-specific calculations.

Kept separate from the trade grader so a scoring page never rebuilds trades or
generates prose. Finite TTLs allow completed-week stat corrections to propagate.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sleeper_dynasty.cache import FileCache
from sleeper_dynasty.api.platform import platform_for_league_id
from sleeper_dynasty.engine.lineup import BENCH_SLOTS, SLOT_ELIGIBILITY
from sleeper_dynasty.engine.scoring_leaders import (
    build_scoring_rows, completed_week, score_player_week,
)
from sleeper_dynasty.models.scoring import ThresholdBonus

log = logging.getLogger(__name__)


async def _gather(*calls):
    """Drain sibling requests before raising, so the owner can safely close HTTP."""
    results = await asyncio.gather(*calls, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


async def load_scoring_leaders(league_id: str, cache_dir: Path, client) -> dict:
    cache = FileCache(cache_dir / "scoring")
    # Result keys are league-scoped; raw NFL data is shared across leagues.
    result_key = f"board_v2_{league_id}.json"
    saved = cache.read(result_key, max_age_seconds=300)
    if saved is not None:
        return saved
    semaphore = asyncio.Semaphore(4)

    async def read_source(key, ttl, fetch, valid):
        data = cache.read(key, max_age_seconds=ttl)
        if data is not None and valid(data):
            return data
        async with semaphore:
            log.info("Fetching scoring source %s", key)
            data = await fetch()
        if not valid(data):
            raise ValueError("Sleeper returned incomplete scoring data. Try again shortly.")
        cache.write(key, data)
        return data

    async def league_data():
        league, _ = await client.get_league(league_id)
        return asdict(league)

    league, state = await _gather(
        read_source(f"league_{league_id}.json", 300, league_data,
                    lambda d: isinstance(d, dict) and bool(d.get("scoring_settings"))),
        read_source("nfl_state.json", 60, client.get_nfl_state,
                    lambda d: isinstance(d, dict) and bool(d.get("season"))),
    )
    season = int(league["season"])
    source_namespace = platform_for_league_id(league_id)
    bonuses = [ThresholdBonus(**bonus) for bonus in league.get("scoring_bonuses", ())]
    cutoff = completed_week(season, state)

    async def roster_data():
        rosters = [asdict(roster) for roster in await client.get_rosters(league_id)]
        if (len(rosters) != league["total_rosters"]
                or len({r["roster_id"] for r in rosters}) != len(rosters)):
            raise ValueError("Sleeper's roster data is incomplete. Try again shortly.")
        return rosters

    players, rosters, users = await _gather(
        read_source("players.json", 86400, client.get_players,
                    lambda d: isinstance(d, dict) and bool(d)
                    and all(isinstance(p, dict) for p in d.values())),
        read_source(f"rosters_{league_id}.json", 300, roster_data,
                    lambda d: isinstance(d, list) and len(d) == league["total_rosters"]
                    and all(isinstance(r, dict) and isinstance(r.get("players"), list) for r in d)),
        read_source(f"users_{league_id}.json", 300, lambda: client.get_users(league_id),
                    lambda d: isinstance(d, dict) and all(isinstance(u, dict) for u in d.values())),
    )
    roster_ids = {pid for roster in rosters for pid in roster["players"]}
    if any(not (players.get(pid) or {}).get("position") for pid in roster_ids):
        cache.invalidate("players.json")
        players = await read_source("players.json", 86400, client.get_players,
                                    lambda d: isinstance(d, dict) and bool(d)
                                    and all(isinstance(p, dict) for p in d.values()))
        if any(not (players.get(pid) or {}).get("position") for pid in roster_ids):
            cache.invalidate("players.json")
            raise ValueError("Sleeper's roster player details are incomplete. Try again shortly.")
    rows = []
    all_rows = []
    if cutoff:

        async def week_data(week):
            try:
                raw, matchups = await _gather(
                    read_source(f"stats_{source_namespace}_{season}_{week}.json", 3600,
                                lambda: client.get_stats(season, week),
                                lambda d: isinstance(d, dict) and all(isinstance(s, dict) for s in d.values()) and any(
                                    isinstance(s, dict) and s.get("gp")
                                    for s in d.values())),
                    read_source(f"matchups_{league_id}_{week}.json", 3600,
                                lambda: client.get_raw_matchups(league_id, week),
                                lambda d: isinstance(d, list) and len(d) == league["total_rosters"]
                                and all(isinstance(m, dict) and isinstance(m.get("players_points"), dict)
                                        and m["players_points"] for m in d)),
                )
                return week, raw, matchups
            except ValueError as exc:
                raise ValueError(f"Week {week}: {exc}") from exc

        bundles = await _gather(*(week_data(w) for w in range(1, cutoff + 1)))
        weeks = {week: raw for week, raw, _ in bundles}
        # TEAM_* rows are team aggregate bookkeeping, not fantasy defenses
        # (which have bare team IDs and player-catalog entries). Every actual
        # player with a recorded game needs metadata, even if unrostered.
        played_ids = {pid for raw in weeks.values() for pid, stats in raw.items()
                      if stats.get("gp") and not pid.startswith("TEAM_")}
        if any(not (players.get(pid) or {}).get("position") for pid in played_ids):
            cache.invalidate("players.json")
            players = await read_source("players.json", 86400, client.get_players,
                                        lambda d: isinstance(d, dict) and bool(d)
                                        and all(isinstance(p, dict) for p in d.values()))
            if any(not (players.get(pid) or {}).get("position") for pid in played_ids):
                cache.invalidate("players.json")
                raise ValueError("Sleeper's player details are incomplete. Try again shortly.")

        # Reconcile every rostered player, not just starters, before claiming
        # that the same scoring rules are correct for unrostered players.
        for week, raw, matchups in bundles:
            for matchup in matchups:
                for pid, actual in matchup["players_points"].items():
                    calculated = score_player_week(raw.get(pid) or {}, league["scoring_settings"],
                                                   (players.get(pid) or {}).get("position", ""),
                                                   bonuses=bonuses)
                    if abs(calculated - Decimal(str(actual))) > Decimal(".02"):
                        log.warning("Scoring mismatch league=%s week=%s player=%s calculated=%s actual=%s",
                                    league_id, week, pid, calculated, actual)
                        cache.invalidate(f"stats_{source_namespace}_{season}_{week}.json")
                        cache.invalidate(f"matchups_{league_id}_{week}.json")
                        raise ValueError(f"Week {week}: Calculated points do not match Sleeper's league scores. "
                                         "A scoring rule or stat correction needs reconciliation; try again shortly.")
        defensive_slots = {
            "DL": {"DL", "DE", "DT"}, "DB": {"DB", "CB", "S", "SS", "FS"},
            "IDP_FLEX": {"DL", "DE", "DT", "LB", "DB", "CB", "S", "SS", "FS"},
        }
        eligible = set().union(*(SLOT_ELIGIBILITY.get(slot, defensive_slots.get(slot, {slot}))
                                 for slot in league["roster_positions"] if slot not in BENCH_SLOTS))
        all_rows = build_scoring_rows(weeks, players, league["scoring_settings"], cutoff,
                                      bonuses=bonuses)
        ranks = Counter((row["position"], row["rank"]) for row in all_rows)
        for row in all_rows:
            row["tied"] = ranks[row["position"], row["rank"]] > 1
        rows = [row for row in all_rows if row["position"] in eligible]
        if not rows:
            raise ValueError("Sleeper's player scores are incomplete. Try again shortly.")
    # Ownership is current; points and ranks retain the whole completed season.
    # Reuse the scorer's rows so transferring/filtering never changes WR2 to WR1.
    ranked = {row["player_id"]: row for row in all_rows}
    franchises = []
    for roster in sorted(rosters, key=lambda r: r["roster_id"]):
        owner_id = roster.get("owner_id") or None
        user = users.get(owner_id) or {}
        roster_players = []
        for pid in roster["players"]:
            if pid in ranked:
                roster_players.append(ranked[pid])
            else:
                player = players[pid]
                name = player.get("full_name") or " ".join(
                    str(player.get(k) or "") for k in ("first_name", "last_name")
                ).strip() or pid
                roster_players.append({
                    "player_id": pid, "name": name, "position": player["position"],
                    "team": player.get("team"), "rank": None, "points": None,
                    "games": 0, "points_per_game": None,
                })
        franchises.append({
            "roster_id": roster["roster_id"], "owner_id": owner_id,
            "name": user.get("team_name") or user.get("display_name") or f"Franchise {roster['roster_id']}",
            "owner_name": user.get("display_name") if owner_id else None,
            "players": roster_players,
        })
    result = {
        "league_id": league_id, "league_name": league["name"], "season": season,
        "through_week": cutoff, "updated_at": datetime.now(timezone.utc).isoformat(),
        "players": rows, "franchises": franchises,
    }
    cache.write(result_key, result)
    log.info("Scoring leaders ready league=%s season=%s through_week=%s players=%s",
             league_id, season, cutoff, len(rows))
    return result
