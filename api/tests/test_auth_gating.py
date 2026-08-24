from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import LeagueMembership, User
from app.db.session import get_db
from app.main import app as fastapi_app

SECRET = "test-secret-at-least-32-bytes-long-xxxxxx"


def _token(secret: str = SECRET, *, sub: str = "g-1", email: str = "u@test.local") -> str:
    payload = {
        "sub": sub,
        "email": email,
        "name": "U",
        "picture": None,
        "exp": datetime.now(tz=timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _og_token(secret: str = SECRET, **extra) -> str:
    """The sessionless token the OG-card image routes mint (web/lib/og-token.ts):
    a scope, with no identity claims at all."""
    payload = {
        "scope": "og-card",
        "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=2),
        **extra,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def db_maker(tmp_path):
    """Per-test SQLite DB wired into the app via a get_db override."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        yield maker
    finally:
        fastapi_app.dependency_overrides.clear()
        asyncio.run(engine.dispose())


@pytest.fixture()
def client(db_maker, monkeypatch):
    # Real auth path (no get_current_user override). Configure the shared secret.
    monkeypatch.setenv("TRADE_GRADER_AUTH_BACKEND_SECRET", SECRET)
    return TestClient(fastapi_app)


def _seed_member(maker, *, google_sub: str, league_id: str, is_admin: bool = False):
    async def _run():
        async with maker() as db:
            user = User(google_sub=google_sub, email="u@test.local", is_admin=is_admin)
            db.add(user)
            await db.flush()
            db.add(LeagueMembership(user_id=user.id, league_id=league_id))
            await db.commit()

    asyncio.run(_run())


# ── League routes ─────────────────────────────────────────────────────────────


def test_league_route_401_without_token(client):
    resp = client.get("/api/league/L1/owner-names")
    assert resp.status_code == 401


def test_league_route_401_with_bad_signature(client):
    resp = client.get("/api/league/L1/owner-names", headers=_auth(_token("wrong-secret")))
    assert resp.status_code == 401


def test_league_route_403_without_membership(client):
    # Valid token, but no membership row and league is not allowlisted.
    resp = client.get("/api/league/L1/owner-names", headers=_auth(_token()))
    assert resp.status_code == 403


def test_league_route_passes_guard_with_membership(client, db_maker):
    _seed_member(db_maker, google_sub="g-1", league_id="L1")
    resp = client.get("/api/league/L1/owner-names", headers=_auth(_token()))
    # Guard passed → handler ran and hit a cold cache (409). The point is it is
    # neither 401 nor 403.
    assert resp.status_code == 409


def test_league_route_passes_guard_via_allowlist(client, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_ALLOWLISTED_LEAGUE_ID", "L1")
    resp = client.get("/api/league/L1/owner-names", headers=_auth(_token()))
    assert resp.status_code == 409  # guard passed without a membership row


def test_allowlist_does_not_grant_writes(client, monkeypatch):
    # The rollout bridge is read-only: a PUT to the allowlisted league without a
    # membership row must still be 403.
    monkeypatch.setenv("TRADE_GRADER_ALLOWLISTED_LEAGUE_ID", "L1")
    resp = client.put(
        "/api/league/L1/owner-names",
        json={"overrides": {}},
        headers=_auth(_token()),
    )
    assert resp.status_code == 403


# ── Admin routes ──────────────────────────────────────────────────────────────


def test_admin_route_401_without_token(client):
    assert client.get("/api/settings/config").status_code == 401


def test_admin_route_403_for_non_admin(client):
    resp = client.get("/api/settings/config", headers=_auth(_token()))
    assert resp.status_code == 403


def test_admin_route_200_for_admin(client, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "admin@test.local")
    resp = client.get(
        "/api/settings/config", headers=_auth(_token(email="admin@test.local"))
    )
    assert resp.status_code == 200
    assert "llm_model" in resp.json()


# ── Open route ────────────────────────────────────────────────────────────────


def test_health_is_open(client):
    assert client.get("/api/health").status_code == 200


# ── Bets route ────────────────────────────────────────────────────────────────


def test_bets_route_gated_and_db_backed(client, db_maker):
    # Anonymous → 401 (guard applies to the bets router).
    resp = client.get("/api/league/L1/bets")
    assert resp.status_code == 401
    # Member → 200 with an empty ledger: bets are DB-backed, no 409 cold-cache.
    _seed_member(db_maker, google_sub="g-1", league_id="L1")
    resp = client.get("/api/league/L1/bets", headers=_auth(_token()))
    assert resp.status_code == 200
    assert resp.json() == {"bets": []}


# ── Admin cross-league access ─────────────────────────────────────────────────
#
# The app owner is the only admin and needs to open leagues they are not a
# member of, to see how another league is set up and to reproduce bugs. The
# capability is deliberately the smallest one that covers that: reads pass,
# writes do not. See docs/superpowers/specs/2026-08-12-admin-league-access-design.md


def test_admin_may_read_a_league_they_are_not_a_member_of(
    client, db_maker, monkeypatch
):
    # `is_admin` is derived from ADMIN_EMAILS on every upsert, so seeding the
    # DB row does not grant it — drive the real path. Membership is on a
    # DIFFERENT league, so nothing but the admin flag can be letting them into L1.
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "u@test.local")
    _seed_member(db_maker, google_sub="g-1", league_id="L-OTHER")
    resp = client.get("/api/league/L1/owner-names", headers=_auth(_token()))
    # Guard passed → handler ran and hit a cold cache. Neither 401 nor 403.
    assert resp.status_code == 409


def test_admin_access_does_not_grant_writes(client, db_maker, monkeypatch):
    """Read + refresh only. There is no undo on an owner-name override, so a
    debugging session must not be able to mutate a stranger's league."""
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "u@test.local")
    _seed_member(db_maker, google_sub="g-1", league_id="L-OTHER")
    resp = client.put(
        "/api/league/L1/owner-names",
        headers=_auth(_token()),
        json={"names": {"u1": "X"}},
    )
    assert resp.status_code == 403


def test_non_admin_still_cannot_read_someone_elses_league(client, db_maker):
    """The bypass keys on is_admin, not on merely being signed in."""
    _seed_member(db_maker, google_sub="g-1", league_id="L-OTHER")
    resp = client.get("/api/league/L1/owner-names", headers=_auth(_token()))
    assert resp.status_code == 403


def test_admin_membership_still_grants_writes_on_their_own_league(
    client, db_maker, monkeypatch
):
    """Being admin must not COST an admin anything on a league they belong to."""
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "u@test.local")
    _seed_member(db_maker, google_sub="g-1", league_id="L1")
    resp = client.put(
        "/api/league/L1/owner-names",
        headers=_auth(_token()),
        json={"names": {"u1": "X"}},
    )
    assert resp.status_code != 403


# ── OG card (social share image) principal ────────────────────────────────────
#
# The four opengraph-image routes render league/owner/trade share cards for link
# unfurls. Crawlers carry no session, so those routes mint a scoped, identity-
# less token instead (web/lib/og-token.ts). This DELIBERATELY exposes the card
# data to unauthenticated requests; these tests pin the boundary that keeps the
# exposure to exactly that. See app/auth/deps.py's module header.


@pytest.mark.parametrize(
    "path",
    [
        "/api/league/L1",
        "/api/league/L1/leaderboard",
        "/api/league/L1/owner/u1",
        "/api/league/L1/trade/t1",
    ],
)
def test_og_token_may_read_the_four_card_endpoints(client, path):
    # No membership row, no allowlist, no admin: the og scope alone gets in.
    # 409 = the guard passed and the handler hit a cold cache. Not 401/403.
    resp = client.get(path, headers=_auth(_og_token()))
    assert resp.status_code == 409, resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/league/L1/owner-names",
        "/api/league/L1/profiles",
        "/api/league/L1/bets",
        "/api/league/L1/refresh",
        "/api/league/L1/trades",
        "/api/league/L1/draft/2024",
    ],
)
def test_og_token_cannot_read_any_other_league_route(client, path):
    """The allowlist is four paths. Everything else on the league routers —
    including /refresh, which would kick off an expensive rebuild — falls
    through to the user path and 401s."""
    resp = client.get(path, headers=_auth(_og_token()))
    assert resp.status_code == 401, resp.text


def test_og_token_cannot_write(client):
    resp = client.put(
        "/api/league/L1/owner-names",
        json={"overrides": {}},
        headers=_auth(_og_token()),
    )
    assert resp.status_code == 401


def test_og_card_reads_are_rate_limited(client, monkeypatch):
    """The four card endpoints are reachable WITHOUT a session, and each hit
    costs a backend read plus a Satori rasterization in the web service.

    This is a regression test with a specific history: the og branch set a
    rate-limit KEY (`request.state.user_id`) but nothing applied a LIMIT to
    these endpoints, and no SlowAPIMiddleware is registered — so 300 consecutive
    og reads produced zero 429s. Setting a key meters nothing on its own.
    """
    from app.ratelimit import limiter

    limiter.reset()
    monkeypatch.setenv("TRADE_GRADER_RATE_LIMIT_OG_CARD", "3/minute")

    codes = [
        client.get("/api/league/L1", headers=_auth(_og_token())).status_code
        for _ in range(6)
    ]
    limiter.reset()

    # 409 = guard passed, cold cache. The limit must cut in before all six.
    assert 429 in codes, f"og traffic was never throttled: {codes}"
    assert codes[0] == 409, codes


def test_rate_limit_does_not_throttle_a_signed_in_user(client, monkeypatch):
    """The og limit must NOT apply to real users. These four are the main app's
    own routes — the dashboard, the leaderboard, an owner, a trade — so a
    blanket ceiling would throttle normal usage to defend against crawlers.
    `og_card_only` is what scopes it; this proves the scoping works.
    """
    from app.ratelimit import limiter

    limiter.reset()
    monkeypatch.setenv("TRADE_GRADER_RATE_LIMIT_OG_CARD", "3/minute")

    codes = [
        client.get("/api/league/L1", headers=_auth(_token())).status_code
        for _ in range(6)
    ]
    limiter.reset()

    assert 429 not in codes, f"a signed-in user was throttled by the og limit: {codes}"


@pytest.mark.parametrize(
    "path", ["/api/me", "/api/me/leagues", "/api/settings/config", "/api/nfl-state"]
)
def test_og_token_is_not_a_user_identity(client, path):
    """get_current_user rejects the scope outright, which is what closes every
    user-scoped router (and, below, the user upsert + active-days stamp)."""
    resp = client.get(path, headers=_auth(_og_token()))
    assert resp.status_code == 401, resp.text


def test_og_token_cannot_post_telemetry(client):
    resp = client.post(
        "/api/events", json={"path": "/league/L1"}, headers=_auth(_og_token())
    )
    assert resp.status_code == 401


def test_og_token_creates_no_user_row_and_no_active_day(client, db_maker):
    """The product-metric guarantee: card traffic must not mint junk users nor
    count as a daily active user."""
    for _ in range(3):
        assert client.get("/api/league/L1", headers=_auth(_og_token())).status_code == 409

    async def _count():
        async with db_maker() as db:
            rows = (await db.execute(select(User))).scalars().all()
            return [(r.email, r.active_days) for r in rows]

    assert asyncio.run(_count()) == []


def test_og_token_with_identity_claims_still_cannot_impersonate(client, db_maker):
    """Even if a scoped token also carried a sub/email, the scope check runs
    first — so no user row is upserted for it."""
    token = _og_token(sub="g-og", email="crawler@test.local")
    assert client.get("/api/me", headers=_auth(token)).status_code == 401

    async def _count():
        async with db_maker() as db:
            return (await db.execute(select(User))).scalars().all()

    assert asyncio.run(_count()) == []


def test_og_token_with_bad_signature_is_rejected(client):
    resp = client.get("/api/league/L1", headers=_auth(_og_token("wrong-secret")))
    assert resp.status_code == 401


def test_user_token_still_cannot_read_a_stranger_league_via_card_paths(client, db_maker):
    """The og branch keys on the scope claim, not on the path: a normal session
    token hitting a card path is still membership-gated."""
    _seed_member(db_maker, google_sub="g-1", league_id="L-OTHER")
    assert client.get("/api/league/L1", headers=_auth(_token())).status_code == 403


def test_og_read_never_calls_the_user_writers(client, monkeypatch):
    """Rollback-immune version of the no-user-row guarantee, WITH a control.

    ``test_og_token_creates_no_user_row_and_no_active_day`` counts ``User`` rows
    after three card GETs — but every card endpoint answers 409 on a cold cache,
    and the ``db_maker`` fixture rolls the session back on any raised
    HTTPException. A normal, fully-upserted user token doing the same three GETs
    therefore also leaves zero rows, so that assertion holds whether or not the
    og branch short-circuits. It cannot fail.

    This one spies on the two writers instead, and pins the control explicitly:
    the spies must stay silent for og traffic and must fire for a session token
    on the same endpoint at the same 4xx status.
    """
    from app.auth import deps

    real_upsert = deps.users.upsert_from_token
    real_touch = deps.users.touch_activity
    calls: list[str] = []

    async def spy_upsert(db, **kw):
        calls.append("upsert")
        return await real_upsert(db, **kw)

    async def spy_touch(db, user):
        calls.append("touch")
        return await real_touch(db, user)

    monkeypatch.setattr(deps.users, "upsert_from_token", spy_upsert)
    monkeypatch.setattr(deps.users, "touch_activity", spy_touch)

    for path in (
        "/api/league/L1",
        "/api/league/L1/leaderboard",
        "/api/league/L1/owner/u1",
        "/api/league/L1/trade/t1",
    ):
        assert client.get(path, headers=_auth(_og_token())).status_code == 409
    assert calls == [], f"og traffic reached the user writers: {calls}"

    # CONTROL: same fixture, same endpoint, same 4xx — a session token *does*
    # reach both writers. Without this the assertion above proves nothing.
    assert client.get("/api/league/L1", headers=_auth(_token())).status_code == 403
    assert calls == ["upsert", "touch"]
