"""Per-user onboarding: link Sleeper, discover leagues, manage memberships.

All routes are user-scoped (``get_current_user``) — they are NOT league-gated,
since this is how a user bootstraps their first league. The heavy analysis
engine stays shared and league-keyed; these endpoints only touch the identity
DB plus read-only Sleeper discovery.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.deps import get_cache_dir
from app.ratelimit import limiter
from app.repositories import memberships, users
from app.services.chain_cache import ChainCache
from sleeper_dynasty.api.sleeper import SleeperClient
log = logging.getLogger(__name__)
router = APIRouter()


# Short in-process cache for Sleeper discovery (username+season → leagues) to
# blunt repeated fan-out to the public Sleeper API. Per-user "already_imported"
# is layered on per request, so only the upstream data is cached.
_DISCOVERY_TTL_SECONDS = 60.0
_discovery_cache: dict[tuple[str, int], tuple[float, list[dict]]] = {}


async def _discover_leagues(username: str, season: int | None) -> list[dict]:
    client = SleeperClient()
    try:
        if season is None:
            state = await client.get_nfl_state()
            season = int(state.get("season"))
        key = (username.lower(), season)
        hit = _discovery_cache.get(key)
        if hit is not None and (time.monotonic() - hit[0]) < _DISCOVERY_TTL_SECONDS:
            return hit[1]
        try:
            sleeper_uid = await client.get_user_id(username)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sleeper user '{username}' not found",
            ) from exc
        leagues = await client.get_leagues(sleeper_uid, season)
        discovered = [
            {
                "league_id": lg.league_id,
                "name": lg.name,
                "season": lg.season,
                "total_rosters": lg.total_rosters,
                "format": lg.format,
            }
            for lg in leagues
        ]
        _discovery_cache[key] = (time.monotonic(), discovered)
        return discovered
    finally:
        await client.close()


def _cache_dir() -> Path:
    return get_cache_dir()


class MyLeague(BaseModel):
    league_id: str
    name: str | None = None
    season: int | None = None
    warm: bool
    sleeper_roster_id: int | None = None
    added_at: str


class SleeperLeague(BaseModel):
    league_id: str
    name: str
    season: int
    total_rosters: int
    already_imported: bool
    format: str = "dynasty"


class AddLeagueReq(BaseModel):
    league_id: str
    sleeper_roster_id: int | None = None
    name: str | None = None


class MeProfile(BaseModel):
    email: str
    name: str | None = None
    avatar_url: str | None = None
    sleeper_user_id: str | None = None
    sleeper_username: str | None = None
    is_admin: bool


class LinkSleeperReq(BaseModel):
    username: str


def _profile(user: User) -> MeProfile:
    return MeProfile(
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        sleeper_user_id=user.sleeper_user_id,
        sleeper_username=user.sleeper_username,
        is_admin=user.is_admin,
    )


@router.get("/api/me", response_model=MeProfile)
async def get_me(user: User = Depends(get_current_user)) -> MeProfile:
    return _profile(user)


@router.post("/api/me/link-sleeper", response_model=MeProfile)
async def link_sleeper(
    body: LinkSleeperReq,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeProfile:
    """Soft-link a Sleeper username (resolves to a Sleeper user_id for roster
    auto-match + add-league prefill). Never used for authorization."""
    username = body.username.strip()
    client = SleeperClient()
    try:
        try:
            sleeper_uid = await client.get_user_id(username)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sleeper user '{username}' not found",
            ) from exc
    finally:
        await client.close()
    await users.set_sleeper_link(
        db, user, sleeper_user_id=sleeper_uid, sleeper_username=username
    )
    return _profile(user)


@router.delete("/api/me/link-sleeper", response_model=MeProfile)
async def unlink_sleeper(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeProfile:
    await users.set_sleeper_link(db, user, sleeper_user_id=None, sleeper_username=None)
    return _profile(user)


@router.get("/api/me/leagues", response_model=list[MyLeague])
async def my_leagues(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[MyLeague]:
    """The current user's imported leagues, annotated with cache warmth."""
    rows = await memberships.list_for_user(db, user.id)
    cache = ChainCache(cache_dir=_cache_dir())
    out: list[MyLeague] = []
    for m in rows:
        entry = cache.read(m.league_id)
        name = season = None
        if entry is not None:
            name = (entry.league_name_by_id or {}).get(m.league_id)
            season = (entry.league_season_by_id or {}).get(m.league_id)
        name = name or m.league_name
        # Backfill the name for older memberships (added before we stored it)
        # that are still cold — one best-effort Sleeper lookup, then persisted.
        if not name:
            try:
                client = SleeperClient()
                try:
                    lg, _ = await client.get_league(m.league_id)
                    name = lg.name
                finally:
                    await client.close()
                if name:
                    m.league_name = name
                    await db.flush()
            except Exception:
                log.exception("league name backfill failed for %s", m.league_id)
        out.append(
            MyLeague(
                league_id=m.league_id,
                name=name,
                season=season,
                warm=entry is not None,
                sleeper_roster_id=m.sleeper_roster_id,
                added_at=m.added_at.isoformat(),
            )
        )
    return out


@router.get("/api/me/sleeper-leagues", response_model=list[SleeperLeague])
@limiter.limit(get_settings().rate_limit_discovery)
async def sleeper_leagues(
    request: Request,
    username: str | None = None,
    season: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SleeperLeague]:
    """Discover a Sleeper user's leagues (dynasty, keeper, or redraft) for a
    season, marking ones already imported by this user. Defaults to the
    linked Sleeper username. Fans out to the public Sleeper API (cached
    briefly; rate-limited per user)."""
    uname = (username or user.sleeper_username or "").strip()
    if not uname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Sleeper username provided or linked to your account",
        )
    discovered = await _discover_leagues(uname, season)
    existing = {m.league_id for m in await memberships.list_for_user(db, user.id)}
    return [
        SleeperLeague(
            league_id=d["league_id"],
            name=d["name"],
            season=d["season"],
            total_rosters=d["total_rosters"],
            already_imported=d["league_id"] in existing,
            format=d["format"],
        )
        for d in discovered
    ]


@router.post("/api/me/leagues", response_model=MyLeague, status_code=201)
async def add_league(
    body: AddLeagueReq,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyLeague:
    """Import a league for the current user (idempotent, cap-enforced).

    Does no LLM work here: the league's cold-start refresh happens when the
    user opens it (the existing 409 → SSE refresh flow), so adding an already
    cached league costs nothing (first-importer-pays dedup)."""
    rows = await memberships.list_for_user(db, user.id)
    already = next((m for m in rows if m.league_id == body.league_id), None)
    if already is None:
        cap = get_settings().max_leagues_per_user
        if len(rows) >= cap:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"league limit reached ({cap})",
            )
    # Capture the league name now so the UI shows it immediately (before the
    # analysis cache warms). Prefer the client-supplied name; else fetch it.
    league_name = body.name
    if not league_name:
        try:
            client = SleeperClient()
            try:
                lg, _ = await client.get_league(body.league_id)
                league_name = lg.name
            finally:
                await client.close()
        except Exception:
            league_name = None

    m = await memberships.add(
        db,
        user_id=user.id,
        league_id=body.league_id,
        sleeper_roster_id=body.sleeper_roster_id,
        league_name=league_name,
    )
    # Roster auto-match ("this is you"): if the user linked Sleeper and we don't
    # already know their roster, find the roster they own in this league.
    if m.sleeper_roster_id is None and user.sleeper_user_id:
        try:
            client = SleeperClient()
            try:
                rosters = await client.get_rosters(body.league_id)
            finally:
                await client.close()
            for r in rosters:
                if r.owner_id == user.sleeper_user_id:
                    m.sleeper_roster_id = r.roster_id
                    await db.flush()
                    break
        except Exception:
            log.exception("roster auto-match failed for league %s", body.league_id)
    entry = ChainCache(cache_dir=_cache_dir()).read(m.league_id)
    return MyLeague(
        league_id=m.league_id,
        name=((entry.league_name_by_id or {}).get(m.league_id) if entry else None)
        or m.league_name,
        season=(entry.league_season_by_id or {}).get(m.league_id) if entry else None,
        warm=entry is not None,
        sleeper_roster_id=m.sleeper_roster_id,
        added_at=m.added_at.isoformat(),
    )


@router.delete("/api/me/leagues/{league_id}", status_code=204)
async def remove_league(
    league_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Drop a membership. The shared chain cache is intentionally left intact
    (the scheduler stops warming it once the last member leaves)."""
    await memberships.remove(db, user_id=user.id, league_id=league_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
