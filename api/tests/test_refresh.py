"""Refresh execution belongs to the worker, independent of browser observers."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services.chain_cache import ChainCache
from app.services.generation.models import GenerationOperation
from app.services.generation.worker import Worker

from tests.test_generation_gateway import seed_job
from tests.test_refresh_service import _entry


@pytest.mark.asyncio
async def test_worker_refresh_persists_progress_and_cache(maker, tmp_path, monkeypatch):
    await seed_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.kind, job.state, job.actor_kind = "refresh", "queued", "member"
    entry = _entry(league_id="synthetic", chain=[{"league_id": "synthetic", "season": 2026,
        "format_verified": True}], league_season_by_id={"synthetic": 2026})
    async def grade(self, *, progress_cb, **kwargs):
        assert kwargs["force"] is False
        await progress_cb("chain", "Walking")
        return entry
    client = SimpleNamespace(close=AsyncMock())
    connected = AsyncMock(return_value=client)
    monkeypatch.setattr("app.services.platform_client.connected_client", connected)
    monkeypatch.setattr("app.services.grader.GraderService.run", grade)
    monkeypatch.setattr("app.services.analyst.generate_analyst", AsyncMock())
    monkeypatch.setattr("app.services.player_context.collect_player_news", AsyncMock())
    await Worker(maker, tmp_path).tick()
    assert ChainCache(tmp_path).read("synthetic") is not None
    client.close.assert_awaited_once()
    assert connected.call_args.kwargs["user_id"] == "owner"
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.state == "succeeded"
        assert json.loads(job.progress_json)["stage"] == "done"


@pytest.mark.asyncio
async def test_provider_limit_is_saved_without_private_exception(maker, tmp_path, monkeypatch):
    from sleeper_dynasty.api.yahoo import YahooRateLimitError
    await seed_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.kind, job.state = "refresh", "queued"
    monkeypatch.setattr(Worker, "refresh", AsyncMock(side_effect=YahooRateLimitError("private upstream details")))
    await Worker(maker, tmp_path).tick()
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
        assert job.reason == "yahoo_rate_limited"
        assert "private" not in job.progress_json


@pytest.mark.asyncio
async def test_revoked_manual_yahoo_actor_never_uses_another_member(maker, tmp_path, monkeypatch):
    from app.db.models import LeagueMembership, User, YahooConnection, YahooLeagueGrant
    from app.services.generation.models import stamp
    await seed_job(maker)
    lid = "470.l.100000001"
    async with maker.begin() as db:
        db.add(User(id="other", google_sub="other", email="other@test.local"))
        for uid, generation in (("owner", "reconnected"), ("other", "current")):
            db.add(LeagueMembership(user_id=uid, league_id=lid))
            db.add(YahooConnection(user_id=uid, generation=generation, status="connected", sealed_tokens="synthetic", expires_at=stamp()+1000))
            db.add(YahooLeagueGrant(user_id=uid, league_id=lid, generation=generation, expires_at=stamp()+1000))
        job = await db.get(GenerationOperation, "job")
        job.kind, job.state, job.league_id, job.connection_generation = "refresh", "queued", lid, "old-generation"
    client = AsyncMock()
    monkeypatch.setattr("app.services.platform_client.connected_client", client)
    await Worker(maker, tmp_path).tick()
    client.assert_not_awaited()
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).reason == "provider_grant_changed"
