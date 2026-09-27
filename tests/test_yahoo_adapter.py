"""Replay anonymized real Yahoo responses; mutations are named per test."""

import json
from pathlib import Path

import pytest

from sleeper_dynasty.api.yahoo import YahooAdapter, YahooDataError
from sleeper_dynasty.api.yahoo_json import collection, merge_fragments

FIXTURES = Path(__file__).parent / "fixtures/yahoo"
LK = "470.l.100000001"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def ids():
    out = {}

    def walk(node):
        if isinstance(node, dict):
            if "player_id" in node:
                out.setdefault(str(node["player_id"]), str(900000 + len(out)))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for name in [
        "roster_current",
        "roster_points_wk1",
        "transactions_all",
        "prior_trades",
    ]:
        walk(fixture(name))
    return out


class Replay(YahooAdapter):
    def __init__(self, routes=None, id_map=None):
        super().__init__("synthetic-token", id_map=ids() if id_map is None else id_map)
        self.routes = routes or {}
        self.requested = []

    async def _get(self, path, **params):
        self.requested.append(path)
        if path in self.routes:
            return self.routes[path]
        if path.endswith("/settings"):
            return fixture("league_settings")
        if path.endswith("/standings"):
            return fixture("standings")
        if path.endswith("/teams"):
            return fixture("teams")
        if "/scoreboard;week=1" in path:
            return fixture("scoreboard_wk1")
        if "/scoreboard;week=3" in path:
            raise AssertionError("future or incomplete week should not be read")
        if "/roster;week=1/" in path:
            return fixture("roster_points_wk1")
        if "/players;player_keys=" in path:
            keys = set(path.split("player_keys=", 1)[1].split("/", 1)[0].split(","))
            players = []
            for p in sorted(FIXTURES.glob("player_points_wk1_batch*.json")):
                node = merge_fragments(
                    json.loads(p.read_text())["fantasy_content"]["league"]
                )
                players.extend(
                    x
                    for x in collection(node["players"])
                    if merge_fragments(x["player"])["player_key"] in keys
                )
            return {
                "fantasy_content": {
                    "league": [
                        {},
                        {
                            "players": {
                                **{str(i): p for i, p in enumerate(players)},
                                "count": len(players),
                            }
                        },
                    ]
                }
            }
        if "/roster/players" in path:
            return fixture("roster_current")
        if path.endswith("/draftresults"):
            return fixture("draftresults")
        if "/transactions" in path:
            return fixture("transactions_all")
        if "/game_weeks" in path:
            return fixture("game_weeks")
        raise AssertionError(path)


@pytest.mark.asyncio
async def test_captured_settings_keep_custom_scoring_and_metadata_renew():
    # Mutation: reading renew from settings or leaving scoring empty loses real data.
    a = Replay()
    try:
        league, prior = await a.get_league(LK)
        assert (league.season, league.total_rosters, league.format) == (
            2026,
            10,
            "keeper",
        )
        assert prior == "461.l.100000002"
        assert league.scoring_settings["rec"] == 0.5
        assert league.scoring_settings["pass_td"] == 6
        assert "WRRB_FLEX" in league.roster_positions
        assert "FLEX" in league.roster_positions
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_captured_current_rosters_have_players_and_distinct_owners():
    # Mutation: leaving players empty destroys current-value and tenure scoring.
    a = Replay()
    try:
        rosters = await a.get_rosters(LK)
        assert len(rosters) == 10
        assert len({r.owner_id for r in rosters}) == 10
        assert all(len(r.players) >= 17 for r in rosters)
        assert sum(r.wins for r in rosters) == 10
        assert all(r.points_for > 0 for r in rosters)
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_captured_scoreboard_and_lineups_preserve_actual_points():
    # Mutation: flattening only dict names loses nested numeric scoreboard envelopes.
    a = Replay()
    try:
        rows = await a.get_raw_matchups(LK, 1)
        assert len(rows) == 10
        assert len({r["matchup_id"] for r in rows}) == 5
        assert all(len(r["starters"]) == 10 for r in rows)
        assert all(len(r["players"]) >= 18 for r in rows)
        for row in rows:
            assert sum(
                row["players_points"][p] for p in row["starters"]
            ) == pytest.approx(row["points"], abs=0.02)
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_future_weeks_do_not_create_zero_score_games_or_fetch_rosters():
    # Mutation: fetching all 18 weeks treats future schedules as played data.
    a = Replay()
    try:
        assert await a.get_raw_matchups(LK, 18) == []
        assert not any("/roster;" in p or "/scoreboard;" in p for p in a.requested)
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_captured_transactions_preserve_adds_and_drops():
    # Mutation: reading only trades/drop subsets omits add-only roster changes.
    a = Replay()
    try:
        rows = await a.get_roster_transactions(LK)
        assert len(rows) == 50  # 55 total includes five commissioner-only actions.
        assert any(r["adds"] and r["drops"] for r in rows)
        assert any(r["adds"] and not r["drops"] for r in rows)
        assert all(r["created"] > 10**12 for r in rows)
        assert any(r["leg"] > 0 for r in rows)
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_draft_slot_does_not_shift_after_unmapped_player():
    # Mutation: counting mapped picks rather than overall positions shifts the slot.
    raw = fixture("draftresults")["fantasy_content"]["league"]
    picks = collection(merge_fragments(raw)["draft_results"])
    second = picks[1]["draft_result"]
    pid = second["player_key"].split(".p.")[1]
    a = Replay(id_map={pid: "synthetic-player"})
    try:
        rows = await a.get_draft_results(LK)
        target = next(r for r in rows if r["pick_no"] == 2)
        assert target["draft_slot"] == 2
        assert target["player_id"] == "synthetic-player"
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_draft_mapping_does_not_depend_on_rosters_being_fetched_first():
    # Mutation: drafts contain only Yahoo keys, so new players disappear when
    # no earlier roster read happened to populate the mapping.
    class NewPlayerDraft(YahooAdapter):
        async def _get(self, path, **params):
            if path.endswith("/draftresults"):
                return {
                    "fantasy_content": {
                        "league": [
                            {"num_teams": 2, "season": "2026"},
                            {
                                "draft_results": {
                                    "0": {
                                        "draft_result": {
                                            "round": 1,
                                            "pick": 1,
                                            "team_key": LK + ".t.1",
                                            "player_key": "470.p.990000001",
                                        }
                                    },
                                    "count": 1,
                                }
                            },
                        ]
                    }
                }
            if "/players;player_keys=" in path:
                return {
                    "fantasy_content": {
                        "league": [
                            {},
                            {
                                "players": {
                                    "0": {
                                        "player": [
                                            {
                                                "player_id": "990000001",
                                                "name": {"full": "Example Rookie"},
                                                "display_position": "RB",
                                            }
                                        ]
                                    },
                                    "count": 1,
                                }
                            },
                        ]
                    }
                }
            raise AssertionError(path)

    from sleeper_dynasty.api.yahoo import player_name_index

    a = NewPlayerDraft("synthetic", id_map={})
    a._name_index = player_name_index(
        {"test-rookie": {"full_name": "Example Rookie", "position": "RB"}}
    )
    try:
        picks = await a.get_draft_results(LK)
        assert len(picks) == 1
        assert picks[0]["player_id"] == "test-rookie"
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_protocol_is_complete():
    # Mutation: missing unfiltered roster transactions violates the current contract.
    from sleeper_dynasty.api.platform import LeaguePlatform

    a = Replay()
    try:
        assert isinstance(a, LeaguePlatform)
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_draft_reads_used_by_real_grader_are_available():
    # Mutation: a protocol that omits raw draft reads passes type checks but
    # crashes in build_trade_history before a single Yahoo grade is produced.
    a = Replay()
    try:
        drafts = await a.get_drafts(LK)
        assert len(drafts) == 1
        assert drafts[0]["status"] == "complete"
        assert drafts[0]["season"] == "2026"
        picks = await a.get_draft_picks(drafts[0]["draft_id"])
        assert picks
        assert all(p["player_id"] in ids().values() for p in picks)
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_bad_league_response_fails_loudly():
    # Mutation: defaulting missing metadata creates a plausible but empty league.
    a = Replay({f"/league/{LK}/settings": {"fantasy_content": {}}})
    try:
        with pytest.raises(YahooDataError):
            await a.get_league(LK)
    finally:
        await a.close()


def test_new_player_mapping_requires_unique_normalized_name_and_position():
    # Mutation: choosing the first name hit merges namesakes or positions.
    from sleeper_dynasty.api.yahoo import player_name_index, resolve_named_player

    universe = {
        "a": {"full_name": "Example Runner", "position": "RB"},
        "b": {"full_name": "Same Name", "position": "WR"},
        "c": {"full_name": "Same Name", "position": "WR"},
        "d": {"full_name": "Example Runner", "position": "CB"},
        "e": {
            "full_name": "Two Way",
            "position": "DB",
            "fantasy_positions": ["DB", "WR"],
        },
    }
    index = player_name_index(universe)
    assert (
        resolve_named_player(
            {"name": {"full": "Example Runner Jr."}, "display_position": "RB"}, index
        )
        == "a"
    )
    assert (
        resolve_named_player(
            {"name": {"full": "Same Name"}, "display_position": "WR"}, index
        )
        is None
    )
    assert (
        resolve_named_player(
            {"name": {"full": "Example Runner"}, "display_position": "QB"}, index
        )
        is None
    )
    assert (
        resolve_named_player(
            {"name": {"full": "Two Way"}, "display_position": "WR"}, index
        )
        == "e"
    )


@pytest.mark.asyncio
async def test_unmapped_starter_blocks_grading_instead_of_inventing_lineup_skill():
    # Mutation: silently skip an unknown starter and grade an incomplete lineup.
    a = Replay(id_map={})
    try:
        with pytest.raises(YahooDataError, match="starter"):
            await a.get_raw_matchups(LK, 1)
    finally:
        await a.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_errors_are_bounded_and_do_not_echo_tokens(monkeypatch, status):
    from unittest.mock import AsyncMock

    import httpx

    from sleeper_dynasty.api.yahoo import YahooAuthenticationError

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="private-token upstream details")

    monkeypatch.setattr("sleeper_dynasty.api.yahoo.asyncio.sleep", AsyncMock())
    a = YahooAdapter("private-token", id_map={}, transport=httpx.MockTransport(respond))
    try:
        error = YahooAuthenticationError if status in (401, 403) else YahooDataError
        with pytest.raises(error) as exc:
            await a.get_league(LK)
        assert "private-token" not in str(exc.value)
        assert len(calls) == (1 if status in (401, 403) else 3)
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_captured_playoffs_keep_consolation_out_of_title_path():
    # Mutation: treating all is_playoffs games as title-path inflates production.
    prior = "461.l.100000002"
    a = Replay(
        {
            f"/league/{prior}/settings": fixture("prior_settings"),
            f"/league/{prior}/scoreboard;week=16": fixture("prior_scoreboard_wk16"),
            f"/league/{prior}/scoreboard;week=17": {"fantasy_content": {"league": []}},
        }
    )
    try:
        league, _ = await a.get_league(prior)
        phases = await a.get_phase_map(league)
        assert phases[(16, 2)] == "playoff"
        assert phases[(16, 4)] == "toilet"
        assert (16, 1) not in phases  # Bye, not a played playoff game.
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_captured_trade_preserves_both_sides_and_excludes_partial_trade():
    # Mutation: retain the mapped half of a trade and grade it as a giveaway.
    prior = "461.l.100000002"
    routes = {f"/league/{prior}/transactions": fixture("prior_trades")}
    a = Replay(routes)
    try:
        trades = await a.get_trade_transactions(prior)
        assert len(trades) == 1
        trade = trades[0]
        assert len(trade["roster_ids"]) == 2
        assert set(trade["adds"]) == set(trade["drops"])
        assert all(trade["adds"][p] != trade["drops"][p] for p in trade["adds"])
    finally:
        await a.close()
    incomplete = ids()
    del incomplete[next(k for k, v in incomplete.items() if v in trade["adds"])]
    a = Replay(routes, id_map=incomplete)
    try:
        assert await a.get_trade_transactions(prior) == []
    finally:
        await a.close()
