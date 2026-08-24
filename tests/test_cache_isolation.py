"""The guard guarding itself.

Without these, ``tests/conftest.py``'s autouse fixture can be quietly broken by
a refactor and the suite stays green — which is the exact failure mode the guard
exists to close. Each test here fails loudly on a different way of breaking it:

* the sandbox redirect silently stops applying,
* the tripwire silently stops biting,
* or the guard over-reaches and breaks tests that pass an explicit directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sleeper_dynasty.cache as cache_mod
from sleeper_dynasty.cache import FileCache

from .conftest import REAL_CACHE_ROOT, under_real_cache_root

REAL_CACHE_DIR = Path.home() / ".sleeper-dynasty" / "cache"


def test_default_cache_dir_constant_is_redirected():
    """Layer 1: the module constant no longer points at the developer's disk."""
    assert cache_mod.DEFAULT_CACHE_DIR != REAL_CACHE_DIR
    assert not under_real_cache_root(cache_mod.DEFAULT_CACHE_DIR)


def test_bare_filecache_lands_in_the_sandbox():
    """A bare ``FileCache()`` — the shape at all three CLI call sites."""
    cache = FileCache()
    assert cache.cache_dir != REAL_CACHE_DIR
    assert not under_real_cache_root(cache.cache_dir)


def test_default_is_resolved_at_call_time_not_definition_time():
    """The production change this guard depends on.

    If ``__init__`` ever goes back to ``cache_dir: Path = DEFAULT_CACHE_DIR``,
    the constant is bound into ``__defaults__`` at import and the conftest's
    monkeypatch becomes a no-op that nothing else would notice.
    """
    assert FileCache.__init__.__defaults__ in (None, (None,))


@pytest.mark.parametrize(
    "target",
    [REAL_CACHE_DIR, REAL_CACHE_ROOT, REAL_CACHE_DIR / "nested"],
    ids=["cache-dir", "root", "below-cache-dir"],
)
def test_tripwire_bites_on_an_explicit_real_path(target):
    """Layer 2: an escape that passes the real path explicitly still fails.

    This is the ``grader_io.py`` shape — a call site that always passes an
    argument, just the wrong one — which layer 1 cannot see. Proving the
    tripwire raises is what makes the guard self-verifying rather than
    aspirational.
    """
    with pytest.raises(AssertionError, match="real cache directory"):
        FileCache(target)


def test_explicit_tmp_path_still_works(tmp_path):
    """The guard must not break tests that already isolate themselves."""
    cache = FileCache(cache_dir=tmp_path)
    cache.write("k.json", {"a": 1})
    assert cache.read("k.json") == {"a": 1}


def test_invalidate_all_cannot_reach_the_real_directory(tmp_path):
    """The specific operation that ate the warm cache, run against a sandbox."""
    cache = FileCache()
    cache.write("chain_1.json", {"x": 1})
    cache.invalidate_all()
    assert cache.read("chain_1.json") is None
    assert not under_real_cache_root(cache.cache_dir)
