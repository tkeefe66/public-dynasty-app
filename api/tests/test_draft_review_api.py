from app.models.league import DashboardResp, DraftReview
from app.services.aggregations import _draft_review

from tests.helpers import minimal_chain_cache_entry


def _entry(picks):
    return minimal_chain_cache_entry(
        league_id="L1",
        drafted_picks=picks,
        owners={"u1": {"owner_name": "Alice"}, "u2": {"owner_name": "Bob"}},
    )


def _pick(rnd, slot, production, drafter="u1", season=2025, baseline_delta=None):
    return {
        "player_id": f"p{rnd}{slot}", "full_name": f"Player {rnd}.{slot:02d}",
        "position": "RB", "drafter_id": drafter, "round": rnd, "slot": slot,
        "picks_in_round": 12, "draft_season": season,
        "production_total": production, "baseline_delta": baseline_delta,
    }


PICKS = [_pick(1, 1, 10.0, "u1"), _pick(1, 2, 50.0, "u2"), _pick(2, 1, 900.0, "u2")]


def test_dashboard_resp_carries_draft_review():
    assert "draft_review" in DashboardResp.model_fields


def test_draft_review_defaults_to_none():
    """A response built without one must not imply a draft happened."""
    assert DashboardResp.model_fields["draft_review"].default is None


def test_built_only_during_the_draft_window():
    """Year-round it would put a ranking pass on every dashboard response for
    a block nothing renders."""
    for phase in ("regular", "post", "offseason"):
        assert _draft_review(_entry(PICKS), phase) is None


def test_built_during_the_draft_window():
    review = _draft_review(_entry(PICKS), "draft")
    assert isinstance(review, DraftReview)
    assert review.season == 2025
    assert review.total == 3


def test_attaches_owner_refs_to_both_picks():
    review = _draft_review(_entry(PICKS), "draft")
    assert review.best.owner is not None
    assert review.best.owner.owner_name == "Bob"
    assert review.worst.owner.owner_name == "Alice"


def test_pre_feature_cache_has_no_review():
    """An entry graded before drafted_picks existed must not 500 the dashboard."""
    assert _draft_review(minimal_chain_cache_entry(league_id="L1"), "draft") is None


def test_an_unplayed_class_returns_ungraded_results():
    """Right after a draft everything is 0.0 — naming a best pick would be
    fabricating one out of ties. But the results (who took whom) are real
    the moment the draft completes, so the review still comes back with
    graded=False and null best/worst rather than disappearing entirely."""
    fresh = [_pick(1, s, 0.0) for s in range(1, 13)]
    review = _draft_review(_entry(fresh), "draft")
    assert review is not None
    assert review.graded is False
    assert review.best is None
    assert review.worst is None
    assert review.total == 12


def test_an_unplayed_class_still_carries_the_market_preview():
    """No played game needed for value-vs-consensus, so it's set even while
    graded=False — the ungraded window's actual 'so what'."""
    fresh = [
        _pick(1, 1, 0.0, "u1", baseline_delta=-6.0),
        _pick(1, 2, 0.0, "u2", baseline_delta=4.0),
    ]
    review = _draft_review(_entry(fresh), "draft")
    assert review.graded is False
    assert review.best_value.drafter_id == "u2"
    assert review.best_value.owner.owner_name == "Bob"
    assert review.best_value.baseline_delta == 4.0
    assert review.reach.drafter_id == "u1"
    assert review.reach.owner.owner_name == "Alice"
    assert review.matched == 2


def test_market_preview_falls_back_to_none_below_two_matches():
    fresh = [_pick(1, 1, 0.0, "u1", baseline_delta=-6.0), _pick(1, 2, 0.0, "u2")]
    review = _draft_review(_entry(fresh), "draft")
    assert review.best_value is None
    assert review.reach is None
    assert review.matched == 1
