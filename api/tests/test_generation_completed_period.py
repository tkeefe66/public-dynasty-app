import httpx
import pytest
from app.services.chain_cache import ChainCache
from app.services.generation.planner import automatic_reason
from app.services.generation.registry import register_entry
from app.services.grader import GraderService

from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts
from tests.services._grader_fixtures import _run_with_one_trade


@pytest.mark.asyncio
@pytest.mark.parametrize("current_week,completed_week,phase", [(14, 13, "regular"), (15, 14, "post"), (16, 14, "post")])
async def test_completed_generation_week_survives_playoff_transition(maker, tmp_path, monkeypatch, current_week, completed_week, phase):
    def offline(*args, **kwargs):
        raise RuntimeError("network disabled")
    monkeypatch.setattr(httpx.Client, "request", offline)
    monkeypatch.setattr(httpx.AsyncClient, "request", offline)
    monkeypatch.setattr("app.services.blurb_gen.owner_rating_facts_by_scope", lambda entry: {
        "all": {"u1": OwnerRatingFacts("u1", "Alice", None, "career", 1, 80)}})
    matchups = {("L", wk, rid): {"team_points": 100, "opponent_points": 100,
        "opponent_roster_id": 3-rid, "starters": [], "players_points": {}}
        for wk in (13, 14, 15) for rid in (1, 2)}
    entry = await _run_with_one_trade(GraderService(), cache_dir=tmp_path,
        nfl_state={"season_type": "regular", "season": 2024, "week": current_week},
        supporting_extra={"matchups": matchups})
    assert entry.league_phase["phase"] == phase
    assert entry.generation_period == {"season": 2024, "week": completed_week}
    if phase == "post":
        assert entry.week_recap == {}
    summaries = [row for row in entry.generation_inputs if row["feature"] == "gm_rating_blurb"]
    assert summaries and all(row["payload"]["week"] == completed_week for row in summaries)
    cache = ChainCache(tmp_path)
    cache.write("L", entry)
    assert cache.read("L").generation_period == entry.generation_period
    async with maker.begin() as db:
        season = await register_entry(db, entry, verified=True)
        assert season.latest_week == completed_week
        for feature in ("analyst", "gm_rating_blurb", "franchise_blurb"):
            assert automatic_reason(season, feature, {"season": 2024, "week": completed_week}, 0) == ""
