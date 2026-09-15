import asyncio
from datetime import datetime

import pytest

from app.services.grader import GraderService
from app.services.chain_cache import ChainCacheEntry
from sleeper_dynasty.models.player import KTCValue


class _FakeClient:
    async def walk_league_history(self, lid):
        from types import SimpleNamespace
        return [SimpleNamespace(league_id="L", season=2024, name="Bros",
                                total_rosters=10, playoff_week_start=15,
                                format="dynasty")]
    async def get_players(self):
        return {"p1": {"full_name": "Bijan Robinson", "position": "RB"}}
    async def get_rosters(self, lid):
        from types import SimpleNamespace
        return [SimpleNamespace(owner_id="u_mike", players=["p1"])]
    async def close(self): ...


def _supporting_factory(matchups=None, roster_map=None):
    async def _supporting(*a, **k):
        return dict(
            ktc_by_player_id={"p1": KTCValue(name="Bijan", normalized_name="bijan",
                                             position="RB", superflex_value=6000)},
            matchups=matchups or {},
            roster_to_user_by_league=roster_map or {"L": {1: "u_mike"}},
            playoff_weeks_by_league={"L": 15},
            playoff_week_start_by_league={"L": 15},
            phase_by_lwr={},
            league_season_by_id={"L": 2024},
            owners={"u_mike": {"owner_name": "Mike"}, "u_tom": {"owner_name": "Tom"}},
            league_name_by_id={"L": "Bros"}, pick_value_table={}, warnings=[],
        )
    return _supporting


async def _history(*a, **k):
    from sleeper_dynasty.models.trade import (
        PlayerAsset, PickAsset, Trade, TradeSide, ResolvedTrade)
    # Mike receives Bijan (player) for a 2025 1st he gave away.
    pick = PickAsset(2025, 1, "u_mike")
    pl = PlayerAsset("p1", "Bijan Robinson")
    mike = TradeSide("u_mike", [pl], [pick]); tom = TradeSide("u_tom", [pick], [pl])
    t = Trade("t1", "L", 2024, 1, datetime(2024, 6, 1),
              {"u_mike": mike, "u_tom": tom})
    return [ResolvedTrade(trade=t, sides={"u_mike": mike, "u_tom": tom})], {}


class _Writer:
    def write(self, facts):
        return {"verdict": "v", "body": "b"}


def test_run_populates_became_grades():
    # Bijan scores 18 in week 5 on Mike's roster (rid 1) post-trade.
    matchups = {("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                              "players_points": {"p1": 18.0}}}
    events = []
    async def cb(stage, message, **x): events.append(stage)

    async def go():
        return await GraderService().run(
            client=_FakeClient(), current_league_id="L", progress_cb=cb,
            cache_dir=None, _build_trade_history=_history,
            _pull_supporting_data=_supporting_factory(matchups), _story_writer=_Writer(),
        )

    entry: ChainCacheEntry = asyncio.run(go())
    assert "t1" in entry.became_grades
    mike = entry.became_grades["t1"]["grades"]["u_mike"]
    assert mike["ktc"] == 6000.0
    assert mike["production"] == 18.0
    assert mike["regular"] == 18.0
    assert mike["playoff"] == 0.0
    assert mike["toilet"] == 0.0
    assert "Bijan Robinson" in mike["terminal_labels"]
    assert "became" in events
    assert entry.became_grades["t1"].get("terminal_hash")


def test_run_keeps_terminal_fingerprint_stable_when_assets_unchanged(tmp_path):
    # The fingerprint describes the assets, not freshness of their grades.
    matchups = {("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                              "players_points": {"p1": 18.0}}}
    async def cb(stage, message, **x): ...

    async def run_once():
        return await GraderService().run(
            client=_FakeClient(), current_league_id="L", progress_cb=cb,
            cache_dir=tmp_path, _build_trade_history=_history,
            _pull_supporting_data=_supporting_factory(matchups), _story_writer=_Writer(),
        )

    first = asyncio.run(run_once())
    from app.services.chain_cache import ChainCache
    ChainCache(cache_dir=tmp_path).write("L", first)
    h1 = first.became_grades["t1"]["terminal_hash"]

    second = asyncio.run(run_once())
    h2 = second.became_grades["t1"]["terminal_hash"]
    assert h1 == h2


def test_became_refresh_updates_scores_and_values_without_new_trade(tmp_path):
    # Reusing by terminal asset IDs alone must fail: same roster, new scores
    # (including a correction within the same week), and a new market value.
    from app.services.chain_cache import ChainCache

    async def cb(stage, message, **extra):
        pass

    async def go():
        resolved, _ = await _history()
        from dataclasses import asdict
        resolved_dicts = [asdict(rt) for rt in resolved]
        supporting = await _supporting_factory()()
        grader = GraderService()
        kwargs = dict(resolved=resolved, resolved_dicts=resolved_dicts,
                      supporting=supporting, current_league_id="L",
                      cache_dir=tmp_path, progress_cb=cb)
        first = await grader._compute_became(**kwargs)
        entry = ChainCacheEntry(
            league_id="L", chain=[], resolved_trades=[], grades={}, owners={},
            playoff_weeks_by_league={}, roster_to_user_by_league={},
            league_name_by_id={}, league_season_by_id={}, cached_at="",
            became_grades=first)
        ChainCache(tmp_path).write("L", entry)
        for points, value in [(18.0, 6100), (20.5, 5900)]:
            supporting["matchups"] = {
                ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                              "players_points": {"p1": points}}}
            supporting["ktc_by_player_id"]["p1"].superflex_value = value
            result = await grader._compute_became(**kwargs)
            actual = result["t1"]["grades"]["u_mike"]
            assert actual["production"] == points
            assert actual["regular"] == points
            assert actual["ktc"] == value
            entry.became_grades = result
            ChainCache(tmp_path).write("L", entry)

    asyncio.run(go())


@pytest.mark.parametrize("skip_llm", [True, False])
def test_refresh_drops_unscored_story_when_first_points_arrive(tmp_path, skip_llm):
    from app.services.chain_cache import ChainCache

    async def cb(stage, message, **extra):
        pass

    async def go():
        kwargs = dict(client=_FakeClient(), current_league_id="L", progress_cb=cb,
                      cache_dir=tmp_path, _build_trade_history=_history)
        first = await GraderService().run(
            **kwargs, _pull_supporting_data=_supporting_factory(),
            _story_writer=_Writer())
        first.trade_stories["t1"] = {
            "verdict": "No points yet", "body": "The season has not started.",
            "facts_hash": "old", "generated_at": first.cached_at}
        first.llm_generated_at = first.cached_at
        ChainCache(tmp_path).write("L", first)
        second = await GraderService().run(
            **kwargs, skip_llm=skip_llm, _story_writer=_Writer(),
            _pull_supporting_data=_supporting_factory({
                ("L", 5, 1): {"players": ["p1"], "starters": ["p1"],
                              "players_points": {"p1": 18.0}}}))
        assert second.grades["t1"]["production_total"]["u_mike"] == 18.0
        assert "t1" not in second.trade_stories

    asyncio.run(go())
