"""Durable per-league owner links, written only from confirmed identities."""

import json
import re
from dataclasses import asdict
from pathlib import Path

from sleeper_dynasty.api.owner_identity import OwnerIdentity
from sleeper_dynasty.util.atomic import write_json_atomic


class OwnerIdentityStore:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)

    def _path(self, league_id):
        if not re.fullmatch(r"\d+\.l\.\d+", league_id):
            raise ValueError("Owner identity mappings require a valid Yahoo league key.")
        return self.cache_dir / f"owner_identity_{league_id}.json"

    def read(self, league_id) -> OwnerIdentity:
        path = self._path(league_id)
        if not path.exists():
            return OwnerIdentity()
        try:
            return OwnerIdentity(**json.loads(path.read_text()))
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("Cannot read owner identity mapping; restore or correct the saved links.") from exc

    def write(self, league_id, identity: OwnerIdentity):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self._path(league_id), asdict(identity))
