import json
from types import SimpleNamespace

import pytest
from app.services.generation.models import (
    GenerationCandidate,
    GenerationOperation,
    GenerationPolicy,
    LeagueSeason,
    LeagueSeries,
    stamp,
)
from app.services.generation.store import Held, digest, dump
from sqlalchemy import select

from tests.test_generation_gateway import BODY, REQUEST, FakeTransport, seed_job


@pytest.mark.asyncio
async def test_blocked_first_page_cannot_starve_other_automatic_candidates(maker):
    from app.services.generation.worker import admit_automatic
    await seed_job(maker)
    async with maker.begin() as db:
        (await db.get(GenerationPolicy,"app")).value_json = dump({"paused":False,
            "features":{"gm_rating_blurb":{"mode":"automatic"}}})
        (await db.get(LeagueSeason,"synthetic")).latest_week = 2
        for i in range(101):
            payload = {"facts":{}, "season":2026, "week":2, "event_at":stamp()}
            db.add(GenerationCandidate(key=f"candidate-{i:03d}",series_id="series",league_id="synthetic",
                feature="trade_story" if i < 100 else "gm_rating_blurb", subject=f"subject-{i}", event="week:2",
                payload_json=dump(payload),digest=digest(payload),eligible_at=stamp()-200,observed_at=i))
    await admit_automatic(maker)
    await admit_automatic(maker)
    async with maker() as db:
        assert await db.scalar(select(GenerationOperation.id).where(GenerationOperation.subject=="subject-100"))


def test_automatic_historical_summary_scope_requires_explicit_approval():
    from app.services.generation.planner import automatic_reason
    season = SimpleNamespace(season=2026, latest_week=2)
    assert automatic_reason(season,"gm_rating_blurb",
        {"season":2026,"week":2,"target":{"scope":"2023"}},stamp()) == "historical_approval_required"


@pytest.mark.asyncio
async def test_remove_and_readd_last_member_keeps_series_held(maker):
    from app.repositories import memberships
    await seed_job(maker)
    async with maker.begin() as db:
        await memberships.remove(db,user_id="owner",league_id="synthetic")
        await memberships.add(db,user_id="owner",league_id="synthetic")
        assert (await db.get(LeagueSeries,"series")).hold == "membership_removed"


@pytest.mark.asyncio
async def test_feature_pause_after_paid_validation_prevents_publication(maker):
    from app.services.generation.artifacts import save_artifact
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway

    from tests.test_generation_worker import prepare
    await prepare(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation,"job")
        job.state="running"
    transport=FakeTransport(body=json.dumps({**BODY,"content":[{"type":"text","text":json.dumps({"blurb":"Valid profile","highlights":{}})}]}))
    result=await generate(job,Gateway(maker,transport,epoch="test-epoch"))
    async with maker.begin() as db:
        (await db.get(GenerationPolicy,"app")).value_json=dump({"paused":False,"features":{"gm_rating_blurb":{"paused":True}}})
    async with maker.begin() as db:
        with pytest.raises(Held,match="feature_paused"):
            await save_artifact(db,job.id,job.generation,result)
    assert transport.sends==1


@pytest.mark.asyncio
async def test_old_season_scheduler_job_cannot_purchase_after_renewal(maker):
    from app.services.generation.gateway import Gateway
    await seed_job(maker)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,"job")
        job.actor_kind="scheduler"
        job.payload_json=dump({"season":2026,"event_at":stamp()})
        (await db.get(GenerationPolicy,"app")).value_json=dump({"paused":False,"features":{"trade_story":{"mode":"automatic"}}})
        db.add(LeagueSeason(league_id="renewed",provider="sleeper",provider_key="renewed",series_id="series",season=2027))
    transport=FakeTransport()
    with pytest.raises(Held,match="historical_approval_required"):
        await Gateway(maker,transport,epoch="test-epoch").invoke("job",1,1,REQUEST)
    assert transport.sends==0


@pytest.mark.asyncio
async def test_transport_has_no_hidden_retry_and_429_cooldown_is_shared(maker, monkeypatch):
    import httpx
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import GenerationControl, ProviderAttempt
    from app.services.generation.transport import AnthropicTransport
    await seed_job(maker)
    calls=[]
    retries=[]
    async def respond(request):
        calls.append(request)
        return httpx.Response(429,json={"error":{"type":"rate_limit_error"}},headers={"retry-after":"120"})
    def factory(**kwargs):
        retries.append(kwargs["retries"])
        return httpx.MockTransport(respond)
    monkeypatch.setenv("ANTHROPIC_API_KEY","synthetic-no-network-key")
    monkeypatch.setattr(httpx,"AsyncHTTPTransport",factory)
    gateway=Gateway(maker,AnthropicTransport(),epoch="test-epoch")
    with pytest.raises(Held,match="provider_rejected"):
        await gateway.invoke("job",1,1,REQUEST)
    with pytest.raises(Held,match="provider_cooldown"):
        await Gateway(maker,AnthropicTransport(),epoch="test-epoch").invoke("job",1,2,REQUEST)
    assert retries==[0] and len(calls)==1
    async with maker() as db:
        assert (await db.get(GenerationControl,"global")).cooldown_until>stamp()
        assert (await db.scalar(select(ProviderAttempt))).receipt_json


@pytest.mark.asyncio
async def test_exhausted_but_complete_checkpoint_can_resume_publication_without_purchase(maker, tmp_path):
    from app.services.generation.administration import job_action
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway
    from app.services.generation.worker import Worker

    from tests.test_generation_worker import prepare
    await prepare(maker)
    async with maker.begin() as db:
        job=await db.get(GenerationOperation,"job")
        job.state,job.max_calls="running",1
    transport=FakeTransport(body=json.dumps({**BODY,"content":[{"type":"text","text":json.dumps({"blurb":"Valid","highlights":{}})}]}))
    await generate(job,Gateway(maker,transport,epoch="test-epoch"))
    async with maker.begin() as db:
        row=await db.get(GenerationOperation,"job")
        row.state="held"
        await job_action(db,"job",SimpleNamespace(expected_generation=row.generation,expected_state="held",
            action="resume",reason="Resume saved validation after pause"),"owner")
    await Worker(maker,tmp_path,transport=transport,epoch="test-epoch").tick()
    assert transport.sends==1
    async with maker() as db:
        assert (await db.get(GenerationOperation,"job")).state=="succeeded"


@pytest.mark.asyncio
async def test_receipt_storage_failure_does_not_resend(maker, monkeypatch):
    from app.services.generation.gateway import Gateway
    await seed_job(maker)
    transport=FakeTransport()
    gateway=Gateway(maker,transport,epoch="test-epoch")
    async def unavailable(*args):
        raise RuntimeError("receipt storage unavailable")
    monkeypatch.setattr(gateway,"record_receipt",unavailable)
    with pytest.raises(RuntimeError,match="storage unavailable"):
        await gateway.invoke("job",1,1,REQUEST)
    with pytest.raises(Held,match="provider_outcome_unknown"):
        await Gateway(maker,transport,epoch="test-epoch").invoke("job",1,1,REQUEST)
    assert transport.sends==1


@pytest.mark.asyncio
async def test_unknown_model_price_retains_receipt_and_stops_other_work(maker):
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import GenerationControl, ProviderAttempt
    await seed_job(maker)
    transport=FakeTransport(body=json.dumps({**BODY,"model":"unregistered-provider-model"}))
    with pytest.raises(Held,match="pricing_unknown"):
        await Gateway(maker,transport,epoch="test-epoch").invoke("job",1,1,REQUEST)
    async with maker() as db:
        row=await db.scalar(select(ProviderAttempt))
        assert row.receipt_json and row.cost_microusd is None
        assert (await db.get(GenerationControl,"global")).provider_hold=="accounting_attention"


@pytest.mark.asyncio
async def test_abandoned_unknown_receipt_settles_once_without_replacement(maker):
    from app.services.generation.administration import resolve_attempt
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import GenerationOutbox, ProviderAttempt
    from app.services.generation.transport import Receipt
    from sqlalchemy import func
    await seed_job(maker)
    gateway=Gateway(maker,FakeTransport(lost=True),epoch="test-epoch")
    with pytest.raises(Held):
        await gateway.invoke("job",1,1,REQUEST)
    async with maker.begin() as db:
        row=await db.scalar(select(ProviderAttempt))
        ident=row.id
        await resolve_attempt(db,ident,SimpleNamespace(expected_state="unknown",action="abandon_unknown",
            workers_stopped=True,evidence="Original worker stopped; provider outcome unavailable",reason="Resolve uncertainty"),"owner")
        assert row.cost_microusd is None and row.state=="abandoned"
    receipt=Receipt(200,json.dumps(BODY),{"request-id":"late-receipt"})
    await gateway.record_receipt(ident,receipt)
    await gateway.record_receipt(ident,receipt)
    async with maker() as db:
        assert (await db.get(ProviderAttempt,ident)).cost_microusd==35
        assert (await db.get(GenerationOperation,"job")).state=="cancelled"
        assert await db.scalar(select(func.count()).select_from(GenerationOperation))==1
        assert await db.scalar(select(func.count()).select_from(GenerationOutbox))==1


@pytest.mark.asyncio
async def test_shared_breaker_survives_new_worker_and_blocks_next_subject(maker):
    from app.services.generation.commands import attention
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import GenerationControl
    await seed_job(maker)
    for index in range(3):
        async with maker.begin() as db:
            job=await db.get(GenerationOperation,"job")
            job.state="running"
            await attention(db,"job",1,"validation_failed")
    async with maker.begin() as db:
        assert json.loads((await db.get(GenerationControl,"global")).breakers_json)["trade_story"]["open"]
        job=await db.get(GenerationOperation,"job")
        job.state="running"
        job.subject="next-subject"
    transport=FakeTransport()
    with pytest.raises(Held,match="feature_breaker_open"):
        await Gateway(maker,transport,epoch="test-epoch").invoke("job",1,1,REQUEST)
    assert transport.sends==0
