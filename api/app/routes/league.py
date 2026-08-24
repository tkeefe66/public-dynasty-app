from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import get_settings
from app.deps import get_cache_dir
from app.ratelimit import limiter, og_card_only
from app.models.league import DashboardResp
from app.services.aggregations import build_dashboard
from app.services.chain_cache import ChainCache
from app.services.franchise_redesign import model_for
from app.services.identity import apply_name_overrides
from app.services.leaderboard import load_prev_ratings
from app.services.name_override_store import NameOverrideStore

log = logging.getLogger(__name__)
router = APIRouter()


def _cache_dir() -> Path:
    """Indirection point; tests patch this to point at tmp_path."""
    return get_cache_dir()


@router.get("/api/league/{league_id}", response_model=DashboardResp)
@limiter.limit(lambda: get_settings().rate_limit_og_card, exempt_when=og_card_only)
def league(
    request: Request,
    league_id: str,
    year: str = Query("all"),
    lens: Literal["ktc", "production"] = Query("ktc"),
) -> DashboardResp:
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
    if year == "all":
        year_val: int | Literal["all"] = "all"
    else:
        try:
            year_val = int(year)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid year")
    prev_ratings = load_prev_ratings(cache_dir, league_id, model=model_for(entry))
    is_in_season = datetime.now().month in {9, 10, 11, 12, 1}
    return build_dashboard(
        entry, year=year_val, lens=lens,
        prev_ratings=prev_ratings, is_in_season=is_in_season,
    )
