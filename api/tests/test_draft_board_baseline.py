from app.services.draft_board_view import build_draft_board
from tests.helpers import minimal_chain_cache_entry


def _entry(**pick_over):
    pick = dict(player_id="111", full_name="A Rookie", position="RB",
                drafter_id="u1", round=1, slot=4, picks_in_round=12,
                pick_no=4, draft_season=2025, production_total=0.0)
    pick.update(pick_over)
    return minimal_chain_cache_entry(drafted_picks=[pick, {**pick,
                                                          "player_id": "222",
                                                          "pick_no": 5}])


def test_baseline_fields_reach_the_response():
    board = build_draft_board(
        _entry(baseline=1.5, baseline_delta=2.5, baseline_source="rookie_ecr"),
        season=2025)
    assert board.picks[0].baseline == 1.5
    assert board.picks[0].baseline_delta == 2.5
    assert board.picks[0].baseline_source == "rookie_ecr"


def test_label_names_the_baseline_the_class_actually_has():
    ecr = build_draft_board(_entry(baseline=1.5, baseline_source="rookie_ecr"),
                            season=2025)
    assert ecr.baseline_label == "ECR"
    adp = build_draft_board(_entry(baseline=9.0, baseline_source="sleeper_adp"),
                            season=2025)
    assert adp.baseline_label == "ADP"


def test_label_is_empty_when_no_pick_carries_a_baseline():
    # A class with no baseline must not claim one. The UI drops the columns.
    board = build_draft_board(_entry(), season=2025)
    assert board.baseline_label == ""


def test_pre_feature_rows_default_rather_than_raise():
    # Rows written before this feature carry none of the three keys.
    board = build_draft_board(_entry(), season=2025)
    assert board.picks[0].baseline is None
    assert board.picks[0].baseline_source == ""
