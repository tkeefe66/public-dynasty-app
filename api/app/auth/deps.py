from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import TokenError, decode_backend_token
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.ratelimit import OG_CARD_KEY_PREFIX
from app.repositories import memberships, users

# ── Social-card (OG image) principal ──────────────────────────────────────────
#
# The web app's four `opengraph-image.tsx` routes render a league/owner/trade
# card for link unfurls. An unfurl crawler (Slack, iMessage, Twitter) carries no
# session, and Next's metadata routes get no session even for a signed-in
# visitor, so those routes cannot borrow a user token. They mint their own
# token instead — signed with the same shared secret, but carrying
# ``scope: "og-card"`` and **no identity claims at all** (no ``sub``, no
# ``email``). See ``web/lib/og-token.ts`` for the minting side.
#
# This principal is deliberately NOT a user:
#
#   * ``get_current_user`` rejects an og-card token outright (401). That is what
#     keeps it out of ``users.upsert_from_token`` and ``users.touch_activity``,
#     so card traffic can never create a user row nor inflate the active-days
#     engagement metric. It also seals off every router that depends on
#     ``get_current_user`` directly — ``/api/me/*``, ``/api/events``,
#     ``/api/admin/*``, and the two MUTATING bets handlers (``POST /bets``,
#     ``PATCH /bets/{id}``). NB the bets READS (``GET /bets``,
#     ``GET /bets/summary``) do NOT depend on it; they are closed to card
#     traffic by the path allowlist below instead, which is the only thing
#     keeping them shut. Widen that allowlist and you open these.
#   * ``require_league_member`` admits it for GET/HEAD on exactly the four read
#     endpoints the cards fetch, and nothing else. Every other league route —
#     including ``/refresh``, ``/profiles``, ``/bets`` and ``/owner-names`` —
#     falls through to the normal user path and 401s.
#
# ACCEPTED EXPOSURE: this makes league card data readable without a session,
# because that is the only way a crawler can render a real card. The token
# itself never leaves the Next.js server (it is minted per-render inside the
# image route), so the exposure is bounded by what those four card images print.
SCOPE_CLAIM = "scope"
OG_CARD_SCOPE = "og-card"

# Route templates an og-card token may read, matched against the request path.
# Anything not listed here is unreachable with an og-card token. Adding a
# pattern widens the anonymous read surface — do not add one without deciding
# that the endpoint's whole response is safe to publish.
_OG_CARD_READABLE = (
    re.compile(r"^/api/league/[^/]+$"),  # dashboard  → league card
    re.compile(r"^/api/league/[^/]+/leaderboard$"),  # → Franchise Ratings card
    re.compile(r"^/api/league/[^/]+/owner/[^/]+$"),  # → franchise card
    re.compile(r"^/api/league/[^/]+/trade/[^/]+$"),  # → trade verdict card
)


@dataclass(frozen=True)
class OgCardPrincipal:
    """Non-user, read-only principal for social-card rendering.

    Deliberately shaped like the attributes a route might read off ``User`` so a
    stray access degrades safely: no id, never admin. It is never persisted and
    never counted in any product metric.
    """

    id: str | None = None
    is_admin: bool = False


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return header.split(" ", 1)[1].strip()


def _decode(request: Request) -> dict:
    """Verify the bearer token and return its claims, or 401."""
    token = _bearer_token(request)
    try:
        return decode_backend_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _is_og_card_read(request: Request, claims: dict) -> bool:
    """True when this request is an og-card token doing one of the four card
    reads. Fails closed on anything else (wrong scope, write method, any other
    path)."""
    if claims.get(SCOPE_CLAIM) != OG_CARD_SCOPE:
        return False
    if request.method not in {"GET", "HEAD"}:
        return False
    path = request.url.path
    return any(pat.match(path) for pat in _OG_CARD_READABLE)


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """Authenticate the request from the backend-facing JWT and upsert the
    user row so a record exists on first authenticated hit. 401 on any
    missing/invalid token."""
    claims = _decode(request)

    # An og-card token is not an identity and must never reach the upsert or the
    # active-days stamp below — it would mint a junk user row and count a
    # crawler as a daily active user. Rejecting it here (rather than filtering
    # downstream) is what keeps every user-scoped route closed to card traffic.
    if claims.get(SCOPE_CLAIM) == OG_CARD_SCOPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="og-card token is not a user identity",
            headers={"WWW-Authenticate": "Bearer"},
        )

    google_sub = claims.get("sub")
    email = (claims.get("email") or "").lower()
    if not google_sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token missing sub"
        )

    admin_emails = get_settings().admin_email_list
    user = await users.upsert_from_token(
        db,
        google_sub=str(google_sub),
        email=email,
        name=claims.get("name"),
        avatar_url=claims.get("picture"),
        is_admin=email in admin_emails,
    )
    # Engagement: record activity for today (at most one write per user per day).
    await users.touch_activity(db, user)
    # Expose the user id for the rate limiter's key function (per-user limits).
    request.state.user_id = user.id
    return user


async def require_league_member(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | OgCardPrincipal:
    """Authorize the request for the ``{league_id}`` path param: membership row
    OR the rollout-bridge allowlist. 403 otherwise.

    This resolves the user itself (a direct call, not ``Depends``) so the
    og-card branch below can run *before* ``get_current_user`` — the whole point
    of that branch is to avoid the user upsert and the active-days write.
    """
    league_id = request.path_params.get("league_id")
    if not league_id:
        # Misapplied guard (route has no league_id) — fail closed loudly.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="league guard applied to a route without a league_id",
        )

    # Social-card reads: a sessionless, non-user principal, allowed only for
    # GET/HEAD on the four card endpoints (see the module header for the
    # accepted exposure). Checked first and before any DB touch so no user row
    # and no engagement metric is ever written for card traffic.
    claims = _decode(request)
    if _is_og_card_read(request, claims):
        # Rate-limit key. Card traffic has no user id, so without this it would
        # key by the web proxy's IP and share a budget with every other request.
        #
        # Keyed PER LEAGUE, not a single global "og-card" bucket: one bucket
        # worldwide means anyone hammering one league's card starves every other
        # league's unfurls. Per-league bounds the damage to the league being
        # abused. The limit itself is applied on the four card endpoints
        # (`rate_limit_og_card`, scoped by `ratelimit.og_card_only` so signed-in
        # users on those same routes are not throttled) — setting this key alone
        # meters nothing.
        request.state.user_id = f"{OG_CARD_KEY_PREFIX}{league_id}"
        return OgCardPrincipal()

    user = await get_current_user(request, db)
    if await memberships.is_member(db, user.id, league_id):
        return user
    # Rollout bridge: any signed-in user may *read* the allowlisted league, but
    # writes (PUT owner-names/profiles) still require a real membership row.
    allowlisted = get_settings().allowlisted_league_id
    if league_id == allowlisted and request.method in {"GET", "HEAD"}:
        return user
    # Admin support access: the app owner opens leagues they do not belong to,
    # to see how one is set up and to reproduce reported bugs. Read-only for the
    # same reason as the bridge above — there is no undo on an owner-name
    # override or a bet mutation, and a debugging session must not be able to
    # change a stranger's league. `/refresh` is a GET, so warming a cold cache
    # to reproduce something still works.
    #
    # This lives here, at the one chokepoint every league router already depends
    # on, so no current route misses it and no future route forgets it.
    if user.is_admin and request.method in {"GET", "HEAD"}:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="not a member of this league",
    )


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin only"
        )
    return user
