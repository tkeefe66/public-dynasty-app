# tests/test_became_view.py
from app.services.chain_cache import ChainCacheEntry
from app.services.trade_view import build_trade_detail


def _entry(became_grades):
    rt = {"trade": {"transaction_id": "t1", "traded_at": "2025-08-20T00:00:00",
                    "week": 1, "season": 2025, "league_id": "L"},
          "sides": {"u_a": {"user_id": "u_a", "received": [{"player_id": "4866", "name": "Saquon Barkley", "via_pick": None}], "given": []},
                    "u_b": {"user_id": "u_b", "received": [], "given": [{"player_id": "4866", "name": "Saquon Barkley", "via_pick": None}]}}}
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[rt], grades={},
        owners={"u_a": {"owner_name": "A"}, "u_b": {"owner_name": "B"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2025},
        cached_at="now", current_holders={"4866": "u_a"},
        became_grades=became_grades)


def test_detail_surfaces_became_per_side():
    grades = {"t1": {"terminal_hash": "h", "grades": {
        "u_a": {"ktc": 5000.0, "production": 42.0, "regular": 30.0,
                "playoff": 12.0, "toilet": 5.0, "terminal_labels": ["Player B", "Player C"]}}}}
    resp = build_trade_detail(_entry(grades), "t1")
    assert "u_a" in resp.became
    m = resp.became["u_a"]
    assert m.ktc == 5000.0
    assert m.production == 42.0
    assert m.regular == 30.0
    assert m.playoff == 12.0
    assert m.toilet == 5.0
    assert m.terminal_labels == ["Player B", "Player C"]


def test_detail_became_empty_when_absent():
    resp = build_trade_detail(_entry({}), "t1")
    assert resp.became == {}
