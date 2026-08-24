from __future__ import annotations

import json
from pathlib import Path

from sleeper_dynasty.util.atomic import write_json_atomic


class NameOverrideStore:
    """Per-league display name overrides: {user_id -> display_name}.

    Persists indefinitely in the same cache dir as ChainCache and ProfileStore.
    File: owner_name_overrides_{league_id}.json
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, league_id: str) -> Path:
        return self.cache_dir / f"owner_name_overrides_{league_id}.json"

    def read(self, league_id: str) -> dict[str, str]:
        path = self._path(league_id)
        if not path.exists():
            return {}
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def write(self, league_id: str, overrides: dict[str, str]) -> None:
        write_json_atomic(self._path(league_id), overrides)
