from __future__ import annotations

from types import SimpleNamespace

from app.services.standings_snapshot_store import StandingsSnapshotStore
from app.services.trade_view import build_trade_detail


def _entry():
    rt = {
        "trade": {
            "transaction_id": "t1", "traded_at": "2024-10-01T00:00:00+00:00",
            "week": 4, "season": 2024, "league_id": "LG",
        },
        "sides": {
            "ua": {"received": [], "given": []},
            "ub": {"received": [], "given": []},
        },
    }
    return SimpleNamespace(
        league_id="ENTRY",
        resolved_trades=[rt],
        grades={"t1": {}},
        trade_stories={},
        became_grades={},
        current_holders={},
        league_name_by_id={"LG": "My League"},
        owners={"ua": {"owner_name": "A"}, "ub": {"owner_name": "B"}},
    )


def test_at_trade_standing_attached(tmp_path):
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    store.write("ENTRY", "2024-03", [
        {"owner_id": "ua", "roster_id": 1, "wins": 3, "losses": 0, "ties": 0,
         "points_for": 320.0, "points_against": 250.0, "rank": 1},
        {"owner_id": "ub", "roster_id": 2, "wins": 0, "losses": 3, "ties": 0,
         "points_for": 250.0, "points_against": 320.0, "rank": 2},
    ])
    detail = build_trade_detail(_entry(), "t1", standings_store=store)
    by_owner = {s.user_id: s for s in detail.sides}
    assert by_owner["ua"].at_trade_standing.rank == 1
    assert by_owner["ua"].at_trade_standing.wins == 3
    assert by_owner["ua"].at_trade_standing.total_teams == 2
    assert by_owner["ub"].at_trade_standing.rank == 2


def test_at_trade_standing_null_without_snapshot(tmp_path):
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    detail = build_trade_detail(_entry(), "t1", standings_store=store)
    assert detail.sides[0].at_trade_standing is None


def test_build_trade_detail_without_store_is_backward_compatible():
    detail = build_trade_detail(_entry(), "t1")
    assert all(s.at_trade_standing is None for s in detail.sides)
