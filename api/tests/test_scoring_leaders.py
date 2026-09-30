from types import SimpleNamespace

import httpx
import pytest

from sleeper_dynasty.models.league import League


class Source:
    """Small source boundary; ranking and caching run as production code."""
    def __init__(self):
        self.failed_week = None
        self.matchup_points = 12
        self.stats_calls = []

    async def get_league(self, league_id):
        return League(league_id=league_id, name="Test League", season=2026,
                      total_rosters=2, roster_positions=["WR", "BN"],
                      scoring_settings={"rec": 2}, playoff_week_start=15,
                      num_playoff_teams=2, status="in_season"), None

    async def get_nfl_state(self):
        return {"season": "2026", "season_type": "regular", "week": 3}

    async def get_players(self):
        return {"rostered": {"position": "WR", "full_name": "Rostered Player"},
                "free": {"position": "WR", "full_name": "Free Agent"}}

    async def get_stats(self, season, week):
        self.stats_calls.append(week)
        if week == self.failed_week:
            return {}
        return {"rostered": {"gp": 1, "rec": 6}, "free": {"gp": 1, "rec": 8}}

    async def get_raw_matchups(self, league_id, week):
        return [{"players_points": {"rostered": self.matchup_points}},
                {"players_points": {"inactive": 0}}]


@pytest.mark.asyncio
async def test_free_agents_rank_above_rostered_players_and_raw_cache_is_reused(tmp_path):
    # Mutation: use matchup-only totals, omit week 2, or refetch fresh cached stats.
    from app.services.scoring_leaders import load_scoring_leaders

    source = Source()
    result = await load_scoring_leaders("123", tmp_path, source)
    assert result["through_week"] == 2
    assert [(r["player_id"], r["rank"], r["points"]) for r in result["players"]] == [
        ("free", 1, 32), ("rostered", 2, 24),
    ]
    await load_scoring_leaders("123", tmp_path, source)
    assert sorted(source.stats_calls) == [1, 2]


@pytest.mark.asyncio
async def test_missing_completed_week_refuses_partial_rankings_and_retries(tmp_path):
    # Mutation: turn a failed/empty week into zero points or cache that failure.
    from app.services.scoring_leaders import load_scoring_leaders

    source = Source()
    source.failed_week = 2
    with pytest.raises(ValueError, match="Week 2"):
        await load_scoring_leaders("123", tmp_path, source)
    source.failed_week = None
    result = await load_scoring_leaders("123", tmp_path, source)
    assert result["players"][0]["points"] == 32


@pytest.mark.asyncio
async def test_points_must_reconcile_with_sleeper_matchups(tmp_path):
    # Mutation: publish raw-scored rankings that disagree with league matchup points.
    from app.services.scoring_leaders import load_scoring_leaders

    source = Source()
    source.matchup_points = 20
    with pytest.raises(ValueError, match="match"):
        await load_scoring_leaders("123", tmp_path, source)


@pytest.mark.asyncio
async def test_leaderboard_only_ranks_positions_used_by_the_league(tmp_path):
    # Mutation: expose offensive linemen/IDP/kickers as zero-point leaders in an offense-only league.
    from app.services.scoring_leaders import load_scoring_leaders

    class ExtraPositions(Source):
        async def get_players(self):
            return {**await super().get_players(), "lineman": {"position": "OT"},
                    "kicker": {"position": "K"}}

        async def get_stats(self, season, week):
            return {**await super().get_stats(season, week), "lineman": {"gp": 1},
                    "kicker": {"gp": 1, "xpm": 3}}

    result = await load_scoring_leaders("123", tmp_path, ExtraPositions())
    assert {row["position"] for row in result["players"]} == {"WR"}


@pytest.mark.asyncio
async def test_missing_free_agent_metadata_never_silently_changes_wr1(tmp_path):
    # Mutation: skip an unknown free agent and publish the second-best receiver as WR1.
    from app.services.scoring_leaders import load_scoring_leaders

    class PartialPlayers(Source):
        async def get_players(self):
            return {"rostered": {"position": "WR"}}

    with pytest.raises(ValueError, match="player details"):
        await load_scoring_leaders("123", tmp_path, PartialPlayers())


@pytest.mark.asyncio
async def test_stale_player_catalog_refetches_before_ranking(tmp_path):
    # Mutation: use a cached catalog that predates a newly activated free agent.
    from app.services.scoring_leaders import load_scoring_leaders
    from sleeper_dynasty.cache import FileCache

    FileCache(tmp_path / "scoring").write("players.json", {"rostered": {"position": "WR"}})
    result = await load_scoring_leaders("123", tmp_path, Source())
    assert result["players"][0]["player_id"] == "free"


def test_route_reports_source_rate_limit_and_closes_client(client, monkeypatch):
    # Mutation: hide an upstream 429 behind a successful empty leaderboard.
    from app.routes import scoring

    closed = []

    async def fail(*args):
        request = httpx.Request("GET", "https://api.sleeper.app/v1/state/nfl")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("rate limit", request=request, response=response)

    async def close():
        closed.append(True)

    monkeypatch.setattr(scoring, "SleeperClient", lambda: SimpleNamespace(close=close))
    monkeypatch.setattr(scoring, "load_scoring_leaders", fail)
    response = client.get("/api/league/123/scoring")
    assert response.status_code == 503
    assert "rate limit" in response.json()["detail"].lower()
    assert response.headers["retry-after"] == "60"
    assert closed == [True]


def test_route_returns_ranked_payload(client, monkeypatch):
    # Mutation: route is unregistered or strips the season/cutoff/ranks from response.
    from app.routes import scoring

    async def close():
        pass

    async def load(*args):
        return {"league_id": "123", "league_name": "Test", "season": 2026,
                "through_week": 2, "updated_at": "2026-09-30T00:00:00Z",
                "players": [{"player_id": "p", "name": "Player", "position": "WR",
                             "team": None, "rank": 1, "points": 42, "games": 2,
                             "points_per_game": 21}]}

    monkeypatch.setattr(scoring, "SleeperClient", lambda: SimpleNamespace(close=close))
    monkeypatch.setattr(scoring, "load_scoring_leaders", load)
    response = client.get("/api/league/123/scoring")
    assert response.status_code == 200
    assert response.json()["players"][0]["rank"] == 1
    assert response.json()["through_week"] == 2
