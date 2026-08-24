"""FantasyPros ECR consensus boards: committed history plus weekly capture.

Two layers, merged into ONE timeline so there is no seam between backfilled
and live:

- The committed history (``sleeper_dynasty/data/{packaged}``) carries every
  board up to the day it was generated. Historical boards are immutable, so
  they ship with the code rather than being fetched, and they survive a
  cache-volume wipe — which the snapshot stores do not.
- ``capture_daily`` records boards from ``db_fpecr_latest.csv`` (a 1MB plain
  CSV, scraped weekly) going forward. No parquet reader at runtime.

Each draft's board is resolved once — on-or-before its own day, never after —
and then frozen write-once per ``draft_id``, exactly as ``AdpSnapshotStore``
does. Keying by draft id rather than by date makes immutability structural.

``EcrBoardStore`` is generic over the board type (``subdir``/``packaged``/
``max_age_days``): FantasyPros publishes several ECR flavors out of one feed
(rookie, dynasty overall, dynasty superflex, ...) and each needs its own
isolated timeline plus its own staleness bound. The subdir MUST differ per
board type — ``resolve_for_draft`` pins write-once at
``{subdir}/{draft_id}.json``, so two board types sharing a subdir would let
the first writer permanently poison the second, the same class of failure
``capture_daily``'s empty-refusal guard exists to prevent.

Construct via the named constructors (``EcrBoardStore.rookie(cache_dir)``,
``.dynasty_overall(cache_dir)``, ``.dynasty_superflex(cache_dir)``), never
the bare constructor with a partial set of arguments — the three facts
(subdir, packaged filename, max_age_days) must travel together, and the bare
constructor's defaults are only the rookie triple by convention, not by
contract.

``RookieBoardStore`` is a permanent (not transitional) alias configured for
the original rookie board, so existing call sites are unaffected.
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import date
from importlib.resources import files
from pathlib import Path

from sleeper_dynasty.engine.rookie_board import (
    DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS, MAX_BOARD_AGE_DAYS, parse_boards,
    resolve_board,
)
from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)

_PACKAGE = "sleeper_dynasty.data"
_DAILY_SUBDIR = "daily"

_ROOKIE_SUBDIR = "rookie_ecr"
_ROOKIE_PACKAGED = "rookie_ecr.json.gz"

_DYNASTY_OVERALL_SUBDIR = "dynasty_ecr"
_DYNASTY_OVERALL_PACKAGED = "dynasty_ecr.json.gz"

_DYNASTY_SUPERFLEX_SUBDIR = "dynasty_sf_ecr"
_DYNASTY_SUPERFLEX_PACKAGED = "dynasty_sf_ecr.json.gz"


class EcrBoardStore:
    def __init__(
        self,
        cache_dir: Path,
        subdir: str = _ROOKIE_SUBDIR,
        packaged: str = _ROOKIE_PACKAGED,
        max_age_days: int = MAX_BOARD_AGE_DAYS,
    ):
        self._dir = Path(cache_dir) / subdir
        self._packaged = packaged
        self._max_age_days = max_age_days
        self._committed: dict[str, dict[str, float]] | None = None

    # ---- named constructors -------------------------------------------------
    #
    # Each board type is a (subdir, packaged filename, max_age_days) triple
    # that must agree with itself. The bare constructor's defaults happen to
    # be the rookie triple, so a caller building a dynasty-overall store by
    # passing only subdir/packaged would silently inherit the rookie's 60-day
    # bound instead of the 45-day one that applies to a whole-pool board
    # (see DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS's docstring in rookie_board.py).
    # These constructors bind all three together so that mismatch cannot be
    # expressed at a call site.

    @classmethod
    def rookie(cls, cache_dir: Path) -> "EcrBoardStore":
        return cls(cache_dir, _ROOKIE_SUBDIR, _ROOKIE_PACKAGED, MAX_BOARD_AGE_DAYS)

    @classmethod
    def dynasty_overall(cls, cache_dir: Path) -> "EcrBoardStore":
        return cls(cache_dir, _DYNASTY_OVERALL_SUBDIR, _DYNASTY_OVERALL_PACKAGED,
                    DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS)

    @classmethod
    def dynasty_superflex(cls, cache_dir: Path) -> "EcrBoardStore":
        return cls(cache_dir, _DYNASTY_SUPERFLEX_SUBDIR, _DYNASTY_SUPERFLEX_PACKAGED,
                    DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS)

    # ---- committed history -------------------------------------------------

    def committed(self) -> dict[str, dict[str, float]]:
        """Every board that shipped with the code. Parsed once per instance."""
        if self._committed is None:
            try:
                blob = files(_PACKAGE).joinpath(self._packaged).read_bytes()
                self._committed = parse_boards(json.loads(gzip.decompress(blob)))
            except (OSError, ValueError, ModuleNotFoundError):
                log.exception(
                    "committed ECR history unreadable (%s)", self._packaged)
                self._committed = {}
        return self._committed

    # ---- weekly capture ----------------------------------------------------

    def _daily_path(self, day: date) -> Path:
        return self._dir / _DAILY_SUBDIR / f"{day.isoformat()}.json"

    def capture_daily(self, board: dict[str, float], today: date) -> bool:
        """Write today's board if absent and non-empty. True if written.

        Refuses an empty board: an empty result means the fetch failed, and
        since resolution pins write-once, storing it would poison a baseline
        permanently.
        """
        if not board:
            log.warning("refusing empty ECR capture for %s (%s)",
                        today, self._packaged)
            return False
        path = self._daily_path(today)
        if path.exists():
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, {str(k): float(v) for k, v in board.items()})
        except OSError:
            log.exception("ECR capture failed for %s (%s)", today, self._packaged)
            return False
        log.info("captured ECR (%s) for %s (%d players)",
                  self._packaged, today, len(board))
        return True

    def _captured(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for path in (self._dir / _DAILY_SUBDIR).glob("*.json"):
            try:
                date.fromisoformat(path.stem)
                data = json.loads(path.read_text())
                if isinstance(data, dict) and data:
                    out[path.stem] = {
                        str(k): float(v) for k, v in data.items()}
            except (OSError, ValueError, TypeError):
                continue  # a corrupt day is stepped over, never guessed at
        return out

    def all_boards(self) -> dict[str, dict[str, float]]:
        """Committed history and captured days as one timeline.

        A captured day wins over a committed one of the same date: capture is
        the fresher observation of a board that has since stopped being
        republished.
        """
        merged = dict(self.committed())
        merged.update(self._captured())
        return merged

    # ---- per-draft pin -----------------------------------------------------

    def _pin_path(self, draft_id: str) -> Path:
        return self._dir / f"{draft_id}.json"

    def _read_pin(self, draft_id: str) -> dict[str, float] | None:
        path = self._pin_path(draft_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not data:
                return None
            return {str(k): float(v) for k, v in data.items()}
        except (OSError, ValueError, TypeError):
            log.exception("ECR pin unreadable for draft %s (%s)",
                          draft_id, self._packaged)
            return None

    def resolve_for_draft(
        self, draft_id: str, drafted_on: date,
    ) -> dict[str, float] | None:
        """This draft's frozen board, resolving it from the timeline once.

        Returns None when no board predates the draft: that class is older than
        our history and has no baseline, permanently.
        """
        pinned = self._read_pin(draft_id)
        if pinned is not None:
            return pinned
        resolved = resolve_board(
            self.all_boards(), drafted_on, max_age_days=self._max_age_days)
        if resolved is None:
            return None
        _day, board = resolved
        path = self._pin_path(draft_id)
        if not path.exists():
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                write_json_atomic(path, board)
            except OSError:
                log.exception("ECR pin write failed for %s (%s)",
                              draft_id, self._packaged)
        return board


# Permanent alias (per controller ruling, not transitional): existing call
# sites construct RookieBoardStore(cache_dir) with no board-type knowledge,
# and default to the original rookie subdir/packaged file.
RookieBoardStore = EcrBoardStore
