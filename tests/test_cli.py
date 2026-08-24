import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty import cli
from sleeper_dynasty.cli import parse_args


@pytest.mark.asyncio
async def test_run_recap_builds_and_delivers(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    # Stub the Sleeper client.
    from sleeper_dynasty.models.league import League, Roster, MatchupResult
    from sleeper_dynasty.models.player import Player

    league = League(
        league_id="LID", name="Bros", season=2025, total_rosters=2,
        roster_positions=["QB", "FLEX", "BN"],
        scoring_settings={}, playoff_week_start=15, num_playoff_teams=6,
        status="in_season",
    )
    rosters = [
        Roster(1, "u1", "Team A", ["p1"], 1, 0, 0, 45.0, 0.0),
        Roster(2, "u2", "Team B", ["p2"], 0, 1, 0, 30.0, 0.0),
    ]
    results = [
        MatchupResult(9, 1, 1, 45.0, ["p1"], ["p1"], {"p1": 45.0}),
        MatchupResult(9, 1, 2, 30.0, ["p2"], ["p2"], {"p2": 30.0}),
    ]

    fake = MagicMock()
    fake.get_user_id = AsyncMock(return_value="uid")
    fake.get_leagues = AsyncMock(return_value=[league])
    fake.get_nfl_state = AsyncMock(return_value={"week": 10, "season": "2025"})
    fake.get_rosters = AsyncMock(return_value=rosters)
    fake.get_matchup_results = AsyncMock(return_value=results)
    fake.get_players = AsyncMock(return_value={
        "p1": {"full_name": "Josh Allen", "position": "QB", "team": "BUF"},
        "p2": {"full_name": "Scrub", "position": "RB", "team": "NYJ"},
    })
    fake.get_projections = AsyncMock(return_value={})
    fake.close = AsyncMock()

    args = argparse.Namespace(
        username="me", season=2025, week=9, no_cache=True,
        lore=None, persona=None, model="claude-opus-4-8",
        out=str(tmp_path / "out.html"),
    )

    with patch.object(cli, "SleeperClient", return_value=fake), \
         patch.object(cli, "webbrowser", MagicMock()), \
         patch.object(cli, "fetch_week_schedule", AsyncMock(return_value=[])), \
         patch.object(cli, "RecapWriter") as MockWriter:
        MockWriter.return_value.write.return_value = "# Week 9\n\nThe Analyst."
        await cli._run_recap(args)

    # Writer was given a RecapFacts with week 9.
    facts_arg = MockWriter.return_value.write.call_args[0][0]
    assert facts_arg.week == 9
    assert facts_arg.league_name == "Bros"

    # write() was called with an outlook kwarg (may be None if schedule empty).
    assert "outlook" in MockWriter.return_value.write.call_args.kwargs


def test_parse_args_defaults():
    args = parse_args(["analyze", "testuser"])
    assert args.command == "analyze"
    assert args.username == "testuser"
    assert args.season == 2026
    assert args.week == 1
    assert args.sims == 10000
    assert args.no_cache is False


def test_parse_args_custom():
    args = parse_args(["analyze", "someuser", "--season", "2027", "--week", "5", "--sims", "5000", "--no-cache"])
    assert args.username == "someuser"
    assert args.season == 2027
    assert args.week == 5
    assert args.sims == 5000
    assert args.no_cache is True


def test_parse_args_trades_defaults():
    args = parse_args(["trades", "testuser"])
    assert args.command == "trades"
    assert args.username == "testuser"
    assert args.season == 2026
    assert args.no_cache is False
    assert args.refresh_trades is False
    assert args.private is False


def test_init_lore_writes_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from sleeper_dynasty.cli import _write_lore_template
    path = _write_lore_template(tmp_path / "lore.md")
    from pathlib import Path
    assert Path(path).exists()
    assert "League Lore" in Path(path).read_text()


def test_parse_args_trades_custom():
    args = parse_args([
        "trades", "someuser", "--season", "2025",
        "--refresh-trades", "--private",
    ])
    assert args.command == "trades"
    assert args.username == "someuser"
    assert args.season == 2025
    assert args.refresh_trades is True
    assert args.private is True
