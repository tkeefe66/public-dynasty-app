from __future__ import annotations

import jwt

from app.config import get_settings


class TokenError(Exception):
    """Raised when the backend-facing token is missing, malformed, or invalid."""


def decode_backend_token(token: str) -> dict:
    """Verify and decode the HS256 token minted by the frontend (NextAuth).

    The shared secret is ``TRADE_GRADER_AUTH_BACKEND_SECRET`` (must match the
    web app's ``AUTH_BACKEND_SECRET``). Returns the claims dict; raises
    ``TokenError`` on any failure.
    """
    secret = get_settings().auth_backend_secret
    if not secret:
        raise TokenError("auth_backend_secret is not configured")
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:  # bad signature, expired, malformed, ...
        raise TokenError(str(exc)) from exc
