"""Additive migration and source-observation fencing against real disposable PG."""
import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from app.db.base import Base
from app.services.generation.models import LeagueSeason, ProviderAttempt
from app.services.generation.recap_models import RecapEpisode, RecapObservation
from app.services.recap_video.contracts import EpisodeKey
from app.services.recap_video.readiness import observe_period
from tests.test_generation_gateway import seed_job
from tests.test_generation_postgres import pgmaker  # noqa: F401
from tests.test_recap_readiness import snapshot


@pytest.mark.asyncio
async def test_workflow_migration_preserves_receipts_and_registered_schema(pgmaker, monkeypatch):
    async with pgmaker.kw["bind"].begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    monkeypatch.setenv("TRADE_GRADER_DATABASE_URL", pgmaker.kw["bind"].url.render_as_string(hide_password=False))
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "migrations"))
    await asyncio.to_thread(command.upgrade, config, "0012_recap_budget_ledger")
    async with pgmaker.begin() as db:
        db.add(ProviderAttempt(id="historic", operation_id="historic", stage=1, generation=1,
            request_digest="historic", request_json="{}", model="synthetic", state="unknown"))
    await asyncio.to_thread(command.upgrade, config, "head")
    async with pgmaker() as db:
        assert (await db.get(ProviderAttempt, "historic")).state == "unknown"
        assert not list((await db.scalars(select(RecapEpisode))).all())
        assert not list((await db.scalars(select(RecapObservation))).all())
    await asyncio.to_thread(command.downgrade, config, "0012_recap_budget_ledger")
    await asyncio.to_thread(command.upgrade, config, "head")
    async with pgmaker() as db:
        assert (await db.get(ProviderAttempt, "historic")).state == "unknown"


@pytest.mark.asyncio
async def test_concurrent_observers_preserve_every_snapshot_and_single_identity(pgmaker):
    # Removing lock_control creates duplicate episode inserts under concurrency.
    await seed_job(pgmaker)
    async with pgmaker.begin() as db:
        (await db.get(LeagueSeason, "synthetic")).latest_week = 4
    async def observe():
        async with pgmaker.begin() as db:
            ident = await observe_period(db, EpisodeKey("series", 2026, "4"), snapshot(), 1000)
            await asyncio.sleep(.01)
            return ident
    ids = await asyncio.gather(*(observe() for _ in range(8)))
    assert len(set(ids)) == 1
    async with pgmaker() as db:
        assert len(list((await db.scalars(select(RecapEpisode))).all())) == 1
        assert len(list((await db.scalars(select(RecapObservation))).all())) == 8
