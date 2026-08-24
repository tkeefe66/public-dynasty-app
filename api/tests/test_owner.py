import pytest
from unittest.mock import patch

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _seed(tmp_path):
    entry = ChainCacheEntry(
        league_id="L",
        chain=[
            {"league_id": "L", "season": 2024, "name": "Bros",
             "total_rosters": 2, "playoff_week_start": 15},
        ],
        resolved_trades=[
            {
                "trade": {"transaction_id": "tx1", "league_id": "L",
                          "season": 2024, "week": 2,
                          "traded_at": "2024-09-12T00:00:00+00:00",
                          "sides": {}},
                "sides": {
                    "u_a": {"user_id": "u_a", "received": [], "given": []},
                    "u_b": {"user_id": "u_b", "received": [], "given": []},
                },
            },
        ],
        grades={
            "tx1": {
                "trade_id": "tx1",
                "received_ktc": {"u_a": 500, "u_b": -500},
                "snapshot_value_swing": {"u_a": 500, "u_b": -500},
                "production_total": {"u_a": 100, "u_b": -100},
                "production_regular": {"u_a": 80, "u_b": -80},
                "production_toilet": {"u_a": 5, "u_b": -5},
                "production_playoff": {"u_a": 30, "u_b": -30},
                # 80 + 30 + 5 = 115, but started is 120 ON PURPOSE. Playoff
                # counts live title-path games only, so started points in a
                # placement game or an eliminated week belong to no phase.
                # A fixture where started happened to equal the phase sum
                # could not tell a real read from a derived one.
                "production_started": {"u_a": 120, "u_b": -120},
            },
        },
        owners={"u_a": {"owner_name": "Alice", "team_name": None, "avatar_url": None}, "u_b": {"owner_name": "Bob", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={"L": 15},
        roster_to_user_by_league={"L": {1: "u_a", 2: "u_b"}},
        league_name_by_id={"L": "Bros"},
        league_season_by_id={"L": 2024},
        season_records={
            "2024": {
                "u_a": {"wins": 9, "losses": 4, "ties": 0, "rank": 1,
                        "total_teams": 2, "champion": True, "runner_up": False,
                        "made_playoffs": True, "rounds_won": 2,
                        "playoff_place": 1, "toilet_place": None},
                "u_b": {"wins": 4, "losses": 9, "ties": 0, "rank": 2,
                        "total_teams": 2, "champion": False, "runner_up": True,
                        "made_playoffs": True, "rounds_won": 1,
                        "playoff_place": 2, "toilet_place": None},
            },
        },
        # The v2 rating reads these two dicts and nothing else. Empty means the
        # refresh's signal stage failed, and live_ratings now rates nobody
        # rather than putting the whole league at 1500 (= a league of C's).
        outcome_signals={
            "u_a": {"expected_wins": 0.7, "playoff_success": 0.9, "luck": 0.1},
            "u_b": {"expected_wins": 0.3, "playoff_success": 0.4, "luck": -0.1},
        },
        outlook_signals={
            "u_a": {"roster_value_share": 0.6, "young_core_share": 0.6, "draft_capital": 0.6},
            "u_b": {"roster_value_share": 0.4, "young_core_share": 0.4, "draft_capital": 0.4},
        },
        head_to_head={
            "u_a": {"u_b": {"opponent_id": "u_b", "wins": 7, "losses": 6,
                            "ties": 0, "points_for": 1500.0,
                            "points_against": 1450.0}},
            "u_b": {"u_a": {"opponent_id": "u_a", "wins": 6, "losses": 7,
                            "ties": 0, "points_for": 1450.0,
                            "points_against": 1500.0}},
        },
        cached_at="2026-05-28T12:00:00Z",
        warnings=[],
    )
    ChainCache(cache_dir=tmp_path).write("L", entry)


def test_owner_detail_returns_career_arc_and_totals(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_a")
    assert resp.status_code == 200
    body = resp.json()
    assert body["owner"]["owner_name"] == "Alice"
    assert body["totals_by_lens"]["ktc"] == 500
    assert body["totals_by_lens"]["production"] == 100
    assert body["totals_by_lens"]["started"] == 120
    assert body["totals_by_lens"]["start_pct"] == pytest.approx(120 / 100)
    assert body["best_trade_id"] == "tx1"


def test_owner_detail_returns_per_owner_trade_rows(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_a")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["trades"]) == 1
    row = body["trades"][0]
    assert row["trade_id"] == "tx1"
    assert row["season"] == 2024
    assert row["week"] == 2
    assert row["swing_ktc"] == 500          # u_a's share, not the first party
    assert row["swing_prod"] == 100
    assert row["swing_regular"] == 80
    assert row["swing_playoff"] == 30
    assert row["swing_toilet"] == 5
    # Starters-only across every week — read from the grade, NOT summed from
    # the three phases (which would give 115 here, not 120).
    assert row["swing_started"] == 120
    assert row["swing_started"] != row["swing_regular"] + row["swing_playoff"] + row["swing_toilet"]
    # Start rate: started / total. 120 of 100 is >1 in this synthetic fixture,
    # which is fine — the assertion is that it is the RATIO of those two fields
    # and not some other pair.
    assert row["start_pct"] == pytest.approx(row["swing_started"] / row["swing_prod"])
    # Counterparties exclude the owner themselves.
    cp_ids = [c["user_id"] for c in row["counterparties"]]
    assert cp_ids == ["u_b"]
    # Per-season regular/playoff/toilet power the small-multiples.
    assert body["career_arc"][0]["production_regular"] == 80
    assert body["career_arc"][0]["production_playoff"] == 30
    assert body["career_arc"][0]["production_toilet"] == 5
    # Started rides the arc too, so the career chart can show what a franchise
    # DEPLOYED per season rather than only what it accumulated. Read from the
    # grade, not summed: 80 + 30 + 5 = 115, the real figure is 120.
    assert body["career_arc"][0]["production_started"] == 120


def test_owner_detail_trade_rows_use_each_owners_swing(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_b")
    assert resp.status_code == 200
    row = resp.json()["trades"][0]
    assert row["swing_ktc"] == -500         # u_b lost what u_a gained
    assert row["swing_regular"] == -80
    assert row["swing_playoff"] == -30
    assert row["swing_toilet"] == -5


def test_owner_detail_includes_track_record(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_a")
    tr = resp.json()["track_record"]
    assert tr["titles"] == 1
    assert tr["playoff_appearances"] == 1
    assert tr["best_finish"] == 1
    assert tr["career_wins"] == 9
    assert len(tr["seasons"]) == 1
    assert tr["seasons"][0]["champion"] is True


def test_owner_detail_includes_head_to_head(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_a")
    h2h = resp.json()["head_to_head"]
    assert len(h2h) == 1
    assert h2h[0]["opponent"]["owner_name"] == "Bob"
    assert h2h[0]["wins"] == 7
    assert h2h[0]["losses"] == 6


def test_owner_detail_includes_franchise_rating(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_a")
    fr = resp.json()["franchise_rating"]
    assert fr is not None
    # u_a has the positive trade signals in the fixture, so it's the better GM:
    # rank 1 of 2, an above-average letter, and the rating drives the letter.
    assert fr["of"] == 2
    assert fr["rank"] == 1
    assert fr["letter"] and isinstance(fr["letter"], str)
    assert fr["rating"] >= 1500
    # The receipt carries the v2 pillar breakdown (Results/Assets) for the hero drill-down.
    assert set(fr["pillars"]) == {"results", "assets"}


def test_build_owner_detail_track_record_without_gm_row():
    # The direct (non-route) call still fills track_record + h2h; franchise_rating
    # is None until a leaderboard row is supplied.
    from app.services.owner_view import build_owner_detail
    from app.services.chain_cache import ChainCache as _CC  # noqa: F401

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        _seed(Path(d))
        entry = ChainCache(cache_dir=Path(d)).read("L")
    detail = build_owner_detail(entry, "u_a")
    assert detail.franchise_rating is None
    assert detail.track_record.titles == 1
    assert len(detail.head_to_head) == 1


def test_owner_detail_unknown_user_404(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_missing")
    assert resp.status_code == 404


def test_owner_detail_cold_cache_409(client, tmp_path):
    with patch("app.routes.owner._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L/owner/u_a")
    assert resp.status_code == 409


def test_owner_detail_at_trade_aggregate_over_subset():
    from app.services.owner_view import build_owner_detail

    def grade(today, at):
        # received_ktc drives the realized headline; here it equals the swing so
        # the headline total still sums to 1500. snapshot_value_swing feeds only
        # the at_trade/aged diagnostic.
        g = {
            "received_ktc": {"u_a": today},
            "snapshot_value_swing": {"u_a": today},
            "production_total": {"u_a": 0.0},
        }
        if at is not None:
            g["at_trade_value_swing"] = {"u_a": at}
            g["aged_value_swing"] = {"u_a": today - at}
        else:
            g["at_trade_value_swing"] = None
        return g

    entry = ChainCacheEntry(
        league_id="L1",
        chain=[],
        resolved_trades=[
            {"trade": {"transaction_id": "t1", "season": 2026, "league_id": "L1"}},
            {"trade": {"transaction_id": "t2", "season": 2026, "league_id": "L1"}},
        ],
        grades={"t1": grade(1000.0, 800.0), "t2": grade(500.0, None)},  # t2 blank at-trade
        owners={"u_a": {"owner_name": "A", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="t",
        warnings=[],
    )
    resp = build_owner_detail(entry, "u_a")
    assert resp.totals_by_lens["ktc"] == 1500.0          # all trades
    assert resp.totals_by_lens["ktc_at_trade"] == 800.0  # subset {t1}
    assert resp.totals_by_lens["ktc_aged"] == 200.0      # 1000 - 800 over {t1}


def test_owner_detail_ktc_total_is_realized_received_not_swing():
    """Headline ktc must sum received_ktc, NOT snapshot_value_swing.

    Fixture gives the two metrics DIFFERENT values so the assertion genuinely
    distinguishes realized (6000) from the mark-to-market swing (1900).
    """
    from app.services.owner_view import build_owner_detail

    entry = ChainCacheEntry(
        league_id="L2",
        chain=[],
        resolved_trades=[
            {"trade": {"transaction_id": "t1", "season": 2026, "league_id": "L2"}},
        ],
        grades={
            "t1": {
                "received_ktc": {"u_a": 6000.0},
                "snapshot_value_swing": {"u_a": 1900.0},
                "production_total": {"u_a": 0.0},
            },
        },
        owners={"u_a": {"owner_name": "A", "team_name": None, "avatar_url": None}},
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="t",
        warnings=[],
    )
    resp = build_owner_detail(entry, "u_a")
    assert resp.totals_by_lens["ktc"] == 6000.0          # realized, not 1900 swing
    assert resp.trades[0].swing_ktc == 6000.0            # row also realized
