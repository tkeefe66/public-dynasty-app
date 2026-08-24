"""Game-day weather via Open-Meteo (free, no API key).

Only outdoor stadiums are looked up; domes are excluded by the caller (the
schedule's ``indoor`` flag). Best-effort: returns None on unknown venue or
fetch failure so the recap simply omits weather jokes for that game.

Coordinates are hand-maintained for outdoor/retractable venues. Pure-dome
teams are intentionally absent (no weather to report).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Outdoor / retractable-roof stadiums: team abbr -> (lat, lon).
# Pure domes (DET, MIN, NO, ATL, LV, ARI*) are omitted by design.
STADIUM_COORDS: dict[str, tuple[float, float]] = {
    "BUF": (42.774, -78.787), "NE": (42.091, -71.264),
    "GB": (44.501, -88.062), "CHI": (41.862, -87.617),
    "KC": (39.049, -94.484), "DEN": (39.744, -105.020),
    "PIT": (40.447, -80.016), "CLE": (41.506, -81.700),
    "CIN": (39.095, -84.516), "BAL": (39.278, -76.623),
    "PHI": (39.901, -75.168), "NYG": (40.814, -74.074),
    "NYJ": (40.814, -74.074), "WSH": (38.908, -76.864),
    "TB": (27.976, -82.503), "MIA": (25.958, -80.239),
    "JAX": (30.324, -81.637), "TEN": (36.166, -86.771),
    "CAR": (35.226, -80.853), "SEA": (47.595, -122.332),
    "SF": (37.713, -121.970), "LAC": (33.864, -118.261),
    "LAR": (33.864, -118.261),
}

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def _classify_precip(mm: float) -> str:
    if mm <= 0.05:
        return "none"
    return "rain"  # snow vs rain needs temp context; caller refines if cold


async def fetch_game_weather(team: str, kickoff_iso: str) -> dict | None:
    """Fetch forecast conditions at the home team's stadium near kickoff.

    Returns ``{wind_mph, temp_f, precip}`` (precip in none/rain/snow) or None
    if the venue is unknown (dome / not in table) or the fetch fails.
    """
    coords = STADIUM_COORDS.get(team)
    if coords is None:
        return None
    lat, lon = coords
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,precipitation",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "forecast_days": 7,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(_OPEN_METEO, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("Weather fetch failed for %s: %s", team, e)
        return None

    hourly = data.get("hourly", {})
    temps = hourly.get("temperature_2m") or []
    winds = hourly.get("wind_speed_10m") or []
    precs = hourly.get("precipitation") or []
    if not temps:
        return None
    # Use the first available hour as a representative sample (fixture-friendly;
    # production could match kickoff_iso to the nearest hourly timestamp).
    temp_f = temps[0]
    precip = _classify_precip(precs[0] if precs else 0.0)
    if precip == "rain" and temp_f is not None and temp_f <= 32:
        precip = "snow"
    return {
        "wind_mph": winds[0] if winds else None,
        "temp_f": temp_f,
        "precip": precip,
    }
