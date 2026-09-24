"""Public payload shapes are based on the read-only Sleeper probe; identities are synthetic."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from sleeper_dynasty.api.player_context import PlayerContextClient, SourceUnavailable, normalize_news
from sleeper_dynasty.engine.player_context import build_context

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


def report(title="Left with knee injury", **changes):
    # Captured envelope/metadata shape, with synthetic article text/identifiers.
    row = {"source": "rotoballer", "published": 1790042400000,
           "metadata": {"title": title, "description": "Quarterback left the opening drive with a knee injury.",
                        "topic_id": "synthetic-topic", "url": "https://www.rotoballer.com/player-news/example/1"}}
    row.update(changes)
    return row


def packet(news=None, snaps=None, schedule=None, ids=None):
    reports = normalize_news([report()], observed_at=NOW) if news is None else news
    rows = [{"season": "2026", "week": "2", "game_type": "REG", "player": "Test QB", "pfr_player_id": "TestQB00",
             "team": "NYG", "offense_snaps": "3", "offense_pct": "0.05"}] if snaps is None else snaps
    games = [
        {"season": "2026", "week": "2", "game_type": "REG", "gameday": "2026-09-17", "gametime": "20:15", "home_team": "BUF", "away_team": "MIA"},
        {"season": "2026", "week": "2", "game_type": "REG", "gameday": "2026-09-21", "gametime": "20:15", "home_team": "NYG", "away_team": "LA"},
        {"season": "2026", "week": "3", "game_type": "REG", "gameday": "2026-09-24", "gametime": "20:15", "home_team": "NYG", "away_team": "BUF"},
    ] if schedule is None else schedule
    return build_context(season=2026, week=2, now=NOW,
        results=[SimpleNamespace(starters=["test-qb"], players=["test-qb"], players_points={"test-qb": 0.5})],
        players={"test-qb": SimpleNamespace(full_name="Test QB", position="QB", team="NYG")},
        news_by_player={"test-qb": reports}, snap_rows=rows,
        id_rows=ids if ids is not None else [{"pfr_id": "TestQB00", "sleeper_id": "test-qb"}], schedule_rows=games)


def test_three_snaps_is_limited_opportunity_and_cause_comes_from_report():
    # Mutation: omit usage or turn low points into a poor-performance verdict.
    result = packet()
    player = result["players"][0]
    assert player["usage"] == {"offense_snaps": 3, "offense_share": 0.05, "limited_opportunity": True}
    assert "knee injury" in player["news"][0]["text"]
    assert player["kickoff_at"] == "2026-09-22T00:15:00+00:00"
    assert "injury" not in player["usage"]


def test_captured_seven_snap_twelve_percent_shape_is_limited_opportunity():
    # Mutation: use a 10% threshold, which misses the real short injury outing.
    # Values/columns captured from the read-only source smoke; identity replaced.
    result = packet(snaps=[{"season": "2026", "week": "2", "game_type": "REG", "pfr_player_id": "TestQB00",
                            "team": "NYG", "offense_snaps": "7", "offense_pct": "0.12"}])
    assert result["players"][0]["usage"] == {"offense_snaps": 7, "offense_share": 0.12, "limited_opportunity": True}


@pytest.mark.parametrize("snaps", [[], [{"season": "2025", "week": "2", "game_type": "REG", "pfr_player_id": "TestQB00", "offense_snaps": "0", "offense_pct": "0"}],
    [{"season": "2026", "week": "1", "game_type": "REG", "pfr_player_id": "TestQB00", "offense_snaps": "0", "offense_pct": "0"}],
    [{"season": "2026", "week": "2", "game_type": "POST", "pfr_player_id": "TestQB00", "offense_snaps": "0", "offense_pct": "0"}],
    [{"season": "2026", "week": "2", "game_type": "REG", "pfr_player_id": "TestQB00", "offense_snaps": "NA", "offense_pct": "NaN"}]])
def test_missing_or_wrong_week_usage_is_unknown_not_zero(snaps):
    # Mutation: default absent/bad snap data to zero or ignore season/type.
    assert packet(snaps=snaps)["players"][0]["usage"] is None


def test_ambiguous_player_id_mapping_does_not_assign_usage():
    # Mutation: pick the first or last player from an ambiguous ID mapping.
    result = packet(ids=[{"pfr_id": "TestQB00", "sleeper_id": "test-qb"},
                         {"pfr_id": "TestQB00", "sleeper_id": "another-qb"}])
    assert result["players"][0]["usage"] is None


def test_news_requires_both_publication_and_observation_before_cutoff():
    # Mutation: remove either cutoff check; include exact-boundary observation.
    current = normalize_news([report("Current")], observed_at=NOW)
    future = normalize_news([report("Future", published=int(NOW.timestamp()*1000)+1)], observed_at=NOW)
    later_seen = normalize_news([report("Seen later")], observed_at=NOW.replace(hour=13))
    result = packet(news=current + future + later_seen)
    assert [n["title"] for n in result["players"][0]["news"]] == ["Current"]


def test_missing_schedule_omits_news_instead_of_guessing_week():
    # Mutation: use a rolling calendar window when actual week timing is absent.
    result = packet(schedule=[])
    assert result["players"][0]["news"] == []
    assert "schedule" in result["note"].lower()
    assert result["players"][0]["usage"]["offense_snaps"] == 3


def test_snap_team_alias_uses_actual_schedule_kickoff():
    # Mutation: compare PFR's LAR with the schedule's LA without normalization.
    result = packet(snaps=[{"season": "2026", "week": "2", "game_type": "REG", "pfr_player_id": "TestQB00",
                            "team": "LAR", "offense_snaps": "3", "offense_pct": "0.05"}])
    assert result["players"][0]["kickoff_at"] == "2026-09-22T00:15:00+00:00"


def test_normalization_rejects_unsafe_urls_and_bad_dates_and_retains_analysis():
    # Mutation: accept publisher-supplied javascript/unrelated hosts, or drop analysis.
    raw = report()
    raw["metadata"].update(url="javascript:alert(1)", analysis="<b>Only three plays.</b>")
    good = normalize_news([raw, report(published="not-a-date")], observed_at=NOW)
    assert len(good) == 1
    assert good[0]["url"] is None
    assert "Only three plays." in good[0]["text"]
    assert "<b>" not in good[0]["text"]
    raw["metadata"]["url"] = "https://www.rotoballer.com.evil.example/story"
    assert normalize_news([raw], observed_at=NOW)[0]["url"] is None


@pytest.mark.asyncio
async def test_graphql_client_fetches_read_only_batched_player_news():
    # Mutation: put the wrong player under an alias or ignore GraphQL errors.
    def handler(request):
        body = json.loads(request.content)
        assert "mutation" not in body["query"]
        assert 'player_id:"test-qb"' in body["query"]
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": {"p0": [report()]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await PlayerContextClient(http).news(["test-qb"])
    assert result["test-qb"][0]["metadata"]["title"] == "Left with knee injury"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(429, headers={"Retry-After": "1800"}), httpx.Response(401),
    httpx.Response(200, json={"errors": [{"message": "Unauthorized"}]}), httpx.Response(200, json={"data": {"p0": None}})])
async def test_provider_failure_is_explicit_with_backoff(response):
    # Mutation: interpret refused/null data as a successful empty news feed.
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as http:
        with pytest.raises(SourceUnavailable) as failure:
            await PlayerContextClient(http).news(["test-qb"])
    assert failure.value.retry_after >= 900


@pytest.mark.asyncio
@pytest.mark.parametrize("resource,body", [
    ("snaps", "season,week,pfr_player_id,offense_snaps,offense_pct\n2026,2,TestQB00,3,0.05\n"),
    ("ids", "pfr_id\nTestQB00\n"),
    ("schedule", "season,week,gameday,gametime,game_type\n2026,2,2026-09-21,20:15,REG\n"),
])
async def test_incomplete_csv_schema_reports_unavailable(resource, body):
    # Mutation: accept missing game type/team identity and silently lose context.
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body))) as http:
        with pytest.raises(SourceUnavailable, match="Invalid"):
            await PlayerContextClient(http).csv_rows(resource, 2026)


@pytest.mark.asyncio
async def test_network_timeout_becomes_explicit_source_failure():
    # Mutation: swallow a timeout as an empty successful feed.
    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
        with pytest.raises(SourceUnavailable, match="ReadTimeout"):
            await PlayerContextClient(http).news(["test-qb"])
