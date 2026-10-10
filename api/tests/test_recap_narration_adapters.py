import json
from types import SimpleNamespace
import pytest
from app.services.recap_video import elevenlabs as el
from app.services.generation.store import Held
from tests.test_recap_elevenlabs import RATE


def qualified(monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_ELEVENLABS_VOICE_ID", "synthetic-voice")
    account = {"user_id": "synthetic-user", "workspace_id": "synthetic-workspace"}
    monkeypatch.setenv("TRADE_GRADER_ELEVENLABS_ACCOUNT_IDENTITY_DIGEST", el.canonical(account))
    async def reader(db, episode):
        return approval
    monkeypatch.setattr(el, "QUALIFICATION_READER", reader)
    approval = {"revision": "durable-1", "config": el.preflight_config(), "rate_snapshot": RATE.copy(),
        "metadata": {"provenance": "elevenlabs-readonly-v1", "account": account, "voice": {"voice_id": "synthetic-voice"},
            "model": {"model_id": "eleven_v4", "can_do_text_to_speech": True},
            "subscription": {"tier": "creator", "status": "active"}}}
    return approval


@pytest.mark.asyncio
async def test_preflight_persists_metadata_and_renewal_keeps_compatibility(monkeypatch):
    approval = qualified(monkeypatch)
    first = SimpleNamespace(episode_id="episode", evidence_json="")
    second = SimpleNamespace(episode_id="episode", evidence_json="")
    result = {"report": approval["metadata"], "asset_ids": []}
    evidence = await el.validate_preflight(None, first, result)
    assert evidence == await el.validate_preflight(None, second, result)
    assert json.loads(first.evidence_json)["metadata"] == approval["metadata"]
    with pytest.raises(Held):
        await el.validate_preflight(None, second, {"report": {**approval["metadata"], "qualification_revision": "worker-invented"}})
    approval["rate_snapshot"] = {}
    with pytest.raises(Held, match="media_rate_unqualified"):
        await el.validate_preflight(None, second, result)


@pytest.mark.asyncio
async def test_api_builds_all_ordered_chunks_at_exact_price_and_configuration(maker, tmp_path, monkeypatch):
    from tests.test_recap_speech_reviews import reviewed_artifact
    from app.services.generation.models import ContentArtifact
    from app.services.generation.store import digest, dump
    episode_id, _ = await reviewed_artifact(maker, tmp_path, monkeypatch)
    approval = qualified(monkeypatch)
    row = SimpleNamespace(episode_id=episode_id, evidence_json="")
    evidence = await el.validate_preflight(None, row, {"report": approval["metadata"]})
    async with maker.begin() as db:
        artifact = await db.get(ContentArtifact, "script")
        payload = json.loads(artifact.payload_json)
        payload["script"]["segments"][0]["text"] = "x" * 1999
        artifact.payload_json, artifact.digest = dump(payload), digest(payload)
        plan = await el.build_media_plan(db, artifact, evidence)
    assert [s["kind"] for s in plan] == ["narrate", "narrate", "narrate", "speech_check", "render", "media_check"]
    for s in plan[:3]:
        paid = s["input"]["paid"]
        assert paid["request"]["model_id"] == "eleven_v4"
        assert paid["request"]["inputs"][0]["voice_id"] == "synthetic-voice"
        assert paid["max_microusd"] == len(paid["request"]["inputs"][0]["text"]) * 7
    approval["revision"] = "durable-2"
    with pytest.raises(Held):
        await el.build_media_plan(None, artifact, evidence)


def test_durable_qualification_is_required_even_when_voice_configured(monkeypatch):
    monkeypatch.setattr(el, "QUALIFICATION_READER", None)
    with pytest.raises(Held):
        el.preflight_config()


@pytest.mark.asyncio
async def test_same_plan_different_account_cannot_qualify(monkeypatch):
    approval = qualified(monkeypatch)
    approval["metadata"]["account"]["workspace_id"] = "other-workspace"
    with pytest.raises(Held, match="media_preflight_account_changed"):
        await el.validate_preflight(None, SimpleNamespace(episode_id="episode"), {"report": approval["metadata"]})


@pytest.mark.asyncio
async def test_api_reads_immutable_raw_speech_and_rejects_worker_success_boolean(maker, tmp_path, monkeypatch):
    import hashlib
    import uuid
    from app.services.recap_video.audio import MODEL_REVISION, MODEL_SHA256
    from app.services.recap_video.storage import LocalPrivateMediaStore
    from app.services.generation.recap_models import RecapStage, RecapAsset
    from tests.test_recap_speech_reviews import reviewed_artifact
    from app.services.generation.models import ContentArtifact
    from app.services.generation.store import digest, dump
    from app.services.recap_video.speech_reviews import bind_reviews
    from tests.test_recap_audio import transcript
    _, stage_id = await reviewed_artifact(maker, tmp_path, monkeypatch)
    monkeypatch.setenv("TRADE_GRADER_MEDIA_ASSET_ROOT", str(tmp_path / "objects"))
    store = LocalPrivateMediaStore(tmp_path / "objects")
    raw = {**transcript("Welcome. Avery won by forty points. That is all."), "model_revision": MODEL_REVISION,
        "model_sha256": MODEL_SHA256["model.bin"]}
    data = json.dumps(raw).encode()
    key = str(uuid.uuid4())
    sha = hashlib.sha256(data).hexdigest()
    store.put_verified(key, data, sha)
    async with maker.begin() as db:
        stage = await db.get(RecapStage, stage_id)
        stage.generation = 1
        artifact = await db.get(ContentArtifact, "script")
        payload = json.loads(artifact.payload_json)
        payload["script"]["segments"][0]["text"] = "Avery won by fourteen points."
        artifact.payload_json, artifact.digest = dump(payload), digest(payload)
        stage.input_json = dump({"script": payload["script"], "script_digest": artifact.digest,
            "speech_review": await bind_reviews(db, artifact)})
        prior = await db.get(RecapStage, stage.predecessor_id)
        prior.result_json = json.dumps({"asset_ids": ["audio"]})
        db.add(RecapAsset(id="transcript", stage_id=stage_id, generation=1, digest=sha, size=len(data),
            media_type="application/json", storage_key=key))
    async with maker.begin() as db:
        stage = await db.get(RecapStage, stage_id)
        with pytest.raises(Held, match="speech_verification_failed"):
            await el.validate_speech(db, stage, {"asset_ids": ["transcript"], "report": {
                "transcript_asset_id": "transcript", "audio_asset_ids": ["audio"], "passed": True}})


@pytest.mark.asyncio
@pytest.mark.parametrize("text,passes", [("Welcome. Averie and Blake tied. That is all.", True),
    ("Welcome. Averie and Blake won. That is all.", False),
    ("Welcome. Avery and Brock tied. That is all.", False)])
async def test_canonical_artifact_review_reaches_speech_verifier(maker, tmp_path, monkeypatch, text, passes):
    import hashlib
    import uuid
    from tests.test_recap_speech_reviews import reviewed_artifact, approve
    from tests.test_recap_audio import transcript
    from app.services.recap_video.audio import MODEL_REVISION, MODEL_SHA256
    from app.services.recap_video.storage import LocalPrivateMediaStore
    from app.services.generation.models import ContentArtifact
    from app.services.generation.recap_models import RecapStage, RecapAsset
    from app.services.generation.store import dump
    episode_id, stage_id = await reviewed_artifact(maker, tmp_path, monkeypatch)
    approval = qualified(monkeypatch)
    evidence = await el.validate_preflight(None, SimpleNamespace(episode_id=episode_id), {"report": approval["metadata"]})
    raw = {**transcript(text), "model_revision": MODEL_REVISION, "model_sha256": MODEL_SHA256["model.bin"],
        "name_aliases": {"Blake": ["Brock"]}}
    data, key = json.dumps(raw).encode(), str(uuid.uuid4())
    sha = hashlib.sha256(data).hexdigest()
    monkeypatch.setenv("TRADE_GRADER_MEDIA_ASSET_ROOT", str(tmp_path / "objects"))
    LocalPrivateMediaStore(tmp_path / "objects").put_verified(key, data, sha)
    async with maker.begin() as db:
        review = await approve(db)
        artifact = await db.get(ContentArtifact, "script")
        plan = await el.build_media_plan(db, artifact, evidence)
        stage = await db.get(RecapStage, stage_id)
        stage.input_json = dump(next(p["input"] for p in plan if p["kind"] == "speech_check"))
        prior = await db.get(RecapStage, stage.predecessor_id)
        prior.result_json = dump({"asset_ids": ["audio"]})
        db.add(RecapAsset(id="transcript", stage_id=stage_id, generation=stage.generation,
            digest=sha, size=len(data), media_type="application/json", storage_key=key))
    async with maker.begin() as db:
        stage = await db.get(RecapStage, stage_id)
        result = {"asset_ids": ["transcript"], "report": {"transcript_asset_id": "transcript",
            "audio_asset_ids": ["audio"], "passed": True, "name_aliases": {"Blake": ["Brock"]}}}
        if passes:
            await el.validate_speech(db, stage, result)
            saved = json.loads(stage.evidence_json)
            assert saved["passed"] is True
            assert saved["speech_review"]["rules"][0]["id"] == review.id
            assert saved["speech_review"]["script_digest"] == artifact.digest
        else:
            with pytest.raises(Held, match="speech_verification_failed"):
                await el.validate_speech(db, stage, result)
