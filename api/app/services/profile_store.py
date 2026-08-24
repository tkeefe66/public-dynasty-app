from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sleeper_dynasty.util.atomic import write_json_atomic

Profile = dict[str, Any]
Profiles = dict[str, Profile]


class ProfileStore:
    """Per-league owner profiles (the league "voice" data): win/loss names,
    archetype, rivals, roast — keyed by Sleeper ``user_id``.

    This is *user data*, not a cache: it persists indefinitely (no TTL) in the
    same cache dir as :class:`ChainCache`, in ``profiles_{league_id}.json``.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, league_id: str) -> Path:
        # League IDs are numeric strings; safe filename.
        return self.cache_dir / f"profiles_{league_id}.json"

    def read(self, league_id: str) -> Profiles:
        path = self._path(league_id)
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def _write(self, league_id: str, profiles: Profiles) -> None:
        write_json_atomic(self._path(league_id), profiles)

    def upsert(self, league_id: str, user_id: str, profile: Profile) -> Profiles:
        """Set one owner's profile, persist, and return the full league map."""
        profiles = self.read(league_id)
        profiles[user_id] = profile
        self._write(league_id, profiles)
        return profiles
