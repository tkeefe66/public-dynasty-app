"""Single league-calendar phase for the dashboard lead section.

Derives ``"regular" | "post" | "draft" | "offseason"`` from the SAME inputs
the per-week production phases use — the live nfl_state week split by the
per-season min playoff-start rule (see ``grader.compute_production_series_
payload``) — so the single ``phase`` field can never disagree with the
``production_week_phases`` array on a scored week.

Computed at refresh time (the dashboard route is sync and cache-only) and
persisted on ``ChainCacheEntry.league_phase``.
"""
from __future__ import annotations

import time

from app.services.nfl_state import league_season_year, regular_season_started

# A scheduled draft counts as "the draft window" this many days before its
# start_time (buildup). What closes the window is kickoff, not the last pick —
# see ``_draft_window_open``.
DRAFT_WINDOW_DAYS = 7


def playoff_start_by_season(
    playoff_weeks_by_league: dict[str, int],
    league_season_by_id: dict[str, int],
) -> dict[int, int]:
    """Per-season playoff start week — the same min-across-leagues rule the
    production week-phase array is built with."""
    out: dict[int, int] = {}
    for lg, season in (league_season_by_id or {}).items():
        start = (playoff_weeks_by_league or {}).get(lg) or 15
        out[season] = min(out.get(season, start), start)
    return out


def _completed_draft_is_current(d: dict, nfl_state: dict | None) -> bool:
    """True when a *completed* draft still deserves the draft window.

    A draft's aftermath is the story until the games start: "how did the class
    look" is the best lead a league has between the last pick and kickoff, and
    it is the only thing that links to the draft board. So a completed draft
    holds the window open while BOTH hold:

    - its season is the current **league year** (``nfl_state.league_season``,
      which names the upcoming league year — so last year's draft can never
      reopen the window, including in the gap after a season ends where
      ``season`` may still name the finished year), and
    - the NFL has not yet reached regular-season week 1.

    An unreadable nfl_state answers neither question, and the window stays
    shut rather than guessing: an outage must not resurrect an old class.
    """
    if regular_season_started(nfl_state) is not False:
        return False  # kicked off, or unknowable
    season = league_season_year(nfl_state)
    if not season:
        return False
    try:
        return int(d.get("season") or 0) == season
    except (TypeError, ValueError):
        return False


def _draft_window_open(
    drafts: list[dict] | None, now_ms: int, nfl_state: dict | None = None,
) -> bool:
    """True while a draft is running, imminent, or freshly completed.

    Three ways in:

    - ``drafting`` — the draft is live.
    - ``pre_draft`` starting within ``DRAFT_WINDOW_DAYS`` (a past start_time
      still in pre_draft counts — draft day is here, the commissioner just
      hasn't hit start).
    - ``complete``, for this season's draft, before the NFL's week 1
      (``_completed_draft_is_current``). The window closes at kickoff, not at
      the last pick: the in-season lead takes over on its own from there.

    Note the consequence for dynasty: a May rookie draft holds the ``draft``
    phase through September. That is intended — through the dynasty offseason
    the rookie class is a better lead than trade-of-the-week.
    """
    for d in drafts or []:
        status = str(d.get("status") or "")
        if status == "drafting":
            return True
        if status == "complete":
            if _completed_draft_is_current(d, nfl_state):
                return True
            continue
        if status != "pre_draft":
            continue  # unknown statuses never open the window
        start = d.get("start_time")
        if not start:
            continue
        try:
            if int(start) <= now_ms + DRAFT_WINDOW_DAYS * 86_400_000:
                return True
        except (TypeError, ValueError):
            continue
    return False


def derive_league_phase(
    *,
    nfl_state: dict | None,
    playoff_weeks_by_league: dict[str, int],
    league_season_by_id: dict[str, int],
    current_season: int,
    drafts: list[dict] | None = None,
    now_ms: int | None = None,
) -> dict:
    """``{"phase", "season", "week"}`` for the dashboard.

    "regular"/"post" while an NFL regular-season week is live, split by the
    league's playoff start (identical to the per-week phase rule); "draft"
    during the draft window (see ``_draft_window_open`` — buildup, the draft
    itself, and its aftermath up to kickoff); "offseason" otherwise —
    including the NFL postseason, when the fantasy season is already over.
    ``week`` is null outside regular/post.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    state = nfl_state if isinstance(nfl_state, dict) else {}
    season_type = str(state.get("season_type") or "").strip().lower()
    try:
        week = int(state.get("week") or 0)
    except (TypeError, ValueError):
        week = 0
    try:
        season = int(state.get("season") or 0)
    except (TypeError, ValueError):
        season = 0
    if season_type == "regular" and week >= 1 and season:
        starts = playoff_start_by_season(playoff_weeks_by_league, league_season_by_id)
        phase = "post" if week >= starts.get(season, 15) else "regular"
        return {"phase": phase, "season": season, "week": week}
    if _draft_window_open(drafts, now_ms, state):
        return {"phase": "draft", "season": current_season, "week": None}
    return {"phase": "offseason", "season": current_season, "week": None}
