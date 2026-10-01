"""Real PostgreSQL races. Requires a disposable *_tests database, never production."""
import asyncio
import os

import pytest
import pytest_asyncio
from app.db.base import Base
from app.services.generation.commands import claim_operation, submit_refresh
from app.services.generation.models import GenerationOperation
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def pgmaker():
    url = os.environ.get("GENERATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set GENERATION_TEST_DATABASE_URL to an isolated PostgreSQL *_tests database")
    parsed = make_url(url)
    if not parsed.drivername.startswith("postgresql") or not (parsed.database or "").endswith("_tests"):
        pytest.fail("Concurrency tests require a disposable PostgreSQL database ending in _tests")
    engine = create_async_engine(url, pool_size=16, max_overflow=0)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_submission_and_claim_has_one_winner(pgmaker):
    """Removing the DB gate/unique active key permits duplicate work or raises a race."""
    async def submit(index):
        async with pgmaker.begin() as db:
            return (await submit_refresh(db, "synthetic-league", "user",
                                        idempotency_key=f"request-{index}")).id
    ids = await asyncio.gather(*(submit(i) for i in range(16)))
    assert len(set(ids)) == 1

    async def claim(index):
        async with pgmaker.begin() as db:
            row = await claim_operation(db, f"worker-{index}")
            return row.id if row else None
    claims = await asyncio.gather(*(claim(i) for i in range(16)))
    assert sum(value is not None for value in claims) == 1
    async with pgmaker() as db:
        assert await db.scalar(select(func.count()).select_from(GenerationOperation)) == 1


@pytest.mark.asyncio
async def test_two_gateway_instances_cannot_send_the_same_stage(pgmaker):
    from app.services.generation.gateway import Gateway
    from app.services.generation.store import Held

    from tests.test_generation_gateway import REQUEST, FakeTransport, seed_job

    job = await seed_job(pgmaker)
    transport = FakeTransport(blocked=True)
    first = asyncio.create_task(Gateway(pgmaker, transport, epoch="test-epoch").invoke(job, 1, 1, REQUEST))
    await transport.started.wait()
    with pytest.raises(Held, match="provider_outcome_unknown"):
        await Gateway(pgmaker, transport, epoch="test-epoch").invoke(job, 1, 1, REQUEST)
    transport.release.set()
    await first
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_committed_pause_wins_against_waiting_admission(pgmaker):
    from app.services.generation.gateway import Gateway
    from app.services.generation.store import Held, lock_control

    from tests.test_generation_gateway import REQUEST, FakeTransport, seed_job
    await seed_job(pgmaker)
    transport=FakeTransport()
    async with pgmaker.begin() as db:
        control=await lock_control(db)
        control.hold="owner_paused"
        waiting=asyncio.create_task(Gateway(pgmaker,transport,epoch="test-epoch").invoke("job",1,1,REQUEST))
        await asyncio.sleep(0.05)
        assert not waiting.done()
    with pytest.raises(Held,match="owner_paused"):
        await waiting
    assert transport.sends==0


@pytest.mark.asyncio
@pytest.mark.parametrize("known_microusd, expected_usd, expected_calls", [(None, 1.0, 1), (1_234_567, 2.234567, 2)])
async def test_postgres_legacy_admin_routes_combine_known_and_legacy_costs(
    pgmaker, app, tmp_path, monkeypatch, known_microusd, expected_usd, expected_calls,
):
    """Mutation: return PostgreSQL SUM(bigint)'s Decimal without normalizing USD."""
    from decimal import Decimal
    from types import SimpleNamespace

    from app.auth.deps import require_admin
    from app.db.session import get_db
    from app.repositories.app_settings import set_monthly_budget
    from app.services.generation.models import ProviderAttempt
    from httpx import ASGITransport, AsyncClient

    from sleeper_dynasty.llm.cost_store import LlmCostStore
    from tests.test_generation_gateway import REQUEST, seed_job

    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    await seed_job(pgmaker)
    LlmCostStore(tmp_path).record(model=REQUEST["model"], writer="trade_story",
        league_id="synthetic", input_tokens=1_000_000, output_tokens=0)
    async with pgmaker.begin() as db:
        await set_monthly_budget(db, 10.0)
        if known_microusd is not None:
            db.add(ProviderAttempt(operation_id="job", stage=1, generation=1,
                request_digest="synthetic", request_json="{}", model=REQUEST["model"],
                state="received", usage_state="known", cost_microusd=known_microusd))
            await db.flush()
        total = await db.scalar(select(func.coalesce(func.sum(ProviderAttempt.cost_microusd), 0)))
        assert isinstance(total, Decimal)

    async def isolated():
        async with pgmaker.begin() as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = isolated
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id="owner", is_admin=True)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            overview = await client.get("/api/admin/overview")
            cost = await client.get("/api/settings/llm-cost?period=all")
            leagues = await client.get("/api/admin/leagues")
            budget = await client.put("/api/admin/budget", json={"monthly_budget_usd": 10.0})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert overview.status_code == cost.status_code == leagues.status_code == budget.status_code == 200
    for status in (overview.json()["budget"], cost.json(), budget.json()):
        assert status["monthly_budget_usd"] == 10.0
        assert status["month_to_date_usd"] == pytest.approx(expected_usd)
        assert status["budget_remaining_usd"] == pytest.approx(10.0 - expected_usd)
    costs = cost.json()
    assert costs["total_cost_usd"] == pytest.approx(expected_usd)
    assert costs["total_calls"] == expected_calls
    assert costs["by_writer"]["trade_story"]["cost_usd"] == pytest.approx(expected_usd)
    assert costs["by_league"]["synthetic"]["cost_usd"] == pytest.approx(expected_usd)
    assert sum(day["cost_usd"] for day in costs["daily"]) == pytest.approx(expected_usd)
    assert leagues.json()[0]["spend_mtd_usd"] == pytest.approx(expected_usd)


@pytest.mark.asyncio
@pytest.mark.parametrize("budget, admitted", [(1.75, False), (2.0, True)])
async def test_postgres_budget_admission_combines_known_and_legacy_costs(pgmaker, tmp_path, monkeypatch, budget, admitted):
    """Mutation: duplicate the unnormalized PostgreSQL SUM in budget admission."""
    from app.repositories.app_settings import set_monthly_budget
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import ProviderAttempt
    from app.services.generation.store import Held

    from sleeper_dynasty.llm.cost_store import LlmCostStore
    from tests.test_generation_gateway import REQUEST, FakeTransport, seed_job

    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    job = await seed_job(pgmaker)
    LlmCostStore(tmp_path).record(model=REQUEST["model"], writer="trade_story",
        league_id="synthetic", input_tokens=500_000, output_tokens=0)
    async with pgmaker.begin() as db:
        await set_monthly_budget(db, budget)
        db.add(ProviderAttempt(operation_id="earlier-job", stage=1, generation=1,
            request_digest="synthetic", request_json="{}", model=REQUEST["model"],
            state="received", usage_state="known", cost_microusd=1_250_000))
    transport = FakeTransport()
    gateway = Gateway(pgmaker, transport, epoch="test-epoch")
    if admitted:
        await gateway.invoke(job, 1, 1, REQUEST)
    else:
        with pytest.raises(Held, match="legacy_budget_reached"):
            await gateway.invoke(job, 1, 1, REQUEST)

    async with pgmaker() as db:
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == (2 if admitted else 1)
    assert transport.sends == int(admitted)
