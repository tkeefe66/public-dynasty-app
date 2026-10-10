"""Disposable PostgreSQL lease and dispatch races."""
import asyncio
import pytest
from app.services.generation.models import stamp
from app.services.generation.store import Held
from app.services.recap_video import workflow as work
from tests.test_generation_postgres import pgmaker  # noqa: F401
from tests.test_recap_workflow import seed_media, seed_long_media_chain, fence


@pytest.mark.asyncio
@pytest.mark.parametrize("release", ["expiry", "cancel"])
async def test_render_authority_serializes_workers_and_recovers_after_expiry(pgmaker,tmp_path,monkeypatch,release):
    # Mutation: filter running renders after bounded scan or allow second lease.
    from app.services.generation.recap_models import RecapStage
    _, first = await seed_media(pgmaker,tmp_path,monkeypatch)
    async with pgmaker.begin() as db:
        source=await db.get(RecapStage,first)
        db.add(RecapStage(id="second-render",episode_id=source.episode_id,revision=source.revision,kind="render",chunk=1,
            script_id=source.script_id,operation_id=source.operation_id,predecessor_id=source.predecessor_id,
            input_json=source.input_json,input_digest=source.input_digest,policy_digest=source.policy_digest,epoch=source.epoch))
    now=stamp()
    async def claim(index):
        async with pgmaker.begin() as db:
            return await work.claim_stage(db,f"renderer-{index}",{"render"},now)
    leases=[v for v in await asyncio.gather(*(claim(i) for i in range(8))) if v]
    assert len(leases)==1
    async with pgmaker.begin() as db:
        from sqlalchemy import select
        narration=await db.scalar(select(RecapStage).where(RecapStage.kind=="narrate"))
        db.add(RecapStage(id="independent-narration",episode_id=narration.episode_id,revision=narration.revision,kind="narrate",chunk=1,
            script_id=narration.script_id,operation_id=narration.operation_id,predecessor_id="",
            input_json=narration.input_json,input_digest=narration.input_digest,policy_digest=narration.policy_digest,epoch=narration.epoch))
        assert (await work.claim_stage(db,"narrator",{"render","narrate"},now))["capability"]=="narrate"
        current=await db.get(RecapStage,leases[0]["stage_id"])
        if release=="expiry":
            current.lease_until=now
        else:
            current.state="cancelled"
        assert await work.claim_stage(db,"replacement",{"render"},now)


@pytest.mark.asyncio
async def test_provider_identity_race_preserves_first_evidence(pgmaker, tmp_path, monkeypatch):
    from app.services.generation.store import Conflict
    await seed_media(pgmaker, tmp_path, monkeypatch, "narrate")
    async with pgmaker.begin() as db:
        lease = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        authority = await work.authorize_dispatch(db, **fence(lease), worker_id="narrator")
    async def persist(identity):
        try:
            async with pgmaker.begin() as db:
                await work.persist_identity(db, authority["attempt_id"], {"request_id": identity}, worker_id="narrator")
            return True
        except Conflict:
            return False
    assert sum(await asyncio.gather(persist("first-request"), persist("second-request"))) == 1
    async with pgmaker.begin() as db:
        evidence = await work.recovery_evidence(db, authority["attempt_id"], worker_id="narrator")
        assert evidence["identity"]["request_id"] in {"first-request", "second-request"}


@pytest.mark.asyncio
async def test_long_chain_claim_has_single_runnable_winner(pgmaker, tmp_path, monkeypatch):
    # Mutation: the bounded window hides root, or concurrent claims acquire it twice.
    root = await seed_long_media_chain(pgmaker, tmp_path, monkeypatch)
    async def claim(index):
        async with pgmaker.begin() as db:
            return await work.claim_stage(db, f"worker-{index}", work.MEDIA_KINDS, stamp())
    winners = [lease for lease in await asyncio.gather(*(claim(i) for i in range(12))) if lease]
    assert len(winners) == 1
    assert winners[0]["stage_id"] == root


@pytest.mark.asyncio
async def test_media_claim_and_dispatch_have_single_winner(pgmaker, tmp_path, monkeypatch):
    # Mutation: remove global admission lock; two claimants/dispatchers acquire authority.
    await seed_media(pgmaker, tmp_path, monkeypatch, "narrate")
    async def claim(index):
        async with pgmaker.begin() as db:
            return await work.claim_stage(db, "narrator", {"narrate"}, stamp())
    leases = await asyncio.gather(*(claim(i) for i in range(12)))
    winners = [lease for lease in leases if lease]
    assert len(winners) == 1
    async def dispatch():
        try:
            async with pgmaker.begin() as db:
                return await work.authorize_dispatch(db, **fence(winners[0]), worker_id="narrator")
        except Held as exc:
            assert exc.code == "dispatch_authority_already_issued"
            return None
    assert sum(bool(v) for v in await asyncio.gather(*(dispatch() for _ in range(12)))) == 1


@pytest.mark.asyncio
async def test_cancel_committed_before_waiting_completion_wins(pgmaker, tmp_path, monkeypatch):
    # Mutation: result selection reads lease before acquiring control lock.
    from app.services.generation.store import OwnershipLost
    from tests.test_recap_workflow import result
    episode_id, _ = await seed_media(pgmaker, tmp_path, monkeypatch)
    async with pgmaker.begin() as db:
        lease = await work.claim_stage(db, "renderer", {"render"}, stamp())
    async def complete():
        async with pgmaker.begin() as db:
            return await work.complete_stage(db, **fence(lease), result=result(lease))
    async with pgmaker.begin() as db:
        await work.cancel_media(db, episode_id, "owner", "Synthetic race")
        waiting = asyncio.create_task(complete())
        await asyncio.sleep(.05)
        assert not waiting.done()
    with pytest.raises(OwnershipLost):
        await waiting


@pytest.mark.asyncio
async def test_postgres_restore_quarantines_media_and_retains_receipts(pgmaker, tmp_path, monkeypatch):
    # Mutation: restoring a leased paid checkpoint can reissue physical dispatch.
    from app.db.base import Base
    from app.services.backup_service import dump_database
    from app.services.generation.recovery import restore_database
    from app.services.generation.recap_models import RecapProviderAttempt, RecapStage
    await seed_media(pgmaker, tmp_path, monkeypatch, "narrate")
    async with pgmaker.begin() as db:
        lease = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        authority = await work.authorize_dispatch(db, **fence(lease), worker_id="narrator")
    async with pgmaker() as db:
        blob, counts = await dump_database(db)
    async with pgmaker.kw["bind"].begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with pgmaker.begin() as db:
        assert await restore_database(db, blob) == counts
        assert (await db.get(RecapStage, lease["stage_id"])).reason == "restore_reapproval_required"
        assert (await db.get(RecapProviderAttempt, authority["attempt_id"])).state == "unknown"
        assert await work.claim_stage(db, "narrator", {"narrate"}, stamp()) is None
