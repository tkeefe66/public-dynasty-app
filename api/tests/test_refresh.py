import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.chain_cache import ChainCacheEntry


def _fake_entry(league_id: str) -> ChainCacheEntry:
    return ChainCacheEntry(
        league_id=league_id, chain=[],
        resolved_trades=[], grades={},
        owners={}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={},
        league_season_by_id={}, cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )


def test_refresh_streams_events(client, tmp_path):
    async def fake_run(self, *, client, current_league_id, progress_cb,
                       _build_trade_history=None, _pull_supporting_data=None, **kwargs):
        await progress_cb("chain", "Walking")
        await progress_cb("done", "All set")
        return _fake_entry(current_league_id)

    with patch("app.routes.refresh._cache_dir", return_value=tmp_path), \
         patch("app.services.refresh_service.GraderService.run", new=fake_run):
        with client.stream("GET", "/api/league/L_new/refresh") as resp:
            assert resp.status_code == 200
            chunks = []
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    chunks.append(json.loads(line[5:].strip()))
    stages = [c["stage"] for c in chunks]
    assert "chain" in stages
    assert "done" in stages


def test_refresh_writes_cache_on_completion(client, tmp_path):
    async def fake_run(self, *, client, current_league_id, progress_cb,
                       _build_trade_history=None, _pull_supporting_data=None, **kwargs):
        await progress_cb("done", "done")
        return _fake_entry(current_league_id)

    with patch("app.routes.refresh._cache_dir", return_value=tmp_path), \
         patch("app.services.refresh_service.GraderService.run", new=fake_run):
        with client.stream("GET", "/api/league/L_new/refresh") as resp:
            list(resp.iter_lines())
    cache_file = tmp_path / "chain_L_new.json"
    assert cache_file.exists()


def test_refresh_passes_force_to_grader(client, tmp_path):
    captured = {}

    async def fake_run(self, *, client, current_league_id, progress_cb,
                       cache_dir=None, force=False, **kwargs):
        captured["force"] = force
        captured["cache_dir"] = cache_dir
        await progress_cb("done", "ok")
        return _fake_entry(current_league_id)

    with patch("app.routes.refresh._cache_dir", return_value=tmp_path), \
         patch("app.services.refresh_service.GraderService.run", new=fake_run):
        with client.stream("GET", "/api/league/L1/refresh?force=1") as r:
            for _ in r.iter_lines():
                pass
    assert captured["force"] is True
    assert captured["cache_dir"] is not None
