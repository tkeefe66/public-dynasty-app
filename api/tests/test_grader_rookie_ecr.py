"""The fork: a dynasty class gets a rookie board where it used to get nothing.

These exercise the resolution + wiring seam directly rather than driving a full
GraderService.run (those tests take ~30s each because MagicMock clients fall
into real retry/backoff).
"""
from datetime import date

from app.services.rookie_board_store import RookieBoardStore
from sleeper_dynasty.engine.draft_class import build_draft_classes


def test_a_dynasty_rookie_class_is_not_axis_production():
    # This is WHY the ADP block skipped dynasty: the gate is `axis !=
    # "production"`. The fork must key on something else.
    classes = build_draft_classes(
        drafts_by_league={"lg": [{
            "draft_id": "d1", "season": 2025, "status": "complete",
            "type": "snake", "settings": {"player_type": 1, "teams": 12},
        }]},
        league_format="dynasty", origin_season=2023)
    assert len(classes) == 1
    assert classes[0].kind == "rookie"
    assert classes[0].axis == "blend"


def test_store_resolves_a_board_for_a_dynasty_rookie_class(tmp_path):
    store = RookieBoardStore(tmp_path)
    board = store.resolve_for_draft("d1", date(2025, 5, 16))
    assert board is not None, "committed history must cover a May 2025 draft"
    assert len(board) > 50


def test_resolution_is_bounded_by_the_draft_date(tmp_path):
    store = RookieBoardStore(tmp_path)
    early = store.resolve_for_draft("d-early", date(2025, 5, 16))
    late = store.resolve_for_draft("d-late", date(2026, 5, 6))
    assert early is not None and late is not None
    assert early != late, "two drafts a year apart must face different boards"
