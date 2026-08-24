import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty.api.weather import fetch_game_weather, STADIUM_COORDS

FIX = Path(__file__).parent / "fixtures"


def _resp():
    r = MagicMock()
    r.json.return_value = json.loads((FIX / "open_meteo.json").read_text())
    r.raise_for_status.return_value = None
    return r


def test_stadium_coords_has_outdoor_venues():
    assert "BUF" in STADIUM_COORDS  # outdoor stadium present


@pytest.mark.asyncio
async def test_fetch_game_weather_returns_conditions():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp())):
        wx = await fetch_game_weather("BUF", kickoff_iso="2025-11-09T18:00Z")
    assert wx["wind_mph"] == 22.0
    assert wx["temp_f"] == 28.0
    assert wx["precip"] in ("rain", "snow", "none")


@pytest.mark.asyncio
async def test_fetch_game_weather_unknown_team_returns_none():
    wx = await fetch_game_weather("ZZZ", kickoff_iso="2025-11-09T18:00Z")
    assert wx is None
