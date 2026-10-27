"""Yahoo recaps use the same private facts, authorization and archive pipeline."""
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from app.services.analyst_store import AnalystStore
from app.services.generation.models import (
    GenerationCandidate,
    GenerationOperation,
    LeagueSeason,
    LeagueSeries,
    ProviderAttempt,
)
from sqlalchemy import func, select

from tests.test_analyst import setup_league

YAHOO_ID = "999.l.100000001"
CAPABILITIES = {"format": "redraft", "future_picks": False,
                "roster_continuity": False, "multiyear_history": True}


def yahoo_fixture(monkeypatch):
    client, entry, writer = setup_league()
    entry.league_id = YAHOO_ID
    league, _ = client.get_league.return_value
    client.get_league.return_value = (replace(league, league_id=YAHOO_ID), None)
    monkeypatch.setattr("app.services.analyst.load_player_context", AsyncMock(return_value={}))
    monkeypatch.setattr("app.services.analyst.load_bets_snapshot", AsyncMock(return_value={}))
    monkeypatch.setattr("app.services.analyst.upcoming_outlook", AsyncMock(return_value=None))
    return client, entry, writer


@pytest.mark.asyncio
async def test_yahoo_archive_reads_empty_and_saved_editions(maker, tmp_path, monkeypatch):
    # Mutation: reject valid dotted Yahoo keys and return 503 on every archive read.
    from app.routes.analyst import analyst_archive
    monkeypatch.setattr("app.routes.analyst.get_cache_dir", lambda: tmp_path)
    monkeypatch.setenv("TRADE_GRADER_RECAP_PUBLICATION_MODE", "legacy")
    async with maker() as db:
        assert await analyst_archive(YAHOO_ID, db) == {"editions": []}
        AnalystStore(tmp_path).save(YAHOO_ID, {
            "season": 2026, "week": 1, "league_name": "Yahoo test",
            "generated_at": "2026-09-15T12:00:00+00:00", "model": "reviewed",
            "markdown": "Reviewed saved recap", "facts": {},
        })
        result = await analyst_archive(YAHOO_ID, db)
    assert result["editions"][0]["markdown"] == "Reviewed saved recap"


@pytest.mark.parametrize("league_id", ["..", "../league", "999.l.1/../../x", "999..l.1", "/tmp/x", "999.l.x"])
def test_yahoo_archive_path_does_not_accept_arbitrary_dots(tmp_path, league_id):
    # Mutation: allow every dotted string to fix Yahoo and introduce traversal paths.
    with pytest.raises(ValueError, match="Invalid league identifier"):
        AnalystStore(tmp_path).league_dir(league_id)


@pytest.mark.asyncio
async def test_yahoo_completed_week_stages_facts_and_candidate_without_paid_calls(maker, tmp_path, monkeypatch):
    # Mutation: skip Yahoo in either generation or candidate collection.
    from app.services.analyst import generate_analyst
    from app.services.generation.planner import collect_analyst
    client, entry, writer = yahoo_fixture(monkeypatch)
    async with maker.begin() as db:
        db.add(LeagueSeries(id="series", lifecycle="active", profile="redraft", hold="",
                            activated_at=1, activation_week=0))
        db.add(LeagueSeason(league_id=YAHOO_ID, provider="yahoo", provider_key=YAHOO_ID,
                           series_id="series", season=2026, latest_week=1,
                           capabilities_json=json.dumps(CAPABILITIES), verified_at=1))
    await generate_analyst(client, entry, tmp_path, skip_llm=True, writer=writer)
    saved = AnalystStore(tmp_path).editions(YAHOO_ID)
    assert [(e["week"], e["edition_type"]) for e in saved] == [(1, "results")]
    assert saved[0]["facts"]["matchups"][0]["winner_points"] == 25
    async with maker.begin() as db:
        await collect_analyst(db, YAHOO_ID, "series", tmp_path)
        candidates = (await db.scalars(select(GenerationCandidate))).all()
        assert len(candidates) == 1
        assert candidates[0].feature == "analyst" and candidates[0].hold == ""
        assert json.loads(candidates[0].payload_json)["facts"] == saved[0]["facts"]
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
    assert AnalystStore(tmp_path).published_editions(YAHOO_ID) == []
    writer.write.assert_not_called()


@pytest.mark.asyncio
async def test_partial_yahoo_week_cannot_be_staged_as_complete(tmp_path, monkeypatch):
    # Mutation: accept one side of a Yahoo matchup as a complete weekly recap.
    from app.services.analyst import generate_analyst
    from app.services.generation.readiness import ResultsNotReady
    client, entry, writer = yahoo_fixture(monkeypatch)
    client.get_matchup_results.return_value = client.get_matchup_results.return_value[:1]
    @asynccontextmanager
    async def fence():
        yield None
    with pytest.raises(ResultsNotReady, match="Week 1 results are incomplete"):
        await generate_analyst(client, entry, tmp_path, skip_llm=True, publication_fence=fence)
    assert AnalystStore(tmp_path).editions(YAHOO_ID) == []
    writer.write.assert_not_called()


@pytest.mark.asyncio
async def test_yahoo_rate_limit_reaches_durable_worker_backoff(tmp_path, monkeypatch):
    # Mutation: swallow Yahoo throttling and mark the free refresh succeeded.
    from app.services.analyst import generate_analyst

    from sleeper_dynasty.api.yahoo import YahooRateLimitError
    client, entry, _ = yahoo_fixture(monkeypatch)
    client.get_matchup_results.side_effect = YahooRateLimitError("Retry later", retry_after=600)
    @asynccontextmanager
    async def fence():
        yield None
    with pytest.raises(YahooRateLimitError) as error:
        await generate_analyst(client, entry, tmp_path, skip_llm=True, publication_fence=fence)
    assert error.value.retry_after == 600


@pytest.mark.asyncio
async def test_yahoo_lookahead_throttle_does_not_retry_same_week_immediately(tmp_path, monkeypatch):
    # Mutation: swallow a lookahead throttle, then fetch the same week again in the loop.
    from app.services.analyst import generate_analyst

    from sleeper_dynasty.api.yahoo import YahooRateLimitError
    client, entry, _ = yahoo_fixture(monkeypatch)
    client.get_nfl_state.return_value["week"] = 3
    first = client.get_matchup_results.return_value
    client.get_matchup_results.side_effect = [first, YahooRateLimitError("Retry later", retry_after=600), first]
    @asynccontextmanager
    async def fence():
        yield None
    with pytest.raises(YahooRateLimitError):
        await generate_analyst(client, entry, tmp_path, skip_llm=True, publication_fence=fence)
    assert client.get_matchup_results.await_count == 2


@pytest.mark.asyncio
async def test_scheduler_enqueues_yahoo_only_with_current_connected_grant(maker):
    # Mutation: blanket-skip Yahoo or schedule with a stale/disconnected account.
    from app.db.models import LeagueMembership, User, YahooConnection, YahooLeagueGrant
    from app.services.generation.scheduler import enqueue_members
    async with maker.begin() as db:
        for uid, lid, status, generation in [
            ("connected", YAHOO_ID, "connected", "current"),
            ("stale", "999.l.100000002", "connected", "old"),
            ("disconnected", "999.l.100000003", "disconnected", "current"),
        ]:
            db.add(User(id=uid, google_sub=uid, email=f"{uid}@test.local"))
            db.add(LeagueMembership(user_id=uid, league_id=lid))
            db.add(YahooConnection(user_id=uid, generation="current", sealed_tokens="fixture",
                                   expires_at=1, status=status))
            db.add(YahooLeagueGrant(user_id=uid, league_id=lid, generation=generation, expires_at=1))
    await enqueue_members(kind="analyst_refresh", maker=maker)
    await enqueue_members(kind="analyst_refresh", maker=maker)
    async with maker() as db:
        jobs = (await db.scalars(select(GenerationOperation))).all()
        assert [(j.league_id, j.kind, j.actor_id, j.connection_generation) for j in jobs] == [
            (YAHOO_ID, "analyst_refresh", "connected", "current")]
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0


def test_yahoo_supports_text_recap_but_not_sleeper_video_workflow():
    # Mutation: retain the blanket Analyst exclusion or enable unsupported Yahoo video.
    from app.services.generation.policy import supports_feature
    assert supports_feature(CAPABILITIES, "yahoo", "analyst")
    assert not supports_feature(CAPABILITIES, "yahoo", "recap_video")
