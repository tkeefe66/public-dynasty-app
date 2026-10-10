"""Bounded media protocol. No worker-selected identities, paths, URLs or publication."""
import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select

from app.auth.media_worker import require_media_worker
from app.config import get_settings
from app.db.engine import get_sessionmaker
from app.services.generation.models import stamp
from app.services.generation.recap_models import RecapAsset
from app.services.generation.store import Conflict, Held, OwnershipLost
from app.services.recap_video import workflow as work

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
    if "narrate" not in worker.capabilities:
        raise HTTPException(403, "Narration capability required")
    try:
        async with get_sessionmaker().begin() as db:
            await work.persist_receipt(db, **body.model_dump(), worker_id=worker.worker_id)
        async with get_sessionmaker().begin() as db:
            return await work.settle_receipt(db, body.attempt_id, worker_id=worker.worker_id)
    except (Held, Conflict) as exc:
        raise translate(exc) from None


class LocalImmutableMediaStore:
    """API-only adapter: upload(stream, digest)->metadata, path(key)->local file.

    Task7 bucket adapter replaces upload/read at this authorization boundary;
    it must keep streaming byte limits, digest verification, immutable keys and
    private API streaming (never redirects or worker bucket credentials).
    """
    def __init__(self):
        self.root = get_settings().media_asset_root
        if self.root is None:
            raise Held("media_storage_unconfigured")
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key):
        try:
            if str(uuid.UUID(key)) != key:
                raise ValueError()
        except ValueError:
            raise Held("media_storage_key_invalid") from None
        path = self.root / key
        if path.is_symlink():
            raise Held("media_storage_key_invalid")
        return path

    async def upload(self, stream, expected):
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise HTTPException(422, "SHA256 digest required")
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix=".upload-")
        size, sha = 0, hashlib.sha256()
        try:
            with os.fdopen(fd, "wb") as file:
                async for chunk in stream:
                    size += len(chunk)
                    if size > MAX_ASSET:
                        raise HTTPException(413, "Media asset exceeds maximum upload size")
                    sha.update(chunk)
                    file.write(chunk)
                file.flush()
                os.fsync(file.fileno())
            if not size or sha.hexdigest() != expected:
                raise HTTPException(422, "Uploaded asset is empty or SHA256 digest does not match")
            key = str(uuid.uuid4())
            os.link(temporary, self.path(key))
            return key, size
        finally:
            Path(temporary).unlink(missing_ok=True)


@router.post("/assets")
async def upload(request: Request, worker=Depends(require_media_worker)):
    body = fence_header(request)
    media_type = request.headers.get("content-type", "")
    if media_type not in ("audio/wav", "audio/mpeg", "video/mp4", "image/png", "application/json"):
        raise HTTPException(422, "Unsupported media asset type")
    try:
        async with get_sessionmaker().begin() as db:
            await lease(db, body, worker)
        store = LocalImmutableMediaStore()
        key, size = await store.upload(request.stream(), request.headers.get("x-content-sha256", ""))
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
            path = LocalImmutableMediaStore().path(asset.storage_key)
            if not path.is_file() or path.stat().st_size != asset.size:
                raise Held("media_asset_unavailable")
            return FileResponse(path, media_type=asset.media_type, headers={"Cache-Control": "private, no-store"})
    except (Held, Conflict) as exc:
        raise translate(exc) from None
