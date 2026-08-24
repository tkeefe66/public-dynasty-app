from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.deps import get_cache_dir
from app.models.owner import OwnerProfile
from app.services.chain_cache import ChainCache
from app.services.profile_store import ProfileStore

router = APIRouter()


def _cache_dir() -> Path:
    return get_cache_dir()


@router.get("/api/league/{league_id}/profiles")
def get_profiles(league_id: str) -> dict[str, OwnerProfile]:
    """All owner profiles for the league ({} if none saved yet).

    Reading never requires a warm chain — it just returns the stored voice
    data, so the editor works even before the cold-start refresh completes."""
    return ProfileStore(cache_dir=_cache_dir()).read(league_id)


@router.put("/api/league/{league_id}/profiles/{user_id}")
def put_profile(
    league_id: str, user_id: str, profile: OwnerProfile
) -> dict[str, OwnerProfile]:
    """Upsert one owner's profile; returns the full league map.

    Validates against the chain cache so we only store profiles for real
    owners: 409 if the chain is cold, 404 if the user isn't in the league."""
    cache_dir = _cache_dir()
    entry = ChainCache(cache_dir=cache_dir).read(league_id)
    if entry is None:
        raise HTTPException(status_code=409, detail="cache cold")
    if user_id not in entry.owners:
        raise HTTPException(status_code=404, detail="owner not found")
    return ProfileStore(cache_dir=cache_dir).upsert(
        league_id, user_id, profile.model_dump()
    )
