"""Account connection security tests; only the Yahoo network is replaced."""

import asyncio
import base64
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from app.db.models import User
from fastapi import HTTPException
from sqlalchemy import select


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_YAHOO_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv(
        "TRADE_GRADER_YAHOO_REDIRECT_URI",
        "https://example.test/api/auth/callback/yahoo",
    )
    monkeypatch.setenv(
        "TRADE_GRADER_YAHOO_TOKEN_KEY", base64.urlsafe_b64encode(b"k" * 32).decode()
    )


def test_ciphertext_is_bound_to_user_and_purpose(configured):
    # Mutation: omit user/purpose from AES-GCM AAD, permitting credential swaps.
    from app.services.yahoo_connection import seal, unseal

    ciphertext = seal("u1", "tokens", {"access_token": "very-secret"})
    assert "very-secret" not in ciphertext
    assert unseal("u1", "tokens", ciphertext)["access_token"] == "very-secret"
    for uid, purpose in [("u2", "tokens"), ("u1", "pkce")]:
        with pytest.raises(HTTPException):
            unseal(uid, purpose, ciphertext)


def test_state_is_bound_single_use_and_pkce(maker, configured, monkeypatch):
    # Mutation: accept state for another user or permit callback replay.
    from app.db.models import YahooConnection, YahooOAuthState
    from app.services import yahoo_connection as yc

    requests = []

    def upstream(req):
        requests.append(req)
        return httpx.Response(
            200,
            json={
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
            },
        )

    monkeypatch.setattr(
        yc,
        "oauth_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )

    async def run():
        async with maker() as db:
            db.add_all(
                [
                    User(id="u1", google_sub="g1", email="a@test"),
                    User(id="u2", google_sub="g2", email="b@test"),
                ]
            )
            await db.commit()
            service = yc.YahooConnectionService(db)
            url = await service.start("u1")
            query = parse_qs(urlparse(url).query)
            assert query["scope"] == ["fspt-r"]
            assert query["code_challenge_method"] == ["S256"]
            state = query["state"][0]
            row = await db.get(YahooOAuthState, "u1")
            assert state not in row.state_hash
            with pytest.raises(HTTPException) as wrong_user:
                await service.complete("u2", state, "code")
            assert wrong_user.value.status_code == 400
            await service.complete("u1", state, "code")
            body = parse_qs(requests[0].content.decode())
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(body["code_verifier"][0].encode()).digest()
                )
                .decode()
                .rstrip("=")
            )
            assert query["code_challenge"] == [challenge]
            assert body["client_id"] == ["synthetic-client"]
            assert "client_secret" not in body
            row = await db.get(YahooConnection, "u1")
            assert "access-secret" not in row.sealed_tokens
            assert "refresh-secret" not in row.sealed_tokens
            with pytest.raises(HTTPException):
                await service.complete("u1", state, "code")
            assert len(requests) == 1

    asyncio.run(run())


def test_telemetry_drops_oauth_events_and_breadcrumbs():
    # Mutation: forward code/state/token requests to the error-monitoring vendor.
    from app.services.oauth_telemetry import before_send

    assert (
        before_send(
            {
                "request": {
                    "url": "https://app.test/api/me/yahoo/complete",
                    "data": {"code": "secret"},
                }
            },
            {},
        )
        is None
    )
    event = {
        "breadcrumbs": {
            "values": [
                {"data": {"url": "https://api.login.yahoo.com/oauth2/get_token"}},
                {"message": "safe"},
            ]
        }
    }
    assert before_send(event, {})["breadcrumbs"]["values"] == [{"message": "safe"}]


def test_expired_grant_rechecks_membership_and_fails_closed(
    maker, configured, monkeypatch
):
    # Mutation: grant generation alone permanently authorizes a former member.
    from app.db.models import YahooConnection, YahooLeagueGrant
    from app.services import yahoo_discovery as yd
    from app.services.yahoo_connection import YahooConnectionService, seal

    from sleeper_dynasty.api.yahoo import YahooAdapter

    payload = {
        "fantasy_content": {
            "users": {"0": {"user": [{}, {"games": {"count": 0}}]}, "count": 1}
        }
    }
    monkeypatch.setattr(
        yd,
        "YahooAdapter",
        lambda token: YahooAdapter(
            token,
            transport=httpx.MockTransport(
                lambda req: httpx.Response(200, json=payload)
            ),
        ),
    )

    async def run():
        async with maker() as db:
            db.add(User(id="u1", google_sub="g1", email="a@test"))
            await db.flush()
            db.add(
                YahooConnection(
                    user_id="u1",
                    generation="gen1",
                    sealed_tokens=seal(
                        "u1",
                        "tokens",
                        {"access_token": "secret", "refresh_token": "refresh"},
                    ),
                    expires_at=int(time.time()) + 3600,
                    status="connected",
                )
            )
            db.add(
                YahooLeagueGrant(
                    user_id="u1",
                    league_id="999.l.123",
                    generation="gen1",
                    expires_at=int(time.time()) - 1,
                )
            )
            await db.commit()
            service = YahooConnectionService(db)
            assert not await service.has_grant("u1", "999.l.123")
            with pytest.raises(HTTPException) as denied:
                await service.ensure_grant("u1", "999.l.123")
            assert denied.value.status_code == 403
            await db.rollback()  # mirrors get_db on the failed request
        async with maker() as db:
            assert await db.get(YahooLeagueGrant, ("u1", "999.l.123")) is None

    asyncio.run(run())


def test_expired_state_never_calls_yahoo(maker, configured):
    # Mutation: drop the expiry predicate when consuming OAuth state.
    from app.db.models import YahooOAuthState
    from app.services.yahoo_connection import YahooConnectionService

    async def run():
        async with maker() as db:
            db.add(User(id="u1", google_sub="g1", email="a@test"))
            await db.commit()
            svc = YahooConnectionService(db)
            url = await svc.start("u1")
            state = parse_qs(urlparse(url).query)["state"][0]
            row = await db.get(YahooOAuthState, "u1")
            row.expires_at = time.time() - 1
            await db.commit()
            with pytest.raises(HTTPException) as error:
                await svc.complete("u1", state, "unused")
            assert error.value.status_code == 400

    asyncio.run(run())


def test_refresh_rotation_disconnect_and_account_generation(
    maker, configured, monkeypatch
):
    # Mutation: keep an old refresh token or authorize a grant after disconnect.
    from app.db.models import YahooConnection, YahooLeagueGrant
    from app.services import yahoo_connection as yc

    calls = []

    def upstream(req):
        calls.append(parse_qs(req.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "rotated",
                "expires_in": 3600,
            },
        )

    monkeypatch.setattr(
        yc,
        "oauth_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
    )

    async def run():
        async with maker() as db:
            db.add(User(id="u1", google_sub="g1", email="a@test"))
            await db.flush()
            db.add(
                YahooConnection(
                    user_id="u1",
                    generation="gen1",
                    sealed_tokens=yc.seal(
                        "u1",
                        "tokens",
                        {"access_token": "old", "refresh_token": "original"},
                    ),
                    expires_at=0,
                    status="connected",
                )
            )
            db.add(
                YahooLeagueGrant(user_id="u1", league_id="999.l.123", generation="gen1")
            )
            await db.commit()
            svc = yc.YahooConnectionService(db)
            assert await svc.access_token("u1") == "new-access"
            assert calls[0]["refresh_token"] == ["original"]
            row = await db.get(YahooConnection, "u1")
            assert (
                yc.unseal("u1", "tokens", row.sealed_tokens)["refresh_token"]
                == "rotated"
            )
            assert await svc.has_grant("u1", "999.l.123")
            assert not await svc.has_grant("u2", "999.l.123")
            row.generation = "gen2"
            await db.commit()
            assert not await svc.has_grant("u1", "999.l.123")
            await svc.disconnect("u1")
            assert await db.get(YahooConnection, "u1") is None
            assert not (await db.execute(select(YahooLeagueGrant))).scalars().all()

    asyncio.run(run())


def test_provider_errors_are_redacted_and_revocation_persists(
    maker, configured, monkeypatch
):
    # Mutation: reflect OAuth response bodies or roll back reconnect status.
    from app.db.models import YahooConnection
    from app.services import yahoo_connection as yc

    monkeypatch.setattr(
        yc,
        "oauth_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    400, json={"error": "invalid_grant", "description": "super-secret"}
                )
            )
        ),
    )

    async def run():
        async with maker() as db:
            db.add(User(id="u1", google_sub="g1", email="a@test"))
            await db.flush()
            db.add(
                YahooConnection(
                    user_id="u1",
                    generation="gen1",
                    sealed_tokens=yc.seal(
                        "u1",
                        "tokens",
                        {"access_token": "old", "refresh_token": "original"},
                    ),
                    expires_at=0,
                    status="connected",
                )
            )
            await db.commit()
            with pytest.raises(HTTPException) as error:
                await yc.YahooConnectionService(db).access_token("u1")
            assert error.value.status_code == 409
            assert "super-secret" not in str(error.value)
        async with maker() as db:
            assert (await db.get(YahooConnection, "u1")).status == "reconnect"

    asyncio.run(run())


def test_discovery_uses_real_envelope_and_verified_grants(
    maker, configured, monkeypatch
):
    # Mutation: trust a posted league key, or flatten away Yahoo's numeric wrappers.
    from app.db.models import YahooConnection
    from app.services import yahoo_discovery as yd
    from app.services.yahoo_connection import YahooConnectionService, seal

    from sleeper_dynasty.api.yahoo import YahooAdapter

    fixture = json.loads(
        (Path(__file__).parents[2] / "tests/fixtures/yahoo/discovery.json").read_text()
    )

    def upstream(req):
        if "/users;" in req.url.path:
            return httpx.Response(200, json=fixture)
        return httpx.Response(
            200,
            json={
                "fantasy_content": {
                    "league": [{}, {"settings": [{"uses_roster_import": "1"}]}]
                }
            },
        )

    monkeypatch.setattr(
        yd,
        "YahooAdapter",
        lambda token: YahooAdapter(token, transport=httpx.MockTransport(upstream)),
    )

    async def run():
        async with maker() as db:
            db.add(User(id="u1", google_sub="g1", email="a@test"))
            await db.flush()
            db.add(
                YahooConnection(
                    user_id="u1",
                    generation="gen1",
                    sealed_tokens=seal(
                        "u1",
                        "tokens",
                        {"access_token": "secret", "refresh_token": "refresh"},
                    ),
                    expires_at=time.time() + 3600,
                    status="connected",
                )
            )
            await db.commit()
            leagues = await yd.discover(db, "u1")
            assert len(leagues) == 4
            assert leagues[0]["league_id"] == "999.l.100000001"
            assert leagues[0]["format"] == "keeper"
            assert leagues[0]["total_rosters"] == 10
            assert await YahooConnectionService(db).has_grant(
                "u1", leagues[0]["league_id"]
            )
            with pytest.raises(HTTPException) as error:
                await yd.verify_league(db, "u1", "999.l.999")
            assert error.value.status_code == 403

    asyncio.run(run())


def test_http_connect_discover_add_read_disconnect_cycle(
    maker, configured, monkeypatch
):
    # Mutation: integration wiring bypasses auth/membership, exposes tokens, or
    # disconnect leaves private cached routes readable.
    import jwt
    from app.db.session import get_db
    from app.main import app
    from app.services import yahoo_connection as yc
    from app.services import yahoo_discovery as yd
    from fastapi.testclient import TestClient

    from sleeper_dynasty.api.yahoo import YahooAdapter

    secret = "test-integration-backend-secret-at-least-32-bytes"
    monkeypatch.setenv("TRADE_GRADER_AUTH_BACKEND_SECRET", secret)
    fixture = json.loads(
        (Path(__file__).parents[2] / "tests/fixtures/yahoo/discovery.json").read_text()
    )

    def upstream(req):
        if req.url.host == "api.login.yahoo.com":
            return httpx.Response(
                200,
                json={
                    "access_token": "provider-access",
                    "refresh_token": "provider-refresh",
                    "expires_in": 3600,
                },
            )
        if "/users;" in req.url.path:
            return httpx.Response(200, json=fixture)
        return httpx.Response(
            200,
            json={
                "fantasy_content": {
                    "league": [{}, {"settings": [{"uses_roster_import": "1"}]}]
                }
            },
        )

    transport = httpx.MockTransport(upstream)
    monkeypatch.setattr(
        yc, "oauth_client", lambda: httpx.AsyncClient(transport=transport)
    )
    monkeypatch.setattr(
        yd, "YahooAdapter", lambda token: YahooAdapter(token, transport=transport)
    )

    async def db_override():
        async with maker() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = db_override

    def headers(sub):
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {"sub": sub, "email": f"{sub}@example.test", "exp": time.time() + 600},
                secret,
                algorithm="HS256",
            )
        }

    try:
        c = TestClient(app)
        assert c.get("/api/me/yahoo/status").status_code == 401
        c.headers.update(headers("g1"))
        assert c.get("/api/me/yahoo/status").json()["status"] == "disconnected"
        started = c.post("/api/me/yahoo/start")
        assert started.status_code == 200
        state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][
            0
        ]
        result = c.post(
            "/api/me/yahoo/complete", json={"state": state, "code": "fixture-code"}
        )
        assert result.json() == {"status": "connected"}
        discovered = c.get("/api/me/yahoo/leagues")
        assert discovered.status_code == 200
        key = discovered.json()[0]["league_id"]
        added = c.post(
            "/api/me/leagues", json={"league_id": key, "name": "untrusted name"}
        )
        assert added.status_code == 201
        assert added.json()["name"] == "Example League"
        assert c.get(f"/api/league/{key}/profiles").status_code == 200
        assert (
            c.get(f"/api/league/{key}/profiles", headers=headers("g2")).status_code
            == 403
        )
        assert c.delete("/api/me/yahoo/connection").status_code == 200
        assert c.get(f"/api/league/{key}/profiles").status_code == 409
        assert len(c.get("/api/me/leagues").json()) == 1
    finally:
        app.dependency_overrides.clear()
