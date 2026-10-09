import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Response
from fastapi.responses import FileResponse
from starlette.datastructures import MutableHeaders
from pydantic import BaseModel, Field

from app.deps import get_cache_dir
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


def store():
    return AnalystShares(get_cache_dir())


def private_headers(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"


@router.get("/api/league/{league_id}/analyst/{season}/{week}/share", response_model=ShareState)
def share_state(league_id: str, response: Response, season: int = Path(ge=2000, le=2200), week: int = Path(ge=1, le=18)):
    private_headers(response)
    return store().state(league_id, season, week)


@router.post("/api/league/{league_id}/analyst/{season}/{week}/share", response_model=ShareState)
def create_share(league_id: str, response: Response, season: int = Path(ge=2000, le=2200), week: int = Path(ge=1, le=18)):
    private_headers(response)
    result = store().create(league_id, season, week)
    if result is None:
        raise HTTPException(404, "That recap has not been published.")
    log.info("Analyst sharing enabled league=%s season=%s week=%s", league_id, season, week)
    return result


@router.delete("/api/league/{league_id}/analyst/{season}/{week}/share", response_model=ShareState)
def revoke_share(league_id: str, response: Response, season: int = Path(ge=2000, le=2200), week: int = Path(ge=1, le=18)):
    private_headers(response)
    store().revoke(league_id, season, week)
    log.info("Analyst sharing disabled league=%s season=%s week=%s", league_id, season, week)
    return {"token": None}


@public_router.get("/api/public/analyst/{token}", response_model=PublicEdition)
def public_edition(token: str, response: Response):
    private_headers(response)
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
def public_media(token: str, bundle_id: str, name: str, download: bool = False):
    response = Response()
    private_headers(response)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers["X-Content-Type-Options"] = "nosniff"
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
