"""Yahoo player id -> Sleeper player id.

Sleeper's player_id is this app's canonical key: KTC, FantasyCalc, nflverse,
the chain cache and lineage are all keyed on it. Rather than teach any of them
a second identity scheme, the Yahoo adapter translates at its own boundary and
nothing inward ever sees a Yahoo id.

The map comes from DynastyProcess's ``db_playerids.csv``, which this app
already downloads for injury signals (``engine/injury_data.py``) and which
carries ``yahoo_id`` and ``sleeper_id`` columns side by side.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from sleeper_dynasty.api.player_ids import IDS_URL, build_id_map  # noqa: F401

_CACHE_KEY = "yahoo_to_sleeper_ids.json"
_CACHE_TTL = 7 * 24 * 3600  # ids change only when players enter the league


def build_yahoo_to_sleeper(rows: list[dict]) -> dict[str, str]:
    """Pure: CSV rows -> {yahoo_id: sleeper_id}. See player_ids.build_id_map."""
    return build_id_map(rows, source_col="yahoo_id")


async def fetch_yahoo_to_sleeper(cache=None) -> dict[str, str]:
    """Fetch (or read cached) the yahoo_id -> sleeper_id map.

    Returns {} on any failure. An empty map is not silently acceptable to
    callers — the adapter treats it as fatal — but raising here would take
    down an otherwise healthy refresh at the fetch layer instead of at the
    layer that knows what a missing map means.
    """
    if cache is not None:
        cached = cache.read(_CACHE_KEY, max_age_seconds=_CACHE_TTL)
        if cached:
            return cached
    try:
        from sleeper_dynasty.engine.injury_data import _fetch_csv_rows
        rows = _fetch_csv_rows(IDS_URL)
    except Exception:
        log.warning("player id map fetch failed", exc_info=True)
        return {}
    mapping = build_yahoo_to_sleeper(rows)
    log.info("player id map: %d yahoo ids resolved to sleeper ids", len(mapping))
    if cache is not None and mapping:
        cache.write(_CACHE_KEY, mapping)
    return mapping
