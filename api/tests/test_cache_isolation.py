"""The API-side cache guard, guarding itself.

Same purpose as ``tests/test_cache_isolation.py`` in the engine suite, plus the
one call site a bare-``FileCache()`` guard structurally cannot see:
``grader_io.pull_supporting_data`` with ``league_cache=None``. That site always
passes an argument — it just used to pass a re-imported ``DEFAULT_CACHE_DIR``,
a binding copied at import time that neither the engine-side patch nor
``TRADE_GRADER_CACHE_DIR`` could reach.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sleeper_dynasty.cache as cache_mod
from sleeper_dynasty.cache import FileCache

from app.config import get_settings
from app.services.grader_io import pull_supporting_data

from .conftest import REAL_CACHE_ROOT, under_real_cache_root

REAL_CACHE_DIR = Path.home() / ".sleeper-dynasty" / "cache"


def test_settings_cache_dir_is_redirected():
    """Layer 1: ``TRADE_GRADER_CACHE_DIR`` reaches ``get_settings()``.

    ``get_settings()`` is not memoized, which is what makes a per-test env var
    work. If an ``lru_cache`` is ever added there, this goes red.
    """
    assert not under_real_cache_root(get_settings().cache_dir)


def test_default_cache_dir_constant_is_redirected():
    """Layer 2: engine code reached from an API test lands in the sandbox."""
    assert not under_real_cache_root(cache_mod.DEFAULT_CACHE_DIR)
    assert not under_real_cache_root(FileCache().cache_dir)


@pytest.mark.parametrize(
    "target",
    [REAL_CACHE_DIR, REAL_CACHE_ROOT, REAL_CACHE_DIR / "nested"],
    ids=["cache-dir", "root", "below-cache-dir"],
)
def test_tripwire_bites_on_an_explicit_real_path(target):
    """Layer 3: the only layer that catches an explicit-but-wrong argument."""
    with pytest.raises(AssertionError, match="real cache directory"):
        FileCache(target)


def test_explicit_tmp_path_still_works(tmp_path):
    """The guard must not break tests that already isolate themselves."""
    cache = FileCache(cache_dir=tmp_path)
    cache.write("k.json", {"a": 1})
    assert cache.read("k.json") == {"a": 1}


@pytest.mark.asyncio
async def test_pull_supporting_data_without_league_cache_stays_off_home(monkeypatch):
    """``league_cache=None`` must resolve to the configured dir, not ``Path.home()``.

    Production always passes a real ``league_cache`` (``grader.py``), so this
    fallback is reached only by callers that omit it — which every test doing so
    did, silently, against the developer's disk. The tripwire in the conftest
    turns that into a failure; this test is what exercises the path so the
    tripwire has something to bite on.
    """
    import app.services.grader_io as mod

    async def _ktc():
        return {}

    async def _fc(*, dynasty=True):
        return {}

    monkeypatch.setattr(mod, "fetch_ktc_values", _ktc)
    monkeypatch.setattr(mod, "fetch_fantasycalc_values", _fc)

    seen: list[Path] = []
    real_init = FileCache.__init__

    def recording_init(self, cache_dir=None):
        real_init(self, cache_dir)
        seen.append(self.cache_dir)

    monkeypatch.setattr(FileCache, "__init__", recording_init)

    class _StubClientNoLeagues:
        async def get_players(self):
            return {}

    await pull_supporting_data(
        _StubClientNoLeagues(), [], players={}, league_cache=None)

    assert seen, "expected pull_supporting_data to open a FileCache"
    for path in seen:
        assert not under_real_cache_root(path), f"{path} is under {REAL_CACHE_ROOT}"
    assert seen[-1] == get_settings().cache_dir


@pytest.mark.asyncio
async def test_pull_supporting_data_prefers_the_league_cache_dir(tmp_path, monkeypatch):
    """The fallback must stay a fallback — an explicit league_cache still wins."""
    import app.services.grader_io as mod

    async def _ktc():
        return {}

    async def _fc(*, dynasty=True):
        return {}

    monkeypatch.setattr(mod, "fetch_ktc_values", _ktc)
    monkeypatch.setattr(mod, "fetch_fantasycalc_values", _fc)

    league_dir = tmp_path / "league"
    league_dir.mkdir()

    seen: list[Path] = []
    real_init = FileCache.__init__

    def recording_init(self, cache_dir=None):
        real_init(self, cache_dir)
        seen.append(self.cache_dir)

    monkeypatch.setattr(FileCache, "__init__", recording_init)

    class _StubClientNoLeagues:
        async def get_players(self):
            return {}

    class _LeagueCache:
        cache_dir = league_dir

    await pull_supporting_data(
        _StubClientNoLeagues(), [], players={}, league_cache=_LeagueCache())

    assert seen[-1] == league_dir
