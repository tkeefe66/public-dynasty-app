import asyncio
from pathlib import Path

from app.services.chain_cache import ChainCacheEntry
from app.services.refresh_service import (
    known_league_ids,
    refresh_all_known,
)


def _entry(**over):
    base = dict(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"uA": {"owner_name": "Alice"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="2026-01-01",
    )
    base.update(over)
    return ChainCacheEntry(**base)


def test_known_league_ids_parses_chain_files(tmp_path: Path):
    (tmp_path / "chain_111.json").write_text("{}")
    (tmp_path / "chain_222.json").write_text("{}")
    (tmp_path / "players_nfl.json").write_text("{}")  # non-matching, ignored
    assert known_league_ids(tmp_path) == ["111", "222"]


def test_known_league_ids_empty(tmp_path: Path):
    assert known_league_ids(tmp_path) == []


def test_refresh_all_known_isolates_per_league_errors(tmp_path: Path):
    (tmp_path / "chain_111.json").write_text("{}")
    (tmp_path / "chain_222.json").write_text("{}")
    calls: list[str] = []

    async def fake_refresh(client, lid, *, cache_dir, force=False, progress_cb=None):
        calls.append(lid)
        if lid == "111":
            raise RuntimeError("boom")

    class FakeClient:
        async def close(self):
            return None

    asyncio.run(refresh_all_known(
        tmp_path, _refresh_league=fake_refresh, _client_factory=FakeClient))

    # Both attempted; 111 raised but 222 still ran (error isolation).
    assert calls == ["111", "222"]


def test_refresh_all_known_noop_when_no_leagues(tmp_path: Path):
    created = []

    class FakeClient:
        def __init__(self):
            created.append(1)

        async def close(self):
            return None

    asyncio.run(refresh_all_known(tmp_path, _client_factory=FakeClient))
    assert created == []  # no client created when there's nothing to refresh


def test_scheduler_does_not_send_yahoo_league_to_public_sleeper_client(tmp_path, monkeypatch):
    # Mutation: one shared Sleeper client bypasses platform routing for Yahoo.
    from unittest.mock import AsyncMock
    (tmp_path/'chain_470.l.100000001.json').write_text('{}')
    refresh=AsyncMock()
    monkeypatch.setenv('YAHOO_DEV_ACCESS_TOKEN','not-an-account-connection')
    asyncio.run(refresh_all_known(tmp_path,_refresh_league=refresh))
    refresh.assert_not_awaited()


def test_scheduler_cleanup_failure_does_not_block_next_league(tmp_path):
    # Regression: exceptions in finally escaped the per-league failure boundary.
    (tmp_path/'chain_111.json').write_text('{}')
    (tmp_path/'chain_222.json').write_text('{}')
    calls=[]
    class Client:
        async def close(self):raise RuntimeError('cleanup failed')
    async def refresh(client,lid,**kwargs):calls.append(lid)
    asyncio.run(refresh_all_known(tmp_path,_refresh_league=refresh,_client_factory=Client))
    assert calls==['111','222']


def test_refresh_collects_news_even_when_llm_budget_exhausted(tmp_path, monkeypatch):
    # Mutation: put news collection inside the budget-gated recap writer path.
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services.player_context_store import PlayerContextStore
    from app.services.refresh_service import refresh_league

    from sleeper_dynasty.api.player_context import PlayerContextClient
    entry = _entry()
    monkeypatch.setattr("app.services.refresh_service.GraderService.run", AsyncMock(return_value=entry))
    monkeypatch.setattr("app.services.refresh_service._llm_over_budget", AsyncMock(return_value=True))
    now_ms = int(datetime.now(timezone.utc).timestamp()*1000)
    monkeypatch.setattr(PlayerContextClient, "news", AsyncMock(return_value={"test-qb": [
        {"source": "rotowire", "published": now_ms, "metadata": {"title": "Injury exit", "description": "Three snaps."}}]}))
    platform = SimpleNamespace(get_nfl_state=AsyncMock(return_value={"season": "2026", "season_type": "regular", "week": 3}),
                               get_rosters=AsyncMock(return_value=[SimpleNamespace(players=["test-qb"])]))
    result = asyncio.run(refresh_league(platform, "L", cache_dir=tmp_path))
    saved = PlayerContextStore(tmp_path).read("news:2026:test-qb")
    assert saved is not None
    assert saved["items"][0]["text"] == "Three snaps."
    assert result.league_id == "L"
