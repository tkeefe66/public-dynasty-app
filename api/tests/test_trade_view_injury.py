"""Tests for per-received-player injury context surfacing in build_trade_detail."""
import pytest

from app.services.chain_cache import ChainCacheEntry
from app.services.trade_view import build_trade_detail


@pytest.fixture
def trade_detail_fixture(trade_detail_fixture):
    """Extends conftest's base fixture with a trade_injury payload."""
    entry = trade_detail_fixture["entry"]
    entry.trade_injury = {
        "t1": {
            "u1": {
                "p1": {
                    "games_missed": {"regular": 0, "playoff": 1, "toilet": 0},
                    "missed_weeks": [[2024, 16, "high"]],
                    "currently_out": True,
                    "out_detail": "Out (Knee)",
                }
            }
        }
    }
    return trade_detail_fixture


def test_trade_detail_surfaces_injury(trade_detail_fixture):
    resp = build_trade_detail(**trade_detail_fixture)
    v = resp.injury["u1"]["p1"]
    assert v.games_missed["playoff"] == 1
    assert v.currently_out is True
    assert v.missed_weeks == [[2024, 16, "high"]]


def test_trade_detail_injury_empty_when_absent():
    """When trade_injury is absent, injury field is an empty dict."""
    rt = {
        "trade": {
            "transaction_id": "t1",
            "traded_at": "2024-11-01T00:00:00",
            "week": 5,
            "season": 2024,
            "league_id": "L",
        },
        "sides": {
            "u1": {"user_id": "u1", "received": [], "given": []},
        },
    }
    entry = ChainCacheEntry(
        league_id="L",
        chain=[],
        resolved_trades=[rt],
        grades={"t1": {"snapshot_value_swing": {}, "production_total": {}, "breakdown": {}}},
        owners={"u1": {"owner_name": "Owner One"}},
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={"L": "L"},
        league_season_by_id={"L": 2024},
        cached_at="now",
        warnings=[],
    )
    resp = build_trade_detail(entry, "t1")
    assert resp.injury == {}


def test_trade_detail_injury_out_detail(trade_detail_fixture):
    """out_detail field is surfaced correctly."""
    resp = build_trade_detail(**trade_detail_fixture)
    v = resp.injury["u1"]["p1"]
    assert v.out_detail == "Out (Knee)"
