from app.models.league import DashboardResp, LeagueCapabilitiesResp
from app.services.aggregations import build_dashboard
from app.services.owner_view import build_owner_detail
from tests.helpers import minimal_chain_cache_entry


def test_capabilities_defaults_to_full_dynasty():
    """A response built without capabilities must not demote a dynasty league."""
    caps = LeagueCapabilitiesResp()
    assert caps.format == "dynasty"
    assert caps.future_picks is True
    assert caps.roster_continuity is True
    assert caps.multiyear_history is True


def test_dashboard_resp_carries_capabilities():
    assert "capabilities" in DashboardResp.model_fields


def test_redraft_capabilities_serialize():
    caps = LeagueCapabilitiesResp(
        format="redraft", future_picks=False,
        roster_continuity=False, multiyear_history=False,
    )
    assert caps.model_dump() == {
        "format": "redraft", "future_picks": False,
        "roster_continuity": False, "multiyear_history": False,
    }


# ---- owner_view: redraft omits the Outlook block ----

_OUTLOOK = {
    "age_profile": {"avg_age_by_position": {"RB": 23.0},
                    "league_avg_age_by_position": {"RB": 25.4},
                    "overall_avg_age": 24.0, "aging_risks": [], "core_young": []},
    "draft_capital": {"picks_by_season": {"2027": 5},
                      "picks_by_season_round": {"2027-1": 2},
                      "net_vs_average": 3.0, "status": "pick-rich"},
    "draft_needs": [],
}


def test_owner_view_omits_outlook_for_redraft():
    entry = minimal_chain_cache_entry(
        league_id="L1",
        owners={"uA": {"owner_name": "Alice"}},
        dynasty_outlooks={"uA": _OUTLOOK},
        capabilities={"format": "redraft", "future_picks": False,
                      "roster_continuity": False, "multiyear_history": False},
    )
    resp = build_owner_detail(entry, "uA")
    assert resp is not None
    assert resp.outlook is None


def test_owner_view_keeps_outlook_for_dynasty():
    """Regression: the redraft gate must not swallow outlook for a dynasty
    league (including pre-feature caches with no capabilities dict at all)."""
    entry = minimal_chain_cache_entry(
        league_id="L1",
        owners={"uA": {"owner_name": "Alice"}},
        dynasty_outlooks={"uA": _OUTLOOK},
    )
    resp = build_owner_detail(entry, "uA")
    assert resp is not None
    assert resp.outlook is not None


# ---- owner_view: redraft also drops the franchise-OUTLOOK blurb ----

def test_owner_view_omits_franchise_blurb_for_redraft():
    """The franchise blurb is the Outlook prose ("Writing franchise outlooks").
    Surfacing it on a page that no longer has an Outlook tab is the same
    defect the tab gate fixed, one surface over."""
    entry = minimal_chain_cache_entry(
        league_id="L1",
        owners={"uA": {"owner_name": "Alice"}},
        franchise_blurbs={"uA": {"blurb": "Pick-rich and dangerous.",
                                 "facts_hash": "x", "generated_at": "t"}},
        capabilities={"format": "redraft", "future_picks": False,
                      "roster_continuity": False, "multiyear_history": False},
    )
    assert build_owner_detail(entry, "uA").franchise_blurb is None


def test_owner_view_keeps_franchise_blurb_for_dynasty():
    entry = minimal_chain_cache_entry(
        league_id="L1",
        owners={"uA": {"owner_name": "Alice"}},
        franchise_blurbs={"uA": {"blurb": "Pick-rich and dangerous.",
                                 "facts_hash": "x", "generated_at": "t"}},
    )
    assert (build_owner_detail(entry, "uA").franchise_blurb
            == "Pick-rich and dangerous.")


# ---- standings: redraft leaves the Outlook-derived columns unpopulated ----

_REDRAFT_CAPS = {"format": "redraft", "future_picks": False,
                 "roster_continuity": False, "multiyear_history": False}


def _two_completed_seasons():
    """Real played seasons for BOTH owners.

    Without these `franchise_redesign.rated_owners` returns [], `live_ratings`
    returns {}, and every `window is None` assertion below holds vacuously —
    which is exactly how the previous version of this fixture passed while
    proving nothing about the redraft gate.
    """
    return {
        "2024": {
            "uA": {"wins": 9, "losses": 4, "ties": 0, "rank": 1,
                   "total_teams": 2, "champion": True, "runner_up": False,
                   "made_playoffs": True, "playoff_place": 1, "rounds_won": 2},
            "uB": {"wins": 4, "losses": 9, "ties": 0, "rank": 2,
                   "total_teams": 2, "champion": False, "runner_up": True,
                   "made_playoffs": True, "playoff_place": 2, "rounds_won": 0},
        },
        "2025": {
            "uA": {"wins": 8, "losses": 5, "ties": 0, "rank": 1,
                   "total_teams": 2, "champion": False, "runner_up": True,
                   "made_playoffs": True, "playoff_place": 2, "rounds_won": 1},
            "uB": {"wins": 5, "losses": 8, "ties": 0, "rank": 2,
                   "total_teams": 2, "champion": False, "runner_up": False,
                   "made_playoffs": False, "rounds_won": 0},
        },
    }


def _standings_entry(**over):
    """Two owners, a full dynasty outlook + the v2 signals both pillars read."""
    base = dict(
        league_id="L1",
        chain=[{"league_id": "L1", "season": 2026, "name": "Bros",
                "total_rosters": 2, "playoff_week_start": 15}],
        owners={"uA": {"owner_name": "Alice"}, "uB": {"owner_name": "Bob"}},
        league_season_by_id={"L1": 2026},
        league_name_by_id={"L1": "Bros"},
        dynasty_outlooks={"uA": _OUTLOOK},
        season_records=_two_completed_seasons(),
        outcome_signals={
            "uA": {"expected_wins": 0.66, "playoff_success": 3.0, "luck": 0.05},
            "uB": {"expected_wins": 0.34, "playoff_success": 0.5, "luck": -0.05},
        },
        outlook_signals={
            "uA": {"roster_value_share": 0.62, "young_core_share": 0.44,
                   "draft_capital": 1200.0, "draft_skill": 0.4},
            "uB": {"roster_value_share": 0.38, "young_core_share": 0.21,
                   "draft_capital": 400.0, "draft_skill": -0.2},
        },
    )
    base.update(over)
    return minimal_chain_cache_entry(**base)


def _row(entry):
    resp = build_dashboard(entry, year="all", lens="ktc")
    return next(r for r in resp.standings if r.user_id == "uA")


def test_redraft_standings_carry_no_window_even_when_the_league_is_rated():
    """`ratings` is NOT redraft-gated (aggregations.py:725) though every
    Outlook-derived column IS (`_outlooks_apply`). Deriving `window` ungated
    re-enables the Outlook columns for redraft and labels those franchises
    "Dynasty". The fixture MUST have populated season_records or rated_owners
    returns [] and this proves nothing."""
    entry = _standings_entry(capabilities=_REDRAFT_CAPS)
    resp = build_dashboard(entry, year="all", lens="ktc")
    assert any(r.gm_rating is not None for r in resp.standings)   # league IS rated
    assert all(r.window is None for r in resp.standings)          # and has no stage


def test_standings_drops_outlook_columns_for_redraft():
    row = _row(_standings_entry(capabilities=_REDRAFT_CAPS))
    # Unpopulated, not zeroed — the frontend omits the column on `null`.
    assert row.window is None
    assert row.draft_capital_value is None


def test_dynasty_standings_carry_the_derived_stage():
    """Rated AND holding a current roster -> a stage.

    Note this fixture gives an outlook blob to uA only, so uB is the
    departed-owner shape: rated, but with no roster to have a window about.
    He is asserted separately below rather than folded into `rated`, because
    "every rated row has a stage" is exactly the claim the standings/owner-page
    disagreement came from.
    """
    entry = _standings_entry()
    resp = build_dashboard(entry, year="all", lens="ktc")
    rated = [r for r in resp.standings if r.gm_rating is not None]
    with_outlook = [r for r in rated if r.user_id in entry.dynasty_outlooks]
    assert with_outlook and all(r.window is not None for r in with_outlook)
    assert all(r.window is None for r in rated if r not in with_outlook)


def test_standings_keeps_outlook_columns_for_dynasty():
    """Regression guard: dynasty (and every pre-feature cache, which has no
    capabilities dict at all) still carries the Outlook-derived columns — but
    `window` is now the stage derived from this row's own Franchise Rating,
    never a string read off the persisted blob."""
    from sleeper_dynasty.engine.gm_rating import rating_to_stage
    row = _row(_standings_entry())
    assert row.window == rating_to_stage(row.gm_rating)
    assert row.draft_capital_value == 1200.0


def test_an_unrated_owner_has_no_stage_even_in_a_dynasty_league():
    """No completed season -> absent from `ratings` -> no rating, so no stage.
    An em dash, never a "Rebuilding" invented out of a missing number."""
    entry = _standings_entry(season_records={})
    resp = build_dashboard(entry, year="all", lens="ktc")
    assert all(r.gm_rating is None and r.window is None for r in resp.standings)
