from unittest.mock import patch

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _seed(tmp_path):
    entry = ChainCacheEntry(
        league_id="L",
        chain=[{"league_id": "L", "season": 2024, "name": "Bros",
                "total_rosters": 2, "playoff_week_start": 15}],
        resolved_trades=[
            {
                "trade": {"transaction_id": "tx1", "league_id": "L",
                          "season": 2024, "week": 2,
                          "traded_at": "2024-09-12T00:00:00+00:00",
                          "sides": {}},
                "sides": {
                    "u_a": {
                        "user_id": "u_a",
                        "received": [{"name": "Bijan", "player_id": "p_b"}],
                        "given": [{"name": "Adams", "player_id": "p_a"}],
                    },
                    "u_b": {
                        "user_id": "u_b",
                        "received": [{"name": "Adams", "player_id": "p_a"}],
                        "given": [{"name": "Bijan", "player_id": "p_b"}],
                    },
                },
            },
        ],
        grades={
            "tx1": {
                "trade_id": "tx1",
                "snapshot_value_swing": {"u_a": 1450, "u_b": -1450},
                "production_total": {"u_a": 387, "u_b": -387},
                "production_regular": {"u_a": 300, "u_b": -300},
                "production_toilet": {"u_a": 20, "u_b": -20},
                "production_playoff": {"u_a": 95, "u_b": -95},
                "received_ktc": {"u_a": 7500, "u_b": 6050},
                "breakdown": {
                    "u_a": [{"label": "Bijan", "kind": "player", "player_id": "p_b",
                             "ktc": 7500, "production_total": 387, "production_regular": 300,
                             "production_playoff": 95, "production_toilet": 20}],
                    "u_b": [{"label": "Adams", "kind": "player", "player_id": "p_a",
                             "ktc": 6050, "production_total": 56, "production_regular": 40,
                             "production_playoff": 12, "production_toilet": 4}],
                },
            },
        },
        owners={"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}, "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={"L": 15},
        roster_to_user_by_league={"L": {1: "u_a", 2: "u_b"}},
        league_name_by_id={"L": "Bros"},
        league_season_by_id={"L": 2024},
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    ChainCache(cache_dir=tmp_path).write("L", entry)


def test_trade_detail_returns_each_side(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.trade._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/trade/tx1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trade_id"] == "tx1"
    assert len(body["sides"]) == 2
    alice = next(s for s in body["sides"] if s["user_id"] == "u_a")
    assert alice["snapshot_ktc_swing"] == 1450
    assert alice["production_regular"] == 300
    assert alice["production_playoff"] == 95
    assert alice["production_toilet"] == 20
    assert alice["received"][0]["name"] == "Bijan"


def test_trade_detail_includes_breakdown(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.trade._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/trade/tx1")
    body = resp.json()
    alice = next(s for s in body["sides"] if s["user_id"] == "u_a")
    assert alice["received_ktc"] == 7500
    assert len(alice["breakdown"]) == 1
    row = alice["breakdown"][0]
    assert row["label"] == "Bijan"
    assert row["kind"] == "player"
    assert row["production_total"] == 387


def _seed_flip(tmp_path):
    """A root trade (tx1) where u_b receives Kupp, then flips him (tx2) to u_c
    for Mason. The journey on tx1 should link u_b's Kupp row to tx2."""
    root = {
        "trade": {"transaction_id": "tx1", "league_id": "L", "season": 2024, "week": 2,
                  "traded_at": "2024-09-12T00:00:00+00:00", "sides": {}},
        "sides": {
            "u_a": {"user_id": "u_a", "received": [{"name": "Adams", "player_id": "p_a"}],
                    "given": [{"name": "Kupp", "player_id": "p_k"}]},
            "u_b": {"user_id": "u_b", "received": [{"name": "Kupp", "player_id": "p_k"}],
                    "given": [{"name": "Adams", "player_id": "p_a"}]},
        },
    }
    flip = {
        "trade": {"transaction_id": "tx2", "league_id": "L", "season": 2024, "week": 6,
                  "traded_at": "2024-10-15T00:00:00+00:00", "sides": {}},
        "sides": {
            "u_b": {"user_id": "u_b", "received": [{"name": "Mason", "player_id": "p_m"}],
                    "given": [{"name": "Kupp", "player_id": "p_k"}]},
            "u_c": {"user_id": "u_c", "received": [{"name": "Kupp", "player_id": "p_k"}],
                    "given": [{"name": "Mason", "player_id": "p_m"}]},
        },
    }
    entry = ChainCacheEntry(
        league_id="L", chain=[{"league_id": "L", "season": 2024, "name": "Bros",
                               "total_rosters": 3, "playoff_week_start": 15}],
        resolved_trades=[root, flip],
        grades={"tx1": {"trade_id": "tx1",
                        "breakdown": {
                            "u_a": [{"label": "Adams", "kind": "player", "player_id": "p_a",
                                     "ktc": 6000, "production_total": 40, "production_regular": 40,
                                     "production_playoff": 0, "production_toilet": 0}],
                            "u_b": [{"label": "Kupp", "kind": "player", "player_id": "p_k",
                                     "ktc": 5400, "production_total": 30, "production_regular": 30,
                                     "production_playoff": 0, "production_toilet": 0}]}}},
        became_grades={"tx1": {"grades": {
            "u_b": {"ktc": 3500, "production": 60, "regular": 40, "playoff": 0, "toilet": 0,
                    "terminal_labels": ["Mason"],
                    "breakdown": [{"label": "Mason", "kind": "player", "player_id": "p_m",
                                   "ktc": 3500, "production_total": 60, "production_regular": 40,
                                   "production_playoff": 0, "production_toilet": 0}]}}}},
        owners={"u_a": {"owner_name": "Alice"}, "u_b": {"owner_name": "Bob"},
                "u_c": {"owner_name": "BillyBob"}},
        playoff_weeks_by_league={"L": 15},
        roster_to_user_by_league={"L": {1: "u_a", 2: "u_b", 3: "u_c"}},
        league_name_by_id={"L": "Bros"}, league_season_by_id={"L": 2024},
        current_holders={"p_a": "u_a", "p_m": "u_b", "p_k": "u_c"},
        cached_at="2026-05-28T12:00:00Z", warnings=[],
    )
    ChainCache(cache_dir=tmp_path).write("L", entry)


def test_trade_detail_journey_links_flip(client, tmp_path):
    _seed_flip(tmp_path)
    with patch("app.routes.trade._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/trade/tx1")
    body = resp.json()
    bob = next(s for s in body["sides"] if s["user_id"] == "u_b")
    kupp = bob["breakdown"][0]
    assert kupp["label"] == "Kupp"
    assert kupp["flip"] is not None
    assert kupp["flip"]["to_owner"] == "BillyBob"
    assert kupp["flip"]["trade_id"] == "tx2"
    assert kupp["flip"]["league_id"] == "L"
    assert kupp["flip"]["became"][0]["label"] == "Mason"
    assert kupp["flip"]["became"][0]["production_total"] == 60
    # The kept side's asset gets a terminal_state tag, no flip.
    alice = next(s for s in body["sides"] if s["user_id"] == "u_a")
    assert alice["breakdown"][0]["flip"] is None
    assert alice["breakdown"][0]["terminal_state"] == "on_roster"


def test_trade_detail_unknown_404(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.trade._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/trade/missing")
    assert resp.status_code == 404


def test_trade_detail_includes_at_trade_fields():
    from app.services.trade_view import build_trade_detail
    from app.services.chain_cache import ChainCacheEntry

    entry = ChainCacheEntry(
        league_id="L1",
        chain=[], league_name_by_id={"L1": "Bros"}, league_season_by_id={"L1": 2026},
        owners={"u_a": {"owner_name": "A", "team_name": None, "avatar_url": None},
                "u_b": {"owner_name": "B", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={"L1": 15},
        roster_to_user_by_league={"L1": {1: "u_a", 2: "u_b"}},
        resolved_trades=[{
            "trade": {"transaction_id": "tx1", "league_id": "L1", "season": 2026,
                      "week": 1, "traded_at": "2026-05-03T00:00:00+00:00"},
            "sides": {"u_b": {"received": [], "given": []}},
        }],
        grades={"tx1": {
            "snapshot_value_swing": {"u_b": 8500.0},
            "at_trade_value_swing": {"u_b": 8000.0},
            "aged_value_swing": {"u_b": 500.0},
            "at_trade_approx": True, "at_trade_snapshot_date": "2026-05-31",
            "production_total": {"u_b": 0.0},
        }},
        cached_at="t", warnings=[],
    )
    resp = build_trade_detail(entry, "tx1")
    side = next(s for s in resp.sides if s.user_id == "u_b")
    assert side.at_trade_ktc_swing == 8000.0
    assert side.aged_ktc_swing == 500.0
    assert side.at_trade_approx is True
    assert side.at_trade_snapshot_date == "2026-05-31"
