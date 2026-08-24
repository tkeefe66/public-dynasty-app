from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty.api.sleeper import SleeperClient
from sleeper_dynasty.models.league import League, Roster, Matchup, DraftPick

from tests.helpers import load_fixture


def mock_response(fixture_name: str) -> MagicMock:
    """Create a mock httpx Response with sync json() and raise_for_status()."""
    resp = MagicMock()
    resp.json.return_value = load_fixture(fixture_name)
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture
def client():
    return SleeperClient()


class TestGetUserId:
    @pytest.mark.asyncio
    async def test_returns_user_id(self, client):
        resp = mock_response("user.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            user_id = await client.get_user_id("testuser")
        assert user_id == "123456789"


class TestGetLeagues:
    @pytest.mark.asyncio
    async def test_returns_league_list(self, client):
        resp = mock_response("leagues.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            leagues = await client.get_leagues("123456789", 2026)
        assert len(leagues) == 1
        assert leagues[0].name == "Dynasty Bros"
        assert leagues[0].total_rosters == 12
        assert isinstance(leagues[0], League)


class TestGetRosters:
    @pytest.mark.asyncio
    async def test_returns_roster_list(self, client):
        users_resp = mock_response("users.json")
        rosters_resp = mock_response("rosters.json")

        with patch.object(
            client._client, "get", AsyncMock(side_effect=[users_resp, rosters_resp])
        ):
            rosters = await client.get_rosters("league_001")
        assert len(rosters) == 2
        assert rosters[0].owner_name == "Alice's Aces"
        assert rosters[0].wins == 5
        assert isinstance(rosters[0], Roster)


class TestGetMatchups:
    @pytest.mark.asyncio
    async def test_returns_matchup_list(self, client):
        resp = mock_response("matchups_week1.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            matchups = await client.get_matchups("league_001", week=1)
        assert len(matchups) == 1
        assert matchups[0].roster_id_1 == 1
        assert matchups[0].roster_id_2 == 2
        assert isinstance(matchups[0], Matchup)


class TestGetUsers:
    @pytest.mark.asyncio
    async def test_returns_user_map(self, client):
        resp = mock_response("users.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            users = await client.get_users("league_001")
        assert len(users) == 3
        # Custom team avatar (a full URL) wins.
        assert users["user_aaa"]["display_name"] == "Alice"
        assert users["user_aaa"]["team_name"] == "Alice's Aces"
        assert users["user_aaa"]["avatar_url"] == "https://sleepercdn.com/uploads/team_aaa.png"
        # Falls back to the account avatar id → thumbs URL.
        assert users["user_bbb"]["avatar_url"] == "https://sleepercdn.com/avatars/thumbs/acct_bbb"
        # No avatar anywhere → None; no team name → None.
        assert users["user_ccc"]["avatar_url"] is None
        assert users["user_ccc"]["team_name"] is None


class TestGetTransactions:
    @pytest.mark.asyncio
    async def test_returns_raw_transactions(self, client):
        resp = mock_response("transactions_mixed.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            txs = await client.get_transactions("league_001", week=3)
        assert isinstance(txs, list)
        assert len(txs) == 2
        # Pin assertions to concrete fixture values
        trade = next(t for t in txs if t["type"] == "trade")
        waiver = next(t for t in txs if t["type"] == "waiver")
        assert trade["transaction_id"] == "tx_002"
        assert trade["status"] == "complete"
        assert waiver["transaction_id"] == "tx_wv_001"
        assert waiver["status"] == "complete"


class TestGetTradedPicks:
    @pytest.mark.asyncio
    async def test_returns_draft_picks(self, client):
        resp = mock_response("traded_picks.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            picks = await client.get_traded_picks("league_001")
        assert len(picks) == 1
        assert picks[0].season == 2027
        assert picks[0].round == 1
        assert isinstance(picks[0], DraftPick)


class TestGetDrafts:
    @pytest.mark.asyncio
    async def test_returns_drafts(self, client):
        resp = mock_response("drafts.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            drafts = await client.get_drafts("league_2024")
        assert isinstance(drafts, list)
        assert len(drafts) == 1
        assert drafts[0]["draft_id"] == "draft_2024_a"
        assert drafts[0]["status"] == "complete"


class TestGetDraftPicks:
    @pytest.mark.asyncio
    async def test_returns_draft_picks(self, client):
        resp = mock_response("draft_picks.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            picks = await client.get_draft_picks("draft_2024_a")
        assert isinstance(picks, list)
        assert len(picks) == 2
        # Each pick carries draft_slot, round, pick_no, roster_id, player_id.
        first = picks[0]
        for key in ("round", "pick_no", "draft_slot", "roster_id", "player_id"):
            assert key in first
        # Pin to concrete fixture values
        assert picks[0]["round"] == 1
        assert picks[0]["player_id"] == "p_rookie_a"
        assert picks[0]["draft_slot"] == 1
        assert picks[1]["round"] == 2
        assert picks[1]["player_id"] == "p_rookie_b"


class TestGetLeague:
    @pytest.mark.asyncio
    async def test_returns_league_and_prev_id(self, client):
        resp = mock_response("league_meta.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            league, prev_id = await client.get_league("league_2024")
        assert isinstance(league, League)
        assert league.league_id == "league_2024"
        assert league.season == 2024
        assert prev_id == "league_2023"

    @pytest.mark.asyncio
    async def test_returns_none_prev_id_when_origin(self, client):
        # Build a one-off response where previous_league_id is null.
        resp = MagicMock()
        payload = load_fixture("league_meta.json")
        payload["previous_league_id"] = None
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            _, prev_id = await client.get_league("league_2024")
        assert prev_id is None

    @pytest.mark.asyncio
    async def test_returns_none_prev_id_when_sentinel_zero_string(self, client):
        # Sleeper marks a chain's first season with the string "0" (not
        # null) for previous_league_id. This must normalize to None too,
        # or callers will try to fetch /league/0 and 404.
        resp = MagicMock()
        payload = load_fixture("league_meta.json")
        payload["previous_league_id"] = "0"
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            _, prev_id = await client.get_league("league_2024")
        assert prev_id is None


class TestGetMatchupResults:
    @pytest.mark.asyncio
    async def test_returns_per_roster_entries(self, client):
        resp = mock_response("matchup_results_week1.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            results = await client.get_matchup_results("LID", 1)
        assert len(results) == 2
        r1 = next(r for r in results if r.roster_id == 1)
        assert r1.matchup_id == 1
        assert r1.points == 142.3
        assert r1.starters == ["100", "200"]
        assert r1.players_points["300"] == 31.0


class TestGetNflState:
    @pytest.mark.asyncio
    async def test_returns_current_week(self, client):
        resp = mock_response("nfl_state.json")
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            state = await client.get_nfl_state()
        assert state["week"] == 10
        assert state["season"] == "2025"


class TestWalkLeagueHistory:
    @pytest.mark.asyncio
    async def test_walks_back_to_origin(self, client):
        # Simulate three seasons: 2024 -> 2023 -> 2022 -> (origin).
        def make_resp(league_id, prev_id, season):
            r = MagicMock()
            r.json.return_value = {
                "league_id": league_id,
                "name": "Dynasty Bros",
                "season": str(season),
                "status": "complete",
                "total_rosters": 12,
                "previous_league_id": prev_id,
                "roster_positions": [],
                "settings": {"playoff_week_start": 15, "num_playoff_teams": 6},
                "scoring_settings": {},
            }
            r.raise_for_status.return_value = None
            return r

        responses = [
            make_resp("league_2024", "league_2023", 2024),
            make_resp("league_2023", "league_2022", 2023),
            make_resp("league_2022", None, 2022),
        ]
        with patch.object(
            client._client, "get", AsyncMock(side_effect=responses)
        ):
            chain = await client.walk_league_history("league_2024")
        assert [lg.league_id for lg in chain] == [
            "league_2024", "league_2023", "league_2022",
        ]
        assert [lg.season for lg in chain] == [2024, 2023, 2022]

    @pytest.mark.asyncio
    async def test_stops_at_sentinel_zero_previous_league_id(self, client):
        # The oldest season in a chain reports previous_league_id as the
        # string "0", not null. The walk must terminate there without
        # requesting /league/0 (which 404s in production).
        def make_resp(league_id, prev_id, season):
            r = MagicMock()
            r.json.return_value = {
                "league_id": league_id,
                "name": "Dynasty Bros",
                "season": str(season),
                "status": "complete",
                "total_rosters": 12,
                "previous_league_id": prev_id,
                "roster_positions": [],
                "settings": {"playoff_week_start": 15, "num_playoff_teams": 6},
                "scoring_settings": {},
            }
            r.raise_for_status.return_value = None
            return r

        responses = [
            make_resp("league_2024", "league_2023", 2024),
            make_resp("league_2023", "0", 2023),
        ]
        mock_get = AsyncMock(side_effect=responses)
        with patch.object(client._client, "get", mock_get):
            chain = await client.walk_league_history("league_2024")
        assert [lg.league_id for lg in chain] == ["league_2024", "league_2023"]
        # Only two calls made — never requested /league/0.
        assert mock_get.call_count == 2
        called_urls = [call.args[0] for call in mock_get.call_args_list]
        assert "/league/0" not in called_urls

    @pytest.mark.asyncio
    async def test_single_season_chain(self, client):
        r = MagicMock()
        r.json.return_value = {
            "league_id": "solo",
            "name": "Solo",
            "season": "2025",
            "status": "complete",
            "total_rosters": 12,
            "previous_league_id": None,
            "roster_positions": [],
            "settings": {},
            "scoring_settings": {},
        }
        r.raise_for_status.return_value = None
        with patch.object(client._client, "get", AsyncMock(return_value=r)):
            chain = await client.walk_league_history("solo")
        assert len(chain) == 1
        assert chain[0].league_id == "solo"


class TestGetWinnersBracket:
    @pytest.mark.asyncio
    async def test_returns_bracket_list(self, client):
        bracket_data = [{"m": 1, "r": 1, "t1": 6, "t2": 12, "w": 6, "l": 12}]
        resp = MagicMock()
        resp.json.return_value = bracket_data
        resp.raise_for_status.return_value = None
        mock_get = AsyncMock(return_value=resp)
        with patch.object(client._client, "get", mock_get):
            result = await client.get_winners_bracket("L1")
        assert result == bracket_data
        mock_get.assert_called_once_with("/league/L1/winners_bracket")


class TestGetLosersBracket:
    @pytest.mark.asyncio
    async def test_returns_empty_list_on_http_error(self, client):
        import httpx

        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        with patch.object(client._client, "get", AsyncMock(return_value=resp)):
            result = await client.get_losers_bracket("L1")
        assert result == []
