"""Qualified independent NFL season inventory, retaining both original sources.

Qualification is technical crosschecking, not authority to void a game. Current
17-game schedules only; unknown formats fail closed rather than changing counts.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from collections import Counter
from datetime import datetime

import httpx

from sleeper_dynasty.api.nfl_schedule import NFL_TEAMS, _SCOREBOARD

log = logging.getLogger(__name__)
SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/refs/heads/master/data/games.csv"
ALIASES = {"LA": "LAR", "WAS": "WSH"}


class InventoryUnqualified(ValueError):
    def __init__(self, reason):
        super().__init__("schedule_inventory_unqualified: " + reason)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def qualify_inventory(source: bytes, secondary: list[bytes], season: int) -> dict:
    """Require complete team/game coverage and a one-to-one second-source match."""
    try:
        reader = csv.DictReader(io.StringIO(source.decode("utf-8")))
        required = {"game_id", "season", "game_type", "week", "gameday", "gametime", "home_team", "away_team", "espn"}
        if not required.issubset(reader.fieldnames or []) or season < 2021:
            raise ValueError("unsupported schedule schema or season")
        rows = [r for r in reader if r["season"] == str(season) and r["game_type"] == "REG"]
        if len(rows) != 272 or len({r["game_id"] for r in rows}) != 272:
            raise ValueError("expected 272 unique regular-season games")
        counts = Counter(ALIASES.get(r[s], r[s]) for r in rows for s in ("home_team", "away_team"))
        if set(counts) != NFL_TEAMS or set(counts.values()) != {17}:
            raise ValueError("expected 32 teams with 17 games each")
        events = []
        for raw in secondary:
            payload = json.loads(raw)
            if not isinstance(payload.get("events"), list):
                raise ValueError("missing second-source events")
            events.extend(e for e in payload["events"] if e.get("season") == {**e.get("season", {}), "year": season, "type": 2})
        indexed = {str(e["id"]): e for e in events}
        ids = {r["espn"] for r in rows}
        if "" in ids or len(ids) != 272 or len(indexed) != len(events) or set(indexed) != ids:
            raise ValueError("second source has missing, duplicate, or extra event identities")
        games = []
        slots = set()
        for row in rows:
            event = indexed[row["espn"]]
            week = int(row["week"])
            if week not in range(1, 19) or event["week"]["number"] != week:
                raise ValueError("conflicting NFL week")
            comps = event["competitions"]
            if len(comps) != 1 or len(comps[0]["competitors"]) != 2:
                raise ValueError("ambiguous event competitors")
            teams = {c["homeAway"]: ALIASES.get(c["team"]["abbreviation"], c["team"]["abbreviation"])
                     for c in comps[0]["competitors"]}
            if set(teams) != {"home", "away"} or teams["home"] == teams["away"]:
                raise ValueError("invalid event competitors")
            for side in ("home", "away"):
                if teams[side] != ALIASES.get(row[side + "_team"], row[side + "_team"]):
                    raise ValueError("conflicting event competitors")
                if (week, teams[side]) in slots:
                    raise ValueError("team appears twice in one week")
                slots.add((week, teams[side]))
            kickoff = comps[0].get("date") or event["date"]
            dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("kickoff lacks timezone")
            # Upstream gameday is venue/date-oriented; UTC can fall next day.
            if abs((dt.date() - datetime.fromisoformat(row["gameday"]).date()).days) > 1:
                raise ValueError("conflicting schedule dates")
            games.append({"event_id": row["espn"], "source_id": row["game_id"], "week": week,
                "home": teams["home"], "away": teams["away"], "kickoff": kickoff,
                "gameday": row["gameday"], "gametime": row["gametime"]})
        games.sort(key=lambda g: (g["week"], g["event_id"]))
        sources = {"nflverse": source.decode("utf-8"), "espn": [b.decode("utf-8") for b in secondary]}
        return {"season": season, "revision": _hash(games), "version": _hash(sources), "games": games,
            "source_bytes": sources, "provenance": {"nflverse": SCHEDULE_URL,
                "espn": [f"{_SCOREBOARD}?dates={year}&limit=1000" for year in (season, season + 1)],
                "qualification": "full-season-32x17-crosswalk-v1"}}
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError) as exc:
        raise InventoryUnqualified(str(exc)) from exc


async def fetch_inventory(season: int) -> dict:
    log.info("Qualifying NFL season inventory season=%s", season)
    async with httpx.AsyncClient(timeout=30.0) as client:
        primary = await client.get(SCHEDULE_URL)
        primary.raise_for_status()
        secondary = []
        # A calendar-year query alone silently omits January regular-season games.
        for year in (season, season + 1):
            response = await client.get(_SCOREBOARD, params={"dates": year, "limit": 1000})
            response.raise_for_status()
            secondary.append(response.content)
    return qualify_inventory(primary.content, secondary, season)
