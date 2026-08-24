import pytest

from app.services import refresh_service


@pytest.mark.asyncio
async def test_refresh_league_passes_cache_dir_for_reuse(monkeypatch, tmp_path):
    """refresh_league must invoke GraderService.run with the cache_dir so the
    incremental reuse path can engage."""
    seen = {}

    async def _fake_run(self, **kwargs):
        seen.update(kwargs)
        from app.services.chain_cache import ChainCacheEntry
        return ChainCacheEntry(
            league_id=kwargs["current_league_id"], chain=[], resolved_trades=[],
            grades={}, owners={}, playoff_weeks_by_league={},
            roster_to_user_by_league={}, league_name_by_id={},
            league_season_by_id={}, cached_at="")

    monkeypatch.setattr(
        "app.services.grader.GraderService.run", _fake_run)
    monkeypatch.setattr(
        refresh_service, "compute_season_ratings", lambda entry: {})

    class _Client:
        async def get_nfl_state(self):
            return {"season_type": "off", "week": 0}

    await refresh_service.refresh_league(
        _Client(), "L", cache_dir=tmp_path, force=False)

    assert seen["cache_dir"] == tmp_path
    assert seen["force"] is False
