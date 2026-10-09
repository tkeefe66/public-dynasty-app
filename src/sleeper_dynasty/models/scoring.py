"""Platform-neutral scoring rules in addition to linear stat multipliers."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache

THRESHOLD_BONUS_PREFIX = "bonus_gte:"
_STAT_KEY = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class ThresholdBonus:
    """Award points once when a week's combined stats reach ``target``.

    Rules are cumulative: every satisfied rule awards its own points. Compound
    categories are one rule with several component keys, not a separate award
    for each component. Provider IDs and payload envelopes stay in adapters.
    """

    stat_keys: tuple[str, ...]
    target: float
    points: float

    def __post_init__(self) -> None:
        if not isinstance(self.stat_keys, (tuple, list)) or not self.stat_keys:
            raise ValueError("A scoring bonus requires at least one stat key.")
        keys = tuple(self.stat_keys)
        if (any(not isinstance(key, str) or not key or key.strip() != key for key in keys)
                or len(set(keys)) != len(keys)):
            raise ValueError("Scoring bonus stat keys must be nonempty and unique.")
        object.__setattr__(self, "stat_keys", keys)
        for name in ("target", "points"):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float, Decimal))
                    or not math.isfinite(value)):
                raise ValueError(f"Scoring bonus {name} must be a finite number.")
            object.__setattr__(self, name, float(value))
        if self.target < 0:
            raise ValueError("A scoring bonus target cannot be negative.")


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
    """Encode the legacy persisted format; new leagues use ``ThresholdBonus``.

    An earlier release stored positive weekly rules inside ``scoring_settings``
    as ``bonus_gte:kr_yd+pr_yd:100``. Keep its public helper and stable spellings
    so existing caches and callers remain readable during the transition.
    """
    if (not isinstance(stat_keys, (tuple, list)) or not stat_keys
            or any(not isinstance(key, str) or not _STAT_KEY.fullmatch(key) for key in stat_keys)
            or len(set(stat_keys)) != len(stat_keys)):
        raise ValueError("Invalid threshold scoring stat.")
    number = _number(target)
    if number <= 0:
        raise ValueError("Scoring bonus thresholds must be positive.")
    threshold = format(number, "f")
    if "." in threshold:
        threshold = threshold.rstrip("0").rstrip(".")
    return f"{THRESHOLD_BONUS_PREFIX}{'+'.join(sorted(stat_keys))}:{threshold}"


@lru_cache(maxsize=256)
def _threshold_rule(key: str) -> tuple[tuple[str, ...], Decimal]:
    parts = key.split(":")
    if len(parts) != 3 or parts[0] != THRESHOLD_BONUS_PREFIX[:-1]:
        raise ValueError("Invalid threshold scoring rule.")
    keys = tuple(parts[1].split("+"))
    # Validate persisted keys too: corrupt rules must never silently score zero.
    threshold_bonus_key(keys, parts[2])
    return tuple(sorted(keys)), _number(parts[2])


def split_scoring_rules(
    scoring: Mapping[str, float], bonuses: Sequence[ThresholdBonus] = (),
) -> tuple[dict[str, float], tuple[ThresholdBonus, ...]]:
    """Read typed and legacy rules without mutating or double-pricing either.

    Typed entries are cumulative, so repeated identical milestones coalesce by
    summing their declared awards. A legacy entry representing that same rule
    must agree with the combined award. Identical representations count once;
    conflicting representations fail explicitly rather than picking a winner.
    """
    linear = {}
    typed = {}
    for bonus in bonuses:
        identity = (tuple(sorted(bonus.stat_keys)), _number(bonus.target))
        typed[identity] = typed.get(identity, Decimal(0)) + _number(bonus.points)
    legacy = {}
    for key, value in scoring.items():
        if not isinstance(key, str) or not key.startswith(THRESHOLD_BONUS_PREFIX):
            linear[key] = value
            continue
        identity = _threshold_rule(key)
        points = _number(value)
        if identity in legacy and legacy[identity] != points:
            raise ValueError("Conflicting legacy threshold scoring rules.")
        legacy[identity] = points
    for identity, points in legacy.items():
        if identity in typed and typed[identity] != points:
            raise ValueError("Conflicting typed and legacy threshold scoring rules.")
        typed[identity] = points
    rules = tuple(ThresholdBonus(keys, target, points)
                  for (keys, target), points in typed.items())
    return linear, rules


def has_threshold_bonuses(
    scoring: Mapping[str, float], bonuses: Sequence[ThresholdBonus] = (),
) -> bool:
    """Whether either persisted representation requires weekly bonus evidence."""
    _, rules = split_scoring_rules(scoring, bonuses)
    return any(bonus.points for bonus in rules)


def weekly_scoring_stats(stats: dict, scoring: dict) -> dict:
    """Compatibility for callers deriving legacy flags from one actual week.

    Fresh weekly scoring uses ``split_scoring_rules`` and ignores these flags.
    This helper preserves the previous public API and copy-on-write contract;
    never use it on season totals or aggregate projections.
    """
    split_scoring_rules(scoring)  # Validate all rules, including duplicate aliases.
    values = dict(stats)
    seen = set()
    played = _number(stats["gp"]) > 0 if stats.get("gp") is not None else None
    for key in scoring:
        if not isinstance(key, str) or not key.startswith(THRESHOLD_BONUS_PREFIX):
            continue
        identity = _threshold_rule(key)
        keys, target = identity
        actual = sum((_number(stats.get(stat, 0)) for stat in keys), Decimal(0))
        # Overwrite pre-derived flags, and never repeat the same canonical rule
        # just because a persisted alias orders components differently.
        values[key] = int(bool(stats) and played is not False
                          and identity not in seen and actual >= target)
        seen.add(identity)
    return values
