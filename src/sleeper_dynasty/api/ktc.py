"""KeepTradeCut dynasty-value scraper.

KTC publishes a 0-9999 integer "value" scale for dynasty players and
rookie draft picks, updated daily. They don't expose a public JSON API,
but the rankings page embeds the full player list as a ``playersArray``
JavaScript variable in the HTML. That's by far the most reliable thing
to scrape — far better than trying to read the DOM.

We fetch both the Superflex (format=2) and 1QB (format=1) variants and
merge them. Each player object already carries BOTH ``oneQBValues`` and
``superflexValues``, but the top-500 ordering differs between formats,
so fetching both gets us a slightly larger union of players.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.util.name_match import normalize_player_name

log = logging.getLogger(__name__)

_KTC_URL = (
    "https://keeptradecut.com/dynasty-rankings"
    "?page=0&filters=QB|WR|RB|TE|RDP&format={fmt}"
)

# Regex to pluck the embedded JS array. Non-greedy match between the
# assignment and the trailing semicolon on its own line. We use re.DOTALL
# because the array spans many lines.
_PLAYERS_ARRAY_RE = re.compile(
    r"var\s+playersArray\s*=\s*(\[.*?\])\s*;", re.DOTALL
)

# Format identifiers KTC uses in their URL.
_FORMAT_SUPERFLEX = 2
_FORMAT_ONE_QB = 1


async def fetch_ktc_values() -> dict[str, KTCValue]:
    """Fetch current KTC dynasty values for both Superflex and 1QB formats.

    Returns:
        Dict keyed by ``normalize_player_name(player.name)``. Empty on
        network or parse failure — same graceful-degradation contract as
        the FantasyPros fetcher.
    """
    log.info("Fetching KTC dynasty values")
    merged: dict[str, KTCValue] = {}

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True
    ) as client:
        for fmt in (_FORMAT_SUPERFLEX, _FORMAT_ONE_QB):
            url = _KTC_URL.format(fmt=fmt)
            try:
                resp = await client.get(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (compatible; sleeper-dynasty/0.1)"
                        ),
                    },
                )
            except httpx.HTTPError as e:
                log.warning("KTC fetch failed (format=%d): %s", fmt, e)
                continue

            if resp.status_code != 200:
                log.warning("KTC returned %d (format=%d)", resp.status_code, fmt)
                continue

            parsed = parse_ktc_html(resp.text)
            if not parsed:
                log.warning(
                    "KTC format=%d parsed 0 players — embedded array "
                    "missing or layout changed",
                    fmt,
                )
            _merge_ktc(merged, parsed)

    log.info("KTC: %d unique players parsed", len(merged))
    return merged


def parse_ktc_html(html: str) -> dict[str, KTCValue]:
    """Extract ``playersArray`` from KTC HTML and convert to KTCValue dict.

    Returns dict keyed by normalized name. Empty if the JS array isn't
    present or fails to parse.
    """
    m = _PLAYERS_ARRAY_RE.search(html)
    if not m:
        log.warning("KTC: playersArray JS variable not found")
        return {}

    try:
        raw_players: list[dict[str, Any]] = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        log.warning("KTC: failed to parse playersArray JSON: %s", e)
        return {}

    out: dict[str, KTCValue] = {}
    for p in raw_players:
        ktc = _build_ktc_value(p)
        if ktc is None:
            continue
        out[ktc.normalized_name] = ktc
    return out


def _build_ktc_value(raw: dict[str, Any]) -> KTCValue | None:
    """Convert one KTC playersArray entry into a KTCValue.

    Returns None if the entry is missing required fields. KTC's data
    schema is generally stable but we defensively skip malformed rows
    rather than crashing the whole import.
    """
    name = raw.get("playerName")
    position = raw.get("position")
    if not name or not position:
        return None

    sf = raw.get("superflexValues") or {}
    one = raw.get("oneQBValues") or {}

    def _opt_int(d: dict[str, Any], key: str) -> int | None:
        v = d.get(key)
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return KTCValue(
        name=name,
        normalized_name=normalize_player_name(name),
        position=position,
        superflex_value=_opt_int(sf, "value"),
        one_qb_value=_opt_int(one, "value"),
        superflex_position_rank=_opt_int(sf, "positionalRank"),
        one_qb_position_rank=_opt_int(one, "positionalRank"),
    )


# Maps the ordinal word in a KTC pick name ("1st", "2nd", …) to a round number.
_PICK_ORDINALS = {
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
    "5th": 5, "6th": 6, "7th": 7, "8th": 8,
}
# "2025 Early 1st", "2025 Mid 2nd", "2025 Late 3rd", or "2025 1st".
_PICK_NAME_RE = re.compile(
    r"^(?P<year>\d{4})\s+(?:(?P<tier>early|mid|late)\s+)?(?P<ord>\d(?:st|nd|rd|th))$",
    re.IGNORECASE,
)


def _parse_pick_name(name: str) -> tuple[int, int] | None:
    """Parse a KTC pick name into (season, round); None if it isn't a pick."""
    m = _PICK_NAME_RE.match(name.strip())
    if not m:
        return None
    rnd = _PICK_ORDINALS.get(m.group("ord").lower())
    if rnd is None:
        return None
    return int(m.group("year")), rnd


def _avg(vals: list[int]) -> int | None:
    present = [v for v in vals if v is not None]
    if not present:
        return None
    return round(sum(present) / len(present))


def build_pick_value_table(
    ktc_values: dict[str, KTCValue],
) -> dict[tuple[int, int], KTCValue]:
    """Group KTC draft-pick entries into a round-level value table.

    Recognizes picks by name pattern (year + ordinal), independent of the
    ``position`` string, then averages Early/Mid/Late entries within a round
    because the precise slot isn't known until end-of-season standings.

    Returns ``(season, round) -> KTCValue`` with averaged superflex/1QB values.
    """
    buckets: dict[tuple[int, int], list[KTCValue]] = {}
    for val in ktc_values.values():
        key = _parse_pick_name(val.name)
        if key is None:
            continue
        buckets.setdefault(key, []).append(val)

    table: dict[tuple[int, int], KTCValue] = {}
    for (season, rnd), entries in buckets.items():
        sf = _avg([e.superflex_value for e in entries])
        one = _avg([e.one_qb_value for e in entries])
        table[(season, rnd)] = KTCValue(
            name=f"{season} Round {rnd}",
            normalized_name=f"{season} round {rnd}",
            position="PICK",
            superflex_value=sf,
            one_qb_value=one,
        )

    # KTC only publishes pick values 1-2 seasons out. Extend 3 additional years
    # for far-future picks by reusing the latest priced value for each round —
    # the best available proxy until KTC catches up.
    if table:
        max_season = max(s for (s, r) in table)
        rounds = {r for (s, r) in table}
        for rnd in rounds:
            latest_v = table.get((max_season, rnd))
            if latest_v is None:
                continue
            for future in range(max_season + 1, max_season + 4):
                if (future, rnd) not in table:
                    table[(future, rnd)] = KTCValue(
                        name=f"{future} Round {rnd}",
                        normalized_name=f"{future} round {rnd}",
                        position="PICK",
                        superflex_value=latest_v.superflex_value,
                        one_qb_value=latest_v.one_qb_value,
                    )
    return table


def parse_pick_name_tiered(name: str) -> tuple[int, int, str] | None:
    """Parse a KTC pick name into (season, round, tier); tier is "" if untiered."""
    m = _PICK_NAME_RE.match(name.strip())
    if not m:
        return None
    rnd = _PICK_ORDINALS.get(m.group("ord").lower())
    if rnd is None:
        return None
    return int(m.group("year")), rnd, (m.group("tier") or "").lower()


def build_pick_value_table_tiered(
    ktc_values: dict[str, KTCValue],
) -> dict[tuple[int, int, str], KTCValue]:
    """Tier-aware pick table: (season, round, tier) -> KTCValue, NOT averaged.

    Parallel to build_pick_value_table, which keeps the round-average fallback.
    """
    table: dict[tuple[int, int, str], KTCValue] = {}
    for val in ktc_values.values():
        key = parse_pick_name_tiered(val.name)
        if key is not None:
            table[key] = val
    return table


def _merge_ktc(
    accumulator: dict[str, KTCValue],
    new: dict[str, KTCValue],
) -> None:
    """Merge a freshly-parsed KTC page into the accumulator.

    Both format=1 and format=2 pages carry the same ``oneQBValues`` and
    ``superflexValues`` blobs per player, so when both pages return the
    same player we can safely overwrite (the data is consistent). We
    fill in non-None fields on the existing entry when re-encountered
    instead of overwriting wholesale, so a partial result from one page
    isn't lost if the other page is sparse.
    """
    for key, val in new.items():
        existing = accumulator.get(key)
        if existing is None:
            accumulator[key] = val
            continue
        # Combine: prefer non-None on existing, fill in from new.
        accumulator[key] = KTCValue(
            name=existing.name,
            normalized_name=existing.normalized_name,
            position=existing.position,
            superflex_value=existing.superflex_value
            if existing.superflex_value is not None
            else val.superflex_value,
            one_qb_value=existing.one_qb_value
            if existing.one_qb_value is not None
            else val.one_qb_value,
            superflex_position_rank=existing.superflex_position_rank
            if existing.superflex_position_rank is not None
            else val.superflex_position_rank,
            one_qb_position_rank=existing.one_qb_position_rank
            if existing.one_qb_position_rank is not None
            else val.one_qb_position_rank,
        )
