"""NFL weekly schedule from ESPN's public scoreboard feed.

Used to derive bye weeks (teams not playing) and to know venue/indoor for
weather lookups. Best-effort: callers treat failures as "no schedule data"
and omit bye/weather beats rather than failing the recap.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
)

# All 32 NFL team abbreviations (ESPN style).
NFL_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LV", "LAC", "LAR", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SF", "SEA", "TB",
    "TEN", "WSH",
}


async def fetch_week_schedule(season: int, week: int) -> list[dict]:
    """Fetch the week's games. Returns a list of
    ``{home, away, kickoff, venue, indoor}`` dicts.
    """
    params = {"seasontype": 2, "week": week, "dates": season}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_SCOREBOARD, params=params)
        resp.raise_for_status()
        data = resp.json()

    return parse_scoreboard(data)


def parse_scoreboard(data: dict, *, strict=False) -> list[dict]:
    if strict and not isinstance(data.get("events"), list):
        raise ValueError("scoreboard events missing")
    games = []
    for event in data.get("events", []):
        if strict and (not event.get("id") or len(event.get("competitions", [])) != 1):
            raise ValueError("scoreboard event identity or competition missing")
        for comp in event.get("competitions", []):
            venue = comp.get("venue") or {}
            home = away = None
            for c in comp.get("competitors", []):
                abbr = (c.get("team") or {}).get("abbreviation")
                if c.get("homeAway") == "home":
                    home = abbr
                elif c.get("homeAway") == "away":
                    away = abbr
            if strict and (not home or not away or home == away or len(comp.get("competitors", [])) != 2):
                raise ValueError("scoreboard competitors incomplete")
            if home and away:
                status = (event.get("status") or comp.get("status") or {}).get("type") or {}
                games.append({
                    "home": home, "away": away,
                    "kickoff": comp.get("date"),
                    "venue": venue.get("fullName"),
                    "indoor": bool(venue.get("indoor", False)),
                    "event_id": str(event.get("id") or ""),
                    "completed": status.get("completed") is True,
                    "status": status.get("name") or "UNKNOWN",
                    "state": status.get("state") or "unknown",
                })
    return games


async def fetch_week_evidence(season: int, week: int) -> dict:
    """Strict evidence path. Errors remain visible, never masquerade as an empty week."""
    params = {"seasontype": 2, "week": week, "dates": season}
    async with httpx.AsyncClient(timeout=30.0) as client:
        logger.info("Fetching NFL completion evidence season=%s week=%s", season, week)
        response = await client.get(_SCOREBOARD, params=params)
        response.raise_for_status()
        data = response.json()
        return {"games": parse_scoreboard(data, strict=True), "raw": response.text,
                "source": str(response.url), "provider_timestamp": response.headers.get("date", "")}


def derive_byes(games: list[dict]) -> set[str]:
    """Teams on bye = all NFL teams minus those appearing in this week's games.

    Returns an empty set when ``games`` is empty: no schedule data means we
    can't know who's on bye, and claiming all 32 teams are on bye would emit
    nonsense bye beats for every roster (e.g. on an offseason/out-of-range
    week where ESPN returns no events).
    """
    if not games:
        return set()
    playing = set()
    for g in games:
        playing.add(g["home"])
        playing.add(g["away"])
    return NFL_TEAMS - playing
