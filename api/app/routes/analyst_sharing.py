import logging

from fastapi import APIRouter, HTTPException, Path, Response
from pydantic import BaseModel, Field

from app.deps import get_cache_dir
from app.services.analyst_shares import AnalystShares
from app.services.analyst_store import AnalystSource

log = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()


class ShareState(BaseModel):
    token: str | None


class PublicEdition(BaseModel):
    season: int
    week: int
    league_name: str
    generated_at: str
    markdown: str
    revision: int
    correction_note: str | None
    sources: list[AnalystSource] = Field(default_factory=list)
    context_note: str | None = None


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
        edition = store().resolve(token)
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, "This recap could not be loaded. Please try again.")
    if edition is None:
        raise HTTPException(404, "This share link is unavailable or has been disabled.")
    return edition
