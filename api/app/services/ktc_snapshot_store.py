"""Dated KTC snapshots for at-trade valuation.

One JSON file per calendar day (snapshots/ktc_YYYY-MM-DD.json) holding the raw
name-keyed KTC table (includes pick entries). Captured opportunistically on
refresh. Snapshots are immutable history — no TTL.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)

_SUBDIR = "snapshots"

# Valuation sources are namespaced by directory. Dynasty keeps the original
# `snapshots/` path so existing installs need no migration; redraft accrues in
# its own. They must never share: a dynasty price applied to a redraft trade is
# the exact silent-mispricing bug this separation exists to prevent, and the two
# tables are keyed the same way, so nothing but the directory keeps them apart.
_DEFAULT_SOURCE = "dynasty"


class KtcSnapshotStore:
    def __init__(self, cache_dir: Path, source: str = _DEFAULT_SOURCE):
        sub = _SUBDIR if source == _DEFAULT_SOURCE else f"{_SUBDIR}-{source}"
        self.source = source
        self.dir = Path(cache_dir) / sub
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, d: date) -> Path:
        return self.dir / f"ktc_{d.isoformat()}.json"

    def capture(self, ktc_values: dict[str, KTCValue], today: date) -> bool:
        """Write today's snapshot if absent and non-empty. Returns True if written."""
        if not ktc_values:
            return False
        path = self._path(today)
        if path.exists():
            return False
        write_json_atomic(path, [v.to_dict() for v in ktc_values.values()])
        return True

    def _load(self, path: Path) -> dict[str, KTCValue] | None:
        if not path.exists():
            return None
        try:
            rows = json.loads(path.read_text())
            return {v.normalized_name: v for v in (KTCValue.from_dict(r) for r in rows)}
        except (OSError, ValueError, KeyError) as e:
            log.warning("KTC snapshot unreadable (%s); ignoring", e)
            return None

    def list_dates(self) -> list[date]:
        out: list[date] = []
        for p in self.dir.glob("ktc_*.json"):
            try:
                out.append(date.fromisoformat(p.stem[len("ktc_"):]))
            except ValueError:
                continue
        return sorted(out)

    def value_extremes(self) -> dict[str, tuple[float, float]]:
        """Min/max superflex value per normalized name across ALL snapshots.

        Window-bounded: snapshots only exist from when capture began
        (~May 2026), so these are not true career extremes for older assets.
        Returns {normalized_name: (lowest, highest)}.
        """
        out: dict[str, tuple[float, float]] = {}
        for d in self.list_dates():
            snap = self._load(self._path(d))
            if not snap:
                continue
            for name, v in snap.items():
                if v.superflex_value is None:
                    continue
                val = float(v.superflex_value)
                lo, hi = out.get(name, (val, val))
                out[name] = (min(lo, val), max(hi, val))
        return out

    def match(
        self, trade_date: date, cutoff: date
    ) -> tuple[dict[str, KTCValue] | None, date | None, bool]:
        """Snapshot to value a trade made on trade_date.

        1. latest snapshot with date <= trade_date  -> (snap, date, approx=False)
        2. else if trade_date >= cutoff             -> earliest snapshot, approx=True
        3. else                                     -> (None, None, False)
        A snapshot that fails to load is treated as absent.
        """
        dates = self.list_dates()
        if not dates:
            return (None, None, False)
        before = [d for d in dates if d <= trade_date]
        if before:
            d = max(before)
            snap = self._load(self._path(d))
            return (snap, d, False) if snap is not None else (None, None, False)
        if trade_date >= cutoff:
            d = min(dates)
            snap = self._load(self._path(d))
            return (snap, d, True) if snap is not None else (None, None, False)
        return (None, None, False)
