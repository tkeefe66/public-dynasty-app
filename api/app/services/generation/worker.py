"""A durable worker owns refresh and generation; browser connections only observe."""
import asyncio
import contextlib
import logging
import uuid

from sqlalchemy import select

from app.db.models import User
from app.services.generation.commands import (
    LEASE_SECONDS,
    attention,
    authorize_candidate,
    claim_operation,
    require_actor,
    require_owner,
)
from app.services.generation.gateway import Gateway
from app.services.generation.models import (
    ArtifactHead,
    GenerationCandidate,
    GenerationOperation,
    LeagueSeason,
    stamp,
)
from app.services.generation.store import (
    Held,
    OwnershipLost,
    digest,
    dump,
    lock_control,
    resolve_policy,
)
from app.services.generation.transport import AnthropicTransport

log = logging.getLogger(__name__)


async def admit_automatic(maker):
    from app.config import get_settings
    from app.db.models import LeagueMembership
    async with maker.begin() as db:
        await lock_control(db)
        candidates = (await db.scalars(select(GenerationCandidate).where(
            GenerationCandidate.hold == "", GenerationCandidate.eligible_at > 0
        ).order_by(GenerationCandidate.observed_at).limit(100))).all()
        for candidate in candidates:
            policy = await resolve_policy(db, candidate.series_id)
            feature = policy["policy"]["features"][candidate.feature]
            if policy["blocked_by"] or feature["paused"] or feature["mode"] != "automatic":
                continue
            from app.services.generation.planner import automatic_reason
            season = await db.get(LeagueSeason, candidate.league_id)
            import json
            if not season or automatic_reason(season, candidate.feature,
                    json.loads(candidate.payload_json), stamp()):
                continue
            # A paid narrative is generated once per semantic event. Refreshes,
            # model changes and prompt edits never create a new authorization.
            key = "automatic:" + digest([candidate.subject, candidate.event])
            if await db.scalar(select(GenerationOperation.id).where(GenerationOperation.authorization_key == key)):
                continue
            head = await db.get(ArtifactHead, candidate.subject)
            if head and candidate.feature == "trade_story":
                continue
            # Automatic generation runs as an explicit current owner principal.
            owners = (await db.scalars(select(User).where(User.is_admin.is_(True),
                User.email.in_(get_settings().admin_email_list)))).all()
            for owner in owners:
                if ".l." in candidate.league_id and not await db.scalar(select(
                        LeagueMembership.id).where(LeagueMembership.user_id == owner.id,
                            LeagueMembership.league_id == candidate.league_id)):
                    continue
                try:
                    await authorize_candidate(db, candidate.key, actor_id=owner.id, actor_kind="scheduler",
                        reason="Automatic generation for a new eligible event", authorization_key=key)
                    break
                except Held:
                    continue


class Worker:
    def __init__(self, maker, cache_dir, *, transport=None, epoch=""):
        self.maker, self.cache_dir = maker, cache_dir
        self.id = str(uuid.uuid4())
        self.gateway = Gateway(maker, transport or AnthropicTransport(), epoch=epoch)

    async def heartbeat(self, job):
        while True:
            await asyncio.sleep(30)
            async with self.maker.begin() as db:
                await lock_control(db)
                row = await require_owner(db, job.id, job.generation)
                row.lease_until = stamp() + LEASE_SECONDS

    @contextlib.asynccontextmanager
    async def fence(self, job):
        async with self.maker.begin() as db:
            await lock_control(db)
            await require_owner(db, job.id, job.generation)
            await require_actor(db, job)
            yield db

    async def refresh(self, job):
        from app.services.platform_client import connected_client
        from app.services.refresh_service import refresh_league
        async with self.maker() as db:
            await require_actor(db, job)
            client = await connected_client(job.league_id, db=db, user_id=job.actor_id)
        async def progress(stage, message, **extra):
            async with self.fence(job) as db:
                row = await db.get(GenerationOperation, job.id)
                row.progress_json = dump({"stage": stage, "message": message, **extra})
                row.updated_at = stamp()
        try:
            await refresh_league(client, job.league_id, cache_dir=self.cache_dir,
                progress_cb=progress, generation_fence=lambda: self.fence(job))
            async with self.fence(job) as db:
                from app.services.generation.commands import finish
                await finish(db, job.id, job.generation)
        finally:
            await client.close()

    async def tick(self):
        await self.gateway.reconcile_receipts()
        from app.services.generation.publication import drain
        await drain(self.maker, self.cache_dir)
        async with self.maker.begin() as db:
            job = await claim_operation(db, self.id)
        if job is None:
            return False
        heartbeat = asyncio.create_task(self.heartbeat(job))
        try:
            if job.kind == "refresh":
                await self.refresh(job)
            else:
                from app.services.generation.artifacts import save_artifact
                from app.services.generation.features import generate
                result = await generate(job, self.gateway)
                async with self.maker.begin() as db:
                    await save_artifact(db, job.id, job.generation, result)
        except OwnershipLost:
            log.info("stale worker stopped operation=%s", job.id)
        except asyncio.CancelledError:
            async with self.maker.begin() as db:
                await lock_control(db)
                row = await db.get(GenerationOperation, job.id)
                if row.state == "running" and row.generation == job.generation:
                    row.state, row.reason = "needs_attention", "worker_shutdown"
                    row.generation += 1
            raise
        except Exception as exc:
            code = exc.code if isinstance(exc, Held) else "execution_failed"
            log.exception("operation stopped id=%s reason=%s", job.id, code)
            try:
                async with self.maker.begin() as db:
                    await lock_control(db)
                    row = await require_owner(db, job.id, job.generation)
                    if code in ("concurrency_busy", "series_concurrency_busy", "provider_cooldown"):
                        row.state, row.reason = "queued", code
                    elif isinstance(exc, Held) and code not in (
                            "provider_outcome_unknown", "response_invalid", "pricing_unknown",
                            "provider_rejected", "attempt_allowance_exhausted"):
                        row.state, row.reason = "held", code
                    else:
                        await attention(db, job.id, job.generation, code)
            except OwnershipLost:
                pass
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError, OwnershipLost):
                await heartbeat
        return True


async def worker_loop(cache_dir):
    from app.config import get_settings
    from app.db.engine import get_sessionmaker
    worker = Worker(get_sessionmaker(), cache_dir, epoch=get_settings().generation_execution_epoch)
    while True:
        try:
            await admit_automatic(worker.maker)
            worked = await worker.tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("generation worker cycle failed; work remains durable")
            worked = False
        await asyncio.sleep(1 if worked else 5)
