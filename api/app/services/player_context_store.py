"""Durable public-source observations, separate from rebuildable league caches."""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)


class PlayerContextStore:
    def __init__(self, cache_dir: Path):
        self.root = Path(cache_dir) / "player_context"

    def _path(self, key):
        return self.root / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def read(self, key) -> dict | None:
        try:
            data = json.loads(self._path(key).read_text())
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            log.warning("Player context observation unreadable; source unavailable", exc_info=True)
            return None

    def write(self, key, data):
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=self.root, prefix=".context-", delete=False) as handle:
            temporary = Path(handle.name)
            try:
                json.dump(data, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
                os.replace(temporary, self._path(key))
            finally:
                temporary.unlink(missing_ok=True)

    @contextmanager
    def claim(self, key=None):
        self.root.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(key.encode()).hexdigest() if key else "collection"
        with (self.root / f".{name}.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
