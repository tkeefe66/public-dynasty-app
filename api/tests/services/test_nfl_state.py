from app.services.nfl_state import completed_seasons, scoring_in_progress


def test_offseason_is_not_in_progress():
    assert scoring_in_progress({"season_type": "off", "week": 0}) is False
    assert scoring_in_progress({"season_type": "pre", "week": 2}) is False


def test_regular_and_post_season_are_in_progress():
    assert scoring_in_progress({"season_type": "regular", "week": 5}) is True
    assert scoring_in_progress({"season_type": "post", "week": 1}) is True


def test_missing_or_malformed_state_is_conservative_true():
    assert scoring_in_progress(None) is True
    assert scoring_in_progress({}) is True
    assert scoring_in_progress({"season_type": "regular", "week": 0}) is False


def test_unrecognized_season_type_is_conservative_true():
    # An unknown/future season_type must force the safe full-rebuild path
    # rather than being treated as "not scoring" and silently reusing rollups.
    assert scoring_in_progress({"season_type": "weird", "week": 5}) is True
    assert scoring_in_progress({"season_type": "regular_season", "week": 5}) is True


def test_season_type_whitespace_is_stripped():
    # Stray whitespace around a known phase must still classify correctly.
    assert scoring_in_progress({"season_type": " off ", "week": 0}) is False
    assert scoring_in_progress({"season_type": " regular ", "week": 5}) is True


# --- completed_seasons ------------------------------------------------------
# CRITICAL A / the "which season is actually done" gate for draft verdicts.

def test_the_newest_season_is_excluded_while_it_is_still_being_played():
    # Aug 2026: 2026 is live. A chain covering 2025 and 2026 must read 2025
    # as complete and 2026 as not yet.
    state = {"season_type": "regular", "season": 2026, "week": 1}
    assert completed_seasons({2025, 2026}, state) == {2025}


def test_the_newest_season_is_included_once_its_own_season_is_over():
    # Feb 2027, after the Super Bowl: nfl_state still names 2026 (the
    # just-finished year) but season_type has rolled to "off" -> not in
    # progress -> 2026 now reads complete.
    state = {"season_type": "off", "season": 2026, "week": 0}
    assert completed_seasons({2025, 2026}, state) == {2025, 2026}


def test_a_later_live_nfl_season_does_not_mean_the_chain_rolled_over():
    # The chain has not yet grown a 2027 league, but the real NFL calendar
    # has moved on: state.season == 2027 (> the chain's newest, 2026). This
    # is the exact bug being fixed: "is the NFL playing something right
    # now" (scoring_in_progress alone would say yes, for 2027) is NOT the
    # same question as "is the CHAIN's newest season (2026) still live" —
    # 2026 is confirmed done because the live year has moved past it.
    state = {"season_type": "regular", "season": 2027, "week": 3}
    assert completed_seasons({2025, 2026}, state) == {2025, 2026}


def test_an_unreadable_state_excludes_the_newest_season():
    # Can't confirm completion -> stay conservative. Under-counting yields
    # Average instead of Hit; over-counting is the Bust-cascade this whole
    # gate exists to prevent.
    assert completed_seasons({2025, 2026}, None) == {2025}
    assert completed_seasons({2025, 2026}, {}) == {2025}


def test_an_empty_chain_has_no_completed_seasons():
    assert completed_seasons(set(), {"season_type": "off", "season": 2026}) == set()
