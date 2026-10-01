"""Credential-free contract check for the actual API container; uses temporary SQLite."""
import asyncio
import json
import os
import tempfile
from pathlib import Path


async def check():
    from app.db.base import Base
    from app.db.models import LeagueMembership, User
    from app.services.generation.models import (
        ContentArtifact,
        GenerationControl,
        GenerationOperation,
        GenerationPolicy,
        LeagueSeason,
        LeagueSeries,
        ProviderAttempt,
    )
    from app.services.generation.policy import HAIKU, Policy
    from app.services.generation.store import digest, dump
    from app.services.generation.transport import Receipt
    from app.services.generation.worker import Worker
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    class FakeTransport:
        sends = 0
        async def send(self, request):
            self.sends += 1
            return Receipt(200, json.dumps({"id":"synthetic-message", "type":"message", "role":"assistant",
                "model":HAIKU, "content":[{"type":"text","text":json.dumps({"blurb":"Saved profile.","highlights":{}})}],
                "stop_reason":"end_turn", "stop_sequence":None, "usage":{"input_tokens":10, "output_tokens":5,
                    "cache_read_input_tokens":0, "cache_creation_input_tokens":0}}), {})

    os.environ["TRADE_GRADER_ADMIN_EMAILS"] = "contract@test.local"
    os.environ["TRADE_GRADER_GENERATION_EMERGENCY_PAUSE"] = "false"
    os.environ["TRADE_GRADER_LLM_MONTHLY_BUDGET_USD"] = "0"
    with tempfile.TemporaryDirectory() as folder:
        os.environ["TRADE_GRADER_CACHE_DIR"] = folder
        engine = create_async_engine(f"sqlite+aiosqlite:///{folder}/contract.db")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        payload = {"facts":{"user_id":"u", "owner_name":"Owner", "team_name":None, "scope_label":"career",
            "rank":1, "rating":80, "pillars":{}}, "target":{"slot":"owner_rating_blurbs","scope":"all","key":"u"}}
        async with maker.begin() as db:
            db.add(User(id="owner", google_sub="contract", email="contract@test.local", is_admin=True))
            db.add(LeagueMembership(user_id="owner", league_id="synthetic"))
            db.add(GenerationControl(id="global", epoch="contract", hold=""))
            db.add(GenerationPolicy(scope="app", value_json=dump({"paused":False})))
            db.add(LeagueSeries(id="series", lifecycle="active", profile="dynasty", hold="", activated_at=1))
            db.add(LeagueSeason(league_id="synthetic", provider="sleeper", provider_key="synthetic",
                series_id="series", season=2026, verified_at=1, capabilities_json=dump({"format":"dynasty",
                    "future_picks":True, "roster_continuity":True, "multiyear_history":True})))
            db.add(GenerationOperation(id="job",kind="generation",league_id="synthetic",series_id="series",
                feature="gm_rating_blurb",subject="profile",actor_id="owner",actor_kind="admin",
                max_calls=2,epoch="contract",payload_json=dump(payload),request_digest=digest(payload),
                policy_json=dump({"policy":Policy(paused=False).model_dump()})))
        transport = FakeTransport()
        worker = Worker(maker, Path(folder), transport=transport, epoch="contract")
        assert await worker.tick()
        assert not await worker.tick()
        async with maker() as db:
            assert (await db.get(GenerationOperation,"job")).state == "succeeded"
            assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1
            receipt = await db.scalar(select(ProviderAttempt))
            assert receipt.receipt_json and receipt.cost_microusd == 35
        assert transport.sends == 1
        await engine.dispose()
        print("Runtime contract passed: one fake send, receipt, priced attempt, validated artifact; no repeat send.")


if __name__ == "__main__":
    asyncio.run(check())
