"""Shared test fixtures for grader tests."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.chain_cache import ChainCacheEntry
from app.services.grader import GraderService


async def _run_with_one_trade(
    svc: GraderService, *, cache_dir, nfl_state,
    league_format: str = "dynasty", captured: dict | None = None,
    supporting_extra: dict | None = None,
):
    """Run GraderService with a single trade (transaction_id="t1") and minimal
    supporting data.  Modelled on the fixture pattern in
    api/tests/test_grader_became.py and api/tests/test_grader_holders.py.

    ``cache_dir`` is passed to ``svc.run`` so the ChainCache path is exercised.
    ``nfl_state`` is forwarded as ``_nfl_state`` (the injection point for the
    reuse-decision block).

    ``league_format`` is the platform-neutral format stamped on the chain's
    one league ("dynasty" | "keeper" | "redraft") — the input the capability
    derivation and the KTC-snapshot gate both read.
    ``supporting_extra`` is merged into the fake ``pull_supporting_data``
    return, for stages that read a key the minimal fixture omits (e.g.
    ``winners_bracket_by_league`` for the postseason lead).
    ``captured``, when given, receives the kwargs ``run`` actually handed to
    ``pull_supporting_data`` (notably ``snapshot_store``), so a test can assert
    on the wiring rather than only on the entry.
    """
    from sleeper_dynasty.models.trade import PlayerAsset, TradeSide, Trade, ResolvedTrade

    async def _progress(stage, message, **extra):
        pass

    class _FakeClient:
        async def walk_league_history(self, lid):
            return [
                SimpleNamespace(
                    league_id="L", season=2024, name="Bros",
                    total_rosters=2, playoff_week_start=15,
                    status="complete", playoff_round_type=0,
                    format=league_format,
                )
            ]

        async def get_players(self):
            return {"p1": {"full_name": "Player One", "position": "RB"}}

        async def get_rosters(self, lid):
            return [
                SimpleNamespace(owner_id="u1", players=["p1"]),
                SimpleNamespace(owner_id="u2", players=[]),
            ]

    async def _fake_history(client, current_league_id, player_names, **kwargs):
        pl = PlayerAsset("p1", "Player One")
        side1 = TradeSide("u1", [pl], [])
        side2 = TradeSide("u2", [], [pl])
        t = Trade(
            "t1", "L", 2024, 1, datetime(2024, 6, 1),
            {"u1": side1, "u2": side2},
        )
        return [ResolvedTrade(trade=t, sides={"u1": side1, "u2": side2})], {}

    async def _fake_supporting(client, chain, **kwargs):
        if captured is not None:
            captured.update(kwargs)
        return {
            "ktc_by_player_id": {},
            "matchups": {},
            "roster_to_user_by_league": {"L": {1: "u1", 2: "u2"}},
            "playoff_weeks_by_league": {"L": 15},
            "playoff_week_start_by_league": {"L": 15},
            "phase_by_lwr": {},
            "league_season_by_id": {"L": 2024},
            "owners": {
                "u1": {"owner_name": "Alice"},
                "u2": {"owner_name": "Bob"},
            },
            "league_name_by_id": {"L": "Bros"},
            "pick_value_table": {},
            "warnings": [],
            **(supporting_extra or {}),
        }

    return await svc.run(
        client=_FakeClient(),
        current_league_id="L",
        progress_cb=_progress,
        cache_dir=cache_dir,
        skip_llm=True,
        _build_trade_history=_fake_history,
        _pull_supporting_data=_fake_supporting,
        _nfl_state=nfl_state,
    )


def _v2_entry(*, capabilities: dict) -> ChainCacheEntry:
    """A minimal two-owner ChainCacheEntry with the persisted v2 signal dicts
    populated (outcome_signals/outlook_signals — see franchise_redesign
    Task 6) and both owners' full set of required fields. ``u1`` is built up
    everywhere ``u2`` is down, so ranking assertions have something real to
    check.
    """
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"u1": {"owner_name": "Alice"}, "u2": {"owner_name": "Bob"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={},
        cached_at="2026-08-16T00:00:00+00:00",
        capabilities=capabilities,
        # A completed season for both owners: without it neither qualifies for
        # a rating at all (franchise_redesign.rated_owners — the thin-evidence
        # gate), which is the correct answer for a league that has played
        # nothing but not the subject of these tests.
        season_records={
            "2024": {
                "u1": {"wins": 10, "losses": 4, "ties": 0},
                "u2": {"wins": 4, "losses": 10, "ties": 0},
            },
        },
        outcome_signals={
            "u1": {"expected_wins": 0.65, "playoff_success": 0.80, "luck": 0.10},
            "u2": {"expected_wins": 0.35, "playoff_success": 0.10, "luck": -0.10},
        },
        outlook_signals={
            "u1": {"roster_value_share": 0.60, "young_core_share": 0.55, "draft_capital": 0.70},
            "u2": {"roster_value_share": 0.40, "young_core_share": 0.20, "draft_capital": 0.30},
        },
        # Populated on both fixtures so the redraft absence test proves the
        # format gate hides the column - not that the data was never there.
        roster_ranks={
            "u1": {"rank": 1, "of": 2},
            "u2": {"rank": 2, "of": 2},
        },
    )


@pytest.fixture
def dynasty_entry() -> ChainCacheEntry:
    return _v2_entry(capabilities={"format": "dynasty"})


@pytest.fixture
def redraft_entry() -> ChainCacheEntry:
    return _v2_entry(capabilities={"format": "redraft"})
