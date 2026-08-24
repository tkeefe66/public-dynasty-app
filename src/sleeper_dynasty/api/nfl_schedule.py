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

    games = []
    for event in data.get("events", []):
        for comp in event.get("competitions", []):
            venue = comp.get("venue") or {}
            home = away = None
            for c in comp.get("competitors", []):
                abbr = (c.get("team") or {}).get("abbreviation")
                if c.get("homeAway") == "home":
                    home = abbr
                elif c.get("homeAway") == "away":
                    away = abbr
            if home and away:
                games.append({
                    "home": home, "away": away,
                    "kickoff": comp.get("date"),
                    "venue": venue.get("fullName"),
                    "indoor": bool(venue.get("indoor", False)),
                })
    return games


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
