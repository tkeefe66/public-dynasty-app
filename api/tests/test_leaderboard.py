from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.models.leaderboard import LeaderboardResp
from app.services.chain_cache import ChainCache, ChainCacheEntry
from app.services.leaderboard import build_leaderboard
from app.services.rating_snapshot_store import RatingSnapshotStore


def _grade(ktc, regular, playoff, toilet=None):
    return {
        "snapshot_value_swing": ktc,
        "received_ktc": ktc,
        "production_total": {u: v for u, v in regular.items()},
        "production_regular": regular,
        "production_playoff": playoff,
        "production_toilet": toilet or {u: 0.0 for u in regular},
    }


def _sample_entry() -> ChainCacheEntry:
    # Three owners; alice clearly best, carol clearly worst.
    return ChainCacheEntry(
        league_id="L_current",
        chain=[
            {"league_id": "L_current", "season": 2026, "name": "Bros",
             "total_rosters": 3, "playoff_week_start": 15},
            {"league_id": "L_prev", "season": 2024, "name": "Bros",
             "total_rosters": 3, "playoff_week_start": 15},
        ],
        resolved_trades=[
            {"trade": {"transaction_id": "tx_2024", "league_id": "L_prev",
                       "season": 2024, "week": 2,
                       "traded_at": "2024-09-12T00:00:00+00:00", "sides": {}},
             "sides": {}},
            {"trade": {"transaction_id": "tx_2026", "league_id": "L_current",
                       "season": 2026, "week": 1,
                       "traded_at": "2026-05-19T00:00:00+00:00", "sides": {}},
             "sides": {}},
        ],
        grades={
            "tx_2024": _grade(
                {"u_alice": 1000.0, "u_bob": 0.0, "u_carol": -1000.0},
                {"u_alice": 800.0, "u_bob": 0.0, "u_carol": -800.0},
                {"u_alice": 400.0, "u_bob": 0.0, "u_carol": -400.0},
            ),
            "tx_2026": _grade(
                {"u_alice": 50.0, "u_bob": 0.0, "u_carol": -50.0},
                {"u_alice": 50.0, "u_bob": 0.0, "u_carol": -50.0},
                {"u_alice": 0.0, "u_bob": 0.0, "u_carol": 0.0},
            ),
        },
        owners={
            "u_alice": {"owner_name": "Alice", "team_name": None, "avatar_url": None},
            "u_bob": {"owner_name": "Bob", "team_name": None, "avatar_url": None},
            "u_carol": {"owner_name": "Carol", "team_name": None, "avatar_url": None},
        },
        playoff_weeks_by_league={"L_current": 15, "L_prev": 15},
        roster_to_user_by_league={
            "L_current": {1: "u_alice", 2: "u_bob", 3: "u_carol"},
            "L_prev": {1: "u_alice", 2: "u_bob", 3: "u_carol"},
        },
        league_name_by_id={"L_current": "Bros", "L_prev": "Bros"},
        league_season_by_id={"L_current": 2026, "L_prev": 2024},
        # Outcome/outlook signals linearly spaced (bob = the league mean -> z 0).
        # v1 keys (championships/playoff_depth/... and roster_value/youth) are
        # still here because their non-scoring consumers read them (e.g.
        # gm_rating_blurb, _playoff_rate_by_uid) -- see test_rating_signals_v2's
        # "v1 outcome keys survive" test. The v2 keys below are what
        # franchise_redesign.build_v2_pillars actually reads.
        outcome_signals={
            "u_alice": {"championships": 2, "playoff_depth": 4, "made_playoffs": 1.0,
                        "final_seed": 3.0, "points_for_rank": 3.0,
                        "expected_wins": 0.7, "playoff_success": 0.8, "luck": 0.2},
            "u_bob": {"championships": 1, "playoff_depth": 2, "made_playoffs": 0.5,
                      "final_seed": 2.0, "points_for_rank": 2.0,
                      "expected_wins": 0.5, "playoff_success": 0.5, "luck": 0.0},
            "u_carol": {"championships": 0, "playoff_depth": 0, "made_playoffs": 0.0,
                        "final_seed": 1.0, "points_for_rank": 1.0,
                        "expected_wins": 0.3, "playoff_success": 0.2, "luck": -0.2},
        },
        outlook_signals={
            "u_alice": {"roster_value": 60000, "draft_capital": 0.6, "youth": -25,
                        "roster_value_share": 0.6, "young_core_share": 0.6},
            "u_bob": {"roster_value": 45000, "draft_capital": 0.4, "youth": -27,
                      "roster_value_share": 0.4, "young_core_share": 0.4},
            "u_carol": {"roster_value": 30000, "draft_capital": 0.2, "youth": -29,
                        "roster_value_share": 0.2, "young_core_share": 0.2},
        },
        cached_at="2026-05-28T12:00:00Z",
        # A played season for all three: live_ratings rates only owners with
        # one behind them (franchise_redesign.rated_owners).
        season_records={
            "2024": {
                "u_alice": {"wins": 10, "losses": 4, "ties": 0},
                "u_bob": {"wins": 7, "losses": 7, "ties": 0},
                "u_carol": {"wins": 4, "losses": 10, "ties": 0},
            },
        },
        warnings=[],
    )


def test_build_leaderboard_ranks_by_rating_and_centers():
    resp = build_leaderboard(_sample_entry(), year="all", prev_ratings={})
    assert isinstance(resp, LeaderboardResp)
    assert resp.scope == "all"
    assert [r.user_id for r in resp.rows] == ["u_alice", "u_bob", "u_carol"]
    assert [r.rank for r in resp.rows] == [1, 2, 3]
    # symmetric league -> the middle GM sits at base 1500
    assert resp.rows[1].rating == 1500
    # all trends flat with no prior snapshot
    assert all(r.trend == 0 for r in resp.rows)


def test_each_row_carries_franchise_letter():
    from sleeper_dynasty.engine.gm_rating import rating_to_letter

    resp = build_leaderboard(_sample_entry(), year="all", prev_ratings={})
    for r in resp.rows:
        assert r.letter == rating_to_letter(r.rating)
    # The exactly-average middle GM (rating 1500) is a C.
    assert resp.rows[1].letter == "C"


def test_pillars_reconcile_to_rating_minus_base():
    resp = build_leaderboard(_sample_entry(), year="all", prev_ratings={})
    for r in resp.rows:
        pillar_sum = sum(p.contribution for p in r.pillars.values())
        assert abs(pillar_sum - (r.rating - 1500)) <= 2
        for p in r.pillars.values():
            sig_sum = sum(s.contribution for s in p.signals.values())
            assert abs(sig_sum - p.contribution) <= 1


def test_trend_from_prev_ratings():
    # Prior snapshot had carol ahead of alice -> alice moved up, carol down.
    prev = {"u_carol": 1800, "u_bob": 1500, "u_alice": 1200}
    resp = build_leaderboard(_sample_entry(), year="all", prev_ratings=prev)
    by_uid = {r.user_id: r for r in resp.rows}
    assert by_uid["u_alice"].trend == 2   # was rank 3, now rank 1
    assert by_uid["u_carol"].trend == -2  # was rank 1, now rank 3
    assert by_uid["u_bob"].trend == 0


def test_year_filter_scopes_metrics():
    resp = build_leaderboard(_sample_entry(), year=2026, prev_ratings={})
    assert resp.scope == "2026"
    alice = next(r for r in resp.rows if r.user_id == "u_alice")
    assert alice.trades == 1
    assert alice.net_ktc == 50.0


def test_live_ratings_assembles_v2_pillars():
    """live_ratings returns the v2 pillars (results/assets), not the legacy
    three-pillar tree (outcomes/trade_impact/outlook) and not the v1 redesign
    tree (results/skill/outlook) -- v2 drops Skill entirely."""
    from app.services.franchise_redesign import live_ratings
    entry = _sample_entry()
    ratings = live_ratings(entry)
    assert set(ratings["u_alice"]["pillars"]) == {"results", "assets"}
    assert "expected_wins" in ratings["u_alice"]["pillars"]["results"]["signals"]
    assert "roster_value_share" in ratings["u_alice"]["pillars"]["assets"]["signals"]


# ---- route ----

def _seed(cache_dir: Path) -> None:
    ChainCache(cache_dir=cache_dir).write("L_current", _sample_entry())


def test_route_cold_cache_returns_409(client, tmp_path):
    with patch("app.routes.leaderboard._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_unseen/leaderboard")
    assert resp.status_code == 409
    assert "cold" in resp.json()["detail"].lower()


def test_route_warm_cache_returns_board(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.leaderboard._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_current/leaderboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "all"
    assert body["rows"][0]["owner"]["owner_name"] == "Alice"
    assert body["rows"][0]["rank"] == 1


def test_route_year_param(client, tmp_path):
    _seed(tmp_path)
    with patch("app.routes.leaderboard._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_current/leaderboard?year=2026")
    assert resp.status_code == 200
    assert resp.json()["scope"] == "2026"


def test_route_trend_uses_prior_week_snapshot(client, tmp_path):
    _seed(tmp_path)
    store = RatingSnapshotStore(cache_dir=tmp_path)
    # Earlier week: carol on top. Current week: present but ignored for baseline.
    store.write(
        "L_current", "2024-08", {"u_carol": 1800, "u_bob": 1500, "u_alice": 1200},
        model="v2_dynasty",
    )
    store.write(
        "L_current", "2024-09", {"u_alice": 1800, "u_bob": 1500, "u_carol": 1200},
        model="v2_dynasty",
    )
    with patch("app.routes.leaderboard._cache_dir", return_value=tmp_path):
        resp = client.get("/api/league/L_current/leaderboard")
    by_uid = {r["user_id"]: r for r in resp.json()["rows"]}
    assert by_uid["u_alice"]["trend"] == 2
    assert by_uid["u_carol"]["trend"] == -2


def test_compute_season_ratings_is_empty_under_v2():
    # v2's signals (outcome_signals/outlook_signals) are single all-time,
    # decay-weighted dicts -- there is no per-season slice left to compute.
    # A per-year loop over an all-time tree would just replay the same
    # number under every season key, which downstream consumers then read
    # as a genuine (and false) "no year-over-year movement". See
    # api/tests/services/test_season_ratings_v2.py for the consumer-side
    # (_rise_hero_stat) degradation this enables.
    from app.services.leaderboard import compute_season_ratings
    assert compute_season_ratings(_sample_entry()) == {}


def test_build_leaderboard_exposes_v2_pillars():
    from app.services.leaderboard import build_leaderboard
    entry = _sample_entry()
    resp = build_leaderboard(entry, year="all", prev_ratings={})
    assert resp.rows, "expected at least one row"
    assert set(resp.rows[0].pillars.keys()) == {"results", "assets"}


def test_gm_row_carries_the_model_that_produced_the_rating():
    """A rating pooled without knowing which tree produced it is
    uninterpretable (Task 3 finding) — the stamp must survive to GMRow."""
    resp = build_leaderboard(_sample_entry(), year="all", prev_ratings={})
    assert resp.rows, "expected at least one row"
    for r in resp.rows:
        # _sample_entry has no capabilities dict -> reads as full dynasty.
        assert r.model == "v2_dynasty"
