from __future__ import annotations

from unittest.mock import patch

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _seed(tmp_path):
    entry = ChainCacheEntry(
        league_id="L",
        chain=[],
        resolved_trades=[],
        grades={},
        owners={
            "u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
            "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
        },
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"},
        league_season_by_id={"L": 2024},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    ChainCache(cache_dir=tmp_path).write("L", entry)


def test_get_profiles_empty(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.profiles._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/profiles")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_put_then_get_reflects(client, tmp_path):
    _seed(tmp_path)
    profile = {
        "win_name": "Alice",
        "loss_name": "Alicia",
        "archetype": "The Closer",
        "rivals": ["u_b"],
        "roast": "never punts",
    }
    with patch("app.routes.profiles._cache_dir", return_value=tmp_path):
        put = client.put("/api/league/L/profiles/u_a", json=profile)
        assert put.status_code == 200
        get = client.get("/api/league/L/profiles")
    body = get.json()
    assert set(body) == {"u_a"}
    assert body["u_a"]["win_name"] == "Alice"
    assert body["u_a"]["rivals"] == ["u_b"]


def test_put_unknown_owner_404(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.profiles._cache_dir", return_value=tmp_path):
        resp = client.put("/api/league/L/profiles/u_ghost", json={"win_name": "X"})
    assert resp.status_code == 404


def test_put_cold_cache_409(client, tmp_path):
    with patch("app.routes.profiles._cache_dir", return_value=tmp_path):
        resp = client.put("/api/league/L/profiles/u_a", json={"win_name": "X"})
    assert resp.status_code == 409


def test_get_cold_cache_returns_empty(client, tmp_path):
    # Reading profiles never requires a warm chain — return what's stored ({}).
    with patch("app.routes.profiles._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/profiles")
    assert resp.status_code == 200
    assert resp.json() == {}
