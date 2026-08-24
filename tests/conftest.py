"""Engine-suite fixtures.

The autouse guard below is the point of this file.

Why it exists: ``tests/test_cli.py::test_run_recap_builds_and_delivers`` pinned
``tmp_path`` for its output but not for the cache directory, so ``pytest
tests/`` reached ``cli.py``'s bare ``FileCache()``, called ``invalidate_all()``
on the developer's REAL ``~/.sleeper-dynasty/cache/`` and unlinked every
``chain_*.json`` blob in it, then wrote its own two-player fixture back over
``players_nfl.json``. The suite stayed green the whole time it was doing that —
which is the whole problem. A later measurement read the substitute blob, parsed
it fine, and reported a wrong conclusion.

The fix is deliberately a general guard rather than a patch to the one test that
got caught: this class of defect is invisible on a green suite, so protection
that depends on someone remembering to apply it to the *next* test does not hold.
Three CLI entry points construct a bare ``FileCache()`` (``_run_analysis``,
``_run_trades``, ``_run_recap``), and ``test_integration.py`` is immune only by
the accident of patching ``FileCache`` to assert on the mock.

Two layers, because one is not enough:

1. ``DEFAULT_CACHE_DIR`` is redirected to a per-test sandbox, so anything
   constructing a bare ``FileCache()`` lands under ``tmp_path``.
2. ``FileCache.__init__`` is wrapped with a tripwire that raises the moment a
   cache is pointed at the real directory. Layer 1 cannot catch a call site that
   passes an explicit argument which happens to be the real path — exactly the
   shape of ``grader_io.py``'s old fallback — so layer 2 is what makes the guard
   cover future escapes rather than only today's known ones.

Opt out of a single test with ``@pytest.mark.real_cache_dir``. An opt-out is
visible in a diff; the current implicit opt-in is not.

The mirror of this guard lives in ``api/tests/conftest.py``. The two suites are
separately-rooted packages that are both named ``tests``, so there is nowhere to
share a module from without a sys.path hack; they are kept deliberately
parallel instead.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import sleeper_dynasty.cache as cache_mod
from sleeper_dynasty.cache import FileCache

#: The real, developer-owned root. Recomputed from ``Path.home()`` rather than
#: imported from the engine, so a broken patch of ``DEFAULT_CACHE_DIR`` cannot
#: make this comparison vacuously true.
REAL_CACHE_ROOT = Path.home() / ".sleeper-dynasty"


def under_real_cache_root(candidate: Path) -> bool:
    """True when ``candidate`` is the real root or lives inside it.

    Compared through ``realpath`` on both sides: macOS home directories and
    pytest's ``tmp_path`` both routinely involve symlinks, and a plain string
    compare would let ``/private/var/...`` and ``/var/...`` disagree.
    """
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
    monkeypatch.setattr(cache_mod, "DEFAULT_CACHE_DIR", sandbox)

    real_init = FileCache.__init__

    def guarded_init(self, cache_dir: Path | None = None) -> None:
        resolved = (
            Path(cache_dir) if cache_dir is not None else cache_mod.DEFAULT_CACHE_DIR
        )
        if under_real_cache_root(resolved):
            raise AssertionError(
                f"Test opened a FileCache on the real cache directory ({resolved}). "
                f"Tests must never read or write {REAL_CACHE_ROOT} — running the "
                f"suite against it has already destroyed a warm cache once, "
                f"silently. Pass an explicit tmp_path, or mark the test "
                f"@pytest.mark.real_cache_dir if it truly needs real data."
            )
        real_init(self, resolved)

    monkeypatch.setattr(FileCache, "__init__", guarded_init)
    yield
