from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import get_settings
from app.deps import get_cache_dir
from app.ratelimit import limiter, og_card_only
from app.models.leaderboard import LeaderboardResp
from app.services.chain_cache import ChainCache
from app.services.identity import apply_name_overrides
from app.services.franchise_redesign import model_for
from app.services.leaderboard import build_leaderboard, load_prev_ratings
from app.services.name_override_store import NameOverrideStore

log = logging.getLogger(__name__)
router = APIRouter()


def _cache_dir() -> Path:
    """Indirection point; tests patch this to point at tmp_path."""
    return get_cache_dir()


@router.get("/api/league/{league_id}/leaderboard", response_model=LeaderboardResp)
@limiter.limit(lambda: get_settings().rate_limit_og_card, exempt_when=og_card_only)
def leaderboard(
    request: Request,
    league_id: str,
    year: str = Query("all"),
) -> LeaderboardResp:
    cache_dir = _cache_dir()
    entry = ChainCache(cache_dir=cache_dir).read(league_id)
    if entry is None:
        raise HTTPException(
            status_code=409,
            detail="cache cold: kick off refresh via POST /api/league/{id}/refresh",
        )
    overrides = NameOverrideStore(cache_dir=cache_dir).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)
    if year == "all":
        year_val: int | Literal["all"] = "all"
    else:
        try:
            year_val = int(year)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid year")
    prev_ratings = load_prev_ratings(
        cache_dir, league_id, model=model_for(entry)
    )
    return build_leaderboard(entry, year=year_val, prev_ratings=prev_ratings)
