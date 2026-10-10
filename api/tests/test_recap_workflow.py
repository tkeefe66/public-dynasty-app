"""Synthetic durable lease fences; no provider requests."""
import pytest
import json
from sqlalchemy import select
from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationOperation, stamp
from app.services.generation.recap_models import RecapStage, RecapProviderAttempt, RecapAsset
from app.services.generation.store import Held, OwnershipLost, digest, dump
from app.services.recap_video import workflow as work


async def seed_media(maker, tmp_path, monkeypatch, kind="render"):
    from tests.test_recap_video_script import seed, approved_payload
    episode_id, saved = await seed(maker, tmp_path, monkeypatch)
    monkeypatch.setenv("TRADE_GRADER_GENERATION_EXECUTION_EPOCH", "test-epoch")
    async def validate(db, stage, result):
        if result["report"] != {"verified": stage.input_digest}:
            raise Held("synthetic_report_invalid")
    async def plan(db, artifact, evidence):
        return [dict(kind=k, chunk=0, input={"paid": {"request": {"text": "Synthetic narration"},
            "rate_snapshot": {"unit": "character", "price": "1"}, "max_microusd": 100}} if k == "narrate" else {"script": artifact.digest})
            for k in ("narrate", "speech_check", "render", "media_check")]
    monkeypatch.setattr(work, "MEDIA_PLAN_BUILDER", plan)
    monkeypatch.setattr(work, "RESULT_VALIDATORS", {k: validate for k in work.MEDIA_KINDS})
    monkeypatch.setattr(work, "RECEIPT_SETTLERS", {"elevenlabs": lambda req, rate, receipt:
        ("received", 17, "") if receipt == {"status": 200, "request": digest(req)} else ("unknown", None, "provider_outcome_unknown")})
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.state, job.artifact_id = "succeeded", "script"
        payload = approved_payload(saved)
        db.add(ContentArtifact(id="script", operation_id=job.id, series_id="series", league_id="synthetic",
            feature="recap_video", subject=job.subject, revision=1, payload_json=dump(payload), digest=digest(payload), provenance="managed"))
        db.add(ArtifactHead(subject=job.subject, artifact_id="script", revision=1))
    async with maker.begin() as db:
        rows = await work.start_media(db, "script")
        for row in rows:
            if row.kind == kind:
                target = row.id
                break
            row.state, row.result_json = "succeeded", dump({"asset_ids": []})
    return episode_id, target


def fence(lease):
    return {k: lease[k] for k in ("stage_id", "generation", "epoch", "input_digest")}


def result(lease):
    return {"status": "ok", "asset_ids": [], "report": {"verified": lease["input_digest"]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["generation", "epoch", "input_digest", "worker_id", "expiry", "cancel", "actor", "article", "policy"])
async def test_completion_rechecks_every_authority_fence(maker, tmp_path, monkeypatch, change):
    # Mutation: omit each corresponding lease/current-authority guard before selecting output.
    episode_id, target = await seed_media(maker, tmp_path, monkeypatch)
    now = stamp()
    async with maker.begin() as db:
        leased = await work.claim_stage(db, "renderer", {"render", "publish"}, now)
    args = {**fence(leased), "worker_id": "renderer", "now": now}
    if change in ("generation", "epoch", "input_digest", "worker_id"):
        args[change] = 999 if change == "generation" else "changed"
    if change == "expiry":
        args["now"] = leased["expires_at"]
    async with maker.begin() as db:
        if change == "cancel":
            await work.cancel_media(db, episode_id, "owner", "Synthetic cancellation")
        if change == "actor":
            (await db.get(GenerationOperation, "job")).actor_id = "removed"
        if change == "article":
            (await db.get(ArtifactHead, "article-subject")).revision = 2
        if change == "policy":
            from app.services.generation.models import GenerationPolicy
            (await db.get(GenerationPolicy, "app")).revision += 1
    async with maker.begin() as db:
        with pytest.raises((Held, OwnershipLost)):
            await work.complete_stage(db, **args, result=result(leased))
    async with maker() as db:
        assert (await db.get(RecapStage, target)).state != "succeeded"


@pytest.mark.asyncio
async def test_duplicate_completion_and_restart_reuse_checkpoint(maker, tmp_path, monkeypatch):
    # Mutation: completed stage returns to queue or accepts a second result.
    await seed_media(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        leased = await work.claim_stage(db, "renderer", {"render"}, stamp())
        assert await work.complete_stage(db, **fence(leased), result=result(leased)) == {"stage_id": leased["stage_id"], "state": "succeeded"}
    async with maker.begin() as db:
        with pytest.raises(OwnershipLost):
            await work.complete_stage(db, **fence(leased), result=result(leased))
        assert await work.claim_stage(db, "restarted", {"render"}, stamp()) is None
        assert (await work.claim_stage(db, "qa", {"media_check"}, stamp()))["capability"] == "media_check"


@pytest.mark.asyncio
async def test_free_crash_backoff_then_attention(maker, tmp_path, monkeypatch):
    # Mutation: free crashes loop immediately/unboundedly or paid stages share free retries.
    _, target = await seed_media(maker, tmp_path, monkeypatch)
    now = stamp()
    for delay in (60, 300, 900):
        async with maker.begin() as db:
            leased = await work.claim_stage(db, "renderer", {"render"}, now)
            assert leased
        now = leased["expires_at"]
        async with maker.begin() as db:
            assert await work.claim_stage(db, "restarted", {"render"}, now) is None
            row = await db.get(RecapStage, target)
            assert row.next_attempt_at == now + delay
        now += delay
    async with maker.begin() as db:
        leased = await work.claim_stage(db, "renderer", {"render"}, now)
        assert await work.claim_stage(db, "restarted", {"render"}, leased["expires_at"]) is None
        assert (await db.get(RecapStage, target)).state == "needs_attention"


@pytest.mark.asyncio
async def test_one_dispatch_unknown_crash_and_late_receipt_only_settles_money(maker, tmp_path, monkeypatch):
    # Mutation: replay authority after crash; treat late receipt as current result; ignore media ledger in obligations.
    episode_id, target = await seed_media(maker, tmp_path, monkeypatch, "narrate")
    now = stamp()
    async with maker.begin() as db:
        leased = await work.claim_stage(db, "narrator", {"narrate"}, now)
        authority = await work.authorize_dispatch(db, **fence(leased), worker_id="narrator", now=now)
    async with maker.begin() as db:
        with pytest.raises(Held, match="already_issued"):
            await work.authorize_dispatch(db, **fence(leased), worker_id="narrator", now=now)
        assert await work.claim_stage(db, "restart", {"narrate"}, leased["expires_at"]) is None
    async with maker.begin() as db:
        await work.record_receipt(db, authority["attempt_id"], {"status": 200, "request": digest(authority["request"])}, worker_id="narrator")
        assert (await db.get(RecapStage, target)).state == "needs_attention"
        from app.services.generation.recap_budget import _obligations
        obligations = [r for r in await _obligations(db) if r["attempt_id"] == authority["attempt_id"]]
        assert len(obligations) == 1 and obligations[0]["known"] == 17
        assert not obligations[0]["outcome_unknown"] and not obligations[0]["unknown"]
        with pytest.raises(OwnershipLost):
            await work.complete_stage(db, **fence(leased), result=result(leased), worker_id="narrator", now=now)


@pytest.mark.asyncio
async def test_crash_after_raw_receipt_reconciles_without_resending(maker, tmp_path, monkeypatch):
    # Mutation: raw receipt is lost before parsing, or restart purchases a new attempt.
    await seed_media(maker, tmp_path, monkeypatch, "narrate")
    async with maker.begin() as db:
        leased = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        authority = await work.authorize_dispatch(db, **fence(leased), worker_id="narrator")
    raw = {"status": 200, "request": digest(authority["request"])}
    async with maker.begin() as db:
        await work.persist_receipt(db, authority["attempt_id"], raw, worker_id="narrator")
    async with maker() as db:
        attempt = await db.get(RecapProviderAttempt, authority["attempt_id"])
        assert json.loads(attempt.receipt_json) == raw and attempt.settled_at == 0
    await work.reconcile_media_receipts(maker)
    async with maker.begin() as db:
        assert (await db.get(RecapProviderAttempt, authority["attempt_id"])).cost_microusd == 17
        with pytest.raises(Held, match="already_issued"):
            await work.authorize_dispatch(db, **fence(leased), worker_id="narrator")


@pytest.mark.asyncio
async def test_financial_settlement_never_authorizes_unknown_replacement(maker, tmp_path, monkeypatch):
    # Mutation: known invoice amount erases independent provider outcome uncertainty.
    episode_id, _ = await seed_media(maker, tmp_path, monkeypatch, "narrate")
    from app.services.generation.recap_budget import reserve_plan, reconcile_allocation
    from app.services.generation.recap_models import RecapBudgetAllocation
    async with maker.begin() as db:
        leased = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        authority = await work.authorize_dispatch(db, **fence(leased), worker_id="narrator")
        attempt = await db.get(RecapProviderAttempt, authority["attempt_id"])
        attempt.state = "abandoned"
        allocation = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id == attempt.id))
        await reconcile_allocation(db, allocation.id, 17, {"invoice": "synthetic"}, "owner", "Synthetic invoice review")
        assert attempt.cost_microusd == 17 and attempt.state == "abandoned"
        with pytest.raises(Held, match="recap_provider_outcome_unknown"):
            await reserve_plan(db, episode_id, "series", "replacement", [dict(key="new", category="video",
                operation_id="new", max_microusd=20, rate_snapshot={"unit": "character"})], stamp())


@pytest.mark.asyncio
async def test_narration_respects_remaining_video_cap(maker, tmp_path, monkeypatch):
    # Mutation: media reservation bypasses existing episode budget.
    episode_id, _ = await seed_media(maker, tmp_path, monkeypatch, "narrate")
    from app.services.generation.recap_budget import RecapCaps, save_caps
    async with maker.begin() as db:
        await save_caps(db, "series", RecapCaps(video_episode_microusd=99), 0, "owner", "Synthetic cap", False)
        leased = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        with pytest.raises(Held, match="recap_budget_video_episode"):
            await work.authorize_dispatch(db, **fence(leased), worker_id="narrator")
        assert await db.scalar(select(RecapProviderAttempt.id)) is None


@pytest.mark.asyncio
async def test_later_narration_chunk_rechecks_lowered_caps(maker, tmp_path, monkeypatch):
    # Mutation: replay of a reserved plan bypasses subsequently lowered episode caps.
    episode_id, target = await seed_media(maker, tmp_path, monkeypatch, "narrate")
    from app.services.generation.recap_budget import RecapCaps, save_caps
    async with maker.begin() as db:
        first = await db.get(RecapStage, target)
        second = RecapStage(episode_id=episode_id, revision=1, kind="narrate", chunk=1, script_id=first.script_id,
            operation_id=first.operation_id, predecessor_id=first.id, input_json=first.input_json,
            input_digest=first.input_digest, policy_digest=first.policy_digest, epoch=first.epoch)
        db.add(second)
        await db.flush()
        leased = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        authority = await work.authorize_dispatch(db, **fence(leased), worker_id="narrator")
        await work.record_receipt(db, authority["attempt_id"], {"status": 200, "request": digest(authority["request"])}, worker_id="narrator")
        await work.complete_stage(db, **fence(leased), result=result(leased))
        await save_caps(db, "series", RecapCaps(video_episode_microusd=100), 0, "owner", "Synthetic lower cap", True)
        next_lease = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        assert next_lease["stage_id"] == second.id
        with pytest.raises(Held, match="recap_budget_video_episode"):
            await work.authorize_dispatch(db, **fence(next_lease), worker_id="narrator")


@pytest.mark.asyncio
async def test_api_queue_and_projection_reject_media_role(maker, tmp_path):
    # Mutation: claim unregistered API kind; allow media worker to project readers.
    from tests.test_generation_gateway import seed_job
    from app.services.generation.commands import claim_operation
    from app.services.generation.publication import drain
    await seed_job(maker)
    async with maker.begin() as db:
        (await db.get(GenerationOperation, "job")).state = "queued"
        assert await claim_operation(db, "renderer", capabilities={"render", "publish"}) is None
    with pytest.raises(Held, match="api_projector_required"):
        await drain(maker, tmp_path, execution_role="media")


@pytest.mark.asyncio
async def test_reobservation_preserves_progress_but_changed_facts_fence_stage(maker, tmp_path, monkeypatch):
    # Mutation: every observation resets active media to ready, or changed facts retain lease authority.
    from app.services.generation.recap_models import RecapEpisode, RecapObservation
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    episode_id, target = await seed_media(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        leased = await work.claim_stage(db, "renderer", {"render"}, stamp())
        episode = await db.get(RecapEpisode, episode_id)
        episode.stable_since = 1000
        snapshot = json.loads((await db.get(RecapObservation, episode.latest_observation_id)).snapshot_json)
        await observe_period(db, EpisodeKey("series", 2026, "4"), snapshot, 5500)
        assert episode.lifecycle == "rendering"
        assert (await db.get(RecapStage, target)).generation == leased["generation"]
        snapshot["scores"]["4"][0]["points"] = "99.000"
        await observe_period(db, EpisodeKey("series", 2026, "4"), snapshot, 6400)
        assert (await db.get(RecapStage, target)).generation > leased["generation"]
        assert episode.hold == "recap_facts_changed"
        with pytest.raises(OwnershipLost):
            await work.complete_stage(db, **fence(leased), result=result(leased))


@pytest.mark.asyncio
async def test_media_provider_failure_preserves_written_readiness(maker, tmp_path, monkeypatch):
    # Mutation: shared episode lifecycle/hold makes ElevenLabs incident hold written Analyst.
    from app.services.recap_video.readiness import require_readiness
    from app.services.generation.provider_control import record_failure, require_provider_ready
    await seed_media(maker, tmp_path, monkeypatch, "narrate")
    async with maker.begin() as db:
        leased = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        await record_failure(db, "elevenlabs", "primary", 401, stamp())
        await work.complete_stage(db, **fence(leased), result={"status": "input_failure", "asset_ids": [], "report": {}})
        job = await db.get(GenerationOperation, "job")
        assert await require_readiness(db, "series", json.loads(job.payload_json), league_id="synthetic")
        await require_provider_ready(db, "anthropic", "primary", stamp())


@pytest.mark.asyncio
async def test_api_prepares_reviewable_script_candidate_from_published_article(maker, tmp_path, monkeypatch):
    # Mutation: omit API article-to-script projection; reject structured claims as missing prose facts.
    from tests.test_recap_video_script import seed
    from app.services.generation.candidate_status import classify_candidates
    from app.services.generation.models import GenerationCandidate
    episode_id, _ = await seed(maker, tmp_path, monkeypatch)
    await work.advance_media(maker)
    async with maker.begin() as db:
        candidate = await db.scalar(select(GenerationCandidate).where(GenerationCandidate.feature == "recap_video"))
        assert json.loads(candidate.payload_json)["episode_id"] == episode_id
        status = await classify_candidates(db, [candidate], actor_id="owner")
        assert status[candidate.key]["availability"] == "available"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["worker", "expiry", "episode", "config", "policy"])
async def test_preflight_without_script_binds_lease_episode_and_configuration(maker, tmp_path, monkeypatch, change):
    # Mutation: accept preflight from wrong worker/expired lease/changed episode/configuration.
    from tests.test_recap_video_script import seed
    from app.services.generation.recap_models import RecapEpisode
    real_gate = work.require_media_preflight
    episode_id, _ = await seed(maker, tmp_path, monkeypatch)
    monkeypatch.setattr(work, "require_media_preflight", real_gate)
    monkeypatch.setenv("TRADE_GRADER_GENERATION_EXECUTION_EPOCH", "test-epoch")
    monkeypatch.setattr(work, "PREFLIGHT_CONFIG", lambda: {"voice": "synthetic-voice", "revision": 1})
    evidence = dict(episode_id=episode_id, account_alias="primary", voice_digest="synthetic-voice",
        rate_digest="synthetic-rate", qualification_revision="synthetic-qualification")
    async def validate(db, stage, submitted):
        if submitted["report"] != evidence:
            raise Held("preflight_evidence_invalid")
        return evidence
    monkeypatch.setattr(work, "RESULT_VALIDATORS", {"preflight": validate})
    async with maker.begin() as db:
        stage = await work.prepare_preflight(db, episode_id, actor_id="owner", reason="Synthetic qualification")
        assert stage.script_id == ""
        leased = await work.claim_stage(db, "narrator", {"preflight"}, stamp())
        with pytest.raises(Held, match="qualification_required"):
            await real_gate(db, episode_id)
    if change == "config":
        monkeypatch.setattr(work, "PREFLIGHT_CONFIG", lambda: {"voice": "changed", "revision": 2})
    async with maker.begin() as db:
        if change == "episode":
            (await db.get(RecapEpisode, episode_id)).facts_digest = "changed"
        if change == "policy":
            from app.services.generation.models import GenerationPolicy
            (await db.get(GenerationPolicy, "app")).revision += 1
    async with maker.begin() as db:
        with pytest.raises((Held, OwnershipLost)):
            await work.complete_stage(db, **fence(leased), result={"status": "ok", "asset_ids": [], "report": evidence},
                worker_id="other" if change == "worker" else "narrator",
                now=leased["expires_at"] if change == "expiry" else stamp())


@pytest.mark.asyncio
async def test_preflight_validated_once_and_expired_evidence_needs_new_checkpoint(maker, tmp_path, monkeypatch):
    # Mutation: opaque worker success becomes qualification, or completed preflight can replay/never expires.
    from tests.test_recap_video_script import seed
    real_gate = work.require_media_preflight
    episode_id, _ = await seed(maker, tmp_path, monkeypatch)
    monkeypatch.setattr(work, "require_media_preflight", real_gate)
    monkeypatch.setenv("TRADE_GRADER_GENERATION_EXECUTION_EPOCH", "test-epoch")
    monkeypatch.setattr(work, "PREFLIGHT_CONFIG", lambda: {"voice": "synthetic-voice", "revision": 1})
    evidence = dict(episode_id=episode_id, account_alias="primary", voice_digest="synthetic-voice",
        rate_digest="synthetic-rate", qualification_revision="synthetic-qualification")
    async def validate(db, stage, result):
        if result["report"] != {"metadata_digest": "synthetic-provider-response"}:
            raise Held("preflight_evidence_invalid")
        return evidence
    monkeypatch.setattr(work, "RESULT_VALIDATORS", {"preflight": validate})
    async with maker.begin() as db:
        stage = await work.prepare_preflight(db, episode_id, actor_id="owner", reason="Synthetic qualification")
        leased = await work.claim_stage(db, "narrator", {"preflight"}, stamp())
        with pytest.raises(Held, match="evidence_invalid"):
            await work.complete_stage(db, **fence(leased), result={"status": "ok", "asset_ids": [], "report": {"approved": True}})
        await work.complete_stage(db, **fence(leased), result={"status": "ok", "asset_ids": [], "report": {"metadata_digest": "synthetic-provider-response"}})
        assert await real_gate(db, episode_id) == evidence
        with pytest.raises(OwnershipLost):
            await work.complete_stage(db, **fence(leased), result=result(leased))
        stage.created_at = stamp() - work.PREFLIGHT_MAX_AGE
        with pytest.raises(Held, match="qualification_expired"):
            await real_gate(db, episode_id)
        renewed = await work.prepare_preflight(db, episode_id, actor_id="owner", reason="Synthetic renewed qualification")
        assert renewed.id != stage.id and renewed.revision == stage.revision + 1


@pytest.mark.asyncio
async def test_fresh_identical_preflight_reuses_completed_script_and_checkpoints(maker, tmp_path, monkeypatch):
    # Mutation: proof renewal changes compatibility digest or leaves free continuation stranded.
    real_gate = work.require_media_preflight
    episode_id, render_id = await seed_media(maker, tmp_path, monkeypatch)
    monkeypatch.setattr(work, "require_media_preflight", real_gate)
    monkeypatch.setattr(work, "PREFLIGHT_CONFIG", lambda: {"voice": "synthetic-voice"})
    evidence = dict(episode_id=episode_id, account_alias="primary", voice_digest="synthetic-voice",
        rate_digest="synthetic-rate", qualification_revision="synthetic-qualification")
    async def validate(db, stage, result):
        assert result["report"] == {"metadata": "exact"}
        return evidence
    monkeypatch.setitem(work.RESULT_VALIDATORS, "preflight", validate)
    async with maker.begin() as db:
        proof = await work.prepare_preflight(db, episode_id, actor_id="owner", reason="Synthetic first proof")
        lease = await work.claim_stage(db, "narrator", {"preflight"}, stamp())
        await work.complete_stage(db, **fence(lease), result={"status": "ok", "asset_ids": [], "report": {"metadata": "exact"}})
        rendering = await work.claim_stage(db, "renderer", {"render"}, stamp())
        await work.complete_stage(db, **fence(rendering), result=result(rendering))
        proof.created_at = stamp() - work.PREFLIGHT_MAX_AGE
        assert await work.claim_stage(db, "qa", {"media_check"}, stamp()) is None
        renewed = await work.prepare_preflight(db, episode_id, actor_id="owner", reason="Synthetic refreshed proof")
        lease = await work.claim_stage(db, "narrator", {"preflight"}, stamp())
        await work.complete_stage(db, **fence(lease), result={"status": "ok", "asset_ids": [], "report": {"metadata": "exact"}})
        assert renewed.id != proof.id
        assert await work.claim_stage(db, "qa", {"media_check"}, stamp())
        assert (await db.get(RecapStage, render_id)).state == "succeeded"
        assert (await db.get(GenerationOperation, "job")).artifact_id == "script"
        assert await db.scalar(select(RecapProviderAttempt.id)) is None


def test_renderer_cannot_claim_publication():
    # Mutation: capability membership alone permits API-owned publication.
    from app.services.recap_video.workflow import worker_can_claim
    assert worker_can_claim({"render"}, "render")
    for kind in ("publish", "analyst_refresh", "generation", "source", "script"):
        assert not worker_can_claim({kind, "render"}, kind)


@pytest.mark.asyncio
async def test_unqualified_media_preflight_fails_closed(maker):
    # Mutation: enabling policy alone authorizes unavailable paid narration.
    from app.services.recap_video.workflow import require_media_preflight
    from app.services.generation.store import Held
    async with maker.begin() as db:
        with pytest.raises(Held, match="media_qualification_required"):
            await require_media_preflight(db, "synthetic-episode")
