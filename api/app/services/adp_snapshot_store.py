"""Daily-dated ADP capture, resolved and pinned to each draft's own date.

Sleeper's ADP is *current* ADP and moves all preseason. Grading a draft in
December against December's ADP turns "did you beat the market" into "did you
beat hindsight" — which is production ranking again, with extra steps.

Two layers:

- A daily snapshot (`capture_daily`) is written unconditionally on every
  refresh, one file per calendar day — we cannot know in advance which day a
  league will draft, and that day's ADP is unrecoverable afterwards.
- A per-draft baseline (`capture`/`read`, and `resolve_for_draft` built on
  top of them) is resolved once from daily history — the snapshot dated on
  the draft's own day, else the nearest EARLIER day, never later — and then
  frozen. Keying by draft_id rather than by date makes that immutability
  structural: there is exactly one draft-day file per draft, and a second
  capture is a no-op rather than a race.

**A daily file holds every scoring variant**, `adp_ppr` / `adp_half_ppr` /
`adp_std` / `adp_2qb`, and the caller names the one it wants at resolve time.
This is a multi-tenant install: leagues with differing scoring share the cache
dir, and a single-variant daily file meant the first league to refresh each
day pinned ITS scoring for everyone — a superflex league writing `adp_2qb`
where a PPR league reads it puts QBs ~20-25 picks off, and since both this
file and the per-draft file are write-once, that wrong baseline would freeze
into the class permanently. Storing all four also makes coverage denser than
namespacing by filename would: any league's refresh preserves the day's
market for every other league's scoring, so one league's refresh failing on
its own draft day cannot cost it its baseline.

Consequence: ADP grading works going forward only from whenever daily capture
began. A draft whose own day predates our daily history — including every
draft that completed before this shipped — has no snapshot to resolve
against and grades on the peer baseline alone, permanently.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)

_SUBDIR = "adp"
_DAILY_SUBDIR = "daily"


class AdpSnapshotStore:
    def __init__(self, cache_dir: Path):
        self._dir = Path(cache_dir) / _SUBDIR

    def _path(self, draft_id: str) -> Path:
        return self._dir / f"{draft_id}.json"

    def capture(self, draft_id: str, adp_by_player: dict[str, float]) -> bool:
        """Record this draft's draft-day ADP. Returns whether a write happened.

        Refuses an empty map: an empty result means the fetch failed, and since
        capture is write-once, storing it would poison the baseline forever.
        """
        if not adp_by_player:
            log.warning(
                "refusing empty ADP capture for draft %s; fetch likely failed",
                draft_id)
            return False
        path = self._path(draft_id)
        if path.exists():
            return False
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, adp_by_player)
        except OSError:
            log.exception("ADP snapshot write failed for draft %s", draft_id)
            return False
        log.info(
            "captured draft-day ADP for draft %s (%d players)",
            draft_id, len(adp_by_player))
        return True

    def read(self, draft_id: str) -> dict[str, float] | None:
        """This draft's draft-day ADP, or None if never captured/unreadable."""
        path = self._path(draft_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                return None
            return {str(k): float(v) for k, v in data.items()}
        except (OSError, ValueError, TypeError):
            log.exception("ADP snapshot unreadable for draft %s", draft_id)
            return None

    def _daily_path(self, d: date) -> Path:
        return self._dir / _DAILY_SUBDIR / f"{d.isoformat()}.json"

    def capture_daily(
        self, adp_by_variant: dict[str, dict[str, float]], today: date,
    ) -> bool:
        """Write today's ADP if absent and non-empty. Returns True if written.

        ``adp_by_variant`` is ``adp_*`` field -> {player_id -> ADP}, covering
        every scoring variant at once (see the module docstring): the writer's
        own league scoring must not decide what other leagues can read back.

        Captured unconditionally on refresh, not only when a draft completes:
        we cannot know in advance which day a league will draft, and ADP as of
        that day is unrecoverable afterwards.
        """
        payload = {
            str(field): dict(m)
            for field, m in (adp_by_variant or {}).items() if m
        }
        if not payload:
            log.warning("refusing empty daily ADP capture for %s", today)
            return False
        path = self._daily_path(today)
        if path.exists():
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, payload)
        except OSError:
            log.exception("daily ADP snapshot write failed for %s", today)
            return False
        log.info(
            "captured daily ADP for %s (%s)",
            today, ", ".join(f"{f}:{len(m)}" for f, m in sorted(payload.items())))
        return True

    def list_dates(self) -> list[date]:
        """Every daily-snapshot date we hold, ascending."""
        out: list[date] = []
        for p in (self._dir / _DAILY_SUBDIR).glob("*.json"):
            try:
                out.append(date.fromisoformat(p.stem))
            except ValueError:
                continue
        return sorted(out)

    def resolve_for_draft(
        self, draft_id: str, drafted_on: date, *, field: str,
    ) -> dict[str, float] | None:
        """This draft's frozen baseline, resolving it from daily history once.

        ``field`` is the ``adp_*`` variant matching the league this draft
        belongs to (``draft_baselines.adp_field_for``). It is threaded in
        explicitly rather than defaulted: a wrong-variant baseline reads as a
        plausible number, and write-once means it can never be corrected.

        Resolution picks the snapshot dated on the draft's own day, else the
        nearest EARLIER day — a draft is graded against the market as it stood
        going in, never after. Returns None when no snapshot predates the
        draft: that draft is older than our history and has no baseline,
        permanently. Handing back a later snapshot would be exactly the
        hindsight grading this store exists to prevent.

        A day whose file is corrupt, or which predates all-variant capture and
        so carries nothing for ``field``, is stepped over — the walk continues
        BACKWARD, never forward, so the on-or-before invariant holds.

        The resolved result is pinned via the write-once per-draft file, so
        later daily captures can never move a baseline that already exists.
        The per-draft file needs no variant in its name: a draft belongs to
        exactly one league, whose scoring picked ``field`` once.
        """
        pinned = self.read(draft_id)
        if pinned is not None:
            return pinned
        candidates = sorted(
            (d for d in self.list_dates() if d <= drafted_on), reverse=True)
        for d in candidates:
            snap = self._load_daily(d, field=field)
            if snap:
                self.capture(draft_id, snap)
                return snap
        return None

    def _load_daily(self, d: date, *, field: str) -> dict[str, float] | None:
        """One variant out of a daily file, or None if absent/unreadable."""
        path = self._daily_path(d)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                return None
            variant = data.get(field)
            if not isinstance(variant, dict):
                return None
            return {str(k): float(v) for k, v in variant.items()}
        except (OSError, ValueError, TypeError):
            log.exception("daily ADP snapshot unreadable for %s", d)
            return None
