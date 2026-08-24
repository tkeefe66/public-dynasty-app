"""Fetch and classify the live NFL scoring state.

``scoring_in_progress`` decides whether the incremental reuse path is safe: when
a regular/post-season week is in progress, weekly points (and therefore the
production/injury rollups) still change day to day. Offseason/preseason/
between-weeks → rollups are frozen.

``fetch_state`` is the read path for surfaces that just want the current week —
the TopBar week note asks on every page view, so the answer is cached
in-process. Sleeper's ``/state/nfl`` changes at most a few times a week, which
makes a short TTL both safe and enough to keep fan-out to one call per process
per interval.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# NFL state advances weekly; five minutes is far tighter than it needs to be and
# still collapses every page view in the window into one upstream call.
STATE_TTL_SECONDS = 300.0

_cache: tuple[float, dict[str, Any]] | None = None


async def fetch_state(client: Any = None) -> dict[str, Any] | None:
    """Sleeper's NFL state, cached for ``STATE_TTL_SECONDS``.

    Returns ``None`` when it can't be fetched — every caller treats an unknown
    state as "say nothing" rather than surfacing an error, so this never raises.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and (now - _cache[0]) < STATE_TTL_SECONDS:
        return _cache[1]
    try:
        if client is None:
            from sleeper_dynasty.api.sleeper import SleeperClient
            client = SleeperClient()
        state = await client.get_nfl_state()
    except Exception:
        log.warning("nfl state fetch failed; callers fall back to silence", exc_info=True)
        return _cache[1] if _cache is not None else None
    if not isinstance(state, dict):
        return None
    _cache = (now, state)
    return state


def reset_cache() -> None:
    """Drop the memo. For tests only."""
    global _cache
    _cache = None


def league_season_year(state: dict | None) -> int | None:
    """The **league year** ``state`` describes, or None when it can't be read.

    Reads ``league_season`` in preference to ``season``. The two are equal most
    of the year and diverge in the gap between a season ending and the league
    year rolling over, where ``season`` can still name the finished year while
    ``league_season`` already names the upcoming one.

    "Which league year are we in" is the question the draft window is actually
    asking, and the distinction is load-bearing there: reading ``season`` would
    let a completed draft from the just-finished year reopen the window during
    that gap. Falls back to ``season`` when ``league_season`` is absent — older
    or partial payloads may omit it, and outside the gap they agree.

    A league chain's own newest season is not a substitute for either: it lags
    until the commissioner creates next year's league.
    """
    if not isinstance(state, dict):
        return None
    for key in ("league_season", "season"):
        try:
            season = int(state.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if season:
            return season
    return None


def regular_season_started(state: dict | None) -> bool | None:
    """Whether the NFL has reached week 1 of ``state``'s regular season.

    ``None`` means unknowable (missing or unrecognized state) — deliberately
    distinct from ``False`` so callers that need a definite "not yet" don't
    read an outage as one.
    """
    if not isinstance(state, dict):
        return None
    season_type = str(state.get("season_type") or "").strip().lower()
    if season_type in ("pre", "off"):
        return False
    if season_type == "post":
        return True  # the NFL postseason is well past week 1
    if season_type != "regular":
        return None
    try:
        week = int(state.get("week") or 0)
    except (TypeError, ValueError):
        return None
    return week >= 1


def scoring_in_progress(state: dict | None) -> bool:
    if not isinstance(state, dict):
        return True  # unknown -> safe (force full rebuild)
    season_type = str(state.get("season_type") or "").strip().lower()
    if season_type in ("pre", "off"):
        return False  # recognized non-scoring phase -> rollups frozen
    if season_type not in ("regular", "post"):
        return True  # missing/unrecognized -> safe (force full rebuild)
    try:
        week = int(state.get("week") or 0)
    except (TypeError, ValueError):
        return True
    return week >= 1


def completed_seasons(chain_seasons: set[int], state: dict | None) -> set[int]:
    """Which of ``chain_seasons`` have a finished NFL regular + post season.

    Every season a league chain has ever rostered is necessarily over except
    possibly the newest — a chain only grows forward, so anything older than
    its own newest season is already in the books by definition. The newest
    is confirmed done only when ``state`` positively says so: its own season
    year has moved past the chain's newest, or matches it exactly with
    scoring no longer in progress. An unreadable ``state``, or one naming a
    year no later than the chain's newest without confirming that year is
    over, cannot confirm completion — the newest season stays excluded, the
    safe direction: under-counting a season yields a conservative (Average,
    not Hit) verdict, while over-counting it is the Hit/Bust misread this
    function exists to prevent.

    Matched on ``state["season"]`` — deliberately not ``league_season_year``,
    which can already name the UPCOMING league year during the post-season
    gap (see its own docstring) — the same raw field ``scoring_in_progress``
    reads its week check against.

    This is why "is the NFL playing something right now" is not the same
    question as "is THIS chain's newest season still live": a chain that
    has not yet rolled over to a new league year must not read its already-
    finished newest season as still in progress just because a LATER NFL
    season has since kicked off — ``state["season"]`` naming a year past the
    chain's newest is exactly what rules that out.
    """
    seasons = set(chain_seasons)
    if not seasons:
        return seasons
    newest = max(seasons)
    try:
        live = int((state or {}).get("season") or 0) or None
    except (TypeError, ValueError):
        live = None
    newest_confirmed_done = live is not None and (
        live > newest or (live == newest and not scoring_in_progress(state))
    )
    return seasons if newest_confirmed_done else (seasons - {newest})
