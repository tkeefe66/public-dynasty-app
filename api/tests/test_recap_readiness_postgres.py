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
        # Seed the historical schema, not today's ORM (provider/account arrived later).
        await db.execute(text("INSERT INTO provider_attempts (id,operation_id,stage,generation,request_digest,request_json,model,state,usage_state,usage_json,pricing_json,provider_request_id,error_code,created_at,settled_at) VALUES ('historic','historic',1,1,'historic','{}','synthetic','unknown','unknown','{}','{}','','',1,0)"))
    # Round-trip only this reversible migration; later authority migrations
    # deliberately forbid downgrade and must never be bypassed by this fixture.
    await asyncio.to_thread(command.upgrade, config, "0013_recap_workflow")
    await asyncio.to_thread(command.downgrade, config, "0012_recap_budget_ledger")
    await asyncio.to_thread(command.upgrade, config, "head")
    async with pgmaker() as db:
        receipt = await db.get(ProviderAttempt, "historic")
        assert (receipt.state, receipt.usage_state, receipt.request_digest, receipt.request_json,
            receipt.usage_json, receipt.pricing_json, receipt.created_at, receipt.settled_at) == (
            'unknown', 'unknown', 'historic', '{}', '{}', '{}', 1, 0)
        assert receipt.provider == 'anthropic' and receipt.account_key == 'primary'
        assert not list((await db.scalars(select(RecapEpisode))).all())
        assert not list((await db.scalars(select(RecapObservation))).all())
    with pytest.raises(RuntimeError, match='archival review'):
        await asyncio.to_thread(command.downgrade, config, "0012_recap_budget_ledger")
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
