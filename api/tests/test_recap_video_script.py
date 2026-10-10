"""Task 5 synthetic integration: durable evidence and zero-send spending fences."""
import json

import pytest
from sqlalchemy import select

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationOperation, GenerationOutbox, GenerationPolicy
from app.services.generation.policy import Policy
from app.services.generation.recap_models import RecapEpisode, RecapObservation, RecapBudgetAllocation
from app.services.generation.store import Held, digest, dump


def approved_payload(saved):
    script = {"article_digest": saved["published_article"]["digest"], "opening": "Cal Mercer is already annoyed.",
        "closing": "This league did it again.", "premises": [],
        "segments": [{"id": c["id"], "owner_ids": c["owner_ids"], "matchup_ids": c["matchup_ids"],
            "claim_ids": [c["id"]], "text": "Both owners tied this matchup.", "spoken_numbers": []}
            for c in saved["claims"]["claims"] if c["kind"] == "result"]}
    script["reviews"] = [{"approved": True, "issues": [], "checked_segment_ids": ["opening", "closing", *[s["id"] for s in script["segments"]]],
        "checks": {k: True for k in ("facts", "article_agreement", "coverage", "spoken_numbers", "premise_variety")}}]
    return {"script": script, "claims": saved["claims"], "episode_id": saved["episode_id"],
        "article_digest": saved["published_article"]["digest"], "source_digest": saved["source_digest"],
        "recap_facts_digest": saved["recap_facts_digest"]}


async def seed(maker, tmp_path, monkeypatch):
    from app.config import get_settings
    from app.services.generation.recap_budget import episode_identity
    from app.services.recap_video.readiness import competitive_digest
    from app.services.recap_video.collector import edition_from_snapshot
    from app.services.recap_video.periods import build_participants
    from tests.test_generation_gateway import seed_job
    from tests.test_recap_readiness import snapshot
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "owner@test.local")
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    await seed_job(maker)
    from app.services.recap_video import workflow
    async def qualified(db, episode_id):
        return dict(episode_id=episode_id, account_alias="primary", voice_digest="synthetic-voice",
            rate_digest="synthetic-rate", qualification_revision="synthetic-qualification")
    monkeypatch.setattr(workflow, "require_media_preflight", qualified)
    source = snapshot()
    source.update(build_participants(source["participants"], source["scores"], source["bracket"], source))
    source["player_metadata"] = {"available": False}
    facts = competitive_digest(source)
    ident = episode_identity("series", 2026, "4")
    edition = {**edition_from_snapshot(source, generated_at=1), "edition_type": "roast", "markdown": "Correct published roast.", "revision": 1}
    async with maker.begin() as db:
        policy = Policy(paused=False)
        policy.features["recap_video"].mode = "manual"
        (await db.get(GenerationPolicy, "app")).value_json = dump(policy.model_dump())
        row = RecapObservation(id="observation", episode_id=ident, observed_at=4600,
            snapshot_json=dump(source), snapshot_digest=digest(source), facts_digest=facts, decision="ready")
        db.add(row)
        db.add(RecapEpisode(episode_id=ident, series_id="series", season=2026, period_id="4",
            league_id="synthetic", week=4, nfl_weeks_json="[4]", lifecycle="ready", admitted_at=1,
            facts_digest=facts, source_digest=digest(source), article_digest=digest(edition), latest_observation_id="observation"))
        db.add(ContentArtifact(id="article", series_id="series", league_id="synthetic", feature="analyst",
            subject="article-subject", revision=1, payload_json=dump(edition), digest=digest(edition),
            facts_json=dump({"recap_facts_digest": facts}), provenance="managed"))
        db.add(ArtifactHead(subject="article-subject", artifact_id="article", revision=1))
        db.add(GenerationOutbox(key="artifact:article", kind="artifact", payload_json=dump({"artifact_id": "article"}), delivered=True))
    from app.services.recap_video.contracts import prepare_script
    async with maker.begin() as db:
        saved = await prepare_script(db, ident, cache_dir=tmp_path)
        saved["media_qualification_digest"] = digest(await qualified(db, ident))
        job = await db.get(GenerationOperation, "job")
        job.feature, job.max_calls, job.subject = "recap_video", 4, "video-subject"
        job.payload_json, job.request_digest = dump(saved), digest(saved)
        job.policy_json = dump({"policy": policy.model_dump()})
    return ident, saved


def test_missing_feature_disabled_and_fixed_stage_plan():
    # Mutation: missing video policy inherits enabled manual, or reserves only first call as written.
    from app.services.generation.accounting import bounded_plan
    policy = Policy(features={"analyst": {"max_calls": 2}})
    assert policy.features["recap_video"].mode == "disabled"
    config = policy.features["recap_video"].model_dump()
    config["model"] = "claude-haiku-4-5-20251001"
    plan = bounded_plan("job", "recap_video", config, config, 4)
    assert len(plan) == 4 and {a["category"] for a in plan} == {"video"}
    assert [a["rate_snapshot"]["model"] for a in plan] == [config["model"], *[config["review_model"]]*3]


@pytest.mark.asyncio
async def test_low_video_cap_prevents_first_transport(maker, tmp_path, monkeypatch):
    # Mutation: treat recap_video as unrelated managed spend or reserve just draft.
    from app.services.generation.gateway import Gateway
    from app.services.generation.recap_budget import RecapCaps, save_caps
    from tests.test_generation_gateway import REQUEST, BODY, FakeTransport
    await seed(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        await save_caps(db, "series", RecapCaps(video_episode_microusd=1_000_000), 0, "owner", "Synthetic cap", False)
    request = {**REQUEST, "model": "claude-sonnet-4-6"}
    transport = FakeTransport(body=json.dumps({**BODY, "model": request["model"]}))
    with pytest.raises(Held, match="recap_budget_video_episode"):
        await Gateway(maker, transport, epoch="test-epoch").invoke("job", 1, 1, request)
    assert transport.sends == 0


@pytest.mark.asyncio
async def test_later_stage_uses_reserved_immutable_price(maker, tmp_path, monkeypatch):
    # Mutation: gateway re-prices later stages instead of copying the full-plan rate snapshot.
    from app.services.generation import accounting
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import ProviderAttempt
    from tests.test_generation_gateway import REQUEST, BODY, FakeTransport
    await seed(maker, tmp_path, monkeypatch)
    request = {**REQUEST, "model": "claude-sonnet-4-6"}
    gateway = Gateway(maker, FakeTransport(body=json.dumps({**BODY, "model": request["model"]})), epoch="test-epoch")
    await gateway.invoke("job", 1, 1, request)
    monkeypatch.setitem(accounting.RATES, request["model"], ("1", "5"))
    await gateway.invoke("job", 1, 2, request)
    async with maker() as db:
        attempt = await db.scalar(select(ProviderAttempt).where(ProviderAttempt.stage == 2))
        assert json.loads(attempt.pricing_json)["input"] == "3"
        assert attempt.cost_microusd == 105


@pytest.mark.asyncio
async def test_review_model_policy_change_stops_next_paid_stage(maker, tmp_path, monkeypatch):
    # Mutation: review stages use draft-only model check or ignore changed current policy.
    from app.services.generation.gateway import Gateway
    from tests.test_generation_gateway import REQUEST, BODY, FakeTransport
    await seed(maker, tmp_path, monkeypatch)
    request = {**REQUEST, "model": "claude-sonnet-4-6"}
    transport = FakeTransport(body=json.dumps({**BODY, "model": request["model"]}))
    gateway = Gateway(maker, transport, epoch="test-epoch")
    await gateway.invoke("job", 1, 1, request)
    async with maker.begin() as db:
        policy = await db.get(GenerationPolicy, "app")
        value = json.loads(policy.value_json)
        value["features"]["recap_video"]["review_model"] = "claude-haiku-4-5-20251001"
        policy.value_json = dump(value)
    with pytest.raises(Held, match="request_model_changed"):
        await gateway.invoke("job", 1, 2, request)
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_published_revision_and_projection_are_required(maker, tmp_path, monkeypatch):
    # Mutation: successful operation or existing article alone counts as reader publication.
    from app.services.recap_video.contracts import require_script_inputs
    ident, saved = await seed(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        item = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == "artifact:article"))
        item.delivered = False
    async with maker.begin() as db:
        with pytest.raises(Held, match="recap_article_unpublished"):
            await require_script_inputs(db, "series", "synthetic", saved)
    async with maker.begin() as db:
        item = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == "artifact:article"))
        item.delivered = True
        (await db.get(ArtifactHead, "article-subject")).revision = 2
    async with maker.begin() as db:
        with pytest.raises(Held, match="recap_article_changed"):
            await require_script_inputs(db, "series", "synthetic", saved)


@pytest.mark.asyncio
async def test_observation_churn_allowed_competitive_change_held(maker, tmp_path, monkeypatch):
    # Mutation: compare latest whole snapshot digest, or skip canonical competitive fence.
    from app.services.recap_video.contracts import require_script_inputs
    from app.services.recap_video.readiness import competitive_digest
    ident, saved = await seed(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        original = await db.get(RecapObservation, "observation")
        source = json.loads(original.snapshot_json)
        source.update(observed_at=9999, news="unrelated")
        db.add(RecapObservation(id="later", episode_id=ident, observed_at=9999, snapshot_json=dump(source),
            snapshot_digest=digest(source), facts_digest=competitive_digest(source), decision="ready"))
        row = await db.get(RecapEpisode, ident)
        row.latest_observation_id, row.source_digest = "later", digest(source)
    async with maker.begin() as db:
        await require_script_inputs(db, "series", "synthetic", saved)
        row = await db.get(RecapEpisode, ident)
        row.facts_digest = "corrected-score"
    async with maker.begin() as db:
        with pytest.raises(Held, match="recap_facts_changed"):
            await require_script_inputs(db, "series", "synthetic", saved)


@pytest.mark.asyncio
async def test_video_reserved_as_full_plan(maker, tmp_path, monkeypatch):
    # Mutation: reserve only first draft, or bill later stages outside video category.
    from app.services.generation.gateway import Gateway
    from app.services.generation.features import ValidatedOutput
    from app.services.generation.artifacts import save_artifact
    from tests.test_generation_gateway import REQUEST, BODY, FakeTransport
    _, saved = await seed(maker, tmp_path, monkeypatch)
    request = {**REQUEST, "model": "claude-sonnet-4-6"}
    transport = FakeTransport(body=json.dumps({**BODY, "model": request["model"]}))
    gateway = Gateway(maker, transport, epoch="test-epoch")
    await gateway.invoke("job", 1, 1, request)
    async with maker() as db:
        allocations = list((await db.scalars(select(RecapBudgetAllocation))).all())
        assert len(allocations) == 4 and {a.category for a in allocations} == {"video"}
    await gateway.invoke("job", 1, 2, request)


@pytest.mark.asyncio
async def test_unresolved_review_cannot_be_saved_as_script(maker, tmp_path, monkeypatch):
    # Mutation: trust ValidatedOutput wrapper without checking final script review.
    from app.services.generation.gateway import Gateway
    from app.services.generation.features import ValidatedOutput
    from app.services.generation.artifacts import save_artifact
    from tests.test_generation_gateway import REQUEST, BODY, FakeTransport
    _, saved = await seed(maker, tmp_path, monkeypatch)
    request = {**REQUEST, "model": "claude-sonnet-4-6"}
    gateway = Gateway(maker, FakeTransport(body=json.dumps({**BODY, "model": request["model"]})), epoch="test-epoch")
    await gateway.invoke("job", 1, 1, request)
    await gateway.invoke("job", 1, 2, request)
    payload = approved_payload(saved)
    payload["script"]["reviews"][-1]["approved"] = False
    async with maker.begin() as db:
        with pytest.raises(Held, match="recap_script_unapproved"):
            await save_artifact(db, "job", 1, ValidatedOutput(payload, digest(payload), digest(saved), 2))


@pytest.mark.asyncio
async def test_relevant_cached_metadata_bound_unrelated_players_ignored(maker, tmp_path, monkeypatch):
    # Mutation: trust submitted player names/positions, or invalidate on unrelated player refresh.
    from app.services.recap_video.contracts import prepare_script, require_script_inputs
    ident, _ = await seed(maker, tmp_path, monkeypatch)
    players = {"p1": {"full_name": "Synthetic Quarterback", "fantasy_positions": ["QB"]},
               "p2": {"full_name": "Synthetic Runner", "fantasy_positions": ["RB"]},
               "p3": {"full_name": "Synthetic Bench", "fantasy_positions": ["RB"]}}
    (tmp_path / "players.json").write_text(dump(players))
    async with maker.begin() as db:
        saved = await prepare_script(db, ident, cache_dir=tmp_path)
        assert saved["player_evidence"]["available"]
        assert any(c["kind"] == "starters" for c in saved["claims"]["claims"])
    players["unrelated"] = {"full_name": "Not Rostered", "fantasy_positions": ["QB"]}
    (tmp_path / "players.json").write_text(dump(players))
    async with maker.begin() as db:
        await require_script_inputs(db, "series", "synthetic", saved)
    players["p1"]["fantasy_positions"] = ["WR"]
    (tmp_path / "players.json").write_text(dump(players))
    async with maker.begin() as db:
        with pytest.raises(Held, match="recap_player_evidence_changed"):
            await require_script_inputs(db, "series", "synthetic", saved)


@pytest.mark.asyncio
async def test_malformed_optional_metadata_preserves_required_coverage(maker, tmp_path, monkeypatch):
    # Mutation: malformed optional player record aborts required matchup/owner script facts.
    from app.services.recap_video.contracts import prepare_script
    ident, _ = await seed(maker, tmp_path, monkeypatch)
    (tmp_path / "players.json").write_text(dump({"p1": None, "p2": {"first_name": 42}}))
    async with maker.begin() as db:
        saved = await prepare_script(db, ident, cache_dir=tmp_path)
    assert saved["claims"]["owner_ids"] == ["owner-1", "owner-2"]
    assert any(c["kind"] == "starters" for c in saved["claims"]["claims"])


@pytest.mark.asyncio
async def test_latest_six_premises_only_from_explicit_published_selections(maker, tmp_path, monkeypatch):
    # Mutation: use all artifact heads, include unpublished correction, count revisions as episodes or cross leagues.
    from app.services.recap_video.contracts import recent_premises
    await seed(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        for i in range(8):
            for revision in (1, 2):
                db.add(ContentArtifact(id=f"script-{i}-{revision}", series_id="series", league_id="synthetic", feature="recap_video",
                    subject=f"video-{i}", revision=revision, digest=f"digest-{i}-{revision}",
                    payload_json=dump({"episode_id": f"episode-{i}", "script": {"premises": [{"premise": f"Premise {i} revision {revision}",
                        "punchline": "Punchline", "owner_ids": ["owner-1"]}]}}), facts_json="{}", provenance="managed"))
        await db.flush()
        ids = [f"script-{i}-1" for i in range(7, -1, -1)]
        history = await recent_premises(db, "series", ids)
        assert [h["episode_id"] for h in history] == [f"episode-{i}" for i in range(7, 1, -1)]
        assert all("revision 1" in h["premises"][0]["premise"] for h in history)
        assert await recent_premises(db, "series", []) == []
        with pytest.raises(Held, match="recap_published_selection_invalid"):
            await recent_premises(db, "other-series", ids)


@pytest.mark.asyncio
async def test_managed_writer_checkpoint_to_durable_private_script(maker, tmp_path, monkeypatch):
    # Mutation: skip real managed adapter, lose script on save, or leak raw source snapshot into prompt.
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway
    from app.services.generation.artifacts import save_artifact
    from app.services.generation.transport import Receipt
    from tests.test_generation_gateway import BODY
    _, saved = await seed(maker, tmp_path, monkeypatch)
    script = {"article_digest": saved["published_article"]["digest"], "opening": "Cal Mercer is already annoyed.",
        "closing": "This league did it again.", "premises": [],
        "segments": [{"id": c["id"], "owner_ids": c["owner_ids"], "matchup_ids": c["matchup_ids"],
            "claim_ids": [c["id"]], "text": "Both owners tied this matchup.", "spoken_numbers": []}
            for c in saved["claims"]["claims"] if c["kind"] == "result"]}
    review = {"approved": True, "issues": [], "checked_segment_ids": ["opening", "closing", *[s["id"] for s in script["segments"]]],
        "checks": {k: True for k in ("facts", "article_agreement", "coverage", "spoken_numbers", "premise_variety")}}
    class Transport:
        requests = []
        async def send(self, request):
            self.requests.append(request)
            tool = request["tools"][0]["name"]
            value = review if tool == "review_script" else script
            return Receipt(200, dump({**BODY, "model": request["model"], "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "id": f"synthetic-{len(self.requests)}", "name": tool, "input": value}]}), {})
    transport = Transport()
    async with maker() as db:
        job = await db.get(GenerationOperation, "job")
    result = await generate(job, Gateway(maker, transport, epoch="test-epoch"))
    assert result.stages == 2
    assert all("source_snapshot" not in dump(r) and "observed_games" not in dump(r) for r in transport.requests)
    async with maker.begin() as db:
        artifact = await save_artifact(db, "job", 1, result)
        persisted = json.loads(artifact.payload_json)
        assert persisted["script"]["segments"] == script["segments"]
        assert persisted["script"]["reviews"][-1] == review
        assert persisted["claims"] == saved["claims"]
        assert artifact.feature == "recap_video"
        assert await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == "artifact:" + artifact.id)) is None
        allocations = list((await db.scalars(select(RecapBudgetAllocation))).all())
        assert all(a.outstanding_microusd == 0 for a in allocations)
