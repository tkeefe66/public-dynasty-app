"""Tests for per-trade production timeline + verdict surfacing in build_trade_detail."""
import pytest

from app.services.chain_cache import ChainCacheEntry
from app.services.trade_view import build_trade_detail


@pytest.fixture
def trade_detail_fixture(trade_detail_fixture):
    """Extends conftest's base fixture with production-series/verdict fields."""
    entry = trade_detail_fixture["entry"]
    entry.trade_production_series = {
        "t1": {
            "u1": {
                "total": [[2024, 5, 0.0], [2024, 6, 10.0]],
                "regular": [],
                "playoff": [],
                "toilet": [],
            }
        }
    }
    entry.trade_production_verdict = {
        "t1": {
            "total": {
                "label": "Won the production battle.",
                "sentence": "x",
                "tone": "good",
                "winner_uid": "u1",
                "totals": {"u1": 10.0},
            }
        }
    }
    entry.production_week_axis = [[2024, 5], [2024, 6]]
    return trade_detail_fixture


def test_trade_detail_surfaces_production(trade_detail_fixture):
    resp = build_trade_detail(**trade_detail_fixture)
    assert resp.production_week_axis  # [[season, week], ...]
    assert "u1" in resp.production_series
    assert "total" in resp.production_series["u1"]
    assert resp.production_series["u1"]["total"][0].season >= 2000
    assert resp.production_verdict["total"].tone in {"good", "bad", "neutral"}


def test_trade_detail_has_per_player_drill(trade_detail_fixture):
    # Extend the entry to include trade_production_players for this trade.
    entry = trade_detail_fixture["entry"]
    entry.trade_production_players = {
        "t1": {
            "u1": [
                {
                    "player_id": "p1",
                    "byMetric": {
                        "total": [[2024, 5, 0.0], [2024, 6, 10.0]],
                        "regular": [],
                        "playoff": [],
                        "toilet": [],
                    },
                }
            ]
        }
    }
    resp = build_trade_detail(**trade_detail_fixture)
    assert "u1" in resp.production_players
    assert resp.production_players["u1"][0].player_id == "p1"
    assert "total" in resp.production_players["u1"][0].series


def test_trade_detail_production_empty_when_absent():
    """When trade_production_series is absent, production fields are empty."""
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
    assert resp.production_series == {}
    assert resp.production_verdict == {}
    assert resp.production_week_axis == []
