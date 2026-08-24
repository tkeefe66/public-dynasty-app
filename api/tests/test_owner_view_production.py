from app.services.chain_cache import ChainCacheEntry
from app.services.owner_view import build_owner_detail


def _entry(**over):
    base = dict(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"u1": {"owner_name": "Alice"}, "u2": {"owner_name": "Bob"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="2026-01-01",
    )
    base.update(over)
    return ChainCacheEntry(**base)


def owner_detail_fixture():
    entry = _entry(
        owner_production_series={
            "u1": {
                "received": {
                    "total": [[2024, 5, 0.0], [2024, 6, 20.0]],
                    "regular": [],
                    "playoff": [],
                    "toilet": [],
                },
                "given": {
                    "total": [[2024, 5, 0.0], [2024, 6, 12.0]],
                    "regular": [],
                    "playoff": [],
                    "toilet": [],
                },
            }
        },
        owner_production_verdict={
            "u1": {
                "total": {
                    "label": "Net positive.",
                    "sentence": "x",
                    "tone": "good",
                    "received_total": 20.0,
                    "given_total": 12.0,
                }
            }
        },
        production_week_axis=[[2024, 5], [2024, 6]],
    )
    return {"entry": entry, "user_id": "u1"}


def test_owner_detail_surfaces_production():
    fixture = owner_detail_fixture()
    resp = build_owner_detail(**fixture)
    assert "received" in resp.production_series
    assert "total" in resp.production_series["received"]
    assert resp.production_verdict["total"].tone in {"good", "bad", "neutral"}
    assert resp.production_week_axis


def test_owner_detail_has_per_trade_drill():
    entry = _entry(
        owner_production_trades={
            "u1": [
                {
                    "trade_id": "t1",
                    "byMetric": {
                        "total": [[2024, 5, 0.0], [2024, 6, 10.0]],
                        "regular": [],
                        "playoff": [],
                        "toilet": [],
                    },
                }
            ]
        }
    )
    resp = build_owner_detail(entry=entry, user_id="u1")
    assert resp.production_trades and resp.production_trades[0].trade_id == "t1"
    assert "total" in resp.production_trades[0].series
