from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from sleeper_dynasty.util.atomic import write_json_atomic

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".sleeper-dynasty" / "cache"
ONE_DAY = 86400


class FileCache:
    def __init__(self, cache_dir: Path | None = None):
        """Resolve the default at CALL time, not at definition time.

        A ``cache_dir: Path = DEFAULT_CACHE_DIR`` default binds the constant
        into ``__defaults__`` when the module is imported, so patching
        ``sleeper_dynasty.cache.DEFAULT_CACHE_DIR`` — which is what the
        constant reads as being for — silently does nothing. That is how the
        engine test suite came to delete the developer's real cache: the
        conftest could not redirect it. Resolving here makes the constant
        genuinely patchable.
        """
        self.cache_dir = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def read(self, key: str, max_age_seconds: int = ONE_DAY) -> dict | list | None:
        path = self.cache_dir / key
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > max_age_seconds:
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            # Treat corrupt cache as missing so callers refetch from source.
            logger.warning(
                "Cache file %s is corrupt (%s); treating as missing",
                path,
                e,
            )
            return None

    def write(self, key: str, data: dict | list) -> None:
        write_json_atomic(self.cache_dir / key, data)

    def invalidate(self, key: str) -> None:
        path = self.cache_dir / key
        if path.exists():
            path.unlink()

    def invalidate_all(self) -> None:
        """Clear every cached payload.

        Restricted to ``*.json`` on purpose: this directory also holds
        ``identity.db``, and the snapshot stores keep dated history in
        subdirectories. Widening the glob would delete the identity database.
        The corollary is that a cache key without a ``.json`` suffix can never
        be reached from here — keys must carry the extension.
        """
        for path in self.cache_dir.iterdir():
            if path.is_file() and path.suffix == ".json":
                path.unlink()
