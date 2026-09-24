import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.player_context import collect_player_news, load_player_context
from app.services.player_context_store import PlayerContextStore
from sleeper_dynasty.api.player_context import SourceUnavailable

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


def league():
    return SimpleNamespace(get_nfl_state=AsyncMock(return_value={"season": "2026", "season_type": "regular", "week": 3}),
                           get_rosters=AsyncMock(return_value=[SimpleNamespace(players=["test-qb", "test-wr"])]))


def news(text="Opening-drive injury"):
    return [{"source": "rotowire", "published": int(NOW.timestamp()*1000)-1000,
             "metadata": {"title": "Test QB update", "description": text, "topic_id": "synthetic"}}]


@pytest.mark.asyncio
async def test_collection_persists_reuses_across_leagues_and_preserves_original(tmp_path):
    # Mutation: replace prior observations or key public news by fantasy league.
    source = SimpleNamespace(news=AsyncMock(return_value={"test-qb": news(), "test-wr": []}))
    await collect_player_news(league(), "test-league", tmp_path, now=NOW, source=source)
    await collect_player_news(league(), "another-league", tmp_path, now=NOW, source=source)
    assert source.news.await_count == 1
    store = PlayerContextStore(tmp_path)
    first = store.read("news:2026:test-qb")
    assert first["items"][0]["text"] == "Opening-drive injury"
    source.news.return_value["test-qb"] = news("Later updated prognosis")
    await collect_player_news(league(), "test-league", tmp_path, now=NOW.replace(hour=19), source=source)
    saved = PlayerContextStore(tmp_path).read("news:2026:test-qb")
    assert {n["text"] for n in saved["items"]} == {"Opening-drive injury", "Later updated prognosis"}
    assert saved["items"][0]["observed_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_failure_backoff_stops_calls_for_other_leagues_and_preserves_evidence(tmp_path):
    # Mutation: retry a provider outage for every player/league or erase old data.
    source = SimpleNamespace(news=AsyncMock(return_value={"test-qb": news(), "test-wr": []}))
    await collect_player_news(league(), "a", tmp_path, now=NOW, source=source)
    source.news.side_effect = SourceUnavailable("HTTP 429", retry_after=1800)
    later = NOW.replace(hour=19)
    await collect_player_news(league(), "a", tmp_path, now=later, source=source)
    await collect_player_news(league(), "b", tmp_path, now=later, source=source)
    assert source.news.await_count == 2
    store = PlayerContextStore(tmp_path)
    assert store.read("news:2026:test-qb")["items"][0]["text"] == "Opening-drive injury"
    assert "429" in store.read("news-provider")["error"]


def test_store_claim_and_cache_invalidation_preserve_observations(tmp_path):
    # Mutation: put durable observations among FileCache's invalidated root files.
    from sleeper_dynasty.cache import FileCache
    store = PlayerContextStore(tmp_path)
    store.write("news:2026:test-qb", {"items": [{"text": "saved"}]})
    with store.claim() as first:
        with PlayerContextStore(tmp_path).claim() as second:
            assert first is True
            assert second is False
    FileCache(tmp_path).invalidate_all()
    assert PlayerContextStore(tmp_path).read("news:2026:test-qb")["items"] == [{"text": "saved"}]


@pytest.mark.asyncio
async def test_observation_and_backoff_use_response_time_not_collection_start(tmp_path):
    # Mutation: stamp a post-kickoff response with the pre-kickoff start time.
    current = NOW

    async def receive(_):
        nonlocal current
        current += timedelta(seconds=30)
        return {"test-qb": news(), "test-wr": []}

    source = SimpleNamespace(news=AsyncMock(side_effect=receive))
    await collect_player_news(league(), "test-league", tmp_path, clock=lambda: current, source=source)
    saved = PlayerContextStore(tmp_path).read("news:2026:test-qb")
    assert saved["items"][0]["observed_at"] == current.isoformat()
    assert saved["fetched_at"] == current.isoformat()
    assert saved["retry_at"] == current.timestamp() + 6 * 3600

    current += timedelta(hours=7)

    async def refuse(_):
        nonlocal current
        current += timedelta(seconds=30)
        raise SourceUnavailable("HTTP 429", retry_after=1800)

    source.news.side_effect = refuse
    await collect_player_news(league(), "test-league", tmp_path, clock=lambda: current, source=source)
    assert PlayerContextStore(tmp_path).read("news-provider")["retry_at"] == current.timestamp() + 1800


@pytest.mark.asyncio
async def test_concurrent_leagues_share_csv_failure_backoff(tmp_path):
    # Mutation: omit the per-resource claim; both leagues issue an outage call.
    async def fail(resource, season):
        await asyncio.sleep(0)
        raise SourceUnavailable("HTTP 429", retry_after=1800)

    source = SimpleNamespace(csv_rows=AsyncMock(side_effect=fail))
    await asyncio.gather(*[
        load_player_context(tmp_path, 2026, 2, [], {}, now=NOW, source=source) for _ in range(2)
    ])
    assert source.csv_rows.await_count == 3
    await load_player_context(tmp_path, 2026, 2, [], {}, now=NOW, source=source)
    assert source.csv_rows.await_count == 3
