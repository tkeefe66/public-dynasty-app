import httpx
import pytest

from sleeper_dynasty.api import fantasycalc


class _Recorder:
    """Captures the params of every GET without touching the network."""

    def __init__(self):
        self.params = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        self.params.append(params)
        return httpx.Response(
            200,
            json=[{"player": {"sleeperId": "4034"}, "value": 5000}],
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_defaults_to_dynasty_values(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(fantasycalc.httpx, "AsyncClient", lambda **kw: rec)
    await fantasycalc.fetch_fantasycalc_values()
    assert all(p["isDynasty"] == "true" for p in rec.params)


@pytest.mark.asyncio
async def test_redraft_flag_flips_the_parameter(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(fantasycalc.httpx, "AsyncClient", lambda **kw: rec)
    await fantasycalc.fetch_fantasycalc_values(dynasty=False)
    assert all(p["isDynasty"] == "false" for p in rec.params)


@pytest.mark.asyncio
async def test_return_shape_is_unchanged(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(fantasycalc.httpx, "AsyncClient", lambda **kw: rec)
    out = await fantasycalc.fetch_fantasycalc_values(dynasty=False)
    assert out == {"4034": {"superflex": 5000, "one_qb": 5000}}
