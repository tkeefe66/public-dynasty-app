import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty.api.nfl_schedule import fetch_week_schedule, derive_byes

FIX = Path(__file__).parent / "fixtures"


def _resp():
    r = MagicMock()
    r.json.return_value = json.loads(
        (FIX / "espn_scoreboard_week10.json").read_text()
    )
    r.raise_for_status.return_value = None
    return r


@pytest.mark.asyncio
async def test_fetch_week_schedule_parses_games():
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_resp())):
        games = await fetch_week_schedule(2025, 10)
    buf = next(g for g in games if g["home"] == "BUF")
    assert buf["away"] == "NE"
    assert buf["indoor"] is False
    det = next(g for g in games if g["home"] == "DET")
    assert det["indoor"] is True


def test_derive_byes_returns_non_playing_teams():
    games = [
        {"home": "BUF", "away": "NE"}, {"home": "DET", "away": "GB"},
    ]
    byes = derive_byes(games)
    assert "BUF" not in byes
    assert "KC" in byes
    assert len(byes) == 32 - 4


def test_derive_byes_empty_schedule_returns_empty():
    # No schedule data must NOT mean "all 32 teams on bye".
    assert derive_byes([]) == set()
