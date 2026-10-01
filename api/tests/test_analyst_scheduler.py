import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from tests.test_analyst import setup_league


@pytest.mark.asyncio
async def test_results_survive_restart_and_do_not_block_next_weeks_roast(tmp_path, monkeypatch):
    # Mutation: replace results before cooldown, or permanently stop trying a full roast.
    from app.services import analyst
    from app.services.analyst_store import AnalystStore
    monkeypatch.setattr(analyst, "load_player_context", AsyncMock(return_value={}))
    monkeypatch.setattr(analyst, "load_bets_snapshot", AsyncMock(return_value={}))
    client, entry, writer = setup_league()
    writer.write.side_effect = ValueError("Provider refused review")
    now = datetime(2026, 9, 15, 8, tzinfo=UTC)
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now)
    assert writer.write.call_count == 1
    store = AnalystStore(tmp_path)
    assert store.editions("123")[0]["edition_type"] == "results"
    original = store.edition_path("123", 2026, 1).read_bytes()
    writer.write.side_effect = None
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now + timedelta(minutes=29))
    assert store.edition_path("123", 2026, 1).read_bytes() == original
    assert writer.write.call_count == 1
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now + timedelta(minutes=30))
    assert [e["week"] for e in AnalystStore(tmp_path).editions("123")] == [1]
    assert store.editions("123")[0]["edition_type"] == "roast"
    assert store.editions("123")[0]["revision"] == 2
    assert "Week 1 results" in store.editions("123")[0]["original_markdown"]
    assert store.edition_path("123", 2026, 1).read_bytes() == original
    client.get_nfl_state.return_value["week"] = 3
    results = client.get_matchup_results.return_value
    client.get_matchup_results.side_effect = lambda lid, week: [replace(r, week=week) for r in results]
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now + timedelta(minutes=31))
    assert [e["week"] for e in AnalystStore(tmp_path).editions("123")] == [2, 1]
    assert store.editions("123")[0]["edition_type"] == "roast"
    assert writer.write.call_count == 3


@pytest.mark.asyncio
async def test_failed_upgrade_preserves_results_without_spurious_revisions(tmp_path, monkeypatch):
    # Mutation: save another results revision on every failed paid retry.
    from app.services import analyst
    from app.services.analyst_store import AnalystStore
    monkeypatch.setattr(analyst, "load_player_context", AsyncMock(return_value={}))
    monkeypatch.setattr(analyst, "load_bets_snapshot", AsyncMock(return_value={}))
    client, entry, writer = setup_league()
    writer.write.side_effect = ValueError("Review rejected")
    now = datetime(2026, 9, 15, 8, tzinfo=UTC)
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now)
    store = AnalystStore(tmp_path)
    before = store.edition_path("123", 2026, 1).read_bytes()
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, now=now + timedelta(minutes=30))
    assert writer.write.call_count == 2
    assert store.editions("123")[0]["revision"] == 1
    assert store.edition_path("123", 2026, 1).read_bytes() == before


@pytest.mark.asyncio
async def test_upgrade_uses_archived_evidence_after_week_rollover(tmp_path, monkeypatch):
    # Mutation: replace a saved open bet/forecast/rank with current data during a roast upgrade.
    from app.services import analyst
    from app.services.analyst_store import AnalystStore
    monkeypatch.setattr(analyst, "load_player_context", AsyncMock(return_value={}))
    monkeypatch.setattr(analyst, "load_bets_snapshot", AsyncMock(return_value={}))
    client, entry, writer = setup_league()
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer, skip_llm=True)
    store = AnalystStore(tmp_path)
    original = store.editions("123")[0]
    original["facts"]["bets"] = {"available": True, "active": [{"stake": "$25", "terms": "Higher finish", "status": "open"}]}
    original["outlook"] = {"week": 2, "matchups": [{"home": "Alice", "away": "Bob", "home_projected": 30,
                          "away_projected": 20, "favorite": "Alice", "spread": 10}], "byes": [], "weather": [], "playoff_stakes": []}
    original["lore"] = "Original profiles"
    store.save_correction("123", original, "Add archived fixture context")
    client.get_nfl_state.return_value["week"] = 3
    results = client.get_matchup_results.return_value
    client.get_matchup_results.side_effect = lambda lid, week: [replace(r, week=week) for r in results]
    await analyst.generate_analyst(client, entry, tmp_path, writer=writer)
    written = writer.write.call_args_list[0]
    assert written.args[0].to_dict() == original["facts"]
    assert written.kwargs["outlook"].to_dict() == original["outlook"]
    assert written.kwargs["lore"] == "Original profiles"
    upgraded = next(e for e in store.editions("123") if e["week"] == 1)
    assert upgraded["facts"] == original["facts"]
    assert upgraded["outlook"] == original["outlook"]


@pytest.mark.asyncio
async def test_scheduler_submits_durable_free_check_without_grader(maker, tmp_path, monkeypatch):
    from app.db.models import LeagueMembership, User
    from app.services import analyst, analyst_scheduler, refresh_service
    from app.services.analyst_store import AnalystStore
    from app.services.generation.scheduler import enqueue_members
    from app.services.generation.worker import Worker
    client, _, writer = setup_league()
    client.close = AsyncMock()
    async with maker.begin() as db:
        db.add(User(id="member", google_sub="synthetic", email="member@test.local"))
        db.add(LeagueMembership(user_id="member", league_id="123"))
    monkeypatch.setattr("app.db.engine.get_sessionmaker", lambda: maker)
    monkeypatch.setattr("app.services.platform_client.connected_client", AsyncMock(return_value=client))
    monkeypatch.setattr(analyst, "load_player_context", AsyncMock(return_value={}))
    monkeypatch.setattr(analyst, "load_bets_snapshot", AsyncMock(return_value={}))
    monkeypatch.setattr(refresh_service.GraderService, "run", AsyncMock(side_effect=AssertionError("Grader must not run")))
    await analyst_scheduler.generate_member_editions(tmp_path)
    await enqueue_members(kind="analyst_refresh", maker=maker)
    assert AnalystStore(tmp_path).editions("123") == []
    worker = Worker(maker, tmp_path)
    assert await worker.tick()
    assert not await worker.tick()
    saved = AnalystStore(tmp_path).editions("123")[0]
    assert saved["edition_type"] == "results"
    assert "Alice 25.00, Bob 15.00" in saved["markdown"]
    writer.write.assert_not_called()
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
    from app import main
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
    monkeypatch.setattr(main, "worker_loop", AsyncMock())
    monkeypatch.setattr(main, "analyst_loop", loop)
    app = main.create_app()
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(started.wait(), timeout=1)
    assert stopped.is_set()
