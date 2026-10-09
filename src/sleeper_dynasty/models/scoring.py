"""Canonical scoring rules that cannot be represented by a raw stat multiplier.

Threshold bonuses stay inside the existing ``dict[str, float]`` scoring contract:
``bonus_gte:pass_yd:300`` awards its configured points once per scoring week at
300+ passing yards. Multiple keys are cumulative, and ``kr_yd+pr_yd`` describes
a threshold on combined return yards, not one threshold for each component.

This namespace deliberately differs from Sleeper's fixed bonus stat names,
whose yardage bands can be mutually exclusive.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache

THRESHOLD_BONUS_PREFIX = "bonus_gte:"
_STAT_KEY = re.compile(r"[a-z][a-z0-9_]*")


def _number(value) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("Invalid threshold scoring data.")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid threshold scoring data.") from None
    if not number.is_finite():
        raise ValueError("Invalid threshold scoring data.")
    return number


def threshold_bonus_key(stat_keys: tuple[str, ...], target) -> str:
    """Encode a positive inclusive threshold on one or more canonical stats."""
    if (not stat_keys or len(set(stat_keys)) != len(stat_keys)
            or any(not _STAT_KEY.fullmatch(key) for key in stat_keys)):
        raise ValueError("Invalid threshold scoring stat.")
    number = _number(target)
    if number <= 0:
        raise ValueError("Scoring bonus thresholds must be positive.")
    # Normalize spellings (100, 100.0, 1e2) before combining repeated bonus slots.
    threshold = format(number, "f")
    if "." in threshold:
        threshold = threshold.rstrip("0").rstrip(".")
    return f"{THRESHOLD_BONUS_PREFIX}{'+'.join(sorted(stat_keys))}:{threshold}"


@lru_cache(maxsize=256)
def _threshold_rule(key: str) -> tuple[tuple[str, ...], Decimal]:
    parts = key.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid threshold scoring rule.")
    stat_keys = tuple(parts[1].split("+"))
    # Validate even persisted keys: a corrupt rule must not silently score zero.
    threshold_bonus_key(stat_keys, parts[2])
    return stat_keys, _number(parts[2])


def weekly_scoring_stats(stats: dict, scoring: dict) -> dict:
    """Derive each configured bonus exactly once from one week's raw stats.

    Never call this on season totals: a season's aggregate yardage cannot tell us
    how many individual games crossed a weekly threshold. Raw stats remain safe
    to share between leagues because this returns a fresh mapping.
    """
    values = dict(stats)
    for key, weight in scoring.items():
        if not key.startswith(THRESHOLD_BONUS_PREFIX):
            continue
        stat_keys, target = _threshold_rule(key)
        _number(weight)
        actual = sum(
            (_number(stats.get(stat_key, 0)) for stat_key in stat_keys), Decimal(0)
        )
        # Overwrite any pre-derived indicator instead of adding to it. A cached
        # or upstream flag must never award the same configured bonus twice.
        values[key] = int(actual >= target)
    return values
