from sleeper_dynasty.engine.draft_results import build_drafted_pick_results
from sleeper_dynasty.engine.draft_signals import DraftedPick

PICK = DraftedPick(
    draft_id="d1", round=1, slot=4, picks_in_round=12, player_id="111",
    drafter_id="u1", draft_season=2025, pick_no=4, draft_kind="rookie",
    is_keeper=False, gradeable=True)

# phase -> points, so the test can assert each lands in its own key.
BY_PHASE = {"total": 100.0, "started": 60.0, "regular": 10.0,
            "playoff": 20.0, "toilet": 0.0}


def _build():
    return build_drafted_pick_results(
        [PICK], ktc_floats={}, normalized_name_by_pid={}, names={}, positions={},
        extremes_by_name={}, acquired_set=set(),
        points_fn=lambda pid, uid, phase: BY_PHASE[phase],
        games_fn=lambda pid, uid: 3, current_holders={}, traded_away_set=set())


def test_production_started_is_emitted():
    assert _build()[0]["production_started"] == 60.0


def test_the_other_four_metrics_are_unchanged():
    row = _build()[0]
    assert row["production_total"] == 100.0
    assert row["production_regular"] == 10.0
    assert row["production_playoff"] == 20.0
    assert row["production_toilet"] == 0.0


def test_started_is_requested_with_its_own_phase_name():
    seen = []

    def spy(pid, uid, phase):
        seen.append(phase)
        return BY_PHASE[phase]

    build_drafted_pick_results(
        [PICK], ktc_floats={}, normalized_name_by_pid={}, names={}, positions={},
        extremes_by_name={}, acquired_set=set(), points_fn=spy,
        games_fn=lambda pid, uid: 0, current_holders={}, traded_away_set=set())
    assert "started" in seen
