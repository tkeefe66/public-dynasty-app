from sleeper_dynasty.engine.draft_results import build_draft_review


def _pick(
    rnd, slot, production, *, drafter="u1", name=None, season=2025, teams=12,
    baseline_delta=None, baseline_source="", projected_points=None,
):
    return {
        "player_id": f"p{rnd}{slot}",
        "full_name": name or f"Player {rnd}.{slot:02d}",
        "position": "RB",
        "drafter_id": drafter,
        "round": rnd,
        "slot": slot,
        "picks_in_round": teams,
        "draft_season": season,
        "production_total": production,
        "baseline_delta": baseline_delta,
        "baseline_source": baseline_source,
        "projected_points": projected_points,
    }


def test_no_picks_is_no_review():
    assert build_draft_review([]) is None


def test_a_draft_nobody_has_played_yet_returns_ungraded_results():
    """Right after a draft every pick is at 0. Ranking those would name a
    'best pick' out of ties, which is fabricated — but the results (who took
    whom) are real the moment the draft completes, so the class still comes
    back, just ungraded."""
    picks = [_pick(1, s, 0.0) for s in range(1, 13)]
    review = build_draft_review(picks)
    assert review is not None
    assert review["graded"] is False
    assert review["best"] is None
    assert review["worst"] is None
    assert review["total"] == 12


def test_uses_the_most_recent_draft_season():
    picks = [
        _pick(1, 1, 500.0, season=2024),
        _pick(1, 1, 100.0, season=2025),
        _pick(1, 2, 200.0, season=2025),
    ]
    review = build_draft_review(picks)
    assert review["season"] == 2025
    assert review["total"] == 2


def test_best_pick_is_the_one_that_most_outproduced_its_slot():
    """A late pick that produced like an early one. Rank-vs-position, so no
    external slot baseline is needed — the draft grades itself."""
    picks = [
        _pick(1, 1, 10.0, name="Bust"),      # position 1, production rank 3
        _pick(1, 2, 50.0, name="Fine"),      # position 2, production rank 2
        _pick(2, 1, 900.0, name="Steal"),    # position 13, production rank 1
    ]
    review = build_draft_review(picks)
    assert review["best"]["full_name"] == "Steal"
    assert review["best"]["round"] == 2
    assert review["best"]["slot"] == 1
    # taken 13th, produced 1st
    assert review["best"]["slot_delta"] == 12


def test_worst_pick_is_the_one_that_most_undershot_its_slot():
    picks = [
        _pick(1, 1, 10.0, name="Bust"),
        _pick(1, 2, 50.0, name="Fine"),
        _pick(2, 1, 900.0, name="Steal"),
    ]
    review = build_draft_review(picks)
    assert review["worst"]["full_name"] == "Bust"
    # taken 1st, produced 3rd
    assert review["worst"]["slot_delta"] == -2


def test_beat_slot_counts_picks_that_outproduced_their_position():
    picks = [
        _pick(1, 1, 10.0),
        _pick(1, 2, 50.0),
        _pick(2, 1, 900.0),
    ]
    review = build_draft_review(picks)
    # Only "Steal" finished ahead of where it was taken.
    assert review["beat_slot"] == 1
    assert review["total"] == 3


def test_draft_position_spans_rounds():
    """Round 2 slot 1 is the 13th pick in a 12-team league, not the 1st."""
    picks = [_pick(1, 12, 5.0), _pick(2, 1, 900.0)]
    review = build_draft_review(picks)
    assert review["best"]["draft_position"] == 13


def test_carries_the_drafting_owner_id():
    picks = [_pick(1, 1, 10.0, drafter="alice"), _pick(2, 1, 900.0, drafter="bob")]
    review = build_draft_review(picks)
    assert review["best"]["drafter_id"] == "bob"
    assert review["worst"]["drafter_id"] == "alice"


def test_ties_resolve_deterministically():
    """Two picks with the same slot_delta must not flip between runs."""
    picks = [_pick(1, 1, 100.0), _pick(1, 2, 100.0), _pick(1, 3, 100.0)]
    first = build_draft_review(picks)
    for _ in range(5):
        assert build_draft_review(picks) == first


def test_a_single_pick_draft_is_not_reviewed():
    """One pick cannot out- or under-perform a field of one."""
    assert build_draft_review([_pick(1, 1, 500.0)]) is None


# --- Shown, not scored ------------------------------------------------------

def test_keepers_are_not_scored():
    """A keep is not a draft decision. Left in the field it could win 'best
    pick', pad 'N of M beat their slot', and shift the production ranking
    every real pick is measured against."""
    picks = [
        _pick(1, 1, 10.0, name="Real A"),
        _pick(1, 2, 20.0, name="Real B"),
        {**_pick(1, 3, 900.0, name="Kept Star"), "is_keeper": True},
    ]
    review = build_draft_review(picks)
    assert review["total"] == 2
    assert review["best"]["full_name"] != "Kept Star"
    assert review["worst"]["full_name"] != "Kept Star"


def test_auction_picks_are_not_scored():
    """An auction's pick_no is the order money changed hands, so a slot
    delta against it is noise — the same reason draft_skill drops them."""
    picks = [
        _pick(1, 1, 10.0, name="A"),
        _pick(1, 2, 20.0, name="B"),
        {**_pick(1, 3, 900.0, name="Auction Steal"), "gradeable": False},
    ]
    review = build_draft_review(picks)
    assert review["total"] == 2
    assert review["best"]["full_name"] != "Auction Steal"


def test_a_class_with_fewer_than_two_scored_picks_reports_results_ungraded():
    """One scorable pick cannot be ranked against anything, so there is no
    grade — but three picks were still made, and saying so beats falling
    through to trade-of-the-week and hiding the board link.

    `total` is every pick made (3), not the scorable subset: "N picks" means
    the draft. Only the graded denominator narrows to scored picks.
    """
    picks = [
        _pick(1, 1, 10.0),
        {**_pick(1, 2, 20.0), "is_keeper": True},
        {**_pick(1, 3, 30.0), "gradeable": False},
    ]
    review = build_draft_review(picks)
    assert review is not None
    assert review["graded"] is False
    assert review["best"] is None and review["worst"] is None
    assert review["total"] == 3


def test_a_season_with_fewer_than_two_picks_at_all_is_not_reviewed():
    """None is now reserved for a class there is nothing to say about."""
    assert build_draft_review([_pick(1, 1, 10.0)]) is None
    assert build_draft_review([]) is None


def test_rows_without_a_gradeable_key_still_score():
    """Pre-feature rows predate auction support and were all snake/linear —
    a missing key must not silently empty the field."""
    picks = [_pick(1, 1, 10.0), _pick(1, 2, 900.0)]
    assert all("gradeable" not in p for p in picks)
    assert build_draft_review(picks)["total"] == 2


# --- Market preview (best value / reach vs ECR/ADP) -------------------------
# Independent of production, so it's real the moment the draft ends — the
# ungraded window's "so what", read off the same baseline_delta the draft
# board already prices per pick (positive = fell past consensus = value;
# negative = a reach).

def test_ungraded_draft_still_surfaces_best_value_and_reach():
    picks = [
        _pick(1, 1, 0.0, name="Reacher", drafter="alice", baseline_delta=-8.0),
        _pick(1, 2, 0.0, name="Chalk", drafter="bob", baseline_delta=0.0),
        _pick(1, 3, 0.0, name="Faller", drafter="carol", baseline_delta=6.0),
    ]
    review = build_draft_review(picks)
    assert review["graded"] is False
    assert review["best_value"]["full_name"] == "Faller"
    assert review["best_value"]["baseline_delta"] == 6.0
    assert review["best_value"]["drafter_id"] == "carol"
    assert review["reach"]["full_name"] == "Reacher"
    assert review["reach"]["baseline_delta"] == -8.0
    assert review["reach"]["drafter_id"] == "alice"
    assert review["matched"] == 3


def test_market_preview_needs_at_least_two_baseline_matches():
    """One matched pick can't be called a steal or a reach relative to
    anything — same 'nothing to compare against' rule as the production
    grade."""
    picks = [
        _pick(1, 1, 0.0, baseline_delta=5.0),
        _pick(1, 2, 0.0, baseline_delta=None),
        _pick(1, 3, 0.0, baseline_delta=None),
    ]
    review = build_draft_review(picks)
    assert review["best_value"] is None
    assert review["reach"] is None
    assert review["matched"] == 1


def test_market_preview_excludes_keepers_and_auction_picks():
    picks = [
        _pick(1, 1, 0.0, name="Real A", baseline_delta=2.0),
        _pick(1, 2, 0.0, name="Real B", baseline_delta=-2.0),
        {**_pick(1, 3, 0.0, name="Kept Star", baseline_delta=50.0), "is_keeper": True},
        {**_pick(1, 4, 0.0, name="Auction Steal", baseline_delta=50.0), "gradeable": False},
    ]
    review = build_draft_review(picks)
    assert review["matched"] == 2
    assert review["best_value"]["full_name"] == "Real A"
    assert review["reach"]["full_name"] == "Real B"


def test_market_preview_ties_broken_by_projected_points_then_draft_order():
    picks = [
        _pick(1, 1, 0.0, name="Early", baseline_delta=4.0, projected_points=100.0),
        _pick(1, 2, 0.0, name="Bigger Upside", baseline_delta=4.0, projected_points=150.0),
    ]
    review = build_draft_review(picks)
    assert review["best_value"]["full_name"] == "Bigger Upside"


def test_market_preview_is_present_once_the_class_is_graded_too():
    """Real production is the stronger story once it exists, but the market
    read stays true and available — the lead just doesn't lead with it."""
    picks = [
        _pick(1, 1, 10.0, name="Bust", baseline_delta=-3.0),
        _pick(1, 2, 50.0, name="Fine", baseline_delta=1.0),
        _pick(2, 1, 900.0, name="Steal", baseline_delta=9.0),
    ]
    review = build_draft_review(picks)
    assert review["graded"] is True
    assert review["best_value"]["full_name"] == "Steal"
    assert review["reach"]["full_name"] == "Bust"
    assert review["matched"] == 3
