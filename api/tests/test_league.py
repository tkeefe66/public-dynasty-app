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


@pytest.mark.parametrize("phase", ["regular", "post"])
def test_auto_year_uses_active_season_and_filters_standings(client, tmp_path, phase):
    # Mutation: resolve auto to all, or use the calendar/latest chain year.
    from datetime import datetime
    from tests.test_aggregations import _sample_entry

    entry = _sample_entry()
    entry.league_phase = {"phase": phase, "season": 2026, "week": 18}
    # Next year's league may already exist while the 2026 season is still live.
    entry.chain.append({"league_id": "L_next", "season": 2027, "name": "Bros", "total_rosters": 2})
    ChainCache(cache_dir=tmp_path).write("L_current", entry)
    with patch("app.routes.league._cache_dir", return_value=tmp_path), patch("app.routes.league.datetime") as clock:
        clock.now.return_value = datetime(2027, 1, 3)
        resp = client.get("/api/league/L_current?year=auto")
    assert resp.status_code == 200
    body = resp.json()
    assert body["selected_year"] == 2026
    assert body["total_trades"] == 1
    assert {t["trade_id"] for t in body["latest_trades"]} == {"tx_2026"}
    assert all(row["trades"] == 1 for row in body["standings"])


@pytest.mark.parametrize("phase", [
    {"phase": "offseason", "season": 2026},
    {"phase": "draft", "season": 2026},
    {},
    {"phase": "regular", "season": 2027},
])
def test_auto_year_falls_back_to_all_without_an_available_active_season(client, tmp_path, phase):
    # Mutation: select the newest chain season even outside the active season.
    entry = _seed_entry(tmp_path)
    entry.league_phase = phase
    ChainCache(cache_dir=tmp_path).write("L_current", entry)
    with patch("app.routes.league._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_current?year=auto")
    assert resp.status_code == 200
    assert resp.json()["selected_year"] == "all"


@pytest.mark.parametrize(("query", "selected", "trade_count"), [
    ("year=all", "all", 2), ("year=2024", 2024, 1), ("", "all", 2),
])
def test_explicit_year_and_existing_api_default_survive_in_season(client, tmp_path, query, selected, trade_count):
    # Mutation: apply the automatic default to explicit choices or other API callers.
    from tests.test_aggregations import _sample_entry

    entry = _sample_entry()
    entry.league_phase = {"phase": "regular", "season": 2026, "week": 5}
    ChainCache(cache_dir=tmp_path).write("L_current", entry)
    with patch("app.routes.league._cache_dir", return_value=tmp_path):
        resp = client.get(f"/api/league/L_current?{query}")
    assert resp.status_code == 200
    assert resp.json()["selected_year"] == selected
    assert resp.json()["total_trades"] == trade_count
