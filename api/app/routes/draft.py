"""League-wide draft board."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.deps import get_cache_dir
from app.models.league import DraftBoardResp, DraftSeasonsResp
from app.services.chain_cache import ChainCache
from app.services.draft_board_view import available_seasons, build_draft_board
from app.services.identity import apply_name_overrides
from app.services.name_override_store import NameOverrideStore

log = logging.getLogger(__name__)
router = APIRouter()


def _cache_dir() -> Path:
    """Indirection point; tests patch this to point at tmp_path."""
    return get_cache_dir()


# Registered BEFORE the `/draft/{season}` int route below. `season` is typed
# `int`, so a literal "seasons" would 422 rather than be captured by it — but
# explicit ordering is clearer than relying on that.
@router.get("/api/league/{league_id}/draft/seasons",
            response_model=DraftSeasonsResp)
def draft_seasons(league_id: str) -> DraftSeasonsResp:
    """Every draft season on this chain, newest first.

    The nav cannot link to a season it doesn't know, and the `/draft` redirect
    route needs one before it can fetch a board — same 409 cold-cache contract
    as every other dashboard endpoint.
    """
    cache_dir = _cache_dir()
    cache = ChainCache(cache_dir=cache_dir)
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(
            status_code=409,
            detail="cache cold: kick off refresh via POST /api/league/{id}/refresh",
        )
    return DraftSeasonsResp(seasons=available_seasons(entry))


@router.get("/api/league/{league_id}/draft/{season}",
            response_model=DraftBoardResp)
def draft_board(league_id: str, season: int) -> DraftBoardResp:
    """One draft class, every owner.

    409 on a cold cache, matching every other dashboard endpoint. 404 names the
    seasons that *do* exist, so a wrong-year link is self-correcting.
    """
    cache_dir = _cache_dir()
    cache = ChainCache(cache_dir=cache_dir)
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(
            status_code=409,
            detail="cache cold: kick off refresh via POST /api/league/{id}/refresh",
        )
    overrides = NameOverrideStore(cache_dir=cache_dir).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)

    board = build_draft_board(entry, season=season)
    if board is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no draft class for season {season}; "
                f"available: {available_seasons(entry) or 'none'}"
            ),
        )
    return board
