"""Raw provider lexical decimals must survive before any float coercion."""
import httpx
import pytest

from sleeper_dynasty.api.sleeper import SleeperClient


@pytest.mark.asyncio
async def test_recap_source_preserves_decimal_bytes_and_reports_bracket_failures():
    async def route(request):
        if "bracket" in request.url.path:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text='[{"roster_id":1,"points":100.0100,"custom_points":101.000,"players_points":{"p":1.2300},"starters":["p","0"]}]')
    client = SleeperClient()
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(route), base_url="https://api.sleeper.app/v1")
    try:
        source = await client.get_recap_source("/league/synthetic/matchups/4")
        assert source["ok"]
        assert source["data"][0]["points"] == "100.0100"
        assert source["data"][0]["custom_points"] == "101.000"
        assert source["data"][0]["players_points"]["p"] == "1.2300"
        assert '100.0100' in source["raw"]
        failed = await client.get_recap_source("/league/synthetic/winners_bracket")
        assert not failed["ok"] and failed["error"] == "http_503"
        assert "data" not in failed
    finally:
        await client.close()
