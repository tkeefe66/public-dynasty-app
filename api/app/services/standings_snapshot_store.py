"""Per-week regular-season standings snapshots for a whole league chain.

One JSON file per entry-league (standings_<league_id>.json) mapping a season-scoped
week key ("{season}-{week:02d}") to the full standings table (list of owner rows).
Written during refresh from the reconstructed history; read by the trade view to
attach each side's as-of-trade standing.

Mirrors ``rating_snapshot_store`` in structure, but is NOT capped — as-of-trade
lookups can reach years back, so full chain history is retained. Completed weeks are
deterministically rewritten on each refresh (reconstruction is pure, so the bytes are
identical); the store is not write-once.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)


class StandingsSnapshotStore:
    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, league_id: str) -> Path:
        return self.dir / f"standings_{league_id}.json"

    def read(self, league_id: str) -> dict[str, list[dict]]:
        """{week_key: [row, ...]} for the league ({} if absent/unreadable)."""
        path = self._path(league_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as e:
            log.warning("standings snapshot unreadable (%s); ignoring", e)
            return {}

    def write(self, league_id: str, week_key: str, rows: list[dict]) -> None:
        """Set (overwrite) the snapshot for ``week_key``. Uncapped."""
        data = self.read(league_id)
        data[week_key] = list(rows)
        write_json_atomic(self._path(league_id), data)

    def write_many(self, league_id: str, history: dict[str, list[dict]]) -> None:
        """Merge a full {week_key: rows} history in one write."""
        data = self.read(league_id)
        data.update(history)
        write_json_atomic(self._path(league_id), data)

    def as_of(self, league_id: str, season: int, week: int) -> list[dict]:
        """Standings table for the latest snapshot at or before ``season``-``week``
        ([] if none exists at or before it)."""
        key = f"{int(season):04d}-{int(week):02d}"
        data = self.read(league_id)
        candidates = [k for k in data if k <= key]
        if not candidates:
            return []
        return data[max(candidates)]
