import pytest

from sleeper_dynasty.api.platform import LeaguePlatform
from sleeper_dynasty.api.sleeper import SleeperClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeHttp:
    """Records GET paths and replays canned payloads."""

    def __init__(self, routes):
        self.routes = routes
        self.paths = []

    async def get(self, path, **kw):
        self.paths.append(path)
        return _FakeResponse(self.routes.get(path, []))

    async def aclose(self):
        return None


def _client(routes):
    c = SleeperClient()
    c._client = _FakeHttp(routes)
    return c


def test_sleeper_client_satisfies_the_protocol():
    assert isinstance(SleeperClient(), LeaguePlatform)


@pytest.mark.asyncio
async def test_get_raw_matchups_returns_the_weeks_rows():
    rows = [{"matchup_id": 1, "roster_id": 3, "points": 100.5}]
    c = _client({"/league/L1/matchups/4": rows})
    assert await c.get_raw_matchups("L1", 4) == rows


@pytest.mark.asyncio
async def test_get_raw_matchups_normalizes_a_null_body_to_empty():
    """Sleeper returns null for a week that does not exist."""
    c = _client({"/league/L1/matchups/99": None})
    assert await c.get_raw_matchups("L1", 99) == []


@pytest.mark.asyncio
async def test_get_trade_transactions_filters_to_complete_trades():
    txs = [
        {"type": "trade", "status": "complete", "transaction_id": "1"},
        {"type": "trade", "status": "failed", "transaction_id": "2"},
        {"type": "waiver", "status": "complete", "transaction_id": "3",
         "drops": {"4034": 1}},
    ]
    routes = {f"/league/L1/transactions/{w}": (txs if w == 1 else [])
              for w in range(1, 19)}
    c = _client(routes)
    out = await c.get_trade_transactions("L1")
    assert [t["transaction_id"] for t in out] == ["1"]


@pytest.mark.asyncio
async def test_get_drop_transactions_excludes_trades():
    txs = [
        {"type": "trade", "status": "complete", "transaction_id": "1",
         "drops": {"4034": 1}},
        {"type": "waiver", "status": "complete", "transaction_id": "3",
         "drops": {"5000": 2}},
        {"type": "waiver", "status": "complete", "transaction_id": "4"},
    ]
    routes = {f"/league/L1/transactions/{w}": (txs if w == 1 else [])
              for w in range(1, 19)}
    c = _client(routes)
    out = await c.get_drop_transactions("L1")
    assert [t["transaction_id"] for t in out] == ["3"]


@pytest.mark.asyncio
async def test_get_roster_transactions_includes_adds_with_no_drops():
    """The gap this method exists to close. An add that drops nobody is
    invisible to get_trade_transactions AND get_drop_transactions."""
    txs = [
        {"type": "waiver", "status": "complete", "transaction_id": "a",
         "adds": {"111": 1}, "drops": None, "status_updated": 1746230400000},
        {"type": "free_agent", "status": "complete", "transaction_id": "b",
         "adds": {"222": 2}, "drops": {"333": 2}, "status_updated": 1746230500000},
        {"type": "trade", "status": "complete", "transaction_id": "c",
         "adds": {"444": 1}, "drops": {"555": 2}, "status_updated": 1746230600000},
        {"type": "waiver", "status": "failed", "transaction_id": "d",
         "adds": {"666": 1}, "drops": None, "status_updated": 1746230700000},
    ]
    routes = {f"/league/L1/transactions/{w}": (txs if w == 1 else [])
              for w in range(1, 19)}
    c = _client(routes)
    out = await c.get_roster_transactions("L1")
    ids = {t["transaction_id"] for t in out}
    assert ids == {"a", "b", "c"}          # the add-only one is INCLUDED
    assert "d" not in ids                   # a failed waiver never touched a roster
    # and the existing feeds still do NOT see it, which is the point
    assert "a" not in {t["transaction_id"] for t in await c.get_drop_transactions("L1")}


@pytest.mark.asyncio
async def test_get_phase_map_derives_from_the_brackets():
    class _Lg:
        league_id = "L1"
        playoff_week_start = 15
        playoff_round_type = 0

    routes = {
        "/league/L1/winners_bracket": [{"r": 1, "t1": 1, "t2": 2}],
        "/league/L1/losers_bracket": [{"r": 1, "t1": 5, "t2": 6}],
    }
    phases = await _client(routes).get_phase_map(_Lg())
    assert phases[(15, 1)] == "playoff"
    assert phases[(15, 6)] == "toilet"


@pytest.mark.asyncio
async def test_roster_and_drop_transactions_share_one_fetch():
    """Mutation this catches: removing the single-slot memo in
    `_all_week_transactions` (or making get_roster_transactions walk the
    weeks itself).

    Sleeper serves every feed from the same 18-week walk and the client
    memoizes one league id. A third caller must not triple the request
    count. Adapted from a test that landed on main against the retired
    get_add_transactions — the guarantee is the client's, not any one
    method's, so it outlives the method it was written for.
    """
    routes = {f"/league/L1/transactions/{w}": [] for w in range(1, 19)}
    c = _client(routes)
    await c.get_roster_transactions("L1")
    await c.get_drop_transactions("L1")
    await c.get_trade_transactions("L1")
    assert len(c._client.paths) == 18
