"""As-of ratings must not borrow present-day facts."""
# ruff: noqa: F811 -- imported pytest fixtures are injected as test parameters.
from copy import deepcopy
from dataclasses import replace

import pytest
from app.services.aggregations import build_dashboard
from app.services.franchise_redesign import live_ratings
from app.services.leaderboard import build_leaderboard

from ._grader_fixtures import dynasty_entry, redraft_entry  # noqa: F401


def test_missing_history_does_not_repeat_current_rating(dynasty_entry):
    # Mutation: ignore year and use the current career signals.
    assert live_ratings(dynasty_entry)
    assert live_ratings(dynasty_entry, year=2024) == {}
    board = build_dashboard(dynasty_entry, year=2024, lens="ktc")
    assert all(row.gm_rating is None for row in board.standings)
    assert all(row.roster_rank is None and row.draft_capital_value is None
               and row.window is None for row in board.standings)
    assert board.rating_scope.status == "unavailable"
    assert "Historical data unavailable" in board.rating_scope.label


@pytest.mark.parametrize("fmt", ["dynasty", "keeper", "redraft"])
def test_selected_snapshot_controls_both_rating_views(dynasty_entry, fmt):
    # Mutation: dashboard or leaderboard scores today's inputs instead.
    entry = replace(dynasty_entry, capabilities={"format": fmt},
                    current_rating_verification={"status": "ready", "format": fmt})
    historical = deepcopy(entry.outcome_signals)
    historical["u1"], historical["u2"] = historical["u2"], historical["u1"]
    assets = deepcopy(entry.outlook_signals)
    assets["u1"], assets["u2"] = assets["u2"], assets["u1"]
    entry.season_rating_inputs = {"2024": {
        "version": 1, "status": "ready", "basis": "season_end",
        "as_of": "2025-01-07", "format": fmt,
        "owners": ["u1", "u2"], "outcome_signals": historical,
        "outlook_signals": assets, "season_records": entry.season_records,
        "roster_ranks": {"u2": {"rank": 1, "of": 2}, "u1": {"rank": 2, "of": 2}},
    }}
    expected = live_ratings(replace(entry, outcome_signals=historical, outlook_signals=assets))
    actual = live_ratings(entry, year=2024)
    assert actual == expected
    assert actual != live_ratings(entry)
    dashboard = build_dashboard(entry, year=2024, lens="ktc", prev_ratings={"u1": 2200})
    leaderboard = build_leaderboard(entry, year=2024, prev_ratings={"u1": 2200})
    assert {r.user_id: r.gm_rating for r in dashboard.standings} == {
        uid: r["rating"] for uid, r in actual.items()}
    assert {r.user_id: r.rating for r in leaderboard.rows} == {
        uid: r["rating"] for uid, r in actual.items()}
    assert all(r.gm_trend == 0 for r in dashboard.standings)
    assert all(r.trend == 0 and r.blurb is None for r in leaderboard.rows)
    if fmt != "redraft":
        assert next(r for r in dashboard.standings if r.user_id == "u1").roster_rank == 2
    before = deepcopy(actual)
    entry.outcome_signals["u1"]["expected_wins"] = 0.99
    entry.outlook_signals["u2"]["draft_capital"] = 999999
    entry.season_records["2026"] = {"u1": {"wins": 14, "losses": 0}}
    assert live_ratings(entry, year=2024) == before
    if fmt == "keeper":
        from app.services.season_ratings import rating_scope
        entry.season_rating_inputs["2024"]["asset_source"] = {
            "draft_rounds": 0, "prices_as_of": "2025-01-06",
            "valuation_policy": {"version": "stats-guy-v1", "priced": 2, "eligible": 2},
        }
        scope = rating_scope(entry, 2024)
        assert scope["valuation_source"] == "stats_guy"
        assert "No future-pick assets" in scope["valuation_note"]
        assert "Generic round" not in scope["valuation_note"]
        entry.season_rating_inputs["2024"]["asset_source"]["valuation_policy"]["version"] = "dynasty-process-v1"
        scope = build_dashboard(entry, year=2024, lens="ktc").rating_scope
        assert scope.valuation_source == "dynasty_process"
        assert scope.prices_as_of == "2025-01-06"
        assert "2/2 offensive players priced" in scope.valuation_note


def test_all_remains_current_career_rating(dynasty_entry):
    # Mutation: require a season snapshot even for All.
    expected = live_ratings(dynasty_entry)
    response = build_dashboard(dynasty_entry, year="all", lens="ktc")
    assert {r.user_id: r.gm_rating for r in response.standings} == {
        uid: r["rating"] for uid, r in expected.items()}
    assert response.rating_scope.status == "ready"
    assert response.rating_scope.basis == "current"


def _historical_support(entry):
    entry.league_season_by_id = {"old": 2024, "new": 2026}
    entry.roster_to_user_by_league = {lg: {1: "u1", 2: "u2"} for lg in ("old", "new")}
    entry.chain = [{"league_id": lg, "season": year, "format": "redraft", "status": "complete" if lg == "old" else "in_season"}
                   for lg, year in entry.league_season_by_id.items()]
    matchups = {}
    for lg in ("old", "new"):
        for week in range(1, 15):
            a, b = (100, 90) if lg == "old" else (90, 100)
            matchups[(lg, week, 1)] = {"team_points": a, "opponent_points": b}
            matchups[(lg, week, 2)] = {"team_points": b, "opponent_points": a}
    return {"matchups": matchups, "league_season_by_id": entry.league_season_by_id,
            "roster_to_user_by_league": entry.roster_to_user_by_league,
            "playoff_week_start_by_league": {"old": 15, "new": 15}, "owners": entry.owners,
            "season_end_dates": {"old": "2025-01-07"}}


def test_completed_latest_season_never_uses_offseason_assets(dynasty_entry):
    # Mutation: treat a completed latest season as current until March.
    from app.services.season_ratings import build_season_rating_inputs
    supporting = _historical_support(dynasty_entry)
    dynasty_entry.cached_at = "2027-02-15T00:00:00+00:00"
    dynasty_entry.chain[1].update(status="complete", format="dynasty")
    snapshot = build_season_rating_inputs(dynasty_entry, supporting)["2026"]
    assert snapshot["basis"] == "season_end"
    assert snapshot["status"] == "unavailable"


def test_refresh_builds_historical_results_without_future_seasons(redraft_entry):
    # Mutation: derive Results from all seasons instead of the bounded history.
    from app.services.season_ratings import build_season_rating_inputs
    supporting = _historical_support(redraft_entry)
    snapshots = build_season_rating_inputs(redraft_entry, supporting)
    old = snapshots["2024"]
    assert old["status"] == "ready"
    assert old["outcome_signals"]["u1"]["expected_wins"] == 1
    assert old["outcome_signals"]["u2"]["expected_wins"] == 0
    assert set(old["season_records"]) == {"2024"}
    supporting["matchups"][("new", 1, 1)]["team_points"] = 100000
    assert build_season_rating_inputs(redraft_entry, supporting)["2024"] == old


def test_refresh_requires_historical_assets_for_both_continuous_formats(dynasty_entry):
    # Mutation: use current holdings or reweight historical ratings to Results-only.
    from app.services.season_ratings import build_season_rating_inputs
    supporting = _historical_support(dynasty_entry)
    for fmt in ("dynasty", "keeper"):
        dynasty_entry.chain[0]["format"] = fmt
        snapshot = build_season_rating_inputs(dynasty_entry, supporting)["2024"]
        assert snapshot["status"] == "unavailable"
        assert "historical roster" in snapshot["reason"]


def test_missing_historical_week_is_unavailable(redraft_entry):
    # Mutation: partial all-play data counts as verified full-season results.
    from app.services.season_ratings import build_season_rating_inputs
    supporting = _historical_support(redraft_entry)
    del supporting["matchups"][("old", 3, 1)]
    snapshot = build_season_rating_inputs(redraft_entry, supporting)["2024"]
    assert snapshot["status"] == "unavailable"
    assert "game results" in snapshot["reason"]


def test_verified_import_flows_through_refresh_into_historical_rating(tmp_path, dynasty_entry):
    # Mutation: importer is disconnected from the refresh builder or historical assets are ignored.
    from app.services.historical_rating_assets import HistoricalAssetStore
    from app.services.season_ratings import build_season_rating_inputs

    from .test_historical_rating_assets import manifest
    supporting = _historical_support(dynasty_entry)
    dynasty_entry.chain[0]["format"] = "dynasty"
    store = HistoricalAssetStore(tmp_path, "L")
    store.import_verified(manifest())
    dynasty_entry.season_rating_inputs = build_season_rating_inputs(dynasty_entry, supporting, asset_store=store)
    snapshot = dynasty_entry.season_rating_inputs["2024"]
    assert snapshot["status"] == "ready"
    rows = live_ratings(dynasty_entry, year=2024)
    assert rows["u1"]["pillars"]["assets"]["signals"]["roster_value_share"]["raw"] == 0.9
    assert rows["u2"]["pillars"]["assets"]["signals"]["draft_capital"]["raw"] == 6000
    response = build_dashboard(dynasty_entry, year=2024, lens="ktc")
    assert response.rating_scope.as_of == "2025-01-07"
    assert next(r for r in response.standings if r.user_id == "u2").draft_capital_value == 6000


def test_corrupt_ready_snapshot_cannot_score_missing_signal_as_zero(dynasty_entry):
    # Mutation: accept incomplete cached signal keys and let the model default to zero.
    dynasty_entry.season_rating_inputs = {"2024": {
        "version": 1, "status": "ready", "format": "dynasty", "owners": ["u1", "u2"],
        "outcome_signals": {"u1": {}, "u2": {}},
        "outlook_signals": dynasty_entry.outlook_signals, "season_records": dynasty_entry.season_records}}
    assert live_ratings(dynasty_entry, year=2024) == {}


def test_season_input_cache_roundtrip_and_default(tmp_path, dynasty_entry):
    # Mutation: cache serializer drops the additive historical field.
    from app.services.chain_cache import ChainCache
    assert dynasty_entry.season_rating_inputs == {}
    dynasty_entry.season_rating_inputs = {"2024": {"version": 1, "status": "unavailable",
                                                 "reason": "No verified asset history"}}
    cache = ChainCache(tmp_path)
    cache.write("L", dynasty_entry)
    assert cache.read("L").season_rating_inputs == dynasty_entry.season_rating_inputs


@pytest.mark.asyncio
async def test_grader_populates_season_inputs_on_free_refresh(tmp_path):
    # Mutation: remove the builder call from the actual refresh path.
    from app.services.grader import GraderService

    from ._grader_fixtures import _run_with_one_trade
    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state={"season": "2026", "week": 1},
        league_format="redraft")
    assert "2024" in entry.season_rating_inputs
    assert entry.season_rating_inputs["2024"]["status"] == "unavailable"
    assert "game results" in entry.season_rating_inputs["2024"]["reason"]
