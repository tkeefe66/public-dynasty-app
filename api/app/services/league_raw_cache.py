"""Per-league raw-fetch cache for sealed (status == "complete") seasons.

Stores two independently-readable bundles per league in one JSON file:
  - trade_bundle: output of the engine's _fetch_league_season_data (minus League)
  - matchup_bundle: the per-league slice of pull_supporting_data

Sealed-season raw data is immutable, so there is no TTL; a SCHEMA_VERSION
mismatch is treated as a miss so a format change can't be misread. ``force``
bypasses reads (writes still happen) for operator-triggered re-pulls.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2


class LeagueRawCache:
    def __init__(self, cache_dir: Path, force: bool = False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.force = force

    def _path(self, league_id: str) -> Path:
        return self.cache_dir / f"raw_{league_id}.json"

    def _load_file(self, league_id: str) -> dict[str, Any] | None:
        path = self._path(league_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError) as e:
            log.warning("raw cache unreadable for %s (%s); ignoring", league_id, e)
            return None
        if raw.get("schema_version") != SCHEMA_VERSION:
            return None
        return raw

    def _write_bundle(self, league_id: str, key: str, payload: dict[str, Any]) -> None:
        existing = self._load_file(league_id) or {
            "schema_version": SCHEMA_VERSION, "league_id": league_id,
            "trade_bundle": None, "matchup_bundle": None,
        }
        existing["schema_version"] = SCHEMA_VERSION
        existing["league_id"] = league_id
        existing[key] = payload
        write_json_atomic(self._path(league_id), existing)

    # -- trade bundle ------------------------------------------------------

    def read_trade_bundle(self, league_id: str) -> dict[str, Any] | None:
        if self.force:
            return None
        raw = self._load_file(league_id)
        if raw is None or raw.get("trade_bundle") is None:
            return None
        b = dict(raw["trade_bundle"])
        if "raw_roster_txs" not in b:
            # A bundle written before get_roster_transactions existed. Read
            # as a miss rather than silently handing back zero roster
            # transactions — the reconstruction downstream would be built
            # on nothing, with no error to show for it.
            return None
        b["roster_to_user"] = {int(k): v for k, v in b["roster_to_user"].items()}
        return b

    def write_trade_bundle(self, league_id: str, bundle: dict[str, Any]) -> None:
        # roster_to_user int keys JSON-stringify on dump; read coerces back.
        self._write_bundle(league_id, "trade_bundle", bundle)

    # -- matchup bundle ----------------------------------------------------

    def read_matchup_bundle(self, league_id: str) -> dict[str, Any] | None:
        if self.force:
            return None
        raw = self._load_file(league_id)
        if raw is None or raw.get("matchup_bundle") is None:
            return None
        b = dict(raw["matchup_bundle"])
        b["roster_to_user"] = {int(k): v for k, v in b["roster_to_user"].items()}
        b["matchups"] = {
            (league_id, int(r["week"]), int(r["roster_id"])): r["entry"]
            for r in b["matchups"]
        }
        return b

    def write_matchup_bundle(self, league_id: str, bundle: dict[str, Any]) -> None:
        payload = dict(bundle)
        payload["matchups"] = [
            {"week": wk, "roster_id": rid, "entry": entry}
            for (_lg, wk, rid), entry in bundle["matchups"].items()
        ]
        self._write_bundle(league_id, "matchup_bundle", payload)
