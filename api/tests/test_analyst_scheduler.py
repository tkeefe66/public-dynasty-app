import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from tests.test_analyst import setup_league


@pytest.mark.asyncio
async def test_failed_generation_backoff_survives_restart_and_resets_for_new_week(tmp_path, monkeypatch):
    # Mutation: retry on every refresh, forget retries on restart, or block a new week's first attempt.
    from app.services import analyst
    from app.services.analyst_store import AnalystStore
    monkeypatch.setattr(analyst, "load_player_context", AsyncMock(return_value={}))
    monkeypatch.setattr(analyst, "load_bets_snapshot", AsyncMock(return_value={}))
    client, entry, writer = setup_league()
    writer.write.side_effect = ValueError("Provider refused review")
    now = datetime(2026, 9, 15, 8, tzinfo=timezone.utc)
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now)
    assert writer.write.call_count == 1
    writer.write.side_effect = None
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now + timedelta(minutes=29))
    assert AnalystStore(tmp_path).editions("123") == []
    assert writer.write.call_count == 1
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now + timedelta(minutes=30))
    assert [e["week"] for e in AnalystStore(tmp_path).editions("123")] == [1]
    client.get_nfl_state.return_value["week"] = 3
    results = client.get_matchup_results.return_value
    client.get_matchup_results.side_effect = lambda lid, week: [replace(r, week=week) for r in results]
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now + timedelta(minutes=31))
    assert [e["week"] for e in AnalystStore(tmp_path).editions("123")] == [2, 1]
    assert writer.write.call_count == 3


@pytest.mark.asyncio
async def test_scheduler_publishes_without_chain_cache_or_grader(tmp_path, monkeypatch):
    # Mutation: continue requiring a full grader refresh before a missing edition can be saved.
    from app.services import analyst, analyst_scheduler
    from app.services.analyst_store import AnalystStore
    from app.services import refresh_service
    client, _, writer = setup_league()
    client.close = AsyncMock()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(analyst, "RecapWriter", lambda **kw: writer)
    monkeypatch.setattr(analyst, "load_player_context", AsyncMock(return_value={}))
    monkeypatch.setattr(analyst, "load_bets_snapshot", AsyncMock(return_value={}))
    monkeypatch.setattr(refresh_service, "_llm_over_budget", AsyncMock(return_value=False))
    monkeypatch.setattr(analyst_scheduler, "_member_league_ids", AsyncMock(return_value=["123", "470.l.123"]))
    monkeypatch.setattr(analyst_scheduler, "SleeperClient", lambda: client)
    monkeypatch.setattr(refresh_service.GraderService, "run", AsyncMock(side_effect=AssertionError("Grader must not run")))
    await analyst_scheduler.generate_member_editions(tmp_path)
    assert AnalystStore(tmp_path).editions("123")[0]["markdown"] == "## Week one\nAlice wins."
    assert not (tmp_path / "chain_123.json").exists()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_checks_again_in_fifteen_minutes_after_failure(tmp_path, monkeypatch):
    # Mutation: a failing cycle kills the loop or it waits for the three-hour grader interval.
    from app.services import analyst_scheduler
    delays = []
    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 3:
            raise asyncio.CancelledError
    cycle = AsyncMock(side_effect=[RuntimeError("Temporary DB failure"), None])
    monkeypatch.setattr(analyst_scheduler, "generate_member_editions", cycle)
    monkeypatch.setattr(analyst_scheduler.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await analyst_scheduler.analyst_loop(tmp_path)
    assert delays == [2, 900, 900]
    assert cycle.await_count == 2


def test_retry_delays_escalate_and_cap_at_six_hours(tmp_path):
    # Mutation: use a fixed short delay and pay for failures four times every hour indefinitely.
    from app.services.analyst_store import AnalystStore
    stamp = 1_800_000_000.0
    for delay in (1800, 3600, 10800, 21600, 21600):
        store = AnalystStore(tmp_path)
        with store.claim("123"):
            assert store.start_attempt("123", 2026, 1, stamp)
            assert not store.start_attempt("123", 2026, 1, stamp + delay - 1)
        stamp += delay


@pytest.mark.asyncio
async def test_app_starts_and_stops_analyst_scheduler(tmp_path, monkeypatch):
    # Mutation: ship a working scheduler that the application never starts.
    import app.main as main
    from app.config import Settings
    started = asyncio.Event()
    stopped = asyncio.Event()
    async def loop(cache_dir):
        assert cache_dir == tmp_path
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    monkeypatch.setattr(main, "get_settings", lambda: Settings(cache_dir=tmp_path, auto_refresh=True))
    monkeypatch.setattr(main, "init_engine", lambda: None)
    monkeypatch.setattr(main, "dispose_engine", AsyncMock())
    monkeypatch.setattr(main, "auto_refresh_loop", AsyncMock())
    monkeypatch.setattr(main, "analyst_loop", loop)
    app = main.create_app()
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(started.wait(), timeout=1)
    assert stopped.is_set()
