import logging
import asyncio
import hashlib
import os
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import MutableHeaders
from pydantic import BaseModel, Field

from app.deps import get_cache_dir
from app.db.session import get_db
from app.auth.deps import require_league_member
from app.services.generation.store import Held
from app.services.recap_video import publication
from app.services.analyst_shares import AnalystShares
from app.services.analyst_media import AnalystMedia, ASSETS
from app.services.analyst_store import AnalystSource

log = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()


class PrivateMediaResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        async def private_send(message):
            if message["type"] == "http.response.start":
                # FileResponse's 400/416 branches construct fresh responses.
                headers = MutableHeaders(scope=message)
                for name in ("cache-control", "referrer-policy", "x-robots-tag", "x-content-type-options"):
                    headers[name] = self.headers[name]
            await send(message)
        await super().__call__(scope, receive, private_send)


class ShareState(BaseModel):
    token: str | None


class PublicMedia(BaseModel):
    id: str
    duration_seconds: float
    video_bytes: int
    audio_bytes: int


class PublicEdition(BaseModel):
    season: int
    week: int
    league_name: str
    generated_at: str
    markdown: str
    edition_type: Literal["roast", "results"] = "roast"
    revision: int
    correction_note: str | None
    sources: list[AnalystSource] = Field(default_factory=list)
    context_note: str | None = None
    media: PublicMedia | None = None
    status: Literal["published", "withdrawn"] = "published"


def store():
    return AnalystShares(get_cache_dir())


def private_headers(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["X-Content-Type-Options"] = "nosniff"


def authority_error(exc):
    response = Response()
    private_headers(response)
    headers = dict(response.headers)
    headers.pop('content-length', None)
    unavailable = isinstance(exc, Held) and exc.code in ('public_unavailable', 'publication_missing')
    if not unavailable:
        headers['Retry-After'] = '5'
    return HTTPException(404 if unavailable else 503,
        'This share link is unavailable or has been disabled.' if unavailable else
        'This recap could not be loaded. Please try again.', headers=headers)


def authority_mode():
    try:
        return publication.mode()
    except Held as exc:
        raise authority_error(exc) from None


@router.get("/api/league/{league_id}/analyst/{season}/{week}/share", response_model=ShareState)
async def share_state(league_id: str, response: Response, season: int = Path(ge=2000, le=2200), week: int = Path(ge=1, le=18), db=Depends(get_db)):
    private_headers(response)
    if authority_mode() == 'database':
        try:
            return await publication.share_state(db, await publication.edition_row(db, league_id, season, week))
        except (Held, SQLAlchemyError) as exc:
            raise authority_error(exc) from None
    return store().state(league_id, season, week)


@router.post("/api/league/{league_id}/analyst/{season}/{week}/share", response_model=ShareState)
async def create_share(league_id: str, response: Response, season: int = Path(ge=2000, le=2200), week: int = Path(ge=1, le=18), db=Depends(get_db), user=Depends(require_league_member)):
    private_headers(response)
    if authority_mode() == 'database':
        try:
            return await publication.change_share(db, await publication.edition_row(db, league_id, season, week), enabled=True, actor_id=user.id)
        except (Held, SQLAlchemyError) as exc:
            raise authority_error(exc) from None
    result = store().create(league_id, season, week)
    if result is None:
        raise HTTPException(404, "That recap has not been published.")
    log.info("Analyst sharing enabled league=%s season=%s week=%s", league_id, season, week)
    return result


@router.delete("/api/league/{league_id}/analyst/{season}/{week}/share", response_model=ShareState)
async def revoke_share(league_id: str, response: Response, season: int = Path(ge=2000, le=2200), week: int = Path(ge=1, le=18), db=Depends(get_db), user=Depends(require_league_member)):
    private_headers(response)
    if authority_mode() == 'database':
        try:
            return await publication.change_share(db, await publication.edition_row(db, league_id, season, week), enabled=False, actor_id=user.id)
        except (Held, SQLAlchemyError) as exc:
            raise authority_error(exc) from None
    store().revoke(league_id, season, week)
    log.info("Analyst sharing disabled league=%s season=%s week=%s", league_id, season, week)
    return {"token": None}


@public_router.get("/api/public/analyst/{token}", response_model=PublicEdition, response_model_exclude_unset=True)
async def public_edition(token: str, response: Response, db=Depends(get_db)):
    private_headers(response)
    if authority_mode() == 'database':
        try:
            return (await publication.authorize_public_read(db, token, None, int(time.time())))['article']
        except (Held, SQLAlchemyError, OSError, ValueError, KeyError) as exc:
            raise authority_error(exc) from None
    try:
        media_store = AnalystMedia(get_cache_dir())
        resolved = media_store.resolve(token)
    except (OSError, ValueError, KeyError):
        log.error("Shared recap could not be loaded")
        raise HTTPException(503, "This recap could not be loaded. Please try again.", headers=dict(response.headers))
    if resolved is None:
        raise HTTPException(404, "This share link is unavailable or has been disabled.", headers=dict(response.headers))
    _, edition, manifest = resolved
    return {**edition, "media": media_store.public_metadata(manifest)}


@public_router.api_route("/api/public/analyst/{token}/media/{bundle_id}/{name}", methods=["GET", "HEAD"])
async def public_media(token: str, bundle_id: str, name: str, request: Request, download: bool = False, db=Depends(get_db)):
    response = Response()
    private_headers(response)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers["x-content-type-options"] = "nosniff"
    if authority_mode() == 'database':
        try:
            if name not in ASSETS:
                raise Held('public_unavailable')
            result = await publication.authorize_public_read(db, token, bundle_id, int(time.time()))
            return await private_object_response(request, result, name, download, headers)
        except (Held, SQLAlchemyError, OSError, ValueError, KeyError) as exc:
            raise authority_error(exc) from None
    try:
        result = AnalystMedia(get_cache_dir()).asset(token, bundle_id, name)
    except (OSError, ValueError, KeyError):
        log.error("Shared recap media could not be loaded")
        raise HTTPException(503, "This media could not be loaded. Reload the recap to try again.", headers=headers)
    if result is None:
        raise HTTPException(404, "This media is unavailable or its share link has been disabled.", headers=headers)
    path, edition = result
    filename = f"weekly-recap-{edition['season']}-week-{edition['week']}.{name.rsplit('.', 1)[1]}"
    # Starlette handles HEAD, suffix/open ranges, 206 and 416 without buffering.
    return PrivateMediaResponse(path, media_type=ASSETS[name], headers=headers,
                        filename=filename, content_disposition_type="attachment" if download else "inline")


async def private_object_response(request, result, name, download, headers):
    """Bounded single ranges. Each S3 chunk closes its body even on disconnect."""
    from pathlib import Path as FilePath
    from app.services.recap_video.storage import configured_store
    from starlette.concurrency import run_in_threadpool
    media, edition = result['media'], result['article']
    asset = media['files'][name]
    size = asset['bytes']
    filename = f"weekly-recap-{edition['season']}-week-{edition['week']}.{name.rsplit('.', 1)[1]}"
    etag = '"'+asset['sha256']+'"'
    headers.update({'Accept-Ranges':'bytes', 'ETag':etag, 'Content-Length':str(size),
        'Content-Disposition':f'{"attachment" if download else "inline"}; filename="{filename}"'})
    if media['storage'] == 'legacy':
        path = FilePath(asset['path'])
        if path.is_symlink() or not path.is_file():
            raise Held('public_unavailable')
        def metadata():
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
                return os.fstat(stream.fileno()).st_size, hashlib.file_digest(stream, 'sha256').hexdigest()
        if await asyncio.to_thread(metadata) != (size, asset['sha256']):
            raise Held('public_asset_corrupt')
        def read(start, end):
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
                stream.seek(start)
                data = stream.read(end-start+1)
            if len(data) != end-start+1:
                raise ValueError('Legacy media truncated')
            return data
    else:
        store = configured_store()
        metadata = await asyncio.to_thread(store.head, asset['key'])
        if metadata != {'size':size, 'sha256':asset['sha256']}:
            raise Held('public_asset_corrupt')
        def read(start, end):
            return store.read_range(asset['key'], start, end)
    start, end, status = 0, size-1, 200
    value = request.headers.get('range')
    if value and request.headers.get('if-range', etag) == etag:
        import re
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
        try:
            if not match or not any(match.groups()):
                raise ValueError()
            left, right = match.groups()
            if left:
                start, end = int(left), min(int(right), size-1) if right else size-1
            else:
                if int(right) <= 0:
                    raise ValueError()
                start, end = max(0, size-int(right)), size-1
            if not 0 <= start <= end < size:
                raise ValueError()
        except ValueError:
            headers.update({'Content-Range':f'bytes */{size}', 'Content-Length':'0'})
            return Response(status_code=416, headers=headers)
        status = 206
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    headers['Content-Length'] = str(end-start+1)
    if request.method == 'HEAD':
        return Response(status_code=status, media_type=ASSETS[name], headers=headers)
    async def body():
        cursor = start
        while cursor <= end:
            # No deadline for the whole transfer; each storage call is bounded.
            last = min(cursor+256*1024-1, end)
            yield await run_in_threadpool(read, cursor, last)
            cursor = last+1
    return StreamingResponse(body(), status_code=status, media_type=ASSETS[name], headers=headers)
