"""Coarsened signatures for the LLM-regeneration skip decision.

The three facts packets (trade story, GM blurb, franchise outlook) all feed an
incremental-skip hash: a cached blurb is regenerated only when its facts hash
changes. The trouble is the packets carry values that drift on *every* refresh
without the narrative meaningfully changing — today's KTC market value moves
daily, started-points totals move weekly in-season — so a literal hash of the
packet changes constantly and every blurb regenerates 8×/day per league. That
churn, not per-call price, is the dominant LLM cost.

This module hashes a *coarsened* view instead: continuous magnitudes are banded
to a fixed grid (so sub-band drift collapses to the same hash), pure
week-by-week counters are dropped, and discrete/categorical fields (winner,
rank, flip outcomes, terminal states) are kept exact. The result: a blurb
regenerates on a material change (a winner flip, a flip resolving, a value
crossing a band) but not on cosmetic daily drift. The *full* packet still feeds
the prompt — only the skip hash is coarsened.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# field name -> grid width. A value is rounded to the nearest multiple of its
# width, so any drift smaller than the width collapses to the same bucket.
FIELD_BANDS: dict[str, float] = {
    # KTC market-value scale (hundreds–thousands; daily drift is tens). Banded
    # to 400 so only a *significant* value swing (not a routine market tick)
    # crosses a bucket and regenerates a blurb.
    "net_ktc": 400,
    "ktc": 400,  # margins["ktc"]
    "draft_capital_net": 400,
    # fantasy-points scale (drifts weekly in-season). Banded to 50 (~two starts'
    # worth) so a single good week does not trip a regen; a sustained shift does.
    "production": 50,
    "points_started": 50,
    "playoff_points": 50,
    "points_total": 50,
    "phantom_points": 50,
    "season_high_points": 50,
    "points_per_game": 10,
    "playoff_vs_regular_pct": 50,
    # GM rating (≈800–2200, recomputed each refresh as KTC moves).
    "rating": 150,
    # 0..1 rates / ratios.
    "made_playoffs_rate": 0.2,
    "lopsidedness": 0.15,
    # Share of roster value held by players 25-and-under. Needs an explicit
    # band: _default_width would give a 0..1 ratio a width of 1.0 and collapse
    # every roster in the league to the same bucket.
    "young_core_share": 0.1,
    # roster age (years). Banded to the nearest year — age ticks up daily off
    # birthdates, and "young vs old" is the only narrative signal. No packet
    # sends it any more (the franchise packet swapped it for young_core_share),
    # but the band is harmless and covers any historical dict still hashed.
    "overall_avg_age": 1.0,
}

# Integer fields that are recomputed (and drift) each refresh rather than
# marking a discrete event. Banded like floats — as is any int whose key is in
# FIELD_BANDS (KTC values arrive as ints from the API; a banded field must band
# regardless of numeric type or daily market ticks churn the hash). All other
# ints (rank, counts, season, round, championships) are kept exact — they only
# change on real events.
DRIFTY_INT_KEYS = frozenset({"rating"})

# Pure week-by-week counters: they tick up every in-season refresh and carry no
# narrative weight on their own. Dropped from the signature entirely.
WEEKLY_COUNTER_KEYS = frozenset({
    "starter_weeks",
    "benched_weeks",
    "decisive_starts",
    "last_rostered_week",
    "season_high_week",
    "dropped_before_week",
})


def _default_width(x: float) -> float:
    """Magnitude-appropriate band width for a numeric field not in FIELD_BANDS
    (e.g. nested pillar contributions / signal z-scores)."""
    m = abs(x)
    if m < 10:
        return 1.0
    if m < 100:
        return 10.0
    if m < 1000:
        return 50.0
    return 250.0


def _band(key: str, x: float) -> float:
    width = FIELD_BANDS.get(key) or _default_width(x)
    if width <= 0:
        return float(x)
    return float(round(x / width) * width)


def _coarsen(key: str, value: Any) -> Any:
    # bool is an int subclass — must be checked first, and is kept exact.
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return _band(key, value)
    if isinstance(value, int):
        if key in DRIFTY_INT_KEYS or key in FIELD_BANDS:
            return _band(key, float(value))
        return value
    if isinstance(value, dict):
        return {
            k: _coarsen(k, v)
            for k, v in value.items()
            if k not in WEEKLY_COUNTER_KEYS
        }
    if isinstance(value, list):
        # List items inherit the parent key's banding context; nested dicts
        # re-key off their own field names. Lists of strings are sorted:
        # value-ordered lists (young_core, aging_risks) reshuffle on daily
        # drift, and ordering is not narrative-material — membership is.
        items = [_coarsen(key, v) for v in value]
        if items and all(isinstance(v, str) for v in items):
            return sorted(items)
        return items
    return value  # str, None, etc. — kept exact


def signature_hash(facts_dict: dict[str, Any]) -> str:
    """Stable 16-char hash of a coarsened facts packet (incremental-skip key)."""
    coarse = _coarsen("", facts_dict)
    blob = json.dumps(coarse, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]
