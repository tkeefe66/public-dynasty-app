"""Crash-safe JSON writes for anything on the cache volume.

A plain ``open(path, "w")`` truncates before it writes, so a reader in that
window — the backup job's tar, or the API after a crash — sees a partial file.
Writing to a temp file in the *same directory* and ``os.replace``-ing it makes
the swap atomic on POSIX: readers see the old file or the new one, never half.
Same directory matters — ``os.replace`` across filesystems is not atomic.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path | str, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            # allow_nan=False: json.dump defaults to True, which happily
            # writes literal `NaN`/`Infinity`/`-Infinity` -- non-RFC JSON
            # that silently corrupts a cache file (C1, 2026-08-17: a
            # non-finite `draft_needs` margin was reaching exactly this
            # call and persisting across refreshes). The primary fix
            # belongs upstream, at the value's source -- this is a
            # fail-loud backstop, not the fix: a future non-finite value
            # from ANY caller now raises here (TypeError already `except`ed
            # by every caller and by tests in this file) instead of
            # quietly writing a file no strict JSON reader can parse back.
            json.dump(data, f, allow_nan=False)
        # mkstemp creates at 0600 and os.replace carries that mode onto the
        # target; without this every store on the volume silently narrows from
        # 0644. No fsync: os.replace alone gives the atomicity this is for, and
        # fsync only buys power-loss durability on an explicitly rebuildable
        # cache — at the cost of a disk flush per call on the refresh path.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
