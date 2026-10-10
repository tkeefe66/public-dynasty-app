import json
from copy import deepcopy

import pytest
from app.services.generation.models import ContentArtifact
from app.services.generation.recap_models import RecapEpisode
from app.services.generation.store import Held, digest, dump
from tests.test_recap_workflow import seed_media


async def reviewed_artifact(maker, tmp_path, monkeypatch):
    episode, stage_id = await seed_media(maker, tmp_path, monkeypatch, "speech_check")
    from sleeper_dynasty.llm.recap_video_writer import Script
    async with maker.begin() as db:
        artifact = await db.get(ContentArtifact, "script")
        payload = json.loads(artifact.payload_json)
        payload["claims"]["owners"][0]["name"] = "Avery"
        payload["claims"]["owners"][1]["name"] = "Blake"
        payload["script"]["opening"] = "Welcome."
        payload["script"]["closing"] = "That is all."
        payload["script"]["segments"][0]["text"] = "Avery and Blake tied."
        strict = {k: v for k, v in payload["script"].items() if k != "reviews"}
        payload["script"] = {**Script.model_validate(strict).model_dump(), "reviews": payload["script"]["reviews"]}
        artifact.payload_json, artifact.digest = dump(payload), digest(payload)
    return episode, stage_id


async def approve(db, **changes):
    from app.services.recap_video.speech_reviews import approve_spellings
    payload = json.loads((await db.get(ContentArtifact, "script")).payload_json)
    args = dict(script_id="script", entity_kind="owner", entity_id=payload["claims"]["owners"][0]["id"],
        canonical_token="Avery", aliases=["Averie"], actor_id="owner", reason="Reviewed same person spelling", reusable=True)
    return await approve_spellings(db, **{**args, **changes})


@pytest.mark.asyncio
async def test_review_reuses_only_same_bound_entity_name_series_and_season(maker, tmp_path, monkeypatch):
    from app.services.recap_video.speech_reviews import bind_reviews
    episode_id, _ = await reviewed_artifact(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        review = await approve(db)
        original = await db.get(ContentArtifact, "script")
        payload = json.loads(original.payload_json)
        next_script = ContentArtifact(id="next-script", series_id="series", league_id="synthetic",
            feature="recap_video", subject="next", revision=2, provenance="managed",
            payload_json=original.payload_json, digest=original.digest)
        db.add(next_script)
        await db.flush()
        binding = await bind_reviews(db, next_script)
        assert binding["aliases"] == {"avery": ["averie"]}
        assert binding["script_id"] == "next-script" and binding["script_revision"] == 2
        assert binding["rules"][0]["id"] == review.id
        assert binding["rules"][0]["script_id"] == "script"
        assert binding["rules"][0]["reviewer_id"] == "owner"
        for field, value in (("id", "different-person"), ("name", "Avery Changed")):
            changed = deepcopy(payload)
            changed["claims"]["owners"][0][field] = value
            next_script.payload_json, next_script.digest = dump(changed), digest(changed)
            assert (await bind_reviews(db, next_script))["aliases"] == {}
        next_script.payload_json, next_script.digest = dump(payload), digest(payload)
        episode = await db.get(RecapEpisode, episode_id)
        episode.season += 1
        assert (await bind_reviews(db, next_script))["aliases"] == {}
        episode.season -= 1
        episode.series_id = next_script.series_id = "different-series"
        assert (await bind_reviews(db, next_script))["aliases"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [dict(canonical_token="tied", aliases=["tide"]),
    dict(canonical_token="fourteen", aliases=["forty"]), dict(canonical_token="not", aliases=["now"]),
    dict(aliases=["Blake"]), dict(actor_id="worker"), dict(entity_id="roster-slot-1")])
async def test_review_rejects_semantic_substitution_or_missing_authority(maker, tmp_path, monkeypatch, changes):
    await reviewed_artifact(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        with pytest.raises((Held, ValueError)):
            await approve(db, **changes)


@pytest.mark.asyncio
async def test_binding_rejects_worker_aliases_and_changed_artifact_revision(maker, tmp_path, monkeypatch):
    from app.services.recap_video.speech_reviews import bind_reviews, validate_binding
    from app.services.generation.recap_models import RecapStage
    _, stage_id = await reviewed_artifact(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        await approve(db)
        artifact = await db.get(ContentArtifact, "script")
        stage = await db.get(RecapStage, stage_id)
        inputs = dict(script=json.loads(artifact.payload_json)["script"], script_digest=artifact.digest,
            speech_review=await bind_reviews(db, artifact))
        assert await validate_binding(db, stage, inputs) == inputs["speech_review"]
        changed = deepcopy(inputs)
        changed["speech_review"]["aliases"]["blake"] = ["brock"]
        with pytest.raises(Held, match="speech_review_binding_changed"):
            await validate_binding(db, stage, changed)
        artifact.revision += 1
        with pytest.raises(Held, match="speech_review_binding_changed"):
            await validate_binding(db, stage, inputs)


@pytest.mark.asyncio
async def test_player_review_uses_source_player_identity(maker, tmp_path, monkeypatch):
    from app.services.recap_video.speech_reviews import bind_reviews
    await reviewed_artifact(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        artifact = await db.get(ContentArtifact, "script")
        payload = json.loads(artifact.payload_json)
        payload["claims"]["claims"][0]["operands"].append({"player_id": "synthetic-player", "name": "Taylor"})
        payload["script"]["opening"] = "Taylor played."
        artifact.payload_json, artifact.digest = dump(payload), digest(payload)
        await approve(db, entity_kind="player", entity_id="synthetic-player", canonical_token="Taylor", aliases=["Tayler"])
        assert (await bind_reviews(db, artifact))["aliases"] == {"taylor": ["tayler"]}
        payload["claims"]["claims"][0]["operands"][-1]["player_id"] = "different-player"
        artifact.payload_json, artifact.digest = dump(payload), digest(payload)
        assert (await bind_reviews(db, artifact))["aliases"] == {}


def test_generated_script_cannot_grant_aliases():
    from sleeper_dynasty.llm.recap_video_writer import Script
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as exc:
        Script.model_validate({"article_digest": "a" * 64, "opening": "Welcome", "closing": "Goodbye",
            "premises": [], "segments": [{"id": "s", "owner_ids": [], "matchup_ids": [], "claim_ids": [],
                "text": "Avery tied", "spoken_numbers": []}], "name_aliases": {"Avery": ["Blake"]}})
    assert any(e["loc"] == ("name_aliases",) and e["type"] == "extra_forbidden" for e in exc.value.errors())


@pytest.mark.asyncio
async def test_review_rechecks_admin_permission(maker, tmp_path, monkeypatch):
    from app.db.models import User
    await reviewed_artifact(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        (await db.get(User, "owner")).is_admin = False
        with pytest.raises(Held, match="admin_permission_removed"):
            await approve(db)


@pytest.mark.asyncio
async def test_exact_script_review_does_not_imply_reuse(maker, tmp_path, monkeypatch):
    from app.services.recap_video.speech_reviews import bind_reviews
    await reviewed_artifact(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        await approve(db, reusable=False)
        artifact = await db.get(ContentArtifact, "script")
        assert (await bind_reviews(db, artifact))["aliases"] == {"avery": ["averie"]}
        artifact.revision += 1
        assert (await bind_reviews(db, artifact))["aliases"] == {}
