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
async def test_api_builds_all_ordered_chunks_at_exact_price_and_configuration(monkeypatch):
    approval = qualified(monkeypatch)
    row = SimpleNamespace(episode_id="episode", evidence_json="")
    evidence = await el.validate_preflight(None, row, {"report": approval["metadata"]})
    artifact = SimpleNamespace(digest="script-hash", payload_json=json.dumps({"episode_id": "episode", "claims": {},
        "script": {"opening": "Opening.", "closing": "Ending.", "segments": [{"id": "s1", "text": "x" * 1999}]}}))
    plan = await el.build_media_plan(None, artifact, evidence)
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
    from tests.test_recap_workflow import seed_media
    from tests.test_recap_audio import transcript
    _, stage_id = await seed_media(maker, tmp_path, monkeypatch, "speech_check")
    monkeypatch.setenv("TRADE_GRADER_MEDIA_ASSET_ROOT", str(tmp_path / "objects"))
    store = LocalPrivateMediaStore(tmp_path / "objects")
    raw = {**transcript("Avery won by forty points."), "model_revision": MODEL_REVISION,
        "model_sha256": MODEL_SHA256["model.bin"]}
    data = json.dumps(raw).encode()
    key = str(uuid.uuid4())
    sha = hashlib.sha256(data).hexdigest()
    store.put_verified(key, data, sha)
    async with maker.begin() as db:
        stage = await db.get(RecapStage, stage_id)
        stage.generation = 1
        stage.input_json = json.dumps({"script": {"segments": [{"id": "s", "text": "Avery won by fourteen points.",
            "spoken_numbers": [{"spoken": "fourteen", "value": "14"}]}]}})
        prior = await db.get(RecapStage, stage.predecessor_id)
        prior.result_json = json.dumps({"asset_ids": ["audio"]})
        db.add(RecapAsset(id="transcript", stage_id=stage_id, generation=1, digest=sha, size=len(data),
            media_type="application/json", storage_key=key))
    async with maker.begin() as db:
        stage = await db.get(RecapStage, stage_id)
        with pytest.raises(Held, match="speech_verification_failed"):
            await el.validate_speech(db, stage, {"asset_ids": ["transcript"], "report": {
                "transcript_asset_id": "transcript", "audio_asset_ids": ["audio"], "passed": True}})
