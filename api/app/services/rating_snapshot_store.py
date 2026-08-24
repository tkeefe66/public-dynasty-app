"""Per-NFL-week GM Rating snapshots, for the leaderboard's ▲▼ trend.

One JSON file per league (ratings_<league_id>.json) mapping a key to
``{user_id: rating}``. Written during refresh from the all-time board; read
by the leaderboard service to diff the current ranking against the most
recent earlier week. History is capped at the last 20 weeks.

Mirrors ``ktc_snapshot_store`` in structure (cache_dir, per-key JSON, read/write).

Stored keys are ``f"{model}:{week_key}"``, not the bare NFL week key. A
Franchise Rating number only means something relative to the weight tree
("model") that produced it -- a v1 ``results_led`` 1500 and a v2 ``v2_dynasty``
1500 are not the same quantity, even though the offseason week key barely
moves between them. Without the model in the key, the first snapshot written
after a rating-model change would sit "before" the old model's snapshot in
week order and the trend arrow would diff across models, producing a large,
entirely fictional move -- one that a cache restore (which retars the whole
volume, snapshots included) would keep reintroducing. `write` and
`latest_before` both take the caller's current model and `latest_before`
only ever matches keys stamped with that same model; a predecessor stamped
under a different model is invisible to it, same as if it didn't exist. Old
snapshots written before this change (bare, unprefixed week keys) are never
matched by any model and simply age out via the 20-week cap -- nothing reads
or migrates them.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)

_MAX_WEEKS = 20


class RatingSnapshotStore:
    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, league_id: str) -> Path:
        # League IDs are numeric strings; safe filename.
        return self.dir / f"ratings_{league_id}.json"

    def read(self, league_id: str) -> dict[str, dict[str, int]]:
        """{"model:week_key": {uid: rating}} for the league (raw, every model
        mixed together as stored on disk; {} if absent/unreadable). Callers
        wanting a specific model's history should go through ``latest_before``
        rather than filtering this themselves."""
        path = self._path(league_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as e:
            log.warning("rating snapshot unreadable (%s); ignoring", e)
            return {}

    def write(
        self, league_id: str, week_key: str, ratings: dict[str, int], *, model: str
    ) -> None:
        """Set (overwrite) the snapshot for ``week_key`` under ``model``,
        trimming to the last ``_MAX_WEEKS`` keys (lexicographic on the stored
        ``model:YYYY-WW`` key -- see module docstring for why the model is
        part of the key rather than the week alone)."""
        data = self.read(league_id)
        data[f"{model}:{week_key}"] = dict(ratings)
        if len(data) > _MAX_WEEKS:
            keep = sorted(data)[-_MAX_WEEKS:]
            data = {k: data[k] for k in keep}
        write_json_atomic(self._path(league_id), data)

    def latest_before(
        self, league_id: str, week_key: str, *, model: str
    ) -> dict[str, int]:
        """Ratings from the most recent ``model`` snapshot strictly before
        ``week_key`` ({} if none). Keys stamped with a different model are
        never considered, even if they'd otherwise sort as "earlier" --
        a predecessor under a different weight tree isn't a real trend
        baseline, it's noise (see module docstring)."""
        prefix = f"{model}:"
        data = self.read(league_id)
        earlier = [
            k[len(prefix):] for k in data
            if k.startswith(prefix) and k[len(prefix):] < week_key
        ]
        if not earlier:
            return {}
        return data[f"{prefix}{max(earlier)}"]
