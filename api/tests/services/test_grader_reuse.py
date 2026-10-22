"""Tests for the incremental-reuse path in GraderService.run.

When the NFL is offseason/between-weeks AND no new trades exist since the
prior cache entry, GraderService.run reuses the prior entry's frozen
historical rollups (production series, injury, rating signals) instead of
recomputing them, while ALWAYS recomputing the cheap value layer.
"""
from __future__ import annotations

import pytest

from app.services.grader import GraderService
from ._grader_fixtures import _run_with_one_trade


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_offseason_no_new_trades_reuses_production(monkeypatch, tmp_path):
    """When offseason and no new trades, the production-series builder is NOT
    called — the prior entry's rollups are reused verbatim."""
    from app.services.chain_cache import ChainCache, ChainCacheEntry

    # Seed a prior entry with a sentinel production payload.
    prior = ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[{"trade": {"transaction_id": "t1"}}],
        grades={}, owners={"u1": {"owner_name": "A"}}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={}, league_season_by_id={},
        cached_at="2026-06-01T00:00:00+00:00",
        trade_production_series={"t1": {"u1": {"total": [[2025, 1, 9.0]]}}},
    )
    ChainCache(cache_dir=tmp_path).write("L", prior)

    called = {"production": False}

    def _fake_production(**kwargs):
        called["production"] = True
        return {
            "trade_production_series": {}, "trade_production_verdict": {},
            "owner_production_series": {}, "owner_production_verdict": {},
            "production_week_axis": [], "production_week_phases": [],
            "trade_production_players": {}, "owner_production_trades": {},
        }

    monkeypatch.setattr(
        "app.services.grader.compute_production_series_payload", _fake_production)

    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state={"season_type": "off", "week": 0})

    assert called["production"] is False
    assert entry.trade_production_series == {"t1": {"u1": {"total": [[2025, 1, 9.0]]}}}


@pytest.mark.asyncio
async def test_in_season_recomputes_production(monkeypatch, tmp_path):
    """When scoring is in progress, the production builder IS called even with
    no new trades (the live week still changes)."""
    from app.services.chain_cache import ChainCache, ChainCacheEntry

    prior = ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[{"trade": {"transaction_id": "t1"}}],
        grades={}, owners={"u1": {"owner_name": "A"}}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={}, league_season_by_id={},
        cached_at="2026-06-01T00:00:00+00:00",
        trade_production_series={"t1": {"u1": {"total": [[2025, 1, 9.0]]}}},
    )
    ChainCache(cache_dir=tmp_path).write("L", prior)

    called = {"production": False}

    def _fake_production(**kwargs):
        called["production"] = True
        return {
            "trade_production_series": {}, "trade_production_verdict": {},
            "owner_production_series": {}, "owner_production_verdict": {},
            "production_week_axis": [], "production_week_phases": [],
            "trade_production_players": {}, "owner_production_trades": {},
        }

    monkeypatch.setattr(
        "app.services.grader.compute_production_series_payload", _fake_production)

    await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path,
        nfl_state={"season_type": "regular", "week": 3})

    assert called["production"] is True


@pytest.mark.asyncio
async def test_offseason_reuses_signals(monkeypatch, tmp_path):
    """When offseason and no new trades, the historical signal pillars
    (outcome_signals, lineup_signals, draft_skill_by_season, season_records,
    head_to_head) are reused from the prior entry, not recomputed."""
    from app.services.chain_cache import ChainCache, ChainCacheEntry

    # Seed a prior entry with distinctive signal values that fresh computation
    # would NOT produce.
    prior = ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[{"trade": {"transaction_id": "t1"}}],
        grades={}, owners={"u1": {"owner_name": "A"}}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={}, league_season_by_id={},
        cached_at="2026-06-01T00:00:00+00:00",
        # Distinctive values that will prove reuse vs. recompute.
        outcome_signals={"u1": {"wins": 5.0, "points_for": 1234.5}},
        lineup_signals={"u1": {"lineup_skill": 0.82, "efficiency": 0.91}},
        draft_skill_by_season={"2024": {"u1": 0.75}},
        season_records={"2024": {"u1": {"wins": 12, "losses": 1}}},
        head_to_head={"u1": {"u2": {"wins": 3, "losses": 1}}},
    )
    ChainCache(cache_dir=tmp_path).write("L", prior)

    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state={"season_type": "off", "week": 0})

    # Assert all five signal fields were reused from the prior entry.
    assert entry.outcome_signals == {"u1": {"wins": 5.0, "points_for": 1234.5}}
    assert entry.lineup_signals == {"u1": {"lineup_skill": 0.82, "efficiency": 0.91}}
    assert entry.draft_skill_by_season == {"2024": {"u1": 0.75}}
    assert entry.season_records == {"2024": {"u1": {"wins": 12, "losses": 1}}}
    assert entry.head_to_head == {"u1": {"u2": {"wins": 3, "losses": 1}}}


@pytest.mark.asyncio
async def test_offseason_refresh_keeps_fresh_provider_records_over_old_h2h_cache(tmp_path):
    # Mutation: frozen season_records/outcome_signals overwrite provider corrections.
    from app.services.chain_cache import ChainCache, ChainCacheEntry
    prior = ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[{"trade": {"transaction_id": "t1"}}],
        grades={}, owners={"u1": {"owner_name": "A"}}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={}, league_season_by_id={},
        cached_at="2026-06-01T00:00:00+00:00",
        season_records={"2024": {"u1": {"wins": 5, "losses": 1}}},
        outcome_signals={"u1": {"wins": 5.0}},
    )
    ChainCache(cache_dir=tmp_path).write("L", prior)
    entry = await _run_with_one_trade(GraderService(), cache_dir=tmp_path,
        nfl_state={"season_type": "off", "week": 0}, supporting_extra={
            "roster_records_by_league": {"L": {
                "1": {"wins": 10, "losses": 2, "ties": 0,
                      "points_for": 878.54, "points_against": 800.0},
                "2": {"wins": 2, "losses": 10, "ties": 0,
                      "points_for": 751.24, "points_against": 900.0}}}})
    assert entry.season_records["2024"]["u1"]["wins"] == 10
    assert entry.outcome_signals != prior.outcome_signals
    from app.services.aggregations import build_dashboard
    dashboard = build_dashboard(entry, year=2024, lens="ktc")
    row = next(row for row in dashboard.standings if row.user_id == "u1")
    assert row.season_record == "10-2" and row.season_wins == 10
