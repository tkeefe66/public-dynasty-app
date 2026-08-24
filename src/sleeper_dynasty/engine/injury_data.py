"""Fetch + cache nflverse injury signals, exposed as a (sleeper_id, season, week) map.

High-confidence misses come from rosters_weekly IR/reserve status (sleeper_id native);
soft misses from snap_counts all-zero weeks (pfr_id, mapped via the ff_playerids
crosswalk). High always wins over soft for the same key.
"""

from __future__ import annotations

import csv
import io
import logging

import httpx

from sleeper_dynasty.api.nflverse import (
    parse_roster_status_rows, parse_snap_zero_rows, parse_pfr_to_sleeper,
)

log = logging.getLogger(__name__)

_ROSTER_URL = "https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_{season}.csv"
_SNAP_URL = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv"
_IDS_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_playerids.csv"
_CACHE_TTL_HISTORICAL = 365 * 24 * 3600
_CACHE_TTL_CURRENT = 12 * 3600


def combine_injury_map(roster_high, snap_soft_by_pfr, pfr_to_sleeper):
    """Merge high (sleeper-keyed) + soft (pfr-keyed, remapped) into one sleeper-keyed map.
    High confidence is never overwritten by soft."""
    out = dict(roster_high)
    for (pfr, season, week), info in snap_soft_by_pfr.items():
        sid = pfr_to_sleeper.get(pfr)
        if not sid:
            continue
        key = (sid, season, week)
        if key in out and out[key]["confidence"] == "high":
            continue
        out[key] = info
    return out


def _fetch_csv_rows(url: str) -> list[dict]:
    """GET a CSV and return rows as list[dict]. Raises on HTTP error."""
    resp = httpx.get(url, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def build_injury_map(
    seasons: list[int],
    *,
    cache=None,
    current_season: int | None = None,
    fetch_rows=_fetch_csv_rows,
) -> dict[tuple[str, int, int], dict]:
    """Build the unified injury map for the given seasons. Caches the normalized
    per-season JSON via FileCache (long TTL for past seasons). ``fetch_rows`` is
    injectable for tests. Any per-season failure logs and is skipped (degrade, never raise)."""
    ids_rows = []
    try:
        ids_rows = fetch_rows(_IDS_URL)
    except Exception:
        log.warning("nflverse ff_playerids fetch failed; soft snap signal disabled", exc_info=True)
    pfr_to_sleeper = parse_pfr_to_sleeper(ids_rows)

    merged: dict[tuple[str, int, int], dict] = {}
    for season in seasons:
        ck = f"nflverse_injury_{season}.json"
        ttl = _CACHE_TTL_CURRENT if season == current_season else _CACHE_TTL_HISTORICAL
        cached = cache.read(ck, max_age_seconds=ttl) if cache else None
        if cached is not None:
            for k, v in cached.items():
                sid, s, w = k.split("|")
                merged[(sid, int(s), int(w))] = v
            continue
        try:
            roster_high = parse_roster_status_rows(fetch_rows(_ROSTER_URL.format(season=season)))
        except Exception:
            log.warning("nflverse roster fetch failed for season %s; skipping", season, exc_info=True)
            continue
        snap_soft = {}
        try:
            snap_soft = parse_snap_zero_rows(fetch_rows(_SNAP_URL.format(season=season)))
        except Exception:
            log.warning("nflverse snap_counts fetch failed for season %s; soft signal off", season)
        season_map = combine_injury_map(roster_high, snap_soft, pfr_to_sleeper)
        if cache:
            cache.write(ck, {f"{sid}|{s}|{w}": v for (sid, s, w), v in season_map.items()})
        merged.update(season_map)
    return merged
