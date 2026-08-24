"""Shared slowapi limiter.

Keyed by the authenticated user (``request.state.user_id``, set in
``get_current_user``) so limits are per-user, not per-IP — important because all
API traffic arrives from the single web-proxy IP. Falls back to remote address
for unauthenticated routes.
"""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings


OG_CARD_KEY_PREFIX = "og-card:"


def _user_or_ip(request: Request) -> str:
    return getattr(request.state, "user_id", None) or get_remote_address(request)


def og_card_only(request: Request) -> bool:
    """`exempt_when` predicate: exempt everything that is NOT an og-card read.

    Returns True to EXEMPT (slowapi's sense), so a limit carrying this applies
    to social-card traffic alone. The four card endpoints are the main app's own
    routes — the dashboard, the leaderboard, an owner, a trade — so a blanket
    ceiling on them would throttle signed-in users to protect against crawlers.

    slowapi inspects the predicate's arity: a callable taking exactly ONE
    parameter is handed the request (`slowapi/wrappers.py:32`). Do not add or
    remove a parameter here — at any other arity it is called with no arguments,
    which would raise, and the limit's scoping would silently change.
    """
    key = getattr(request.state, "user_id", None) or ""
    return not str(key).startswith(OG_CARD_KEY_PREFIX)


limiter = Limiter(
    key_func=_user_or_ip,
    default_limits=[get_settings().rate_limit_default],
)
