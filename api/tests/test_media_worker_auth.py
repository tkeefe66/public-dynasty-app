import pytest
from httpx import ASGITransport, AsyncClient
import hashlib
import json
from app.services.generation.models import stamp
from app.services.generation.recap_models import RecapStage
from app.services.recap_video import workflow as work
from tests.test_recap_workflow import seed_media, fence


@pytest.mark.asyncio
async def test_media_credential_is_not_admin(app, monkeypatch):
    # Mutation: dedicated credential reaches user JWT/admin authentication.
    monkeypatch.setenv("TRADE_GRADER_MEDIA_WORKER_TOKEN", "synthetic-worker-secret-" * 3)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        r = await client.get("/api/admin/generation", headers={"Authorization": "Bearer " + "synthetic-worker-secret-" * 3})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_worker_cannot_supply_identity_or_capabilities(app, monkeypatch):
    # Mutation: worker body widens server-owned identity/capabilities.
    monkeypatch.setenv("TRADE_GRADER_MEDIA_WORKER_TOKEN", "synthetic-worker-secret-" * 3)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        r = await client.post("/api/internal/media/claim", json={"worker_id": "api", "capabilities": ["publish"]},
            headers={"Authorization": "Bearer " + "synthetic-worker-secret-" * 3})
        assert r.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize('content_type', ['video/mp4', 'image/jpeg', 'text/vtt'])
async def test_streamed_upload_bounds_digest_and_foreign_assets(app, maker, tmp_path, monkeypatch, content_type):
    # Mutation: trust Content-Length/digest; expose another checkpoint's assets.
    from app.routes import media_worker as routes
    from app.services.generation.recap_models import RecapAsset
    _, stage_id = await seed_media(maker, tmp_path, monkeypatch)
    monkeypatch.setenv("TRADE_GRADER_MEDIA_WORKER_TOKEN", "synthetic-worker-secret-" * 3)
    monkeypatch.setenv("TRADE_GRADER_MEDIA_WORKER_ID", "renderer")
    monkeypatch.setenv("TRADE_GRADER_MEDIA_ASSET_ROOT", str(tmp_path / "assets"))
    monkeypatch.setattr(routes, "get_sessionmaker", lambda: maker)
    monkeypatch.setattr(routes, "MAX_ASSET", 10)
    async with maker.begin() as db:
        leased = await work.claim_stage(db, "renderer", {"render"}, stamp())
        db.add(RecapAsset(id="foreign", stage_id="other-stage", generation=1, digest="x", size=1,
            media_type="video/mp4", storage_key="not-readable"))
    headers = {"Authorization": "Bearer " + "synthetic-worker-secret-" * 3,
        "x-media-lease": json.dumps(fence(leased)), "content-type": content_type,
        "x-content-sha256": hashlib.sha256(b"test").hexdigest()}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        uploaded = await client.post("/api/internal/media/assets", headers=headers, content=b"test")
        assert uploaded.status_code == 200, uploaded.text
        asset_id = uploaded.json()["asset_id"]
        assert (await client.get("/api/internal/media/assets/" + asset_id, headers=headers)).content == b"test"
        assert (await client.get("/api/internal/media/assets/foreign", headers=headers)).status_code == 403
        assert (await client.post("/api/internal/media/assets", headers=headers, content=b"wrong")).status_code == 422
        async def oversized():
            yield b"a" * 6
            yield b"a" * 6
        assert (await client.post("/api/internal/media/assets", headers=headers, content=oversized())).status_code == 413
        assert (await client.post("/api/internal/media/claim", headers=headers, content=b" " * 40001)).status_code == 413
        async def revoked():
            yield b"te"
            async with maker.begin() as db:
                await work.cancel_media(db, (await db.get(RecapStage, stage_id)).episode_id,
                    "owner", "Synthetic cancellation during transfer")
            yield b"st"
        assert (await client.post("/api/internal/media/assets", headers=headers, content=revoked())).status_code == 403


@pytest.mark.asyncio
async def test_user_jwt_cannot_be_media_worker(app, monkeypatch):
    # Mutation: accept backend user tokens on restricted worker protocol.
    import jwt
    monkeypatch.setenv("TRADE_GRADER_AUTH_BACKEND_SECRET", "synthetic-backend-secret-" * 3)
    user_token = jwt.encode({"sub": "synthetic-owner", "email": "owner@test.local"}, "synthetic-backend-secret-" * 3, algorithm="HS256")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.post("/api/internal/media/claim", json={}, headers={"Authorization": "Bearer " + user_token})).status_code == 403


@pytest.mark.asyncio
async def test_exact_recovery_http_handoff_stops_on_missing_history(app,maker,tmp_path,monkeypatch):
    from app.services.recap_video.recovery import enqueue_recovery
    from app.services.generation.recap_models import RecapProviderAttempt,RecapRecoveryRequest
    from app.routes import media_worker as routes
    _,stage_id=await seed_media(maker,tmp_path,monkeypatch,'narrate')
    monkeypatch.setenv('TRADE_GRADER_MEDIA_WORKER_TOKEN','synthetic-worker-secret-'*3)
    monkeypatch.setenv('TRADE_GRADER_MEDIA_WORKER_ID','original')
    monkeypatch.setenv('TRADE_GRADER_MEDIA_WORKER_CAPABILITIES','narrate')
    monkeypatch.setattr(routes,'get_sessionmaker',lambda:maker)
    async with maker.begin() as db:
        lease=await work.claim_stage(db,'original',{'narrate'},stamp())
        sent=await work.authorize_dispatch(db,**fence(lease),worker_id='original')
        await work.persist_identity(db,sent['attempt_id'],{'request_id':'synthetic-request','history_item_id':'synthetic-history'},worker_id='original')
        (await db.get(RecapProviderAttempt,sent['attempt_id'])).state='unknown'
        recovery=await enqueue_recovery(db,sent['attempt_id'],actor_id='owner',reason='Exact history recovery')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://testserver',headers={'Authorization':'Bearer '+'synthetic-worker-secret-'*3}) as client:
        claimed=await client.post('/api/internal/media/recovery-claim',json={})
        assert claimed.json()=={'recovery_id':recovery.id,'attempt_id':sent['attempt_id'],'generation':1}
        assert (await client.post('/api/internal/media/recovery-claim',json={})).json() is None
        body={'recovery_id':recovery.id,'generation':1,'error':'history_unavailable','status':404}
        assert (await client.post('/api/internal/media/recovery-complete',json=body)).status_code==200
        assert (await client.post('/api/internal/media/recovery-complete',json=body)).status_code==403
        assert (await client.post('/api/internal/media/recovery-claim',json={})).json() is None
    async with maker() as db:
        assert (await db.get(RecapRecoveryRequest,recovery.id)).error=='history_unavailable'
        assert (await db.get(RecapProviderAttempt,sent['attempt_id'])).cost_microusd is None
