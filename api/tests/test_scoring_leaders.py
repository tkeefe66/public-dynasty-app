from types import SimpleNamespace

import httpx
import pytest

from sleeper_dynasty.models.league import League, Roster
from sleeper_dynasty.models.scoring import ThresholdBonus


def roster(roster_id, owner_id, players):
    return Roster(roster_id=roster_id, owner_id=owner_id, owner_name="Team",
                  players=players, wins=0, losses=0, ties=0, points_for=0, points_against=0)


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
                "inactive": {"position": "WR", "full_name": "Inactive Player"},
                "free": {"position": "WR", "full_name": "Free Agent"}}

    async def get_rosters(self, league_id):
        return [roster(1, "owner", ["rostered", "inactive"]), roster(2, "", [])]

    async def get_users(self, league_id):
        return {"owner": {"display_name": "Manager", "team_name": "First Team"}}

    async def get_stats(self, season, week):
        self.stats_calls.append(week)
        if week == self.failed_week:
            return {}
        return {"rostered": {"gp": 1, "rec": 6}, "free": {"gp": 1, "rec": 8}}

    async def get_raw_matchups(self, league_id, week):
        return [{"players_points": {"rostered": self.matchup_points}},
                {"players_points": {"inactive": 0}}]


@pytest.mark.asyncio
@pytest.mark.parametrize("absent", ["free", "rostered"])
async def test_yahoo_absent_free_agent_is_disclosed_but_absent_roster_blocks(tmp_path, absent):
    # Mutation: silently exclude players, rank excluded data, or permit missing rostered players.
    from app.services.scoring_leaders import load_scoring_leaders
    from sleeper_dynasty.api.owner_identity import OwnerIdentity, OwnerIdentityClient
    from sleeper_dynasty.cache import FileCache

    class YahooPool(Source):
        async def get_scoring_availability(self, league_id, player_ids):
            assert set(player_ids) == {"rostered", "inactive", "free"}
            return {pid: pid != absent for pid in player_ids}
        async def get_scoring_points(self, league_id, week, player_ids):
            expected = {"rostered": 12, "inactive": 0}
            if not absent:
                expected["free"] = 16
            assert set(player_ids) == set(expected)
            return expected

    source = OwnerIdentityClient(YahooPool(), OwnerIdentity({"owner": "canonical"}, {"canonical": "Manager"}))
    if absent == "rostered":
        with pytest.raises(ValueError, match="rostered"):
            await load_scoring_leaders("999.l.123", tmp_path, source)
        assert not list((tmp_path / "scoring").glob("board_*.json"))
        return
    result = await load_scoring_leaders("999.l.123", tmp_path, source)
    assert [(p["player_id"], p["rank"], p["points"]) for p in result["players"]] == [("rostered", 1, 24)]
    assert result["excluded_players"] == [{"player_id": "free", "name": "Free Agent", "position": "WR"}]
    assert result["franchises"][0]["owner_id"] == "canonical"
    assert "free" in FileCache(tmp_path / "scoring").read("stats_yahoo_2026_1.json")
    # Yahoo adding the player must revalidate the expanded set and restore its rank.
    absent = ""
    cache = FileCache(tmp_path / "scoring")
    for board in (tmp_path / "scoring").glob("board_v4_*.json"):
        cache.invalidate(board.name)
    refreshed = await load_scoring_leaders("999.l.123", tmp_path, source)
    assert refreshed["excluded_players"] == []
    assert [(p["player_id"], p["rank"]) for p in refreshed["players"]] == [("free", 1), ("rostered", 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize("league_format", ["redraft", "keeper", "dynasty"])
async def test_yahoo_reconciles_free_agents_bonuses_and_ownership(tmp_path, league_format):
    # Mutation: use matchup-only verification, omit free agents or gate on dynasty.
    from app.services.scoring_leaders import load_scoring_leaders

    class YahooSource(Source):
        async def get_league(self, league_id):
            league, prior = await super().get_league(league_id)
            league.format = league_format
            league.scoring_bonuses = [ThresholdBonus(("rec",), 8, 5)]
            return league, prior

        async def get_raw_matchups(self, *args):
            raise AssertionError("Yahoo validation must not depend on playoff matchups")

        async def get_scoring_points(self, league_id, week, player_ids):
            assert set(player_ids) == {"rostered", "free", "inactive"}
            return {"rostered": 12, "free": self.free_points, "inactive": 0}

    source = YahooSource()
    source.free_points = 99
    with pytest.raises(ValueError, match="match Yahoo"):
        await load_scoring_leaders("999.l.123", tmp_path, source)
    source.free_points = 21
    result = await load_scoring_leaders("999.l.123", tmp_path, source)
    assert [(p["player_id"], p["points"]) for p in result["players"]] == [("free", 42), ("rostered", 24)]
    assert result["through_week"] == 2
    assert result["franchises"][0]["players"][0]["rank"] == 2


@pytest.mark.asyncio
async def test_yahoo_cache_isolates_normalization_scoring_and_owner_mapping(tmp_path):
    # Mutation: share normalized stats/results across platforms, leagues or owner-map versions.
    from app.services.scoring_leaders import load_scoring_leaders
    from sleeper_dynasty.api.owner_identity import OwnerIdentity, OwnerIdentityClient
    from sleeper_dynasty.cache import FileCache

    class YahooSource(Source):
        rate = 3
        async def get_league(self, league_id):
            league, previous = await super().get_league(league_id)
            league.scoring_settings = {"rec": self.rate}
            return league, previous
        async def get_players(self):
            raise AssertionError("Identical canonical player catalog should be shared")
        async def get_stats(self, season, week):
            self.stats_calls.append(week)
            return {"rostered": {"gp": 1, "rec": 7}, "free": {"gp": 1, "rec": 9}}
        async def get_scoring_points(self, league_id, week, player_ids):
            return {"rostered": 7 * self.rate, "free": 9 * self.rate, "inactive": 0}

    await load_scoring_leaders("123", tmp_path, Source())
    source = YahooSource()
    first = await load_scoring_leaders("999.l.123", tmp_path, source)
    assert first["players"][0]["points"] == 54
    assert sorted(source.stats_calls) == [1, 2]
    source.rate = 4
    second = await load_scoring_leaders("999.l.456", tmp_path, source)
    assert second["players"][0]["points"] == 72
    assert sorted(source.stats_calls) == [1, 2]
    # Mapping changes invalidate derived ownership without rewriting original data.
    identity = OwnerIdentity({"owner": "canonical"}, {"canonical": "Corrected"})
    mapped = await load_scoring_leaders("999.l.456", tmp_path, OwnerIdentityClient(source, identity))
    assert mapped["franchises"][0]["owner_id"] == "canonical"
    assert mapped["franchises"][0]["owner_name"] == "Corrected"
    assert FileCache(tmp_path / "scoring").read("rosters_v3_yahoo_999.l.456_.json")[0]["owner_id"] == "owner"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_position", [None, "K", "DEF"])
async def test_yahoo_kicker_defense_actuals_and_missing_stats(tmp_path, bad_position):
    # Mutation: skip kicker/defense reconciliation or replace missing stats with zero.
    from app.services.scoring_leaders import load_scoring_leaders

    class YahooSource(Source):
        async def get_league(self, league_id):
            league, prior = await super().get_league(league_id)
            league.roster_positions = ["K", "DEF"]
            league.scoring_settings = {"fgm_50p": 5, "pts_allow_0": 10}
            league.scoring_bonuses = [ThresholdBonus(("fgm_50p",), 2, 3)]
            return league, prior
        async def get_players(self):
            return {"k": {"position": "K"}, "d": {"position": "DEF"}}
        async def get_rosters(self, league_id):
            return [roster(1, "owner", ["k"]), roster(2, "", [])]
        async def get_stats(self, season, week):
            return {"k": {"gp": 1, "fgm_50p": 2}, "d": {"gp": 1, "pts_allow": 0, "pts_allow_0": 1}}
        async def get_scoring_points(self, league_id, week, player_ids):
            return {"k": 14 if bad_position == "K" else 13,
                    "d": 11 if bad_position == "DEF" else 10}

    if bad_position:
        with pytest.raises(ValueError, match="match Yahoo"):
            await load_scoring_leaders("999.l.123", tmp_path, YahooSource())
    else:
        result = await load_scoring_leaders("999.l.123", tmp_path, YahooSource())
        assert {p["position"]: p["points"] for p in result["players"]} == {"K": 26, "DEF": 20}


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
@pytest.mark.parametrize("rule_format", ["typed", "legacy", "mixed"])
async def test_bonuses_reconcile_matchups_and_survive_cached_league_settings(tmp_path, rule_format):
    from app.services.scoring_leaders import load_scoring_leaders
    from sleeper_dynasty.cache import FileCache

    class BonusSource(Source):
        async def get_league(self, league_id):
            league, prior = await super().get_league(league_id)
            league.scoring_bonuses = [ThresholdBonus(("rec",), 6, 3),
                                      ThresholdBonus(("rec",), 8, 5)]
            if rule_format != "typed":
                league.scoring_settings.update({"bonus_gte:rec:6": 3, "bonus_gte:rec:8": 5})
            if rule_format == "legacy":
                league.scoring_bonuses = []
            return league, prior

    source = BonusSource()
    source.matchup_points = 15
    expected = [("free", 48), ("rostered", 30)]
    first = await load_scoring_leaders("123", tmp_path, source)
    assert [(r["player_id"], r["points"]) for r in first["players"]] == expected
    cache = FileCache(tmp_path / "scoring")
    cache.invalidate("board_v4_sleeper_123_.json")
    if rule_format == "legacy":
        saved = cache.read("league_v3_sleeper_123.json")
        saved.pop("scoring_bonuses")
        cache.write("league_v3_sleeper_123.json", saved)
    second = await load_scoring_leaders("123", tmp_path, source)
    assert [(r["player_id"], r["points"]) for r in second["players"]] == expected
    assert sorted(source.stats_calls) == [1, 2]


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
            return {"rostered": {"position": "WR"}, "inactive": {"position": "WR"}}

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


@pytest.mark.asyncio
async def test_franchises_keep_global_ranks_full_totals_and_unranked_roster_members(tmp_path):
    # Mutation: rerank a team's players, sum only points earned for that team,
    # omit inactive/unowned rosters, or give missing scores a zero and a rank.
    from app.services.scoring_leaders import load_scoring_leaders
    from sleeper_dynasty.cache import FileCache

    # A still-fresh pre-franchise cache must not omit the new view.
    FileCache(tmp_path / "scoring").write("leaders_123.json", {"players": []})
    result = await load_scoring_leaders("123", tmp_path, Source())
    team, empty = result["franchises"]
    assert (team["roster_id"], team["name"], team["owner_name"]) == (1, "First Team", "Manager")
    assert team["players"][0] == result["players"][1]
    assert (team["players"][0]["rank"], team["players"][0]["points"]) == (2, 24)
    inactive = team["players"][1]
    assert (inactive["name"], inactive["rank"], inactive["points"], inactive["points_per_game"]) == (
        "Inactive Player", None, None, None)
    assert empty["roster_id"] == 2 and empty["players"] == []
    assert empty["name"] == "Franchise 2" and empty["owner_name"] is None


@pytest.mark.asyncio
async def test_incomplete_rosters_fail_instead_of_mislabeling_players_as_free_agents(tmp_path):
    # Mutation: accept one of two rosters and label the missing team's players free agents.
    from app.services.scoring_leaders import load_scoring_leaders

    class PartialRosters(Source):
        async def get_rosters(self, league_id):
            return (await super().get_rosters(league_id))[:1]

    with pytest.raises(ValueError, match="roster"):
        await load_scoring_leaders("123", tmp_path, PartialRosters())


@pytest.mark.asyncio
async def test_roster_changes_refresh_without_recalculating_player_ranks(tmp_path):
    # Mutation: keep a stale owner after the response cache expires, or drop scores on transfer.
    from app.services.scoring_leaders import load_scoring_leaders
    from sleeper_dynasty.cache import FileCache

    source = Source()
    await load_scoring_leaders("123", tmp_path, source)
    cache = FileCache(tmp_path / "scoring")
    cache.invalidate("board_v4_sleeper_123_.json")
    cache.invalidate("rosters_v3_sleeper_123_.json")

    async def transferred(league_id):
        return [roster(1, "owner", []), roster(2, "", ["rostered"])]
    source.get_rosters = transferred
    result = await load_scoring_leaders("123", tmp_path, source)
    assert result["franchises"][0]["players"] == []
    assert result["franchises"][1]["players"][0]["points"] == 24
    assert result["franchises"][1]["players"][0]["rank"] == 2
    assert sorted(source.stats_calls) == [1, 2]


@pytest.mark.asyncio
async def test_roster_only_positions_keep_ties_with_unrostered_players(tmp_path):
    # Mutation: calculate tie labels using only positions in the starting lineup.
    from app.services.scoring_leaders import load_scoring_leaders

    class RemovedKickerSlot(Source):
        async def get_players(self):
            return {**await super().get_players(), "k1": {"position": "K"}, "k2": {"position": "K"}}

        async def get_stats(self, season, week):
            return {**await super().get_stats(season, week), "k1": {"gp": 1}, "k2": {"gp": 1}}

        async def get_rosters(self, league_id):
            return [roster(1, "owner", ["k1"]), roster(2, "", [])]

    result = await load_scoring_leaders("123", tmp_path, RemovedKickerSlot())
    assert all(p["position"] == "WR" for p in result["players"])
    kicker = result["franchises"][0]["players"][0]
    assert (kicker["rank"], kicker["points"], kicker["tied"]) == (1, 0, True)


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

    async def connected(*args, **kwargs):
        return SimpleNamespace(close=close)
    monkeypatch.setattr(scoring, "connected_client", connected)
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
                "through_week": 2, "updated_at": "2026-09-30T00:00:00Z", "franchises": [
                    {"roster_id": 1, "owner_id": "owner", "name": "First Team", "owner_name": "Manager",
                     "players": [{"player_id": "inactive", "name": "Inactive", "position": "WR",
                                  "rank": None, "points": None, "games": 0, "points_per_game": None}]}],
                "players": [{"player_id": "p", "name": "Player", "position": "WR",
                             "team": None, "rank": 1, "points": 42, "games": 2,
                             "points_per_game": 21}]}

    async def connected(*args, **kwargs):
        return SimpleNamespace(close=close)
    monkeypatch.setattr(scoring, "connected_client", connected)
    monkeypatch.setattr(scoring, "load_scoring_leaders", load)
    monkeypatch.setattr(scoring, "NameOverrideStore", lambda path: SimpleNamespace(read=lambda league: {"owner": "Saved name"}))
    response = client.get("/api/league/123/scoring")
    assert response.status_code == 200
    assert response.json()["players"][0]["rank"] == 1
    assert response.json()["through_week"] == 2
    assert response.json()["franchises"][0]["owner_name"] == "Saved name"
    assert response.json()["franchises"][0]["players"][0]["points"] is None


def test_yahoo_route_uses_requesting_members_connection(client, monkeypatch):
    # Mutation: retain numeric-only guard or select another member's credentials.
    from app.routes import scoring
    closed = []
    async def close():
        closed.append(True)
    async def connected(league_id, *, db, user_id):
        assert league_id == "999.l.123" and user_id == "test-user" and db is not None
        return SimpleNamespace(close=close)
    async def load(league_id, *args):
        return {"league_id": league_id, "league_name": "Yahoo", "season": 2026,
                "through_week": 2, "updated_at": "2026-10-01T00:00:00Z", "players": [], "franchises": [],
                "excluded_players": [{"player_id": "absent", "name": "Absent Player", "position": "RB"}]}
    monkeypatch.setattr(scoring, "connected_client", connected, raising=False)
    monkeypatch.setattr(scoring, "load_scoring_leaders", load)
    response = client.get("/api/league/999.l.123/scoring")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["excluded_players"][0]["name"] == "Absent Player"
    assert closed == [True]


@pytest.mark.parametrize("kind,status", [("auth", 409), ("limit", 503), ("data", 503), ("unsupported", 422)])
def test_yahoo_route_handles_client_creation_failures(client, monkeypatch, kind, status):
    # Mutation: only catch errors after creation, losing typed OAuth and throttle failures.
    from app.routes import scoring
    from sleeper_dynasty.api.yahoo import YahooAuthenticationError, YahooRateLimitError, YahooDataError, YahooUnsupportedScoringError
    errors = {"auth": YahooAuthenticationError("Reconnect Yahoo"),
              "limit": YahooRateLimitError("Yahoo rate limit", retry_after=900),
              "data": YahooDataError("Yahoo request timed out; retry later."),
              "unsupported": YahooUnsupportedScoringError("Unsupported Yahoo scoring category")}
    async def connected(*args, **kwargs):
        raise errors[kind]
    monkeypatch.setattr(scoring, "connected_client", connected, raising=False)
    response = client.get("/api/league/999.l.123/scoring")
    assert response.status_code == status
    assert response.json()["detail"] == str(errors[kind])
    if kind == "limit":
        assert response.headers["retry-after"] == "900"
