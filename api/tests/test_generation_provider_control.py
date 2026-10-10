import pytest
from app.services.generation.store import Held


@pytest.mark.asyncio
async def test_provider_accounts_fail_independently(maker):
    # Mutation: ElevenLabs auth failure becomes global/Anthropic hold.
    from app.services.generation.provider_control import account_control, record_failure, require_provider_ready
    from tests.test_generation_gateway import seed_job
    await seed_job(maker)
    async with maker.begin() as db:
        await account_control(db, "elevenlabs", "voice")
        await record_failure(db, "elevenlabs", "voice", 401, 100)
        with pytest.raises(Held, match="provider_auth_failed"):
            await require_provider_ready(db, "elevenlabs", "voice", 100)
        await require_provider_ready(db, "anthropic", "primary", 100)
        await require_provider_ready(db, "elevenlabs", "other", 100)


@pytest.mark.asyncio
async def test_legacy_hold_migrates_without_loss_and_reset_is_scoped(maker):
    # Mutation: discard legacy hold; one provider's uncertainty prevents unrelated reset.
    from app.services.generation.provider_control import account_control, reset_provider
    from app.services.generation.models import GenerationControl, GenerationAudit, ProviderAttempt
    from sqlalchemy import select
    from tests.test_generation_gateway import seed_job
    await seed_job(maker)
    async with maker.begin() as db:
        control = await db.get(GenerationControl, "global")
        control.provider_hold, control.cooldown_until = "provider_auth_failed", 999
        account = await account_control(db, "anthropic", "primary")
        assert account.hold == "provider_auth_failed" and account.cooldown_until == 999
        assert control.provider_hold == "" and control.cooldown_until == 0
        db.add(ProviderAttempt(operation_id="job", stage=1, generation=1, request_digest="x", request_json="{}",
            model="synthetic", provider="anthropic", account_key="primary", state="unknown"))
        other = await account_control(db, "elevenlabs", "voice")
        await reset_provider(db, "elevenlabs", "voice", other.revision, "owner", "Synthetic scoped recovery")
        with pytest.raises(Held, match="provider_outcome_unknown"):
            await reset_provider(db, "anthropic", "primary", account.revision, "owner", "Synthetic recovery")
        assert await db.scalar(select(GenerationAudit.target).where(GenerationAudit.action == "provider_reset")) == "elevenlabs:voice"


@pytest.mark.asyncio
async def test_cooldown_isolated_global_pause_blocks_both(maker, monkeypatch):
    # Mutation: ElevenLabs 429 cooldown blocks Anthropic; global pause only blocks prose.
    from app.services.generation.provider_control import record_failure, require_provider_ready
    from tests.test_generation_gateway import seed_job
    await seed_job(maker)
    async with maker.begin() as db:
        await record_failure(db, "elevenlabs", "primary", 429, 100, delay=90)
        with pytest.raises(Held, match="provider_cooldown"):
            await require_provider_ready(db, "elevenlabs", "primary", 150)
        await require_provider_ready(db, "anthropic", "primary", 150)
        monkeypatch.setenv("TRADE_GRADER_GENERATION_EMERGENCY_PAUSE", "true")
        for provider in ("anthropic", "elevenlabs"):
            with pytest.raises(Held, match="emergency_pause"):
                await require_provider_ready(db, provider, "primary", 200)


@pytest.mark.asyncio
async def test_anthropic_failure_does_not_hold_free_render(maker, tmp_path, monkeypatch):
    # Mutation: global provider status is part of free rendering eligibility.
    from tests.test_recap_workflow import seed_media
    from app.services.generation.provider_control import record_failure
    from app.services.recap_video.workflow import claim_stage
    from app.services.generation.models import stamp
    await seed_media(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        await record_failure(db, "anthropic", "primary", 401, stamp())
        assert await claim_stage(db, "renderer", {"render"}, stamp())


@pytest.mark.asyncio
async def test_other_provider_unknown_attempt_does_not_consume_anthropic_concurrency(maker):
    # Mutation: aggregate both providers' active attempts into Anthropic concurrency gate.
    from app.services.generation.recap_models import RecapProviderAttempt
    from app.services.generation.gateway import Gateway
    from tests.test_generation_gateway import REQUEST, FakeTransport, seed_job
    await seed_job(maker)
    async with maker.begin() as db:
        db.add(RecapProviderAttempt(stage_id="other-stage", episode_id="other-episode", series_id="other-series",
            operation_id="other-operation", provider="elevenlabs", account_key="primary", worker_id="narrator",
            generation=1, epoch="test-epoch", request_digest="request", request_json="{}", pricing_json="{}",
            authority_digest="authority", state="unknown"))
    transport = FakeTransport()
    await Gateway(maker, transport, epoch="test-epoch").invoke("job", 1, 1, REQUEST)
    assert transport.sends == 1
