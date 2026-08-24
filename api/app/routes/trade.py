from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import get_settings
from app.deps import get_cache_dir
from app.ratelimit import limiter, og_card_only
from app.models.league import LatestTrade
from app.models.trade import TradeDetailResp
from app.services.aggregations import build_trades_list
from app.services.chain_cache import ChainCache
from app.services.identity import apply_name_overrides
from app.services.name_override_store import NameOverrideStore
from app.services.standings_snapshot_store import StandingsSnapshotStore
from app.services.trade_view import build_trade_detail

router = APIRouter()


def _cache_dir() -> Path:
    return get_cache_dir()


@router.get(
    "/api/league/{league_id}/trades",
    response_model=list[LatestTrade],
)
def trades(
    league_id: str,
    year: str = Query("all"),
    lens: Literal["ktc", "production"] = Query("ktc"),
) -> list[LatestTrade]:
    """Full trade history in the window (newest first). Powers the Trades tab."""
    cache = ChainCache(cache_dir=_cache_dir())
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    overrides = NameOverrideStore(cache_dir=_cache_dir()).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)
    if year == "all":
        year_val: int | Literal["all"] = "all"
    else:
        try:
            year_val = int(year)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid year")
    return build_trades_list(entry, year=year_val, lens=lens)


@router.get(
    "/api/league/{league_id}/trade/{trade_id}",
    response_model=TradeDetailResp,
)
@limiter.limit(lambda: get_settings().rate_limit_og_card, exempt_when=og_card_only)
def trade(request: Request, league_id: str, trade_id: str) -> TradeDetailResp:
    cache_dir = _cache_dir()
    cache = ChainCache(cache_dir=cache_dir)
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    overrides = NameOverrideStore(cache_dir=cache_dir).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)
    detail = build_trade_detail(
        entry, trade_id,
        standings_store=StandingsSnapshotStore(cache_dir=cache_dir),
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="trade not found")
    return detail
