from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import sleeper_dynasty.cache as cache_mod
from sleeper_dynasty.cache import FileCache

from app.auth.deps import get_current_user, require_admin, require_league_member
from app.db.base import Base
from app.main import app as fastapi_app
from app.services.chain_cache import ChainCacheEntry

# A detached stand-in for the authenticated user. Route handlers only read
# ``.id``/``.is_admin``; using a namespace avoids ORM/session entanglement.
FAKE_USER = SimpleNamespace(id="test-user", email="admin@test.local", is_admin=True)


# ---------------------------------------------------------------------------
# Cache-directory isolation — the mirror of ``tests/conftest.py``
# ---------------------------------------------------------------------------
# The engine suite was found deleting the developer's real
# ``~/.sleeper-dynasty/cache/`` (see that file for the full trace). This suite
# has the same default one layer up: ``app/config.py`` defaults ``cache_dir`` to
# the same real path, and only five test files pinned it to a ``tmp_path``. The
# remaining ~775 tests inherited the real directory and are read-mostly today,
# which is luck rather than design.
#
# Three layers, because each covers a hole the others cannot see:
#   1. ``TRADE_GRADER_CACHE_DIR`` → sandbox, so ``get_settings().cache_dir`` and
#      everything resolved through ``Depends(get_cache_dir)`` lands in tmp_path.
#      ``get_settings()`` is deliberately NOT memoized, so this takes effect per
#      call; adding an ``lru_cache`` there would silently defeat this layer.
#   2. ``DEFAULT_CACHE_DIR`` → sandbox, for engine code reached from API tests.
#   3. A tripwire on ``FileCache.__init__``, which is the only layer that can
#      catch a call site passing an explicit-but-wrong directory. That is what
#      ``grader_io.py`` used to do with its re-imported ``DEFAULT_CACHE_DIR``.
#
# The two suites are separately-rooted packages both named ``tests``, so there
# is nowhere to share a module from without a sys.path hack; they are kept
# deliberately parallel instead.

#: Recomputed from ``Path.home()`` rather than imported, so a broken patch of
#: ``DEFAULT_CACHE_DIR`` cannot make the comparison vacuously true.
REAL_CACHE_ROOT = Path.home() / ".sleeper-dynasty"


def under_real_cache_root(candidate: Path) -> bool:
    """True when ``candidate`` is the real root or lives inside it."""
    real = os.path.realpath(REAL_CACHE_ROOT)
    other = os.path.realpath(candidate)
    return other == real or other.startswith(real + os.sep)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_cache_dir: opt this test out of the cache-directory sandbox "
        "(it genuinely needs the developer's ~/.sleeper-dynasty data).",
    )


@pytest.fixture(autouse=True)
def isolate_cache_dir(request, tmp_path, monkeypatch):
    """Point every cache this test opens at a sandbox, and trip on the real one."""
    if request.node.get_closest_marker("real_cache_dir"):
        yield
        return

    sandbox = tmp_path / "sleeper-dynasty-cache"
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(sandbox))
    monkeypatch.setattr(cache_mod, "DEFAULT_CACHE_DIR", sandbox)

    real_init = FileCache.__init__

    def guarded_init(self, cache_dir: Path | None = None) -> None:
        resolved = (
            Path(cache_dir) if cache_dir is not None else cache_mod.DEFAULT_CACHE_DIR
        )
        if under_real_cache_root(resolved):
            raise AssertionError(
                f"Test opened a FileCache on the real cache directory ({resolved}). "
                f"Tests must never read or write {REAL_CACHE_ROOT} — running a "
                f"suite against it has already destroyed a warm cache once, "
                f"silently. Pass an explicit tmp_path, or mark the test "
                f"@pytest.mark.real_cache_dir if it truly needs real data."
            )
        real_init(self, resolved)

    monkeypatch.setattr(FileCache, "__init__", guarded_init)
    yield


@pytest.fixture()
def app():
    return fastapi_app


@pytest.fixture()
def client(app) -> TestClient:
    """Authenticated + authorized client. The auth guards are exercised
    directly in test_auth_gating.py; every other route test predates auth and
    should behave as if signed in, so we override the guards by default."""
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[require_league_member] = lambda: FAKE_USER
    app.dependency_overrides[require_admin] = lambda: FAKE_USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def maker(tmp_path):
    """Async sqlite session-maker with every table created, no seed data.
    Shared by the side-bets model/repo tests (test_side_bets_model.py,
    test_side_bets_repo.py)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bets.db'}")

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


@pytest.fixture
def trade_detail_fixture():
    """Base kwargs for ``build_trade_detail()``: a two-sided t1 trade on a
    minimal ChainCacheEntry. Shared by test_trade_view_production.py and
    test_trade_view_injury.py, which each extend the returned entry with
    their own extra fields (production series / injury payload)."""
    rt = {
        "trade": {
            "transaction_id": "t1",
            "traded_at": "2024-11-01T00:00:00",
            "week": 5,
            "season": 2024,
            "league_id": "L",
        },
        "sides": {
            "u1": {
                "user_id": "u1",
                "received": [],
                "given": [],
            },
            "u2": {
                "user_id": "u2",
                "received": [],
                "given": [],
            },
        },
    }
    entry = ChainCacheEntry(
        league_id="L",
        chain=[],
        resolved_trades=[rt],
        grades={
            "t1": {
                "snapshot_value_swing": {"u1": 0.0, "u2": 0.0},
                "production_total": {"u1": 10.0, "u2": 0.0},
                "breakdown": {"u1": [], "u2": []},
            }
        },
        owners={
            "u1": {"owner_name": "Owner One", "team_name": None, "avatar_url": None},
            "u2": {"owner_name": "Owner Two", "team_name": None, "avatar_url": None},
        },
        playoff_weeks_by_league={"L": 15},
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        league_name_by_id={"L": "Test League"},
        league_season_by_id={"L": 2024},
        cached_at="2024-11-01T00:00:00Z",
        warnings=[],
    )
    return {"entry": entry, "trade_id": "t1"}
