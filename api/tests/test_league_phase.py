"""League-calendar phase selector for the dashboard lead section.

``derive_league_phase`` uses the same inputs as the production week-phase
array (nfl_state week + the per-season min playoff-start rule), so the single
``phase`` field can never disagree with the per-week phases.
"""
from __future__ import annotations

from app.services.league_phase import derive_league_phase, playoff_start_by_season

_LEAGUES = {"LG": 15}
_SEASONS = {"LG": 2026}
_KW = dict(
    playoff_weeks_by_league=_LEAGUES,
    league_season_by_id=_SEASONS,
    current_season=2026,
)
_NOW_MS = 1_750_000_000_000  # fixed clock for draft-window tests


def test_regular_week():
    p = derive_league_phase(
        nfl_state={"season_type": "regular", "season": "2026", "week": 5},
        now_ms=_NOW_MS, **_KW,
    )
    assert p == {"phase": "regular", "season": 2026, "week": 5}


def test_bracket_week_is_post():
    p = derive_league_phase(
        nfl_state={"season_type": "regular", "season": "2026", "week": 16},
        now_ms=_NOW_MS, **_KW,
    )
    assert p == {"phase": "post", "season": 2026, "week": 16}


def test_playoff_start_uses_min_across_same_season_leagues():
    # Mirrors the production week-phase rule: min playoff start per season.
    starts = playoff_start_by_season({"A": 14, "B": 15}, {"A": 2026, "B": 2026})
    assert starts == {2026: 14}
    p = derive_league_phase(
        nfl_state={"season_type": "regular", "season": "2026", "week": 14},
        playoff_weeks_by_league={"A": 14, "B": 15},
        league_season_by_id={"A": 2026, "B": 2026},
        current_season=2026, now_ms=_NOW_MS,
    )
    assert p["phase"] == "post"


def test_nfl_postseason_is_offseason():
    # NFL playoffs: the fantasy season is over.
    p = derive_league_phase(
        nfl_state={"season_type": "post", "season": "2026", "week": 20},
        now_ms=_NOW_MS, **_KW,
    )
    assert p == {"phase": "offseason", "season": 2026, "week": None}


def test_drafting_draft_opens_the_window():
    p = derive_league_phase(
        nfl_state={"season_type": "off", "season": "2026", "week": 0},
        drafts=[{"status": "drafting", "season": "2026"}],
        now_ms=_NOW_MS, **_KW,
    )
    assert p == {"phase": "draft", "season": 2026, "week": None}


def test_pre_draft_with_imminent_start_time_is_draft():
    soon = _NOW_MS + 2 * 86_400_000  # two days out
    p = derive_league_phase(
        nfl_state={"season_type": "off", "season": "2026", "week": 0},
        drafts=[{"status": "pre_draft", "season": "2026", "start_time": soon}],
        now_ms=_NOW_MS, **_KW,
    )
    assert p["phase"] == "draft"


def test_pre_draft_far_out_is_offseason():
    far = _NOW_MS + 60 * 86_400_000  # two months out
    p = derive_league_phase(
        nfl_state={"season_type": "off", "season": "2026", "week": 0},
        drafts=[{"status": "pre_draft", "season": "2026", "start_time": far}],
        now_ms=_NOW_MS, **_KW,
    )
    assert p["phase"] == "offseason"


def test_this_seasons_completed_draft_holds_the_window_until_kickoff():
    """The window closes at kickoff, not at the last pick. Without this the
    draft lead is dead code: the phase would flip the instant the draft
    completed, and nothing else in the app links to the draft board."""
    p = derive_league_phase(
        nfl_state={"season_type": "pre", "season": "2026", "week": 0},
        drafts=[{"status": "complete", "season": "2026", "start_time": _NOW_MS}],
        now_ms=_NOW_MS, **_KW,
    )
    assert p == {"phase": "draft", "season": 2026, "week": None}


def test_completed_draft_holds_the_window_through_the_dynasty_offseason():
    """A May rookie draft keeps the draft phase into September. Intended: in
    the dynasty offseason the rookie class is the better lead."""
    p = derive_league_phase(
        nfl_state={"season_type": "off", "season": "2026", "week": 0},
        drafts=[{"status": "complete", "season": "2026", "start_time": _NOW_MS}],
        now_ms=_NOW_MS, **_KW,
    )
    assert p["phase"] == "draft"


def test_last_seasons_completed_draft_does_not_reopen_the_window():
    """Once the NFL rolls to the next season, an old class is history — the
    league chain's own newest season lags until next year's league exists, so
    nfl_state.season is the authority on 'current'."""
    p = derive_league_phase(
        nfl_state={"season_type": "off", "season": "2027", "week": 0},
        drafts=[{"status": "complete", "season": "2026", "start_time": _NOW_MS}],
        now_ms=_NOW_MS, **_KW,
    )
    assert p["phase"] == "offseason"


def test_completed_draft_does_not_reopen_during_the_nfl_postseason():
    p = derive_league_phase(
        nfl_state={"season_type": "post", "season": "2026", "week": 20},
        drafts=[{"status": "complete", "season": "2026", "start_time": _NOW_MS}],
        now_ms=_NOW_MS, **_KW,
    )
    assert p["phase"] == "offseason"


def test_completed_draft_does_not_open_the_window_on_unknown_nfl_state():
    """An nfl_state outage answers neither question. The window stays shut
    rather than resurrecting a class we can't date."""
    p = derive_league_phase(
        nfl_state=None,
        drafts=[{"status": "complete", "season": "2026", "start_time": _NOW_MS}],
        now_ms=_NOW_MS, **_KW,
    )
    assert p["phase"] == "offseason"


def test_completed_draft_with_unreadable_season_does_not_open_the_window():
    p = derive_league_phase(
        nfl_state={"season_type": "pre", "season": "2026", "week": 0},
        drafts=[{"status": "complete", "season": "not-a-year"}],
        now_ms=_NOW_MS, **_KW,
    )
    assert p["phase"] == "offseason"


def test_missing_state_falls_back_to_offseason():
    p = derive_league_phase(nfl_state=None, now_ms=_NOW_MS, **_KW)
    assert p == {"phase": "offseason", "season": 2026, "week": None}


def test_regular_week_zero_is_not_in_season():
    p = derive_league_phase(
        nfl_state={"season_type": "regular", "season": "2026", "week": 0},
        now_ms=_NOW_MS, **_KW,
    )
    assert p["phase"] == "offseason"


# --- nfl_state helpers the draft window leans on ----------------------------

def test_regular_season_started_reads_each_season_type():
    from app.services.nfl_state import league_season_year, regular_season_started

    assert regular_season_started({"season_type": "pre", "week": 3}) is False
    assert regular_season_started({"season_type": "off", "week": 0}) is False
    assert regular_season_started({"season_type": "regular", "week": 1}) is True
    assert regular_season_started({"season_type": "regular", "week": 0}) is False
    assert regular_season_started({"season_type": "post", "week": 2}) is True
    # Unknowable is None, never False — an outage must not read as "not yet".
    assert regular_season_started(None) is None
    assert regular_season_started({"season_type": "???"}) is None
    assert league_season_year({"league_season": "2026"}) == 2026
    assert league_season_year({"league_season": "nope"}) is None
    assert league_season_year(None) is None


def test_league_season_year_prefers_league_season_over_season():
    """The two diverge in the gap between a season ending and the league year
    rolling over. `season` can still name the finished year while
    `league_season` already names the upcoming one — and "which league year are
    we in" is the question the draft window is actually asking. Reading
    `season` there would let a completed draft from the just-finished year
    reopen the window during that gap.
    """
    from app.services.nfl_state import league_season_year

    assert league_season_year({"season": "2026", "league_season": "2027"}) == 2027


def test_league_season_year_falls_back_to_season_when_absent():
    """Older or partial payloads may omit league_season; `season` is the next
    best answer and is right outside the rollover gap."""
    from app.services.nfl_state import league_season_year

    assert league_season_year({"season": "2026"}) == 2026
    assert league_season_year({"season": "2026", "league_season": ""}) == 2026


# --- ChainCacheEntry persistence --------------------------------------------

def test_league_phase_round_trips_through_chain_cache(tmp_path):
    from app.services.chain_cache import ChainCache
    from tests.helpers import minimal_chain_cache_entry

    cache = ChainCache(cache_dir=tmp_path)
    entry = minimal_chain_cache_entry(
        league_phase={"phase": "post", "season": 2026, "week": 16})
    cache.write("L", entry)
    back = cache.read("L")
    assert back.league_phase == {"phase": "post", "season": 2026, "week": 16}


def test_pre_feature_entry_defaults_empty_league_phase():
    from tests.helpers import minimal_chain_cache_entry

    assert minimal_chain_cache_entry().league_phase == {}
