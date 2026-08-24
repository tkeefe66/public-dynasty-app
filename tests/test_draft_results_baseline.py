from sleeper_dynasty.engine.draft_results import build_drafted_pick_results
from sleeper_dynasty.engine.draft_signals import DraftedPick


def _pick(**over) -> DraftedPick:
    base = dict(draft_id="d1", round=1, slot=4, picks_in_round=12,
                player_id="111", drafter_id="u1", draft_season=2025, pick_no=4,
                draft_kind="rookie", is_keeper=False, gradeable=True)
    base.update(over)
    return DraftedPick(**base)


def _build(picks, **kw):
    return build_drafted_pick_results(
        picks, ktc_floats={}, normalized_name_by_pid={}, names={},
        positions={}, extremes_by_name={}, acquired_set=set(),
        points_fn=lambda p, u, ph: 0.0, games_fn=lambda p, u: 0,
        current_holders={}, traded_away_set=set(), **kw)


def test_rookie_ecr_populates_baseline_and_names_its_source():
    rows = _build([_pick()], rookie_ecr_by_draft={"d1": {"111": 1.5}})
    assert rows[0]["baseline"] == 1.5
    assert rows[0]["baseline_delta"] == 2.5     # pick 4 taken at consensus 1.5
    assert rows[0]["baseline_source"] == "rookie_ecr"


def test_sleeper_adp_fills_the_baseline_when_there_is_no_rookie_board():
    rows = _build([_pick()], adp_by_draft={"d1": {"111": 9.0}})
    assert rows[0]["baseline"] == 9.0
    assert rows[0]["baseline_delta"] == -5.0    # pick 4 on a 9.0 board = reach
    assert rows[0]["baseline_source"] == "sleeper_adp"


def test_rookie_ecr_wins_when_both_are_present():
    # A dynasty rookie class must never be graded against overall-NFL ADP.
    rows = _build([_pick()],
                  adp_by_draft={"d1": {"111": 9.0}},
                  rookie_ecr_by_draft={"d1": {"111": 1.5}})
    assert rows[0]["baseline_source"] == "rookie_ecr"
    assert rows[0]["baseline"] == 1.5


def test_adp_fields_keep_their_existing_meaning():
    # adp/adp_delta must stay Sleeper ADP. Repointing them is a shape change.
    rows = _build([_pick()],
                  adp_by_draft={"d1": {"111": 9.0}},
                  rookie_ecr_by_draft={"d1": {"111": 1.5}})
    assert rows[0]["adp"] == 9.0
    assert rows[0]["adp_delta"] == -5.0


def test_unranked_pick_is_null_not_zero():
    rows = _build([_pick()], rookie_ecr_by_draft={"d1": {"999": 1.5}})
    assert rows[0]["baseline"] is None
    assert rows[0]["baseline_delta"] is None
    assert rows[0]["baseline_source"] == ""


def test_an_ungradeable_pick_gets_no_baseline():
    # An auction pick_no is the order money changed hands, so a slot delta
    # against it is noise.
    rows = _build([_pick(gradeable=False)],
                  rookie_ecr_by_draft={"d1": {"111": 1.5}})
    assert rows[0]["baseline"] is None
    assert rows[0]["baseline_source"] == ""


def test_baselines_are_keyed_per_draft_not_flattened():
    # A player drafted in two seasons must grade against each season's own
    # market, not whichever class was read last.
    picks = [_pick(), _pick(draft_id="d2", draft_season=2026, pick_no=20)]
    rows = _build(picks, rookie_ecr_by_draft={"d1": {"111": 1.5}, "d2": {"111": 30.0}})
    assert rows[0]["baseline"] == 1.5
    assert rows[1]["baseline"] == 30.0
