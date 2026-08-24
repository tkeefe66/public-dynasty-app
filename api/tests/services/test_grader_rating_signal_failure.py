"""A failed rating-signal stage must be visible, not render as a league of C's.

Under v1 the Skill pillar was built separately, so a ``compute_rating_signals``
failure left part of the tree alive. Under v2 both pillars come from that one
call: if it raises, every signal is missing, every owner scores exactly 1500,
and every letter is a C — indistinguishable from a genuinely flat league unless
something says so.
"""
from __future__ import annotations

import pytest

from app.services.chain_cache import ChainCacheEntry
from app.services.franchise_redesign import live_ratings
from app.services.grader import GraderService

from ._grader_fixtures import _run_with_one_trade

_OFFSEASON = {"season_type": "off", "week": 0}


@pytest.mark.asyncio
async def test_a_failed_signal_stage_appends_a_warning(monkeypatch, tmp_path):
    import app.services.rating_signals as rating_signals

    def _boom(*a, **kw):
        raise RuntimeError("signal stage exploded")

    monkeypatch.setattr(rating_signals, "compute_rating_signals", _boom)

    entry = await _run_with_one_trade(
        GraderService(), cache_dir=tmp_path, nfl_state=_OFFSEASON,
    )

    assert any("rating signals" in w.lower() for w in entry.warnings), entry.warnings
    assert entry.outcome_signals == {}
    assert entry.outlook_signals == {}


def test_live_ratings_rates_nobody_when_both_signal_dicts_are_empty():
    """The same absence the thin-evidence gate renders, reached the other way:
    a stage failure, not a league that has not played."""
    entry = ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"u1": {"owner_name": "A"}, "u2": {"owner_name": "B"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={},
        cached_at="2026-08-16T00:00:00+00:00",
        # Seasons were played — the owners would otherwise qualify.
        season_records={"2024": {
            "u1": {"wins": 10, "losses": 4, "ties": 0},
            "u2": {"wins": 4, "losses": 10, "ties": 0},
        }},
        outcome_signals={},
        outlook_signals={},
    )
    assert live_ratings(entry) == {}
