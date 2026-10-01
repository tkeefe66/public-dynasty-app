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
