"""End-to-end equivalence test: reuse path == full rebuild for unchanged inputs."""
from __future__ import annotations

import pytest

from app.services.grader import GraderService
from app.services.chain_cache import ChainCache, ChainCacheEntry
from ._grader_fixtures import _run_with_one_trade

# All 15 frozen-rollup fields the reuse path copies from the prior entry.
# Single source of truth: both the equivalence test below and the
# frozen-vs-value-layer placement tests read this constant, so a field can
# never be "frozen" in one test and "not frozen" in another.
FROZEN_FIELDS = (
    "trade_production_series", "trade_production_verdict",
    "owner_production_series", "owner_production_verdict",
    "production_week_axis", "production_week_phases",
    "trade_production_players", "owner_production_trades",
    "trade_injury", "trade_departures",
    "outcome_signals", "lineup_signals", "season_records",
    "head_to_head", "draft_skill_by_season",
)


@pytest.mark.asyncio
async def test_reuse_matches_full_rebuild_for_unchanged_inputs(monkeypatch, tmp_path):
    """Build once (full), then refresh offseason with identical inputs and a
    prior entry present: the frozen-rollup fields must be identical."""
    svc = GraderService()

    # First build — no prior entry, so full path runs and writes the cache.
    first = await _run_with_one_trade(
        svc, cache_dir=tmp_path, nfl_state={"season_type": "off", "week": 0})
    from app.services.chain_cache import ChainCache
    ChainCache(cache_dir=tmp_path).write("L", first)

    # Second build — prior entry present, offseason, no new trades -> reuse path.
    second = await _run_with_one_trade(
        svc, cache_dir=tmp_path, nfl_state={"season_type": "off", "week": 0})

    for field in FROZEN_FIELDS:
        assert getattr(second, field) == getattr(first, field), field


def _seed_prior_with_stale_signals(tmp_path) -> ChainCacheEntry:
    """A prior cache entry carrying distinctive, deliberately-stale
    outcome_signals/outlook_signals — values a fresh computation would never
    produce on its own, so equality with the prior proves reuse rather than
    coincidence."""
    prior = ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[{"trade": {"transaction_id": "t1"}}],
        grades={}, owners={"u1": {"owner_name": "A"}}, playoff_weeks_by_league={},
        roster_to_user_by_league={}, league_name_by_id={}, league_season_by_id={},
        cached_at="2026-06-01T00:00:00+00:00",
        outcome_signals={"u1": {"expected_wins": -999.0, "playoff_success": -999.0, "luck": -999.0}},
        outlook_signals={"u1": {"roster_value_share": -999.0, "young_core_share": -999.0, "draft_capital": -999.0}},
    )
    ChainCache(cache_dir=tmp_path).write("L", prior)
    return prior


def _patch_fresh_signals(monkeypatch, *, outcome_signals, outlook_signals):
    """Stand in for compute_rating_signals so the "fresh rebuild" value is
    known and distinct from the seeded prior's stale sentinel — without this,
    a passing assertion on the real minimal fixture data could coincide with
    the prior's value by accident rather than by the reuse-path logic."""
    def _fake(*args, **kwargs):
        return outcome_signals, outlook_signals, {}, {}

    monkeypatch.setattr(
        "app.services.rating_signals.compute_rating_signals", _fake)


@pytest.mark.asyncio
async def test_outlook_signals_are_never_frozen(monkeypatch, tmp_path):
    """outlook_signals must recompute on the incremental (offseason,
    no-new-trades) path — it feeds the Assets pillar, 40% of every dynasty
    and keeper grade, and freezing it would stall roster value through the
    whole offseason, exactly when dynasty value moves most."""
    prior = _seed_prior_with_stale_signals(tmp_path)
    fresh_outlook = {"u1": {"roster_value_share": 0.42, "young_core_share": 0.33, "draft_capital": 0.11}}
    _patch_fresh_signals(
        monkeypatch, outcome_signals=prior.outcome_signals, outlook_signals=fresh_outlook)

    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state={"season_type": "off", "week": 0})

    assert entry.outlook_signals == fresh_outlook
    assert entry.outlook_signals != prior.outlook_signals


@pytest.mark.asyncio
async def test_outcome_signals_are_frozen(monkeypatch, tmp_path):
    """outcome_signals is a historical rollup (season results) and must be
    reused verbatim from the prior entry on the incremental path, not
    recomputed from a fresh (and here, deliberately different) rebuild."""
    prior = _seed_prior_with_stale_signals(tmp_path)
    fresh_outcome = {"u1": {"expected_wins": 0.5, "playoff_success": 0.5, "luck": 0.0}}
    _patch_fresh_signals(
        monkeypatch, outcome_signals=fresh_outcome, outlook_signals=prior.outlook_signals)

    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state={"season_type": "off", "week": 0})

    assert entry.outcome_signals == prior.outcome_signals
    assert entry.outcome_signals != fresh_outcome
