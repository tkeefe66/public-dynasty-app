from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.config import get_settings
from app.deps import get_cache_dir
from app.ratelimit import limiter, og_card_only
from app.models.owner import OwnerDetailResp
from app.services.chain_cache import ChainCache
from app.services.franchise_redesign import model_for
from app.services.identity import apply_name_overrides
from app.services.leaderboard import build_leaderboard, load_prev_ratings
from app.services.name_override_store import NameOverrideStore
from app.services.owner_view import build_owner_detail

router = APIRouter()


def _cache_dir() -> Path:
    return get_cache_dir()


@router.get(
    "/api/league/{league_id}/owner/{user_id}",
    response_model=OwnerDetailResp,
)
@limiter.limit(lambda: get_settings().rate_limit_og_card, exempt_when=og_card_only)
def owner(request: Request, league_id: str, user_id: str) -> OwnerDetailResp:
    cache = ChainCache(cache_dir=_cache_dir())
    entry = cache.read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    overrides = NameOverrideStore(cache_dir=_cache_dir()).read(league_id)
    if overrides:
        apply_name_overrides(entry, overrides)

    # All-time Franchise Rating row for the hero verdict (letter + rank + trend),
    # reusing the leaderboard's canonical computation so the owner page and /gm
    # never disagree. Best-effort: the page still renders if rating build fails.
    gm_row = None
    total_owners = None
    try:
        board = build_leaderboard(
            entry, year="all",
            prev_ratings=load_prev_ratings(
                _cache_dir(), league_id, model=model_for(entry)
            ),
        )
        total_owners = len(board.rows)
        gm_row = next((r for r in board.rows if r.user_id == user_id), None)
    except Exception:
        pass

    detail = build_owner_detail(
        entry, user_id, gm_row=gm_row, total_owners=total_owners,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="owner not found")
    return detail
