import json
import pytest
from sqlalchemy import select
from app.services.generation.models import stamp
from app.services.generation.recap_models import RecapProviderAttempt, RecapStage, RecapBudgetAllocation
from app.services.generation.store import Conflict, OwnershipLost, dump
from app.services.recap_video import workflow as work
from tests.test_recap_workflow import seed_media, fence, result


@pytest.mark.asyncio
async def test_early_identity_then_unknown_recovery_retains_evidence_and_never_dispatches(maker, tmp_path, monkeypatch):
    episode, _ = await seed_media(maker, tmp_path, monkeypatch, "narrate")
    async with maker.begin() as db:
        lease = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        authority = await work.authorize_dispatch(db, **fence(lease), worker_id="narrator")
    attempt_id = authority["attempt_id"]
    async with maker.begin() as db:
        await work.persist_identity(db, attempt_id, {"request_id": "synthetic-request"}, worker_id="narrator")
    async with maker.begin() as db:
        await work.persist_identity(db, attempt_id, {"request_id": "synthetic-request", "history_item_id": "synthetic-history"}, worker_id="narrator")
        recovery = await work.recovery_evidence(db, attempt_id, worker_id="narrator")
        assert recovery["identity"]["history_item_id"] == "synthetic-history"
        assert "dispatch_authority" not in recovery
    with pytest.raises(Conflict):
        async with maker.begin() as db:
            await work.persist_identity(db, attempt_id, {"request_id": "different"}, worker_id="narrator")
    unknown = {"status": 0, "identity": {"request_id": "synthetic-request"}}
    async with maker.begin() as db:
        await work.record_receipt(db, attempt_id, unknown, worker_id="narrator")
        await work.cancel_media(db, episode, "owner", "synthetic cancel")
    monkeypatch.setitem(work.RECEIPT_SETTLERS, "elevenlabs", lambda req, rate, receipt: ("received", 17, "response_invalid"))
    known = {"status": 200, "identity": {"request_id": "synthetic-request", "history_item_id": "synthetic-history"},
        "audio_sha256": "a" * 64, "audio_size": 12}
    async with maker.begin() as db:
        await work.persist_recovery_receipt(db, attempt_id, known, worker_id="narrator")
    async with maker.begin() as db:
        await work.settle_receipt(db, attempt_id, worker_id="narrator")
        await work.persist_recovery_receipt(db, attempt_id, known, worker_id="narrator")
        a = await db.get(RecapProviderAttempt, attempt_id)
        assert a.receipt_json == dump(unknown)
        assert a.recovery_receipt_json == dump(known)
        assert a.cost_microusd == 17 and a.error_code == "response_invalid"
        allocation = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id == attempt_id))
        assert allocation.actual_microusd == 17
        assert (await db.get(RecapStage, lease["stage_id"])).state == "cancelled"
    with pytest.raises(OwnershipLost):
        async with maker.begin() as db:
            await work.complete_stage(db, **fence(lease), result=result(lease), worker_id="narrator")
    with pytest.raises(Conflict):
        async with maker.begin() as db:
            await work.persist_recovery_receipt(db, attempt_id, {**known, "audio_sha256": "b" * 64}, worker_id="narrator")
    with pytest.raises(OwnershipLost):
        async with maker.begin() as db:
            await work.recovery_evidence(db, attempt_id, worker_id="different-worker")


@pytest.mark.asyncio
async def test_receipt_rejects_audio_and_secrets_before_persistence(maker, tmp_path, monkeypatch):
    await seed_media(maker, tmp_path, monkeypatch, "narrate")
    async with maker.begin() as db:
        lease = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        a = await work.authorize_dispatch(db, **fence(lease), worker_id="narrator")
    from app.services.generation.store import Held
    for bad in ({"audio_base64": "unsafe"}, {"nested": {"api_key": "unsafe"}}):
        with pytest.raises(Held):
            async with maker.begin() as db:
                await work.persist_receipt(db, a["attempt_id"], bad, worker_id="narrator")


@pytest.mark.asyncio
async def test_http_recovery_retains_private_audio_after_cancel_without_selection(app, maker, tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.routes import media_worker as routes
    from app.services.recap_video.elevenlabs import canonical
    import hashlib
    episode, _ = await seed_media(maker, tmp_path, monkeypatch, "narrate")
    monkeypatch.setenv("TRADE_GRADER_MEDIA_WORKER_TOKEN", "synthetic-worker-secret-" * 3)
    monkeypatch.setenv("TRADE_GRADER_MEDIA_WORKER_ID", "narrator")
    monkeypatch.setenv("TRADE_GRADER_MEDIA_WORKER_CAPABILITIES", "narrate")
    monkeypatch.setenv("TRADE_GRADER_MEDIA_ASSET_ROOT", str(tmp_path / "audio"))
    monkeypatch.setattr(routes, "get_sessionmaker", lambda: maker)
    async with maker.begin() as db:
        lease = await work.claim_stage(db, "narrator", {"narrate"}, stamp())
        authority = await work.authorize_dispatch(db, **fence(lease), worker_id="narrator")
        await work.cancel_media(db, episode, "owner", "synthetic cancellation")
    attempt_id = authority["attempt_id"]
    headers = {"Authorization": "Bearer " + "synthetic-worker-secret-" * 3}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver", headers=headers) as client:
        assert (await client.post("/api/internal/media/receipt", json={"attempt_id": attempt_id,
            "receipt": {"audio_base64": "forbidden"}})).status_code == 422
        identity = {"request_id": "synthetic-request", "history_item_id": "synthetic-history"}
        assert (await client.post("/api/internal/media/identity", json={"attempt_id": attempt_id, "identity": identity})).status_code == 200
        saved = await client.get(f"/api/internal/media/attempts/{attempt_id}/recovery")
        assert saved.status_code == 200 and saved.json()["identity"] == identity
        audio = b"exact recovered audio"
        sha = hashlib.sha256(audio).hexdigest()
        uploaded = await client.post(f"/api/internal/media/attempts/{attempt_id}/audio", content=audio,
            headers={"Content-Type": "audio/mpeg", "X-Content-SHA256": sha})
        assert uploaded.status_code == 200
        receipt = {"schema": "elevenlabs-v1", "request_digest": canonical(authority["request"]), "identity": identity,
            "status": 200, "outcome": "recovered", "error": "response_invalid", "audio_sha256": sha,
            "audio_size": len(audio), "asset": uploaded.json()}
        assert (await client.post("/api/internal/media/recovery-receipt", json={"attempt_id": attempt_id, "receipt": receipt})).status_code == 200
        response = await client.get("/api/internal/media/assets/" + uploaded.json()["asset_id"], headers={"X-Media-Lease": json.dumps(fence(lease))})
        assert response.status_code == 403
    async with maker() as db:
        assert (await db.get(RecapStage, lease["stage_id"])).state == "cancelled"
