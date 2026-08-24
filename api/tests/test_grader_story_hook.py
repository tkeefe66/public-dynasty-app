import os
import asyncio
from datetime import datetime

from app.services.grader import GraderService
from app.services.chain_cache import ChainCacheEntry


class _FakeClient:
    async def walk_league_history(self, lid):
        from types import SimpleNamespace
        return [SimpleNamespace(league_id="L", season=2024, name="Bros",
                                total_rosters=10, playoff_week_start=15)]
    async def get_players(self):
        return {"p1": {"full_name": "Bijan Robinson", "position": "RB"}}
    async def close(self): ...


async def _supporting(*a, **k):
    return dict(
        ktc_by_player_id={}, matchups={}, roster_to_user_by_league={},
        playoff_weeks_by_league={"L": 15},
        playoff_week_start_by_league={"L": 15},
        phase_by_lwr={},
        league_season_by_id={"L": 2024},
        owners={"u_mike": {"owner_name": "Mike"}, "u_tom": {"owner_name": "Tom"}},
        league_name_by_id={"L": "Bros"}, pick_value_table={}, warnings=[],
    )


async def _history(*a, **k):
    from sleeper_dynasty.models.trade import (
        PlayerAsset, PickAsset, Trade, TradeSide, ResolvedTrade)
    pick = PickAsset(2025, 1, "u_mike")
    pl = PlayerAsset("p1", "Bijan Robinson")
    mike = TradeSide("u_mike", [pl], [pick]); tom = TradeSide("u_tom", [pick], [pl])
    t = Trade("t1", "L", 2024, 1, datetime(2024, 6, 1),
              {"u_mike": mike, "u_tom": tom})
    return [ResolvedTrade(trade=t, sides={"u_mike": mike, "u_tom": tom})], {}


def test_run_populates_trade_stories_with_injected_writer(monkeypatch):
    class FakeWriter:
        def write(self, facts):
            return {"verdict": "Mike robbed Tom.", "body": "Not close."}

    events = []
    async def cb(stage, message, **x): events.append(stage)

    async def go():
        svc = GraderService()
        return await svc.run(
            client=_FakeClient(), current_league_id="L", progress_cb=cb,
            cache_dir=None, _build_trade_history=_history,
            _pull_supporting_data=_supporting, _story_writer=FakeWriter(),
        )

    entry: ChainCacheEntry = asyncio.run(go())
    assert entry.trade_stories["t1"]["verdict"] == "Mike robbed Tom."
    assert "u_mike" in entry.owner_dossiers
    assert "stories" in events
