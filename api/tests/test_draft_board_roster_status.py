from app.services.draft_board_view import build_draft_board
from tests.helpers import minimal_chain_cache_entry


def pick(**over):
    r = dict(player_id="p1", full_name="A Rookie", position="RB", drafter_id="u1",
             round=1, slot=1, picks_in_round=12, pick_no=1, draft_season=2025,
             production_total=200.0, roster_status="traded")
    r.update(over)
    return r


def _board(*picks):
    return build_draft_board(
        minimal_chain_cache_entry(drafted_picks=list(picks)), season=2025)


def test_roster_status_reaches_the_response():
    # `roster_status` is already computed on the persisted pick row
    # (`derive_roster_status` in `draft_results.py`) — this is the same
    # already-computed-just-not-projected read `verdict` gets.
    assert _board(pick(), pick(player_id="p2", pick_no=2)).picks[0].roster_status == "traded"


def test_a_pre_feature_row_defaults_to_rostered_not_a_guess():
    # No `roster_status` key at all on the raw row (pre-feature cache) reads
    # back as the model's own neutral default, matching
    # `DraftPickResult.roster_status`'s default on the owner page.
    b = _board({"player_id": "p1", "full_name": "X", "position": "RB",
                "drafter_id": "u1", "round": 1, "slot": 1, "picks_in_round": 12,
                "pick_no": 1, "draft_season": 2025, "production_total": 0.0})
    assert b.picks[0].roster_status == "rostered"


def test_every_roster_status_value_reaches_the_response():
    b = _board(
        pick(roster_status="rostered"),
        pick(player_id="p2", pick_no=2, roster_status="dropped"),
        pick(player_id="p3", pick_no=3, roster_status="traded"),
    )
    assert [p.roster_status for p in b.picks] == ["rostered", "dropped", "traded"]
