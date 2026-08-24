"""ANTHROPIC_API_KEY unset -> refresh completes, prose stages are bypassed
cleanly rather than constructing a real writer and burning retry rounds on
`TypeError: Could not resolve authentication method...` (the Anthropic SDK's
error when neither an api_key nor ANTHROPIC_API_KEY is present).

Modelled on the fixture pattern in test_grader_story_hook.py /
tests/services/_grader_fixtures.py, but deliberately does NOT pass
skip_llm=True or inject fake writers -- this exercises the real "no key"
detection in GraderService.run rather than the budget guard or the test
injection points.
"""
import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace

import httpx

from app.services.grader import GraderService


class _FakeClient:
    async def walk_league_history(self, lid):
        return [SimpleNamespace(
            league_id="L", season=2024, name="Bros",
            total_rosters=2, playoff_week_start=15,
            status="complete", playoff_round_type=0, format="dynasty",
        )]

    async def get_players(self):
        return {"p1": {"full_name": "Bijan Robinson", "position": "RB"}}

    async def get_rosters(self, lid):
        return [
            SimpleNamespace(owner_id="u1", players=["p1"]),
            SimpleNamespace(owner_id="u2", players=[]),
        ]

    async def close(self): ...


async def _history(*a, **k):
    from sleeper_dynasty.models.trade import (
        PlayerAsset, Trade, TradeSide, ResolvedTrade)
    pl = PlayerAsset("p1", "Bijan Robinson")
    side1 = TradeSide("u1", [pl], [])
    side2 = TradeSide("u2", [], [pl])
    t = Trade("t1", "L", 2024, 1, datetime(2024, 6, 1),
              {"u1": side1, "u2": side2})
    return [ResolvedTrade(trade=t, sides={"u1": side1, "u2": side2})], {}


async def _supporting(*a, **k):
    return dict(
        ktc_by_player_id={}, matchups={},
        roster_to_user_by_league={"L": {1: "u1", 2: "u2"}},
        playoff_weeks_by_league={"L": 15},
        playoff_week_start_by_league={"L": 15},
        phase_by_lwr={},
        league_season_by_id={"L": 2024},
        owners={"u1": {"owner_name": "Alice"}, "u2": {"owner_name": "Bob"}},
        league_name_by_id={"L": "Bros"}, pick_value_table={}, warnings=[],
    )


class _PoisonWriter:
    """Constructing this proves the no-key gate failed to bypass generation
    -- the real assertion under test."""

    def __init__(self, *a, **k):
        raise AssertionError(
            "a real LLM writer was constructed despite ANTHROPIC_API_KEY "
            "being unset")


async def _progress(stage, message, **extra):
    pass


def _no_network(*a, **k):
    raise RuntimeError("network disabled in test")


def test_run_skips_prose_cleanly_with_no_api_key(monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Poison every real writer class the generation stages would construct.
    # If the no-key gate fails to bypass a stage, instantiation raises
    # AssertionError instead of silently retrying a real network call.
    import sleeper_dynasty.llm.trade_story_writer as tsw
    import sleeper_dynasty.llm.gm_rating_blurb_writer as gbw
    import sleeper_dynasty.llm.franchise_outlook_writer as fow
    monkeypatch.setattr(tsw, "TradeStoryWriter", _PoisonWriter)
    monkeypatch.setattr(gbw, "GmRatingBlurbWriter", _PoisonWriter)
    monkeypatch.setattr(fow, "FranchiseOutlookWriter", _PoisonWriter)

    # This minimal fake client is deliberately thin (no draft/projection
    # endpoints) so those unrelated stages fall back to their existing
    # tolerant except-and-continue paths -- not this fix's concern. Block
    # real network egress outright so those fallbacks can't quietly reach
    # nflverse/dynastyprocess/etc, keeping the test offline and fast.
    monkeypatch.setattr(httpx.Client, "request", _no_network)
    monkeypatch.setattr(httpx.AsyncClient, "request", _no_network)

    async def go():
        svc = GraderService()
        return await svc.run(
            client=_FakeClient(), current_league_id="L",
            progress_cb=_progress, cache_dir=None,
            _build_trade_history=_history,
            _pull_supporting_data=_supporting,
        )

    with caplog.at_level(logging.INFO, logger="app.services.grader"):
        entry = asyncio.run(go())

    # The refresh completed -- no exception escaped the poisoned writers,
    # which means none of the three stages attempted to construct one.
    assert entry is not None
    assert entry.trade_stories == {}
    assert entry.owner_rating_blurbs == {}
    assert entry.franchise_blurbs == {}

    # Detected once, up front, and logged at INFO -- not per-stage, and not
    # the wall of tracebacks a retried TypeError would have produced.
    key_msgs = [r for r in caplog.records if "ANTHROPIC_API_KEY" in r.message]
    assert len(key_msgs) == 1
    assert key_msgs[0].levelno == logging.INFO
    assert "skip" in key_msgs[0].message.lower()

    # The specific regression this fix closes: no retry-round log line for
    # any of the three prose stages (that log only fires from inside the
    # generation call this test proves never happens), and nothing logged
    # the Anthropic SDK's no-auth TypeError.
    for record in caplog.records:
        assert "retrying" not in record.message.lower()
        if record.exc_info:
            assert "Could not resolve authentication method" not in str(
                record.exc_info[1])
