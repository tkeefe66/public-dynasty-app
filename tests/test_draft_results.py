from sleeper_dynasty.engine.draft_results import started_points_while_on_roster, build_drafted_pick_results, build_draft_review
from sleeper_dynasty.engine.draft_signals import DraftedPick


def _matchups():
    # (league_id, week, roster_id) -> entry. Player "p1" on roster 1 (owner "U").
    return {
        ("L", 1, 1): {"starters": ["p1"], "players": ["p1"], "players_points": {"p1": 10.0}},
        ("L", 2, 1): {"starters": ["p1"], "players": ["p1"], "players_points": {"p1": 12.0}},
        # week 15 = playoff phase, p1 started:
        ("L", 15, 1): {"starters": ["p1"], "players": ["p1"], "players_points": {"p1": 20.0}},
        # week 16 = toilet phase, p1 started:
        ("L", 16, 1): {"starters": ["p1"], "players": ["p1"], "players_points": {"p1": 7.0}},
        # p1 on a DIFFERENT roster (owner sold him) — must not count:
        ("L", 3, 2): {"starters": ["p1"], "players": ["p1"], "players_points": {"p1": 99.0}},
        # p1 benched (not in starters) — counts for total, not for started tally:
        ("L", 4, 1): {"starters": [], "players": ["p1"], "players_points": {"p1": 8.0}},
    }


_R2U = {"L": {1: "U", 2: "OTHER"}}
_PWS = {"L": 15}
_PHASE = {("L", 15, 1): "playoff", ("L", 16, 1): "toilet"}


def test_regular_started_points_while_on_roster():
    pts = started_points_while_on_roster(
        "p1", "U", phase="regular", matchups=_matchups(),
        roster_to_user_by_league=_R2U,
        phase_by_lwr=_PHASE, playoff_week_start_by_league=_PWS)
    assert pts == 22.0  # weeks 1+2; not the sold-away 99, not the benched 8, not playoff


def test_playoff_started_points_while_on_roster():
    pts = started_points_while_on_roster(
        "p1", "U", phase="playoff", matchups=_matchups(),
        roster_to_user_by_league=_R2U,
        phase_by_lwr=_PHASE, playoff_week_start_by_league=_PWS)
    assert pts == 20.0  # week 15 only


def test_toilet_started_points_while_on_roster():
    pts = started_points_while_on_roster(
        "p1", "U", phase="toilet", matchups=_matchups(),
        roster_to_user_by_league=_R2U,
        phase_by_lwr=_PHASE, playoff_week_start_by_league=_PWS)
    assert pts == 7.0  # week 16 only (losers bracket)


def test_total_points_while_on_roster_includes_bench_all_phases():
    pts = started_points_while_on_roster(
        "p1", "U", phase="total", matchups=_matchups(),
        roster_to_user_by_league=_R2U,
        phase_by_lwr=_PHASE, playoff_week_start_by_league=_PWS)
    # weeks 1+2+15+16 started AND week 4 benched (8.0); never the sold-away 99.
    assert pts == 10.0 + 12.0 + 20.0 + 7.0 + 8.0


def test_points_zero_for_owner_who_never_started_him():
    # "Z" owns no roster in the mapping, so no week is gated to them -> 0.
    # (Owner-gating against a rival who DID start the player is covered by the
    # regular/playoff tests above, which correctly exclude roster 2's week-3 99.)
    pts = started_points_while_on_roster(
        "p1", "Z", phase="regular", matchups=_matchups(),
        roster_to_user_by_league=_R2U,
        phase_by_lwr=_PHASE, playoff_week_start_by_league=_PWS)
    assert pts == 0.0


def _pick(pid, drafter, rnd, slot, season=2025):
    return DraftedPick(draft_id="d", round=rnd, slot=slot, picks_in_round=12,
                       player_id=pid, drafter_id=drafter, draft_season=season)


def test_build_results_career_arc_and_avg_slot():
    picks = [
        _pick("p1", "U", rnd=1, slot=1),
        _pick("p2", "V", rnd=1, slot=2),
    ]
    rows = build_drafted_pick_results(
        picks,
        ktc_floats={"p1": 5000.0, "p2": 3000.0},
        normalized_name_by_pid={"p1": "aida", "p2": "bo"},
        names={"p1": "Aida", "p2": "Bo"},
        positions={"p1": "WR", "p2": "RB"},
        extremes_by_name={"aida": (3000.0, 6000.0)},  # p2 has no history
        acquired_set={("V", "p2")},                    # V got p2 via trade
        points_fn=lambda pid, uid, phase: {
            ("p1", "regular"): 100.0, ("p2", "regular"): 50.0,
            ("p1", "total"): 220.0, ("p2", "total"): 50.0,
            ("p1", "toilet"): 13.0,
        }.get((pid, phase), 0.0),
        games_fn=lambda pid, uid: 0,
        current_holders={},
        traded_away_set=set(),
    )
    by_pid = {r["player_id"]: r for r in rows}
    p1 = by_pid["p1"]
    assert p1["current_value"] == 5000.0
    assert p1["lowest_value"] == 3000.0
    assert p1["highest_value"] == 6000.0
    # round avg = (5000 + 3000) / 2 = 4000; p1 delta = +1000
    assert p1["avg_slot_value"] == 4000.0
    assert p1["acquired_via_trade"] is False
    assert p1["production_total"] == 220.0
    assert p1["production_regular"] == 100.0
    assert p1["production_playoff"] == 0.0
    assert p1["production_toilet"] == 13.0
    p2 = by_pid["p2"]
    # no snapshot history -> low=high=current
    assert p2["lowest_value"] == 3000.0
    assert p2["highest_value"] == 3000.0
    assert p2["acquired_via_trade"] is True


def test_build_results_folds_current_into_extremes():
    # current below the snapshot low, or above the high -> extremes widen to include it
    picks = [_pick("p1", "U", rnd=1, slot=1)]
    rows = build_drafted_pick_results(
        picks, ktc_floats={"p1": 2000.0},
        normalized_name_by_pid={"p1": "aida"}, names={"p1": "Aida"},
        positions={"p1": "WR"}, extremes_by_name={"aida": (3000.0, 6000.0)},
        acquired_set=set(), points_fn=lambda pid, uid, phase: 0.0,
        games_fn=lambda pid, uid: 0, current_holders={}, traded_away_set=set())
    assert rows[0]["lowest_value"] == 2000.0   # current 2000 < snapshot low 3000
    assert rows[0]["highest_value"] == 6000.0


def test_started_games_while_on_roster_counts_starts_owner_gated():
    from sleeper_dynasty.engine.draft_results import started_games_while_on_roster
    n = started_games_while_on_roster(
        "p1", "U", matchups=_matchups(), roster_to_user_by_league=_R2U)
    # weeks 1, 2, 15, 16 started for U; week 4 benched (not counted);
    # week 3 was on roster 2 / OTHER (not counted).
    assert n == 4


def test_started_games_zero_for_owner_who_never_started_him():
    from sleeper_dynasty.engine.draft_results import started_games_while_on_roster
    n = started_games_while_on_roster(
        "p1", "Z", matchups=_matchups(), roster_to_user_by_league=_R2U)
    assert n == 0


def test_derive_roster_status():
    from sleeper_dynasty.engine.draft_results import derive_roster_status
    # still on the drafting owner's roster
    assert derive_roster_status(
        "p1", "U", current_holders={"p1": "U"}, traded_away_set=set()) == "rostered"
    # gone, and U traded him away
    assert derive_roster_status(
        "p1", "U", current_holders={"p1": "V"},
        traded_away_set={("U", "p1")}) == "traded"
    # gone, U did not trade him (dropped / waiver), now unowned
    assert derive_roster_status(
        "p1", "U", current_holders={}, traded_away_set=set()) == "dropped"
    # gone, U did not trade him, picked up by V -> dropped from U's view
    assert derive_roster_status(
        "p1", "U", current_holders={"p1": "V"}, traded_away_set=set()) == "dropped"


def test_build_results_includes_games_started_and_roster_status():
    picks = [
        _pick("p1", "U", rnd=1, slot=1),
        _pick("p2", "V", rnd=1, slot=2),
    ]
    rows = build_drafted_pick_results(
        picks,
        ktc_floats={"p1": 5000.0, "p2": 3000.0},
        normalized_name_by_pid={"p1": "aida", "p2": "bo"},
        names={"p1": "Aida", "p2": "Bo"},
        positions={"p1": "WR", "p2": "RB"},
        extremes_by_name={},
        acquired_set=set(),
        points_fn=lambda pid, uid, phase: 0.0,
        games_fn=lambda pid, uid: {("p1", "U"): 7, ("p2", "V"): 0}.get((pid, uid), 0),
        current_holders={"p1": "U"},                 # p1 still rostered by U
        traded_away_set={("V", "p2")},               # V traded p2 away
    )
    by_pid = {r["player_id"]: r for r in rows}
    assert by_pid["p1"]["games_started"] == 7
    assert by_pid["p1"]["roster_status"] == "rostered"
    assert by_pid["p2"]["games_started"] == 0
    assert by_pid["p2"]["roster_status"] == "traded"


def _review_pick(pid, uid, rnd, slot, prod, *, season=2026, teams=12):
    return {
        "player_id": pid, "full_name": pid.upper(), "position": "RB",
        "drafter_id": uid, "round": rnd, "slot": slot, "picks_in_round": teams,
        "draft_season": season, "production_total": prod,
    }


def test_a_class_with_no_production_returns_results_not_none():
    """Draft night: every pick sits at 0.0. The board must still render who
    took whom — refusing to show a hollow grade is right, refusing to show the
    results is just an empty screen."""
    picks = [_review_pick("p1", "u1", 1, 1, 0.0), _review_pick("p2", "u2", 1, 2, 0.0)]
    review = build_draft_review(picks)
    assert review is not None
    assert review["graded"] is False
    assert review["best"] is None
    assert review["worst"] is None
    assert review["total"] == 2
    assert review["beat_slot"] == 0


def test_a_played_class_grades_normally():
    picks = [_review_pick("p1", "u1", 1, 1, 10.0), _review_pick("p2", "u2", 1, 2, 300.0)]
    review = build_draft_review(picks)
    assert review["graded"] is True
    assert review["best"]["player_id"] == "p2"
    assert review["best"]["slot_delta"] == 1
    assert review["worst"]["player_id"] == "p1"


def test_only_the_latest_season_is_reviewed():
    picks = [
        _review_pick("old", "u1", 1, 1, 500.0, season=2025),
        _review_pick("a", "u1", 1, 1, 10.0), _review_pick("b", "u2", 1, 2, 20.0),
    ]
    review = build_draft_review(picks)
    assert review["season"] == 2026
    assert review["total"] == 2


def test_fewer_than_two_picks_is_unreviewable():
    assert build_draft_review([_review_pick("p1", "u1", 1, 1, 50.0)]) is None
    assert build_draft_review([]) is None


def test_overall_position_spans_rounds():
    picks = [_review_pick("p1", "u1", 2, 1, 300.0), _review_pick("p2", "u2", 1, 1, 10.0)]
    review = build_draft_review(picks)
    # Round 2 slot 1 is the 13th pick; ranking 1st beats that slot by 12.
    assert review["best"]["draft_position"] == 13
    assert review["best"]["slot_delta"] == 12


# --- an all-keeper / all-auction class still reports its results -------------

def _row(pid, uid, pick_no, *, prod=0.0, keeper=False, gradeable=True, season=2026):
    return {
        "player_id": pid, "full_name": pid.upper(), "position": "RB",
        "drafter_id": uid, "round": 1, "slot": pick_no, "picks_in_round": 12,
        "draft_season": season, "pick_no": pick_no, "production_total": prod,
        "is_keeper": keeper, "gradeable": gradeable,
    }


def test_all_auction_class_reports_results_rather_than_vanishing():
    """Auction picks can never be graded — pick_no is the order money changed
    hands. But the draft still happened, and "the class is in the books, N
    picks" is true and worth saying. Returning None sends the lead to
    trade-of-the-week and hides the board link, which is worse than saying
    less."""
    rows = [_row("p1", "u1", 1, gradeable=False), _row("p2", "u2", 2, gradeable=False)]
    review = build_draft_review(rows)
    assert review is not None
    assert review["graded"] is False
    assert review["best"] is None and review["worst"] is None
    assert review["total"] == 2


def test_all_keeper_class_reports_results_rather_than_vanishing():
    rows = [_row("p1", "u1", 1, keeper=True), _row("p2", "u2", 2, keeper=True)]
    review = build_draft_review(rows)
    assert review is not None and review["graded"] is False
    assert review["total"] == 2


def test_ungraded_total_counts_every_pick_made_not_just_scored_ones():
    """The ungraded lead prints "N picks". That N is the draft, so keepers and
    auction picks count — they were picks. Only the GRADED denominator is
    restricted to scored picks, because only those can beat a slot."""
    rows = [
        _row("p1", "u1", 1, keeper=True),
        _row("p2", "u2", 2),
        _row("p3", "u3", 3),
    ]
    review = build_draft_review(rows)
    assert review["graded"] is False
    assert review["total"] == 3


def test_graded_denominator_still_excludes_keepers_and_auction():
    rows = [
        _row("p1", "u1", 1, keeper=True, prod=999.0),
        _row("p2", "u2", 2, prod=100.0),
        _row("p3", "u3", 3, prod=10.0),
    ]
    review = build_draft_review(rows)
    assert review["graded"] is True
    assert review["total"] == 2                      # scored picks only
    assert review["best"]["player_id"] != "p1"       # the keeper cannot win


def test_a_single_pick_season_is_still_unreviewable():
    assert build_draft_review([_row("p1", "u1", 1)]) is None
    assert build_draft_review([]) is None
