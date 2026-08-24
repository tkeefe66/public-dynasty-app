import pytest

from sleeper_dynasty.engine.draft_baselines import (
    ADP_UNDRAFTED, adp_delta, adp_field_for, owner_adp_grades, parse_adp,
    parse_all_adp, parse_projected_points, points_field_for,
)


# --- scoring-format field selection ---

def test_superflex_wins_over_reception_scoring():
    assert adp_field_for(rec_points=1.0, superflex=True) == "adp_2qb"


def test_ppr_half_and_standard_map_to_their_own_fields():
    assert adp_field_for(rec_points=1.0, superflex=False) == "adp_ppr"
    assert adp_field_for(rec_points=0.5, superflex=False) == "adp_half_ppr"
    assert adp_field_for(rec_points=0.0, superflex=False) == "adp_std"


def test_points_field_has_no_superflex_variant():
    assert points_field_for(rec_points=1.0) == "pts_ppr"
    assert points_field_for(rec_points=0.5) == "pts_half_ppr"
    assert points_field_for(rec_points=0.0) == "pts_std"


# --- parsing ---

def test_undrafted_sentinel_is_filtered_out():
    """999.0 means 'never drafted', not 'drafted 999th'. Left in, it becomes a
    catch-all bucket that silently grades every undrafted player identically."""
    raw = {"p1": {"adp_ppr": 12.5}, "p2": {"adp_ppr": ADP_UNDRAFTED}}
    assert parse_adp(raw, field="adp_ppr") == {"p1": 12.5}


def test_missing_and_non_numeric_values_are_skipped():
    raw = {
        "p1": {"adp_ppr": 3.0}, "p2": {}, "p3": {"adp_ppr": None},
        "p4": "not-a-dict", "p5": {"adp_ppr": "x"},
    }
    assert parse_adp(raw, field="adp_ppr") == {"p1": 3.0}


def test_parse_projected_points_keeps_zero_but_drops_missing():
    raw = {"p1": {"pts_ppr": 0.0}, "p2": {"pts_ppr": 210.4}, "p3": {}}
    assert parse_projected_points(raw, field="pts_ppr") == {"p1": 0.0, "p2": 210.4}


def test_booleans_are_rejected_not_coerced():
    """bool is a subclass of int, so an unguarded float() turns True into a
    1.0 ADP — the single most valuable pick in the draft — and False into a
    0.0 projection. Both read as real figures, neither is data."""
    raw = {"p1": {"adp_ppr": True}, "p2": {"adp_ppr": False}, "p3": {"adp_ppr": 4.0}}
    assert parse_adp(raw, field="adp_ppr") == {"p3": 4.0}
    proj = {"p1": {"pts_ppr": True}, "p2": {"pts_ppr": 12.0}}
    assert parse_projected_points(proj, field="pts_ppr") == {"p2": 12.0}


def test_parse_all_adp_covers_every_variant_and_drops_empties():
    """One daily snapshot has to serve every league's scoring, so the parse
    is per-variant. An empty variant is dropped: downstream, empty is
    indistinguishable from a failed fetch."""
    raw = {
        "p1": {"adp_ppr": 10.0, "adp_half_ppr": 11.0, "adp_std": 12.0,
               "adp_2qb": 4.0},
        "p2": {"adp_ppr": 20.0, "adp_2qb": ADP_UNDRAFTED},
    }
    assert parse_all_adp(raw) == {
        "adp_ppr": {"p1": 10.0, "p2": 20.0},
        "adp_half_ppr": {"p1": 11.0},
        "adp_std": {"p1": 12.0},
        "adp_2qb": {"p1": 4.0},
    }
    assert parse_all_adp({"p1": {"pts_ppr": 5.0}}) == {}


# --- deltas ---

def test_positive_delta_means_taken_later_than_the_market_had_him():
    assert adp_delta(pick_no=30, adp=12.0) == pytest.approx(18.0)


def test_negative_delta_means_reached():
    assert adp_delta(pick_no=5, adp=40.0) == pytest.approx(-35.0)


def test_delta_is_none_without_an_adp():
    assert adp_delta(pick_no=30, adp=None) is None


# --- per-owner rollup ---

def test_owner_grade_sums_matched_picks_and_reports_coverage():
    rows = [
        {"drafter_id": "u1", "adp_delta": 10.0},
        {"drafter_id": "u1", "adp_delta": -4.0},
        {"drafter_id": "u1", "adp_delta": None},
        {"drafter_id": "u2", "adp_delta": 2.0},
    ]
    out = owner_adp_grades(rows)
    assert out["u1"]["total_delta"] == pytest.approx(6.0)
    assert out["u1"]["graded_picks"] == 2
    assert out["u1"]["total_picks"] == 3
    assert out["u2"]["graded_picks"] == 1


def test_owner_with_no_matched_picks_reports_zero_coverage_not_a_score():
    """A team of kickers and defenses is not a zero-value draft; it is an
    ungraded one. Reporting 0.0 would read as average."""
    out = owner_adp_grades([{"drafter_id": "u1", "adp_delta": None}])
    assert out["u1"]["graded_picks"] == 0
    assert out["u1"]["total_delta"] is None


def test_keeper_rows_are_excluded_from_the_owner_grade():
    rows = [
        {"drafter_id": "u1", "adp_delta": 50.0, "is_keeper": True},
        {"drafter_id": "u1", "adp_delta": 5.0},
    ]
    out = owner_adp_grades(rows)
    assert out["u1"]["total_delta"] == pytest.approx(5.0)
    assert out["u1"]["graded_picks"] == 1
