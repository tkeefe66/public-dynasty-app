from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _seed_entry(cache_dir: Path) -> ChainCacheEntry:
    entry = ChainCacheEntry(
        league_id="L1",
        chain=[{"league_id": "L1", "season": 2024, "name": "Bros",
                "total_rosters": 2, "playoff_week_start": 15}],
        resolved_trades=[],
        grades={},
        owners={
            "u_tom": {"owner_name": "tkeefe66", "team_name": None, "avatar_url": None},
            "u_jake": {"owner_name": "jakeman99", "team_name": None, "avatar_url": None},
        },
        playoff_weeks_by_league={"L1": 15},
        roster_to_user_by_league={"L1": {1: "u_tom", 2: "u_jake"}},
        league_name_by_id={"L1": "Bros"},
        league_season_by_id={"L1": 2024},
        cached_at="2026-01-01T00:00:00Z",
    )
    ChainCache(cache_dir=cache_dir).write("L1", entry)
    return entry


def test_get_owner_names_warm_cache(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L1/owner-names")
    assert resp.status_code == 200
    body = resp.json()
    uids = {o["user_id"] for o in body["owners"]}
    assert uids == {"u_tom", "u_jake"}
    # No overrides yet — display_name should be None
    for o in body["owners"]:
        assert o["display_name"] is None


def test_get_owner_names_cold_cache_returns_409(client, tmp_path):
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L1/owner-names")
    assert resp.status_code == 409


def test_put_owner_names_saves_and_get_reflects_overrides(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        put_resp = client.put(
            "/api/league/L1/owner-names",
            json={"overrides": {"u_tom": "Tom", "u_jake": "Jake"}},
        )
        assert put_resp.status_code == 200
        get_resp = client.get("/api/league/L1/owner-names")
    assert get_resp.status_code == 200
    by_uid = {o["user_id"]: o["display_name"] for o in get_resp.json()["owners"]}
    assert by_uid["u_tom"] == "Tom"
    assert by_uid["u_jake"] == "Jake"


def test_put_owner_names_ignores_unknown_uids(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        client.put(
            "/api/league/L1/owner-names",
            json={"overrides": {"u_ghost": "Ghost", "u_tom": "Tom"}},
        )
        resp = client.get("/api/league/L1/owner-names")
    by_uid = {o["user_id"]: o["display_name"] for o in resp.json()["owners"]}
    assert by_uid["u_tom"] == "Tom"
    assert "u_ghost" not in by_uid


def test_put_owner_names_strips_empty_strings(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.settings._cache_dir", return_value=tmp_path):
        client.put(
            "/api/league/L1/owner-names",
            json={"overrides": {"u_tom": "  ", "u_jake": "Jake"}},
        )
        resp = client.get("/api/league/L1/owner-names")
    by_uid = {o["user_id"]: o["display_name"] for o in resp.json()["owners"]}
    assert by_uid["u_tom"] is None  # whitespace-only stripped
    assert by_uid["u_jake"] == "Jake"
