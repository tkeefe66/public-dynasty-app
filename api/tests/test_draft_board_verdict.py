from app.services.draft_board_view import build_draft_board
from tests.helpers import minimal_chain_cache_entry


def pick(**over):
    r = dict(player_id="p1", full_name="A Rookie", position="RB", drafter_id="u1",
             round=1, slot=1, picks_in_round=12, pick_no=1, draft_season=2025,
             production_total=200.0, verdict="hit")
    r.update(over)
    return r


def _board(*picks):
    return build_draft_board(
        minimal_chain_cache_entry(drafted_picks=list(picks)), season=2025)


def test_verdict_reaches_the_response():
    assert _board(pick(), pick(player_id="p2", pick_no=2)).picks[0].verdict == "hit"


def test_a_pre_feature_row_has_an_empty_verdict_not_a_guess():
    b = _board({"player_id": "p1", "full_name": "X", "position": "RB",
                "drafter_id": "u1", "round": 1, "slot": 1, "picks_in_round": 12,
                "pick_no": 1, "draft_season": 2025, "production_total": 0.0},
               {"player_id": "p2", "full_name": "Y", "position": "WR",
                "drafter_id": "u2", "round": 1, "slot": 2, "picks_in_round": 12,
                "pick_no": 2, "draft_season": 2025, "production_total": 0.0})
    assert b.picks[0].verdict == ""


def test_the_board_reports_whether_any_pick_carries_a_verdict():
    # The column is dropped entirely when nothing can be judged — a header over
    # a column of dashes is worse than no column.
    assert _board(pick(), pick(player_id="p2", pick_no=2)).has_verdicts is True
    assert _board(pick(verdict=""), pick(player_id="p2", pick_no=2, verdict="")).has_verdicts is False
