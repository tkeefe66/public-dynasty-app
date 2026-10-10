"""Real database serialization, never use a production database."""
import asyncio

import pytest

from app.services.generation import recap_budget as budget
from app.services.generation.store import Held, lock_control
from tests.test_generation_postgres import pgmaker  # noqa: F401
from tests.test_recap_budget_ledger import NOW, allocation, seed


@pytest.fixture(autouse=True)
def owner_allowlist(monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "owner@test.local")


@pytest.mark.asyncio
async def test_last_allowance_race_has_one_winner(pgmaker):
    # Mutation: remove global admission lock; concurrent transactions overspend.
    await seed(pgmaker)
    async with pgmaker.begin() as db:
        await lock_control(db)
    async def reserve(i):
        try:
            async with pgmaker.begin() as db:
                await budget.reserve_plan(db, "episode", "series", str(i), [allocation()], NOW)
                await asyncio.sleep(0.02)
            return "admitted"
        except Held:
            return "held"
    results = await asyncio.gather(*(reserve(i) for i in range(8)))
    assert results.count("admitted") == 1
    assert results.count("held") == 7


@pytest.mark.asyncio
async def test_cap_change_commits_before_waiting_admission(pgmaker):
    # Mutation: cap writes and admission acquire different serialization locks.
    await seed(pgmaker)
    async def reserve():
        async with pgmaker.begin() as db:
            await budget.reserve_plan(db, "episode", "series", "waiting", [allocation()], NOW)
    async with pgmaker.begin() as db:
        await budget.save_caps(db, "series", budget.RecapCaps(video_episode_microusd=1_000_000), 0, "owner", "Lower", False)
        waiting = asyncio.create_task(reserve())
        await asyncio.sleep(0.05)
        assert not waiting.done()
    with pytest.raises(Held, match="video_episode"):
        await waiting


@pytest.mark.asyncio
async def test_unrelated_managed_work_shares_last_app_allowance(pgmaker):
    # Mutation: gateway checks known spend only and ignores other series reservations.
    from app.repositories.app_settings import set_monthly_budget
    from app.db.models import LeagueMembership
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import GenerationOperation, GenerationPolicy, LeagueSeason, LeagueSeries
    from app.services.generation.store import data, dump
    from tests.test_generation_gateway import REQUEST, FakeTransport, seed_job
    await seed_job(pgmaker)
    async with pgmaker.begin() as db:
        await set_monthly_budget(db, 0.1)
        (await db.get(GenerationPolicy, "app")).value_json = dump({"paused": False, "max_concurrency": 4})
        from app.services.generation.provider_control import account_control
        (await account_control(db, "anthropic", "primary")).max_concurrency = 4
        original = await db.get(GenerationOperation, "job")
        db.add(LeagueSeries(id="other-series", lifecycle="active", hold=""))
        db.add(LeagueMembership(user_id="owner", league_id="other"))
        season = await db.get(LeagueSeason, "synthetic")
        db.add(LeagueSeason(**{**data(season), "league_id": "other", "provider_key": "other", "series_id": "other-series"}))
        db.add(GenerationOperation(**{**data(original), "id": "other-job", "series_id": "other-series", "league_id": "other"}))
    transport = FakeTransport(blocked=True)
    first = asyncio.create_task(Gateway(pgmaker, transport, epoch="test-epoch").invoke("job", 1, 1, REQUEST))
    await transport.started.wait()
    try:
        with pytest.raises(Held, match="legacy_budget_reached"):
            await Gateway(pgmaker, transport, epoch="test-epoch").invoke("other-job", 1, 1, REQUEST)
    finally:
        transport.release.set()
        await first
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_ledger_migration_roundtrip_preserves_existing_policy_and_receipts(pgmaker, monkeypatch):
    # Mutation: rewrite applied 0011 or modify historic receipts when adding obligations.
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from app.db.base import Base
    from app.services.generation.models import ProviderAttempt
    from app.services.generation.recap_models import RecapBudgetPolicy
    from app.services.generation.store import dump
    from sqlalchemy import text, select
    async with pgmaker.kw["bind"].begin() as db:
        await db.run_sync(Base.metadata.drop_all)
        await db.execute(text("DROP TABLE IF EXISTS alembic_version"))
    monkeypatch.setenv("TRADE_GRADER_DATABASE_URL", pgmaker.kw["bind"].url.render_as_string(hide_password=False))
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "migrations"))
    await asyncio.to_thread(command.upgrade, config, "0011_recap_budget")
    async with pgmaker.begin() as db:
        db.add(RecapBudgetPolicy(series_id="series", caps_json=dump(budget.RecapCaps().model_dump())))
        # Historical schema intentionally predates provider/account columns. Use
        # its persisted shape rather than today's expanded ORM mapping.
        await db.execute(text("""INSERT INTO provider_attempts
            (id, operation_id, stage, generation, request_digest, request_json, model,
             state, usage_state, receipt_json, usage_json, pricing_json, cost_microusd,
             provider_request_id, status_code, error_code, created_at, settled_at)
            VALUES ('synthetic-old', 'old', 1, 1, 'old', '{}', 'unknown', 'unknown',
                    'unknown', NULL, '{}', '{}', NULL, '', NULL, '', 123, 0)"""))
    async with pgmaker() as db:
        before = {table: (await db.execute(text(f"SELECT * FROM {table}"))).all()
                  for table in ("recap_budget_policies", "provider_attempts")}
    await asyncio.to_thread(command.upgrade, config, "0012_recap_budget_ledger")
    await asyncio.to_thread(command.downgrade, config, "0011_recap_budget")
    await asyncio.to_thread(command.upgrade, config, "0012_recap_budget_ledger")
    async with pgmaker() as db:
        for table, records in before.items():
            assert (await db.execute(text(f"SELECT * FROM {table}"))).all() == records
        assert (await db.execute(select(RecapBudgetPolicy))).scalar_one().series_id == "series"


@pytest.mark.asyncio
async def test_complete_video_envelopes_compete_for_month_before_any_script(pgmaker, tmp_path, monkeypatch):
    # Mutation: monthly admission omits the future narration envelope or loses its serialization lock.
    from tests.test_recap_video_script import seed as seed_script
    from app.services.generation.models import GenerationOperation
    from app.services.generation.accounting import bounded_plan
    from app.services.recap_video.narration_budget import envelope_allocation
    import json
    await seed_script(pgmaker, tmp_path, monkeypatch)
    async with pgmaker.begin() as db:
        await budget.save_caps(db, 'series', budget.RecapCaps(video_month_microusd=4_900_000), 0, 'owner', 'Two script plans fit, two complete video plans do not', False)
        job = await db.get(GenerationOperation, 'job')
        feature = json.loads(job.policy_json)['policy']['features']['recap_video']
        plan = bounded_plan(job.id, job.feature, feature, feature, job.max_calls)
        plan.append(await envelope_allocation(db, job))
    async def reserve(index):
        try:
            async with pgmaker.begin() as db:
                await budget.reserve_plan(db, 'episode-'+str(index), 'series', 'complete-'+str(index), plan, NOW)
                await asyncio.sleep(.02)
            return 'admitted'
        except Held as exc:
            assert exc.code == 'recap_budget_video_month'
            return 'held'
    assert sorted(await asyncio.gather(reserve(1), reserve(2))) == ['admitted', 'held']
