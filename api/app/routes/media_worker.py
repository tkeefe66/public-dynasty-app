"""Bounded media protocol. No worker-selected identities, paths, URLs or publication."""
import hashlib
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select

from app.auth.media_worker import require_media_worker
from app.db.engine import get_sessionmaker
from app.services.generation.models import stamp
from app.services.generation.recap_models import RecapAsset
from app.services.generation.store import Conflict, Held, OwnershipLost
from app.services.recap_video import workflow as work
from app.services.recap_video.storage import configured_store

router = APIRouter(prefix="/api/internal/media", tags=["internal-media"])
MAX_JSON = 40_000
MAX_ASSET = 64 * 1024 * 1024


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Claim(Strict):
    pass


class Fence(Strict):
    stage_id: str = Field(min_length=1, max_length=64)
    generation: int = Field(ge=1)
    epoch: str = Field(min_length=1, max_length=128)
    input_digest: str = Field(pattern="^[0-9a-f]{64}$")


class Result(Strict):
    status: Literal["ok", "transient", "input_failure"]
    asset_ids: list[str] = Field(max_length=64)
    report: dict


class Completion(Fence):
    result: Result


class Receipt(Strict):
    attempt_id: str = Field(min_length=1, max_length=64)
    receipt: dict


class Identity(Strict):
    attempt_id: str = Field(min_length=1, max_length=64)
    identity: dict


class RecoveryCompletion(Strict):
    recovery_id: str = Field(min_length=1,max_length=64)
    generation: int = Field(ge=1)
    error: Literal['','history_unavailable','history_identity_mismatch','history_request_failed'] = ''
    status: int = Field(default=0,ge=0,le=599)


@router.post('/recovery-claim')
async def claim_recovery(request: Request, worker=Depends(require_media_worker)):
    await parse(request,Claim)
    # Authenticated free-only workers still poll their ordinary queue. Capability
    # comes exclusively from server configuration, never from request JSON.
    if 'narrate' not in worker.capabilities:
        return None
    from app.services.recap_video.recovery import claim_recovery as claim
    async with get_sessionmaker().begin() as db:
        return await claim(db,worker.worker_id,stamp())


@router.post('/recovery-complete')
async def complete_recovery(request: Request, worker=Depends(require_media_worker)):
    require_narration(worker)
    body = await parse(request,RecoveryCompletion)
    from app.services.recap_video.recovery import complete_recovery as complete
    try:
        async with get_sessionmaker().begin() as db:
            return await complete(db,**body.model_dump(),worker_id=worker.worker_id)
    except (Held,Conflict) as exc:
        raise translate(exc) from None


def require_narration(worker):
    if "narrate" not in worker.capabilities:
        raise HTTPException(403, "Narration capability required")


@router.post("/identity")
async def identity(request: Request, worker=Depends(require_media_worker)):
    require_narration(worker)
    body = await parse(request, Identity)
    try:
        async with get_sessionmaker().begin() as db:
            return await work.persist_identity(db, **body.model_dump(), worker_id=worker.worker_id)
    except (Held, Conflict) as exc:
        raise translate(exc) from None


@router.get("/attempts/{attempt_id}/recovery")
async def recovery(attempt_id: str, worker=Depends(require_media_worker)):
    require_narration(worker)
    try:
        async with get_sessionmaker().begin() as db:
            return await work.recovery_evidence(db, attempt_id, worker_id=worker.worker_id)
    except (Held, Conflict) as exc:
        raise translate(exc) from None


@router.post("/recovery-receipt")
async def recovery_receipt(request: Request, worker=Depends(require_media_worker)):
    require_narration(worker)
    body = await parse(request, Receipt)
    check_receipt(body.receipt)
    try:
        async with get_sessionmaker().begin() as db:
            await work.persist_recovery_receipt(db, **body.model_dump(), worker_id=worker.worker_id)
        async with get_sessionmaker().begin() as db:
            return await work.settle_receipt(db, body.attempt_id, worker_id=worker.worker_id)
    except (Held, Conflict) as exc:
        raise translate(exc) from None


@router.post("/attempts/{attempt_id}/audio")
async def recovery_audio(attempt_id: str, request: Request, worker=Depends(require_media_worker)):
    """Retain exact retrieved audio after cancellation; never selects a checkpoint."""
    require_narration(worker)
    if request.headers.get("content-type") != "audio/mpeg":
        raise HTTPException(422, "Recovered audio must be audio/mpeg")
    try:
        async with get_sessionmaker().begin() as db:
            attempt = await work._owned_attempt(db, attempt_id, worker.worker_id)
            if not work._identity(attempt).get("history_item_id"):
                raise Held("provider_recovery_identity_unresolved")
        key, size = await store_upload(request)
        async with get_sessionmaker().begin() as db:
            attempt = await work._owned_attempt(db, attempt_id, worker.worker_id)
            count = await db.scalar(select(func.count()).select_from(RecapAsset).where(RecapAsset.stage_id == attempt.stage_id))
            if count >= 64:
                raise Held("media_asset_limit_reached")
            asset = RecapAsset(stage_id=attempt.stage_id, generation=attempt.generation, storage_key=key,
                digest=request.headers["x-content-sha256"], size=size, media_type="audio/mpeg")
            db.add(asset)
            await db.flush()
            return {"asset_id": asset.id, "digest": asset.digest, "size": size}
    except (Held, Conflict) as exc:
        raise translate(exc) from None


async def parse(request, model):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_JSON:
            raise HTTPException(413, "Media request exceeds maximum body size")
        body.extend(chunk)
    try:
        return model.model_validate_json(bytes(body))
    except ValidationError:
        raise HTTPException(422, "Invalid media request fields or types") from None


def fence_header(request):
    raw = request.headers.get("x-media-lease", "")
    if len(raw) > 1024:
        raise HTTPException(422, "Invalid media lease header")
    try:
        return Fence.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, "Invalid media lease header") from None


async def lease(db, body, worker):
    row = await work.require_lease(db, **body.model_dump(), worker_id=worker.worker_id)
    if not work.worker_can_claim(worker.capabilities, row.kind):
        raise HTTPException(403, "Worker capability does not own this lease")
    return row


def translate(exc):
    if isinstance(exc, OwnershipLost):
        return HTTPException(403, "Media lease is not current or does not belong to this worker")
    if isinstance(exc, Held):
        return HTTPException(409, exc.code)
    return HTTPException(409, "Media checkpoint conflicts with saved state")


@router.post("/claim")
async def claim(request: Request, worker=Depends(require_media_worker)):
    await parse(request, Claim)
    async with get_sessionmaker().begin() as db:
        return await work.claim_stage(db, worker.worker_id, worker.capabilities, stamp())


@router.post("/heartbeat")
async def heartbeat(request: Request, worker=Depends(require_media_worker)):
    body = await parse(request, Fence)
    try:
        async with get_sessionmaker().begin() as db:
            await lease(db, body, worker)
            return await work.heartbeat_stage(db, **body.model_dump(), worker_id=worker.worker_id)
    except (Held, Conflict) as exc:
        raise translate(exc) from None


@router.post("/complete")
async def complete(request: Request, worker=Depends(require_media_worker)):
    body = await parse(request, Completion)
    try:
        async with get_sessionmaker().begin() as db:
            await lease(db, Fence.model_validate(body.model_dump(exclude={"result"})), worker)
            return await work.complete_stage(db, **body.model_dump(), worker_id=worker.worker_id)
    except (Held, Conflict) as exc:
        raise translate(exc) from None


@router.post("/authorize-dispatch")
async def dispatch(request: Request, worker=Depends(require_media_worker)):
    body = await parse(request, Fence)
    try:
        async with get_sessionmaker().begin() as db:
            await lease(db, body, worker)
            result = await work.authorize_dispatch(db, **body.model_dump(), worker_id=worker.worker_id)
        # Commit succeeded before exposing one-time authority to worker.
        return result
    except (Held, Conflict) as exc:
        raise translate(exc) from None


@router.post("/receipt")
async def receipt(request: Request, worker=Depends(require_media_worker)):
    body = await parse(request, Receipt)
    check_receipt(body.receipt)
    if "narrate" not in worker.capabilities:
        raise HTTPException(403, "Narration capability required")
    try:
        async with get_sessionmaker().begin() as db:
            await work.persist_receipt(db, **body.model_dump(), worker_id=worker.worker_id)
        async with get_sessionmaker().begin() as db:
            return await work.settle_receipt(db, body.attempt_id, worker_id=worker.worker_id)
    except (Held, Conflict) as exc:
        raise translate(exc) from None


def check_receipt(value):
    from app.services.recap_video.elevenlabs import sanitized_receipt
    try:
        sanitized_receipt(value)
    except (ValueError, TypeError):
        raise HTTPException(422, "Provider receipt metadata contains invalid or unsupported fields") from None


async def store_upload(request):
    expected = request.headers.get("x-content-sha256", "")
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise HTTPException(422, "SHA256 digest required")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_ASSET:
            raise HTTPException(413, "Media asset exceeds maximum upload size")
        data.extend(chunk)
    if not data or hashlib.sha256(data).hexdigest() != expected:
        raise HTTPException(422, "Uploaded asset is empty or SHA256 digest does not match")
    key = str(uuid.uuid4())
    import asyncio
    await asyncio.to_thread(configured_store().put_verified, key, bytes(data), expected)
    return key, len(data)


@router.post("/assets")
async def upload(request: Request, worker=Depends(require_media_worker)):
    body = fence_header(request)
    media_type = request.headers.get("content-type", "")
    if media_type not in ("audio/wav", "audio/mpeg", "video/mp4", "image/png", "image/jpeg", "text/vtt", "application/json"):
        raise HTTPException(422, "Unsupported media asset type")
    try:
        async with get_sessionmaker().begin() as db:
            await lease(db, body, worker)
        key, size = await store_upload(request)
        # No control/DB lock across network upload. Recheck all fences after transfer.
        async with get_sessionmaker().begin() as db:
            row = await lease(db, body, worker)
            count = await db.scalar(select(func.count()).select_from(RecapAsset).where(RecapAsset.stage_id == row.id))
            if count >= 64:
                raise Held("media_asset_limit_reached")
            asset = RecapAsset(stage_id=row.id, generation=row.generation,
                digest=request.headers["x-content-sha256"], size=size, media_type=media_type, storage_key=key)
            db.add(asset)
            await db.flush()
            result = {"asset_id": asset.id, "digest": asset.digest, "size": size}
        return result
    except (Held, Conflict) as exc:
        raise translate(exc) from None


@router.get("/assets/{asset_id}")
async def download(asset_id: str, request: Request, worker=Depends(require_media_worker)):
    body = fence_header(request)
    try:
        async with get_sessionmaker().begin() as db:
            row = await lease(db, body, worker)
            asset = await db.get(RecapAsset, asset_id)
            allowed = await work.allowed_asset_ids(db, row)
            if (not asset or not ((asset.stage_id == row.id and asset.generation == row.generation) or asset.id in allowed)):
                raise HTTPException(403, "Asset does not belong to this lease")
            store = configured_store()
            import asyncio
            metadata = await asyncio.to_thread(store.head, asset.storage_key)
            if metadata != {"size": asset.size, "sha256": asset.digest}:
                raise Held("media_asset_unavailable")
            key, size, media_type = asset.storage_key, asset.size, asset.media_type
        async def chunks():
            for start in range(0, size, 1024 * 1024):
                yield await asyncio.to_thread(store.read_range, key, start, min(size - 1, start + 1024 * 1024 - 1))
        return StreamingResponse(chunks(), media_type=media_type, headers={"Cache-Control": "private, no-store"})
    except (Held, Conflict) as exc:
        raise translate(exc) from None
