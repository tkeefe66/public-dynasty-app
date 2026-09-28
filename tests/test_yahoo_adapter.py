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
async def test_captured_historical_draft_missing_players_preserves_known_selections():
    # Mutation: treating every draft slot as an identified player crashes the import.
    raw = fixture("draftresults_missing_player")
    rows = raw["fantasy_content"]["league"][1]["draft_results"]
    mapping = {
        row["draft_result"]["player_key"].split(".p.")[1]: f"mapped-{i}"
        for i, row in rows.items()
        if i != "count" and row["draft_result"].get("player_key")
    }
    key = "399.l.100000003"
    a = Replay({f"/league/{key}/draftresults": raw}, id_map=mapping)
    try:
        picks = await a.get_draft_results(key)
        assert len(picks) == 158
        assert {p["pick_no"] for p in picks} == set(range(1, 161)) - {153, 154}
        assert picks[-1] == {
            "round": 16,
            "pick_no": 160,
            "draft_slot": 1,
            "roster_id": 7,
            "player_id": "mapped-159",
            "season": 2020,
        }
        assert not a.unmapped_players  # An absent ID is not an unmapped player.
        assert any("2 Yahoo draft selections" in w for w in a.warnings)
        await a.get_draft_results(key)
        assert any("2 Yahoo draft selections" in w for w in a.warnings)
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
@pytest.mark.parametrize("status", [429, 999])
async def test_provider_limits_stop_without_immediate_retries(monkeypatch, status):
    # Mutation: treating Yahoo's access limit as a server error sends rapid retries.
    from unittest.mock import AsyncMock

    import httpx

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, text="private-token upstream details")

    monkeypatch.setattr("sleeper_dynasty.api.yahoo.asyncio.sleep", AsyncMock())
    a = YahooAdapter("private-token", id_map={}, transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(YahooDataError) as exc:
            await a.get_league(LK)
        assert len(calls) == 1
        assert "private-token" not in str(exc.value)
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
        assert len(calls) == (1 if status in (401, 403, 429) else 3)
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


@pytest.mark.asyncio
async def test_completed_playoffs_credit_title_and_exclude_placement_games():
    # Regression: phase flags alone counted third-place games as title games
    # and left championship/round-win records empty in the rating consumer.
    prior = "461.l.100000002"
    a = Replay(
        {
            f"/league/{prior}/settings": fixture("prior_settings"),
            f"/league/{prior}/standings": fixture("prior_standings"),
            f"/league/{prior}/scoreboard;week=16": fixture("prior_scoreboard_wk16"),
            f"/league/{prior}/scoreboard;week=17": fixture("prior_scoreboard_wk17"),
        }
    )
    try:
        league, _ = await a.get_league(prior)
        phases = await a.get_phase_map(league)
        assert (17, 7) not in phases  # Lost semifinal; this is third place.
        assert (17, 4) not in phases  # Consolation placement game.
        assert phases[(17, 3)] == "playoff"
        records = await a.get_postseason_results(league)
        assert records[3]["champion"] and records[3]["rounds_won"] == 2
        assert records[2]["runner_up"] and records[2]["rounds_won"] == 1
        assert records[7]["made_playoffs"] and records[7]["rounds_won"] == 0
        assert records[7]["playoff_place"] == 3
        assert records[9]["made_toilet"] and records[9]["toilet_place"] == 1
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_combined_add_drops_reach_engine_drop_index():
    from sleeper_dynasty.engine.trade_history import build_drop_index

    a = Replay()
    try:
        drops = await a.get_drop_transactions(LK)
        assert len(drops) == 40
        owners = {i: f"owner{i}" for i in range(1, 11)}
        expected = {
            (owners[rid], pid) for tx in drops for pid, rid in tx["drops"].items()
        }
        assert set(build_drop_index(drops, owners)) == expected
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_missing_weekly_roster_resource_is_not_an_empty_lineup():
    raw = fixture("roster_points_wk1")
    raw["fantasy_content"]["league"][1]["teams"]["0"]["team"][1].pop("roster")
    a = Replay({f"/league/{LK}/teams/roster;week=1/players": raw})
    try:
        with pytest.raises(YahooDataError, match="roster"):
            await a.get_raw_matchups(LK, 1)
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_yahoo_defense_yardage_scores_through_canonical_stats():
    from sleeper_dynasty.engine.nfl_actuals import score_week

    a = Replay()
    try:
        league, _ = await a.get_league(LK)
        actual = score_week(
            {"A": {"yds_allow_450_499": 1}, "B": {"yds_allow_550p": 1}},
            league.scoring_settings,
        )
        assert actual == {"A": -1.0, "B": -3.0}
    finally:
        await a.close()


def test_negative_and_low_yardage_boundaries_do_not_overlap():
    from sleeper_dynasty.api.yahoo import normalize_yardage_stats

    for yards in (-1, 0, 99, 100):
        stats = normalize_yardage_stats(
            {"D": {"yds_allow": yards, "yds_allow_0_100": 1}}
        )["D"]
        assert stats["yds_allow_negative"] == int(yards < 0)
        assert stats["yds_allow_0_100"] == int(0 <= yards < 100)


@pytest.mark.asyncio
async def test_weekly_stats_apply_yahoo_boundary_normalization():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sleeper_dynasty.engine.nfl_actuals import score_week

    a = YahooAdapter("synthetic", id_map={})
    a._sleeper_client = SimpleNamespace(
        get_stats=AsyncMock(
            return_value={
                "negative": {"yds_allow": -1, "yds_allow_0_100": 1},
                "boundary": {"yds_allow": 100, "yds_allow_0_100": 1},
            }
        ),
        close=AsyncMock(),
    )
    try:
        points = score_week(
            await a.get_stats(2025, 1), {"yds_allow_negative": 8, "yds_allow_0_100": 4}
        )
        assert points == {"negative": 8, "boundary": 0}
    finally:
        await a.close()


@pytest.mark.asyncio
async def test_multiweek_championship_is_explicitly_unsupported():
    # The single-elimination result walker must not count two legs as two wins.
    raw = fixture("league_settings")
    meta = merge_fragments(raw["fantasy_content"]["league"])
    settings = merge_fragments(meta["settings"])
    settings["has_multiweek_championship"] = 1
    meta["settings"] = settings
    a = Replay({f"/league/{LK}/settings": {"fantasy_content": {"league": [meta]}}})
    try:
        with pytest.raises(YahooDataError, match="multi-week"):
            await a.get_league(LK)
    finally:
        await a.close()
