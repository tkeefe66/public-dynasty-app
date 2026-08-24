from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _seed_entry(cache_dir: Path) -> ChainCacheEntry:
    entry = ChainCacheEntry(
        league_id="L_current",
        chain=[
            {"league_id": "L_current", "season": 2026, "name": "Bros",
             "total_rosters": 2, "playoff_week_start": 15},
        ],
        resolved_trades=[],
        grades={},
        owners={"u_alice": {"owner_name": "Alice", "team_name": None, "avatar_url": None}, "u_bob": {"owner_name": "Bob", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={"L_current": 15},
        roster_to_user_by_league={"L_current": {1: "u_alice", 2: "u_bob"}},
        league_name_by_id={"L_current": "Bros"},
        league_season_by_id={"L_current": 2026},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    cache = ChainCache(cache_dir=cache_dir)
    cache.write("L_current", entry)
    return entry


def test_league_warm_cache_returns_dashboard(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.league._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["league"]["league_id"] == "L_current"
    assert body["selected_year"] == "all"
    assert body["selected_lens"] == "ktc"


def test_league_cold_cache_returns_409(client, tmp_path):
    with patch("app.routes.league._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_unseen")
    assert resp.status_code == 409
    body = resp.json()
    assert "cold" in body["detail"].lower()


def test_league_year_param(client, tmp_path):
    _seed_entry(tmp_path)
    with patch("app.routes.league._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_current?year=2026&lens=production")
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_year"] == 2026
    assert body["selected_lens"] == "production"
