"""Shared plain-function test helpers (not fixtures) for api/tests/*.py.

Import as ``from tests.helpers import ...`` — ``api/tests`` is a package
(``__init__.py`` present) and ``api/`` is on sys.path per
``api/pyproject.toml``'s ``[tool.pytest.ini_options] pythonpath``.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from app.services.chain_cache import ChainCacheEntry


def minimal_chain_cache_entry(**over) -> ChainCacheEntry:
    """A ``ChainCacheEntry`` with every required field defaulted to empty/"now",
    overridable via kwargs. Used by chain-cache round-trip tests that only
    care about one or two specific fields."""
    base = dict(
        league_id="L", chain=[], resolved_trades=[], grades={}, owners={},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="now",
    )
    base.update(over)
    return ChainCacheEntry(**base)


def maker_scope(maker):
    """Adapt a test session-maker into the ``session_scope()`` context-manager
    shape that non-request callers (scheduler, backup job) use."""

    @asynccontextmanager
    async def _scope():
        async with maker() as session:
            yield session
            await session.commit()

    return _scope
