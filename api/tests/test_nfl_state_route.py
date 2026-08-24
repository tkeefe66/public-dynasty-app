"""Current NFL week for the TopBar note (followup C2).

The note is app chrome: it renders before a league is chosen, so this endpoint
is user-scoped but never league-gated, and an upstream failure has to degrade to
silence rather than put an error in the chrome.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user
from app.main import app as fastapi_app
from app.routes import nfl_state as nfl_state_route
from app.services import nfl_state as nfl_state_service


@pytest.fixture()
def client():
    fastapi_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
    nfl_state_service.reset_cache()
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()
        nfl_state_service.reset_cache()


class _Client:
    """Counts calls so the in-process memo can be asserted."""

    def __init__(self, state):
        self.state = state
        self.calls = 0

    async def get_nfl_state(self):
        self.calls += 1
        if isinstance(self.state, Exception):
            raise self.state
        return self.state


def _serve(monkeypatch, state):
    """Substitute the route's state source. No test here touches the network."""
    async def _fetch(client=None):
        return state
    monkeypatch.setattr(nfl_state_route.state_service, "fetch_state", _fetch)


def test_returns_the_current_week(client, monkeypatch):
    _serve(monkeypatch, {"season": "2026", "season_type": "regular", "week": 14})
    r = client.get("/api/nfl-state")
    assert r.status_code == 200
    assert r.json() == {"season": "2026", "season_type": "regular", "week": 14}


def test_upstream_failure_is_a_200_with_nulls(client, monkeypatch):
    _serve(monkeypatch, None)
    r = client.get("/api/nfl-state")
    # Not a 502: the note's contract is to render nothing when the week is
    # unknown, and an error here would surface in the chrome of a working page.
    assert r.status_code == 200
    assert r.json() == {"season": None, "season_type": None, "week": None}


def test_non_numeric_week_degrades_to_null(client, monkeypatch):
    _serve(monkeypatch, {"season": "2026", "season_type": "regular", "week": "soon"})
    assert client.get("/api/nfl-state").json()["week"] is None


def test_requires_a_user_but_no_league_membership():
    # No get_current_user override: the route rejects anonymous callers, and it
    # is registered without the league guard, so it can't 409 on a cold cache.
    fastapi_app.dependency_overrides.clear()
    r = TestClient(fastapi_app).get("/api/nfl-state")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_fetch_state_memoizes_within_the_ttl():
    nfl_state_service.reset_cache()
    fake = _Client({"season": "2026", "season_type": "regular", "week": 14})
    first = await nfl_state_service.fetch_state(fake)
    second = await nfl_state_service.fetch_state(fake)
    assert first == second
    assert fake.calls == 1  # one upstream call serves every page view in the window
    nfl_state_service.reset_cache()


@pytest.mark.asyncio
async def test_fetch_state_returns_none_on_failure_with_no_cache():
    nfl_state_service.reset_cache()
    fake = _Client(RuntimeError("sleeper down"))
    assert await nfl_state_service.fetch_state(fake) is None
    nfl_state_service.reset_cache()


@pytest.mark.asyncio
async def test_fetch_state_serves_the_stale_memo_on_failure():
    """A blip shouldn't blank the note when we already know the week."""
    nfl_state_service.reset_cache()
    good = _Client({"season": "2026", "season_type": "regular", "week": 14})
    await nfl_state_service.fetch_state(good)
    # Force the memo past its TTL rather than sleeping through it.
    nfl_state_service._cache = (0.0, nfl_state_service._cache[1])
    bad = _Client(RuntimeError("sleeper down"))
    assert await nfl_state_service.fetch_state(bad) == {
        "season": "2026", "season_type": "regular", "week": 14,
    }
    nfl_state_service.reset_cache()
