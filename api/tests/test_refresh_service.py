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
