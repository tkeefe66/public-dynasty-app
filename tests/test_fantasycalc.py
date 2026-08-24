"""Tests for the FantasyCalc dynasty-value fallback fetcher."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty.api.fantasycalc import fetch_fantasycalc_values


def _mock_resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


@pytest.mark.asyncio
async def test_fetch_fantasycalc_values_keys_by_sleeper_id():
    sf_payload = [
        {"player": {"sleeperId": "9509", "name": "Bijan", "position": "RB"}, "value": 10439},
        {"player": {"sleeperId": "4046", "name": "Cooper Kupp", "position": "WR"}, "value": 5500},
    ]
    oneqb_payload = [
        {"player": {"sleeperId": "9509", "name": "Bijan", "position": "RB"}, "value": 9800},
    ]

    async def _get(url, params=None):
        if params.get("numQbs") == "2":
            return _mock_resp(sf_payload)
        return _mock_resp(oneqb_payload)

    with patch("httpx.AsyncClient") as MockClient:
        client_instance = MagicMock()
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)
        client_instance.get = AsyncMock(side_effect=_get)
        MockClient.return_value = client_instance
        values = await fetch_fantasycalc_values()

    assert values["9509"] == {"superflex": 10439, "one_qb": 9800}
    assert values["4046"] == {"superflex": 5500}


@pytest.mark.asyncio
async def test_fetch_fantasycalc_values_skips_missing_sleeper_id():
    payload = [
        {"player": {"name": "No Sleeper ID Player"}, "value": 1000},
        {"player": {"sleeperId": "999", "name": "Has Sleeper ID"}, "value": 2000},
    ]

    async def _get(url, params=None):
        return _mock_resp(payload)

    with patch("httpx.AsyncClient") as MockClient:
        client_instance = MagicMock()
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)
        client_instance.get = AsyncMock(side_effect=_get)
        MockClient.return_value = client_instance
        values = await fetch_fantasycalc_values()

    assert "999" in values
    assert values["999"]["superflex"] == 2000
    # Missing sleeperId entries silently skipped.
    assert len(values) == 1


@pytest.mark.asyncio
async def test_fetch_fantasycalc_values_graceful_failure():
    import httpx
    with patch("httpx.AsyncClient") as MockClient:
        client_instance = MagicMock()
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)
        client_instance.get = AsyncMock(side_effect=httpx.ConnectError("no network"))
        MockClient.return_value = client_instance
        values = await fetch_fantasycalc_values()
    assert values == {}
