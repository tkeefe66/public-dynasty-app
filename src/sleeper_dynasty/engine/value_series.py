"""Shared data types for the value-over-time evaluation.

The KTC value-series path (Trade Value progression curves) has been retired
and removed; the functions that computed and rendered it are gone. This module
is kept only because ``AssetTenure`` is still used by ``engine/lineage.py``
(``side_value_tenures``), whose tenures feed the production timeline via
``grader.compute_production_series_payload``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class AssetTenure:
    """One asset's terminal state for the float/lock/cliff evaluation."""

    kind: Literal["player", "pick"]
    player_id: str | None
    season: int | None
    round: int | None
    terminal: Literal["held", "flipped", "dropped"]
    terminal_date: str | None  # ISO "YYYY-MM-DD"; None when held
