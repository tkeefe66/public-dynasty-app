"""Platform-neutral scoring rules in addition to linear stat multipliers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal


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
