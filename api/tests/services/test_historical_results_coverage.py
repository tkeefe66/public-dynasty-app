# ruff: noqa: F811 -- imported pytest fixtures are injected as test parameters.
from copy import deepcopy

import pytest

from ._grader_fixtures import dynasty_entry  # noqa: F401
from .test_historical_rating_assets import manifest
from .test_season_rating_scope import _historical_support


def covered(entry):
    support = _historical_support(entry)
    entry.chain[0]["format"] = "dynasty"
    entry.league_season_by_id["excluded"] = 2023
    entry.roster_to_user_by_league["excluded"] = {1: "u1", 2: "u2"}
    entry.chain.append(
        {
            "league_id": "excluded",
            "season": 2023,
            "format": "dynasty",
            "status": "complete",
        }
    )
    support["playoff_week_start_by_league"]["excluded"] = 15
    support["excluded_result_seasons"] = {2023: "Postseason participation unverified"}
    support["verified_result_seasons"] = [2024]
    return support


def policy(entry, support):
    from app.services.historical_results_coverage import make_coverage

    return make_coverage(
        entry, support, 2024, verified_by="fixture", evidence_sha256="a" * 64
    )


def test_normalized_postseason_changes_invalidate_coverage(dynasty_entry):
    from app.services.historical_results_coverage import apply_coverage

    support = covered(dynasty_entry)
    coverage = policy(dynasty_entry, support).model_dump(mode="json")
    support["postseason_results_by_league"] = {"old": {1: {"champion": True}}}
    with pytest.raises(ValueError, match="changed"):
        apply_coverage(dynasty_entry, support, 2024, coverage)


def test_provisional_keeps_full_assets_and_consistent_scope(tmp_path, dynasty_entry):
    from app.services.aggregations import build_dashboard
    from app.services.historical_rating_assets import HistoricalAssetStore
    from app.services.historical_results_coverage import HistoricalResultsStore
    from app.services.leaderboard import build_leaderboard
    from app.services.season_ratings import build_season_rating_inputs

    support = covered(dynasty_entry)
    results = HistoricalResultsStore(tmp_path)
    results.import_verified(policy(dynasty_entry, support).model_dump(mode="json"))
    missing = build_season_rating_inputs(dynasty_entry, support, results_store=results)[
        "2024"
    ]
    assert missing["status"] == "unavailable"
    assert (
        "assets" in missing["reason"]
        or "asset" in missing["reason"]
        or "historical roster" in missing["reason"]
    )
    assets = HistoricalAssetStore(tmp_path, "L")
    assets.import_verified(manifest())
    dynasty_entry.season_rating_inputs = build_season_rating_inputs(
        dynasty_entry, support, asset_store=assets, results_store=results
    )
    snap = dynasty_entry.season_rating_inputs["2024"]
    assert snap["status"] == "provisional"
    assert set(snap["season_records"]) == {"2024"}
    dashboard = build_dashboard(dynasty_entry, year=2024, lens="ktc")
    board = build_leaderboard(dynasty_entry, year=2024, prev_ratings={})
    assert dashboard.rating_scope.status == board.rating_scope.status == "provisional"
    assert board.rating_scope.included_seasons == [2024]
    assert board.rating_scope.excluded_seasons[0].season == 2023
    assert {r.user_id: r.gm_rating for r in dashboard.standings} == {
        r.user_id: r.rating for r in board.rows
    }
    assert board.rows and all("assets" in row.pillars for row in board.rows)
    assert board.rating_scope.as_of == "2025-01-07"
    # A changed source or membership cannot silently reuse the approval.
    support["matchups"]["old", 1, 1]["team_points"] = 123
    changed = build_season_rating_inputs(
        dynasty_entry, support, asset_store=assets, results_store=results
    )["2024"]
    assert changed["status"] == "unavailable"
    assert "changed" in changed["reason"]


@pytest.mark.parametrize("bad", ["selected", "unknown", "no_reason", "not_verified"])
def test_coverage_rejects_unverified_target_or_incomplete_partition(dynasty_entry, bad):
    support = covered(dynasty_entry)
    if bad == "selected":
        support["excluded_result_seasons"][2024] = "Unverified"
    if bad == "unknown":
        support["excluded_result_seasons"][2022] = "Unverified"
    if bad == "no_reason":
        support["excluded_result_seasons"][2023] = " "
    if bad == "not_verified":
        support["verified_result_seasons"] = []
    with pytest.raises(ValueError):
        policy(dynasty_entry, support)


def test_provisional_digest_and_read_gate_bind_excluded_history(
    tmp_path, dynasty_entry
):
    from app.services.historical_rating_assets import HistoricalAssetStore
    from app.services.season_ratings import (
        build_season_rating_inputs,
        historical_results_digest,
        scoped_rating_entry,
    )

    support = covered(dynasty_entry)
    coverage = policy(dynasty_entry, support).model_dump(mode="json")
    store = HistoricalAssetStore(tmp_path, "L")
    store.import_verified(manifest())
    dynasty_entry.season_rating_inputs = build_season_rating_inputs(
        dynasty_entry, support, asset_store=store, results_coverage={"2024": coverage}
    )
    snap = dynasty_entry.season_rating_inputs["2024"]
    changed = deepcopy(snap)
    changed["results_coverage"]["excluded_seasons"][0]["reason"] = (
        "Different missing history"
    )
    assert historical_results_digest(changed) != historical_results_digest(snap)
    snap["status"] = "ready"
    assert scoped_rating_entry(dynasty_entry, 2024) is None
    snap["status"] = "provisional"
    snap.pop("results_coverage")
    assert scoped_rating_entry(dynasty_entry, 2024) is None


@pytest.mark.parametrize("fmt", ["dynasty", "redraft"])
def test_missing_coverage_stays_unavailable_across_refreshes(
    tmp_path, dynasty_entry, fmt
):
    from app.services.historical_rating_assets import HistoricalAssetStore
    from app.services.season_ratings import build_season_rating_inputs

    support = covered(dynasty_entry)
    dynasty_entry.chain[0]["format"] = fmt
    for (lid, week, rid), row in list(support["matchups"].items()):
        if lid == "old":
            support["matchups"]["excluded", week, rid] = deepcopy(row)
    coverage = policy(dynasty_entry, support).model_dump(mode="json")
    assets = HistoricalAssetStore(tmp_path, "L")
    assets.import_verified(manifest())
    dynasty_entry.season_rating_inputs = build_season_rating_inputs(
        dynasty_entry, support, asset_store=assets, results_coverage={"2024": coverage}
    )
    assert dynasty_entry.season_rating_inputs["2024"]["status"] == "provisional"
    support.pop("excluded_result_seasons")
    support.pop("verified_result_seasons")
    for _ in range(2):
        dynasty_entry.season_rating_inputs = build_season_rating_inputs(
            dynasty_entry, support, asset_store=assets
        )
        snapshot = dynasty_entry.season_rating_inputs["2024"]
        assert snapshot["status"] == "unavailable"
        assert "coverage" in snapshot["reason"].lower()


@pytest.mark.asyncio
async def test_refresh_preserves_coverage_requirement_after_identity_change(tmp_path):
    from app.services.chain_cache import ChainCache, ChainCacheEntry
    from app.services.grader import GraderService

    from ._grader_fixtures import _run_with_one_trade

    prior = ChainCacheEntry(
        league_id="L",
        chain=[],
        resolved_trades=[],
        grades={},
        owners={},
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="2026-06-01T00:00:00+00:00",
        owner_identity_version="old-identity",
        season_rating_inputs={"2024": {"status": "provisional"}},
    )
    ChainCache(cache_dir=tmp_path).write("L", prior)
    refreshed = await _run_with_one_trade(
        GraderService(),
        cache_dir=tmp_path,
        league_format="redraft",
        nfl_state={"season_type": "off", "week": 0},
    )
    snapshot = refreshed.season_rating_inputs["2024"]
    assert snapshot["status"] == "unavailable"
    assert snapshot["requires_results_coverage"] is True
    assert "coverage" in snapshot["reason"].lower()
