from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, require_league_member
from app.main import app
from app.models.common import OwnerRef
from app.models.league import LatestTrade
from app.routes import trade as trade_route

_FAKE_USER = SimpleNamespace(id="test-user", email="u@test.local", is_admin=True)


@pytest.fixture(autouse=True)
def _authorized():
    # These predate auth; bypass the league guard so they test the handler.
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    app.dependency_overrides[require_league_member] = lambda: _FAKE_USER
    try:
        yield
    finally:
        app.dependency_overrides.clear()


class _Entry:
    """Minimal stand-in for a cached chain entry."""
    def __init__(self, chain):
        self.chain = chain


def _client():
    return TestClient(app)


def _fake_items(n: int) -> list[LatestTrade]:
    return [
        LatestTrade(
            trade_id=f"t{i}",
            date="2024-01-01",
            week=i,
            parties=[OwnerRef(user_id="uA", owner_name="A"), OwnerRef(user_id="uB", owner_name="B")],
            assets_short="X for Y",
            swing_ktc=float(i),
            swing_prod=float(-i),
        )
        for i in range(n)
    ]


def test_trades_list_cold_cache_returns_409(monkeypatch, tmp_path):
    monkeypatch.setattr(trade_route, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.chain_cache.ChainCache.read",
        lambda self, league_id: None,
    )
    resp = _client().get("/api/league/123/trades")
    assert resp.status_code == 409


def test_trades_list_returns_all_uncapped(monkeypatch, tmp_path):
    monkeypatch.setattr(trade_route, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.chain_cache.ChainCache.read",
        lambda self, league_id: _Entry(chain=object()),
    )
    items = _fake_items(12)
    captured: dict = {}

    def _fake(entry, *, year, lens):
        captured["year"] = year
        captured["lens"] = lens
        return items

    monkeypatch.setattr(trade_route, "build_trades_list", _fake)
    resp = _client().get("/api/league/123/trades?year=2023&lens=production")
    assert resp.status_code == 200
    body = resp.json()
    # Not capped at 8 the way the dashboard's latest_trades teaser is.
    assert len(body) == 12
    assert body[0]["trade_id"] == "t0"
    assert {"trade_id", "swing_ktc", "swing_prod", "parties"} <= body[0].keys()
    assert captured == {"year": 2023, "lens": "production"}


def test_trades_list_invalid_year_returns_400(monkeypatch, tmp_path):
    monkeypatch.setattr(trade_route, "_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.chain_cache.ChainCache.read",
        lambda self, league_id: _Entry(chain=object()),
    )
    resp = _client().get("/api/league/123/trades?year=banana")
    assert resp.status_code == 400
