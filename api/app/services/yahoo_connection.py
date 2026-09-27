"""Account-scoped Yahoo OAuth. No provider credentials leave this module.

Postgres user-row locks serialize start, reconnect, rotation and disconnect across
replicas, including when the connection row does not exist yet. SQLite is for local
development only; production concurrency relies on PostgreSQL FOR UPDATE.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import uuid
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app.config import get_settings
from app.db.models import User, YahooConnection, YahooLeagueGrant, YahooOAuthState

log = logging.getLogger(__name__)
AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def token_key():
    try:
        key = base64.b64decode(
            get_settings().yahoo_token_key, altchars=b"-_", validate=True
        )
        if len(key) != 32:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise HTTPException(
            503, "Yahoo connection is not configured. Contact the app owner."
        ) from None


def configured() -> bool:
    settings = get_settings()
    try:
        token_key()
    except HTTPException:
        return False
    redirect = urlparse(settings.yahoo_redirect_uri)
    return bool(
        settings.yahoo_client_id
        and redirect.scheme == "https"
        and redirect.netloc
        and not redirect.query
        and not redirect.fragment
    )


def require_config():
    if not configured():
        raise HTTPException(
            503, "Yahoo connection is not configured. Contact the app owner."
        )
    return get_settings()


def seal(user_id: str, purpose: str, value: dict) -> str:
    # Version prefix is part of the persisted envelope; never change v1 AAD.
    nonce = secrets.token_bytes(12)
    aad = json.dumps(["yahoo", 1, user_id, purpose]).encode()
    ciphertext = AESGCM(token_key()).encrypt(nonce, json.dumps(value).encode(), aad)
    return "v1." + base64.urlsafe_b64encode(nonce + ciphertext).decode()


def unseal(user_id: str, purpose: str, value: str) -> dict:
    key = token_key()
    try:
        version, encoded = value.split(".", 1)
        if version != "v1":
            raise ValueError
        data = base64.urlsafe_b64decode(encoded)
        aad = json.dumps(["yahoo", 1, user_id, purpose]).encode()
        return json.loads(AESGCM(key).decrypt(data[:12], data[12:], aad))
    except (ValueError, TypeError, InvalidTag):
        log.error("Yahoo credential could not be opened for user %s", user_id)
        raise HTTPException(
            409, "Yahoo authorization cannot be read. Reconnect Yahoo."
        ) from None


def oauth_client():
    return httpx.AsyncClient(timeout=20, follow_redirects=False)


async def exchange(data: dict) -> dict:
    settings = require_config()
    data = {
        **data,
        "client_id": settings.yahoo_client_id,
        "redirect_uri": settings.yahoo_redirect_uri,
    }
    if settings.yahoo_client_secret:
        data["client_secret"] = settings.yahoo_client_secret
    try:
        async with oauth_client() as client:
            response = await client.post(TOKEN_URL, data=data)
    except httpx.HTTPError:
        log.warning("Yahoo token endpoint unreachable")
        raise HTTPException(
            502, "Yahoo authorization timed out. Try connecting again."
        ) from None
    log.info("Yahoo token exchange HTTP %s", response.status_code)
    if response.status_code in (400, 401, 403):
        raise HTTPException(
            409, "Yahoo authorization expired or was declined. Reconnect Yahoo."
        )
    if response.status_code == 429:
        raise HTTPException(
            429, "Yahoo is rate limiting requests. Wait a minute and retry."
        )
    if response.status_code != 200:
        raise HTTPException(502, "Yahoo authorization is unavailable. Try again later.")
    try:
        result = response.json()
        if (
            not isinstance(result.get("access_token"), str)
            or not result["access_token"]
            or float(result["expires_in"]) <= 0
        ):
            raise ValueError
        return result
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(
            502, "Yahoo returned incomplete authorization. Try connecting again."
        ) from None


class YahooConnectionService:
    def __init__(self, db):
        self.db = db

    async def _lock(self, user_id):
        user = await self.db.scalar(
            select(User.id).where(User.id == user_id).with_for_update()
        )
        if user is None:
            raise HTTPException(401, "Sign in before connecting Yahoo.")

    async def start(self, user_id) -> str:
        settings = require_config()
        await self._lock(user_id)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        await self.db.execute(
            delete(YahooOAuthState).where(YahooOAuthState.user_id == user_id)
        )
        self.db.add(
            YahooOAuthState(
                user_id=user_id,
                state_hash=hashlib.sha256(state.encode()).hexdigest(),
                sealed_verifier=seal(user_id, "pkce", {"verifier": verifier}),
                expires_at=int(time.time()) + 600,
                consumed=False,
            )
        )
        await self.db.commit()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        return (
            AUTHORIZE_URL
            + "?"
            + urlencode(
                {
                    "client_id": settings.yahoo_client_id,
                    "redirect_uri": settings.yahoo_redirect_uri,
                    "response_type": "code",
                    "scope": "fspt-r",
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    async def complete(self, user_id, state: str, code: str):
        require_config()
        digest = hashlib.sha256(state.encode()).hexdigest()
        # Commit consumption BEFORE external I/O: rollback cannot enable replay.
        result = await self.db.execute(
            update(YahooOAuthState)
            .where(
                YahooOAuthState.user_id == user_id,
                YahooOAuthState.state_hash == digest,
                YahooOAuthState.expires_at > time.time(),
                YahooOAuthState.consumed.is_(False),
            )
            .values(consumed=True)
            .returning(YahooOAuthState.sealed_verifier)
        )
        encrypted = result.scalar_one_or_none()
        await self.db.commit()
        if encrypted is None:
            raise HTTPException(
                400, "Yahoo connection expired or was already used. Start again."
            )
        await self._lock(user_id)
        pending = await self.db.get(YahooOAuthState, user_id, populate_existing=True)
        if pending is None or pending.state_hash != digest:
            raise HTTPException(
                400, "Yahoo connection was replaced or cancelled. Start again."
            )
        verifier = unseal(user_id, "pkce", encrypted)["verifier"]
        tokens = await exchange(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
            }
        )
        if not tokens.get("refresh_token"):
            raise HTTPException(
                502, "Yahoo did not grant renewable access. Reconnect Yahoo."
            )
        row = await self.db.get(YahooConnection, user_id, populate_existing=True)
        if row is None:
            row = YahooConnection(user_id=user_id)
            self.db.add(row)
        row.generation = str(uuid.uuid4())
        self._set_tokens(row, tokens)
        await self.db.execute(
            delete(YahooLeagueGrant).where(YahooLeagueGrant.user_id == user_id)
        )
        await self.db.delete(pending)
        await self.db.commit()
        log.info("Yahoo connected for user %s", user_id)

    def _set_tokens(self, row, tokens):
        row.sealed_tokens = seal(
            row.user_id,
            "tokens",
            {
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
            },
        )
        row.expires_at = int(time.time()) + int(tokens["expires_in"])
        row.status = "connected"

    async def access_token(self, user_id) -> str:
        require_config()
        await self._lock(user_id)
        row = await self.db.get(YahooConnection, user_id, populate_existing=True)
        if row is None or row.status != "connected":
            raise HTTPException(409, "Connect Yahoo to access this league.")
        tokens = unseal(user_id, "tokens", row.sealed_tokens)
        if row.expires_at > time.time() + 120:
            return tokens["access_token"]
        try:
            refreshed = await exchange(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                }
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                row.status = "reconnect"
                await self.db.commit()
            raise
        refreshed.setdefault("refresh_token", tokens["refresh_token"])
        self._set_tokens(row, refreshed)
        # A later API error must not roll back a refresh-token rotation.
        await self.db.commit()
        await self._lock(user_id)
        current = await self.db.get(YahooConnection, user_id, populate_existing=True)
        if current is None or current.status != "connected":
            raise HTTPException(409, "Yahoo was disconnected. Connect Yahoo again.")
        return unseal(user_id, "tokens", current.sealed_tokens)["access_token"]

    async def has_grant(self, user_id, league_id) -> bool:
        value = await self.db.scalar(
            select(YahooLeagueGrant.league_id)
            .join(
                YahooConnection,
                YahooConnection.user_id == YahooLeagueGrant.user_id,
            )
            .where(
                YahooLeagueGrant.user_id == user_id,
                YahooLeagueGrant.league_id == league_id,
                YahooLeagueGrant.generation == YahooConnection.generation,
                YahooConnection.status == "connected",
                YahooLeagueGrant.expires_at > time.time(),
            )
        )
        return value is not None

    async def ensure_grant(self, user_id, league_id):
        if await self.has_grant(user_id, league_id):
            return
        await self._lock(user_id)
        if await self.has_grant(user_id, league_id):
            return  # a concurrent request revalidated while we waited
        row = await self.db.get(YahooConnection, user_id, populate_existing=True)
        grant = await self.db.get(
            YahooLeagueGrant, (user_id, league_id), populate_existing=True
        )
        if (
            row is None
            or row.status != "connected"
            or grant is None
            or grant.generation != row.generation
        ):
            raise HTTPException(
                409, "Yahoo connection required. Open Add a league to reconnect Yahoo."
            )
        # Provider membership is not permanent. Bound stale private-data access
        # to five minutes, even when another member keeps the shared cache warm.
        from app.services.yahoo_discovery import verify_league

        await verify_league(self.db, user_id, league_id)
        await self.db.commit()

    async def disconnect(self, user_id):
        await self._lock(user_id)
        for table in (YahooOAuthState, YahooLeagueGrant, YahooConnection):
            await self.db.execute(delete(table).where(table.user_id == user_id))
        await self.db.commit()
        log.info("Yahoo disconnected for user %s", user_id)
