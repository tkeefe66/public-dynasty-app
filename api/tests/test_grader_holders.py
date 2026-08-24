# tests/test_grader_holders.py
import asyncio
from types import SimpleNamespace
from datetime import datetime
from app.services.grader import GraderService


class _Client:
    async def walk_league_history(self, lid):
        return [SimpleNamespace(league_id="L", season=2024, name="Bros", total_rosters=2, playoff_week_start=15)]
    async def get_players(self): return {}
    async def get_rosters(self, lid):
        return [SimpleNamespace(owner_id="u_a", players=["4866", "12493"]),
                SimpleNamespace(owner_id="u_b", players=["777"])]
    async def close(self): ...


async def _supp(*a, **k):
    return dict(ktc_by_player_id={}, matchups={}, roster_to_user_by_league={},
                playoff_weeks_by_league={"L": 15}, league_season_by_id={"L": 2024},
                owners={}, league_name_by_id={"L": "Bros"}, pick_value_table={}, warnings=[],
                owners_display={}, positions={})

async def _hist(*a, **k): return [], {}


def test_run_collects_current_holders():
    async def go():
        return await GraderService().run(
            client=_Client(), current_league_id="L", progress_cb=lambda *a, **k: _noop(),
            cache_dir=None, _build_trade_history=_hist, _pull_supporting_data=_supp,
            _story_writer=type("W", (), {"write": lambda self, f: {"verdict": "v", "body": "b"}})())
    async def _noop(): return None
    entry = asyncio.run(go())
    assert entry.current_holders == {"4866": "u_a", "12493": "u_a", "777": "u_b"}
