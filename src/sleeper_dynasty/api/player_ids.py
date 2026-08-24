"""DynastyProcess ``db_playerids.csv`` -> Sleeper player ids.

Sleeper's ``player_id`` is this app's canonical key. Every external source
translates at its own boundary and nothing inward ever sees a foreign id.

This module owns the fetch and the parse; ``yahoo_ids`` and the rookie-ECR
baseline are two accessors over the same 2.6MB file, so it is pulled once.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Same source engine/injury_data.py uses. Kept as its own constant so a change
# to one consumer's URL cannot silently repoint the other.
IDS_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_playerids.csv"

_CACHE_TTL = 7 * 24 * 3600  # ids change only when players enter the league
_FP_CACHE_KEY = "fantasypros_to_sleeper_ids.json"

# R writes its null as the literal string "NA" when this CSV is generated, and
# pandas hands it back as text rather than a missing value. Observed live: one
# row maps yahoo_id "NA" -> a real sleeper_id, which would then swallow every
# unmapped player into one wrong person.
NULL_TOKENS = {"", "na", "n/a", "nan", "none", "null"}


def clean_id(raw) -> str:
    """Normalize a CSV id cell to a bare string, or "" if it is not an id.

    Two upstream quirks, both observed in the live file:
    * numeric columns round-trip through pandas, so an id can arrive as
      "31002.0" — left alone that never matches a player key;
    * nulls arrive as the literal text "NA" rather than an empty cell.
    """
    s = str(raw or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return "" if s.lower() in NULL_TOKENS else s


def build_id_map(rows: list[dict], *, source_col: str) -> dict[str, str]:
    """Pure: CSV rows -> {source id: sleeper_id}.

    Rows missing either id are skipped — a partial mapping is worse than no
    mapping, because it silently drops players. First row wins on a duplicate
    so two runs over the same CSV can never disagree.
    """
    out: dict[str, str] = {}
    for row in rows:
        src = clean_id(row.get(source_col))
        sid = clean_id(row.get("sleeper_id"))
        if not src or not sid:
            continue
        out.setdefault(src, sid)
    return out


def build_fantasypros_to_sleeper(rows: list[dict]) -> dict[str, str]:
    """Pure: CSV rows -> {fantasypros_id: sleeper_id}."""
    return build_id_map(rows, source_col="fantasypros_id")


async def fetch_fantasypros_to_sleeper(cache=None) -> dict[str, str]:
    """Fetch (or read cached) the fantasypros_id -> sleeper_id map.

    Returns {} on any failure. Callers decide what an empty map means; raising
    here would take down an otherwise healthy refresh at the fetch layer.
    """
    if cache is not None:
        cached = cache.read(_FP_CACHE_KEY, max_age_seconds=_CACHE_TTL)
        if cached:
            return cached
    try:
        from sleeper_dynasty.engine.injury_data import _fetch_csv_rows
        rows = _fetch_csv_rows(IDS_URL)
    except Exception:
        log.warning("player id map fetch failed", exc_info=True)
        return {}
    mapping = build_fantasypros_to_sleeper(rows)
    log.info(
        "player id map: %d fantasypros ids resolved to sleeper ids", len(mapping))
    if cache is not None and mapping:
        cache.write(_FP_CACHE_KEY, mapping)
    return mapping
