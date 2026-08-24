"""Integration test: runs the full pipeline with mocked API calls and mocked HTML report."""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sleeper_dynasty.cli import _run_analysis

from tests.helpers import load_fixture
from tests.helpers import wire_transaction_protocol


@pytest.fixture
def mock_args():
    args = MagicMock()
    args.username = "testuser"
    args.season = 2026
    args.week = 1
    args.sims = 100
    args.no_cache = True
    return args


@pytest.fixture
def mock_players():
    return {
        "4046": {"full_name": "Patrick Mahomes", "position": "QB", "team": "KC", "birth_date": "1995-09-17"},
        "6794": {"full_name": "Justin Jefferson", "position": "WR", "team": "MIN", "birth_date": "1999-06-16"},
        "4984": {"full_name": "Saquon Barkley", "position": "RB", "team": "PHI", "birth_date": "1997-02-09"},
        "2449": {"full_name": "Travis Kelce", "position": "TE", "team": "KC", "birth_date": "1989-10-05"},
        "1479": {"full_name": "Tyler Bass", "position": "K", "team": "BUF", "birth_date": "1997-01-23"},
        "5848": {"full_name": "Jalen Hurts", "position": "QB", "team": "PHI", "birth_date": "1998-08-07"},
        "4866": {"full_name": "Nick Chubb", "position": "RB", "team": "CLE", "birth_date": "1995-12-27"},
        "6803": {"full_name": "CeeDee Lamb", "position": "WR", "team": "DAL", "birth_date": "1999-04-08"},
        "3321": {"full_name": "Mark Andrews", "position": "TE", "team": "BAL", "birth_date": "1995-09-06"},
        "1466": {"full_name": "Harrison Butker", "position": "K", "team": "KC", "birth_date": "1995-07-14"},
    }


@pytest.mark.asyncio
async def test_full_pipeline_runs_without_error(mock_args, mock_players):
    # Use real model instances rather than MagicMock to avoid breaking dataclass-typed downstream code
    from sleeper_dynasty.models.league import League, Roster, Matchup

    league = League(
        league_id="league_001", name="Test Dynasty", season=2026,
        total_rosters=2,
        roster_positions=["QB", "RB", "WR", "TE", "K"],
        scoring_settings={"pass_td": 4.0, "rec": 1.0, "rush_td": 6.0, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1},
        playoff_week_start=15, num_playoff_teams=2, status="in_season",
    )
    rosters = [
        Roster(roster_id=1, owner_id="user_aaa", owner_name="Alice",
               players=["4046", "4984", "6794", "2449", "1479"],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
        Roster(roster_id=2, owner_id="user_bbb", owner_name="Bob",
               players=["5848", "4866", "6803", "3321", "1466"],
               wins=0, losses=0, ties=0, points_for=0, points_against=0),
    ]
    matchup = Matchup(week=1, roster_id_1=1, roster_id_2=2, points_1=None, points_2=None)

    mock_client_instance = AsyncMock()
    mock_client_instance.get_user_id.return_value = "123456789"
    mock_client_instance.get_leagues.return_value = [league]
    mock_client_instance.get_rosters.return_value = rosters
    mock_client_instance.get_traded_picks.return_value = []
    mock_client_instance.get_matchups.return_value = [matchup]
    mock_client_instance.get_players.return_value = mock_players
    mock_client_instance.get_projections.return_value = {
        "4046": {"pass_td": 2.5, "pass_yd": 280, "rush_yd": 20},
        "6794": {"rec": 6, "rec_yd": 90, "rec_td": 0.7},
        "4984": {"rush_yd": 80, "rush_td": 0.6, "rec": 3, "rec_yd": 25},
        "2449": {"rec": 5, "rec_yd": 55, "rec_td": 0.5},
        "1479": {},
        "5848": {"pass_td": 2.0, "pass_yd": 240, "rush_yd": 35, "rush_td": 0.4},
        "4866": {"rush_yd": 70, "rush_td": 0.5, "rec": 2, "rec_yd": 15},
        "6803": {"rec": 7, "rec_yd": 95, "rec_td": 0.8},
        "3321": {"rec": 4, "rec_yd": 45, "rec_td": 0.4},
        "1466": {},
    }
    mock_client_instance.close = AsyncMock()

    mock_report = MagicMock()
    fake_path = Path("/tmp/fake_report.html")
    mock_report.generate.return_value = fake_path

    with (
        patch("sleeper_dynasty.cli.SleeperClient", return_value=mock_client_instance),
        patch("sleeper_dynasty.cli.fetch_fantasypros_projections", new_callable=AsyncMock, return_value={}),
        patch("sleeper_dynasty.cli.fetch_ktc_values", new_callable=AsyncMock, return_value={}),
        patch("sleeper_dynasty.cli.HTMLReport", return_value=mock_report) as mock_report_cls,
        patch("sleeper_dynasty.cli.webbrowser.open") as mock_open,
        patch("sleeper_dynasty.cli.FileCache") as mock_cache_cls,
    ):
        mock_cache_cls.return_value.read.return_value = None
        await _run_analysis(mock_args)

    # HTMLReport was instantiated once with league name + season.
    mock_report_cls.assert_called_once()
    ctor_kwargs = mock_report_cls.call_args.kwargs
    assert ctor_kwargs["league_name"] == "Test Dynasty"
    assert ctor_kwargs["season"] == 2026

    # And generate() was called once, with the keyword args the CLI passes.
    mock_report.generate.assert_called_once()
    call_kwargs = mock_report.generate.call_args.kwargs
    assert call_kwargs["league"] is league
    assert call_kwargs["rosters"] is rosters
    assert "sim_result" in call_kwargs
    assert "dynasty_outlooks" in call_kwargs
    assert "player_projections" in call_kwargs
    assert "player_names" in call_kwargs
    assert "player_ages" in call_kwargs

    # And we opened the rendered file in the browser.
    mock_open.assert_called_once()
    assert mock_open.call_args.args[0].startswith("file://")


# ---------------------------------------------------------------------------
# End-to-end smoke test: trade-grader pipeline (no network)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_pipeline_one_trade_one_season():
    """Single-league chain, one trade, hand-computed expected grades."""
    from datetime import datetime, timezone

    from sleeper_dynasty.engine.trade_grader import (
        aggregate_owner_records,
        grade_trade,
    )
    from sleeper_dynasty.engine.trade_history import build_trade_history
    from sleeper_dynasty.models.league import League, Roster
    from sleeper_dynasty.models.player import KTCValue

    client = MagicMock()
    league_2024 = League(
        league_id="L24", name="Bros", season=2024,
        total_rosters=2, roster_positions=[], scoring_settings={},
        playoff_week_start=15, num_playoff_teams=6, status="complete",
    )
    client.walk_league_history = AsyncMock(return_value=[league_2024])
    client.get_users = AsyncMock(return_value={
        "u_a": {"display_name": "Alice", "team_name": None},
        "u_b": {"display_name": "Bob", "team_name": None},
    })
    client.get_rosters = AsyncMock(return_value=[
        Roster(1, "u_a", "Alice", [], 0, 0, 0, 0, 0),
        Roster(2, "u_b", "Bob", [], 0, 0, 0, 0, 0),
    ])

    async def fake_txs(league_id, week):
        if week == 2:
            return [{
                "type": "trade", "status": "complete",
                "transaction_id": "tx",
                "created": int(datetime(2024, 9, 12, tzinfo=timezone.utc).timestamp() * 1000),
                "leg": 2,
                "roster_ids": [1, 2],
                "adds": {"p_bijan": 1, "p_adams": 2},
                "drops": {"p_adams": 1, "p_bijan": 2},
                "draft_picks": [],
                "waiver_budget": [],
            }]
        return []

    client.get_transactions = AsyncMock(side_effect=fake_txs)

    wire_transaction_protocol(client)
    client.get_drafts = AsyncMock(return_value=[])
    client.get_draft_picks = AsyncMock(return_value=[])

    resolved = await build_trade_history(
        client,
        current_league_id="L24",
        player_names={"p_bijan": "Bijan", "p_adams": "Adams"},
    )
    assert len(resolved) == 1

    # Hand-built KTC + matchup tables.
    ktc = {
        "p_bijan": KTCValue("Bijan", "bijan", "RB", 7500, 7400, None, None),
        "p_adams": KTCValue("Adams", "adams", "WR", 6050, 6000, None, None),
    }
    matchups = {
        ("L24", 3, 1): {
            "starters": ["p_bijan"], "players": ["p_bijan"],
            "players_points": {"p_bijan": 22.0},
            "team_points": 100.0, "opponent_points": 80.0,
        },
        ("L24", 3, 2): {
            "starters": ["p_adams"], "players": ["p_adams"],
            "players_points": {"p_adams": 14.0},
            "team_points": 90.0, "opponent_points": 95.0,
        },
    }
    grade = grade_trade(
        resolved[0],
        ktc_values=ktc,
        matchups=matchups,
        roster_to_user_by_league={"L24": {1: "u_a", 2: "u_b"}},
        playoff_week_start_by_league={"L24": 15},
        fmt="superflex",
    )

    # Lens 1 — Snapshot KTC: Alice gained Bijan (7500) and gave Adams (6050) → +1450.
    assert grade.snapshot_value_swing["u_a"] == pytest.approx(1450.0)
    assert grade.snapshot_value_swing["u_b"] == pytest.approx(-1450.0)

    # Lens 2 — Hindsight (received-only): Alice got Bijan who scored 22 in week 3.
    #   Bob got Adams who scored 14. No phantom subtraction.
    assert grade.production_total["u_a"] == pytest.approx(22.0)
    assert grade.production_total["u_b"] == pytest.approx(14.0)

    # Points Started (regular phase) — Bijan started in week 3 (regular season),
    #   received-only, so the regular-started total matches: 22.0.
    assert grade.production_regular["u_a"] == pytest.approx(22.0)
    # Playoff Points — week 3 is regular season, so 0.
    assert grade.production_playoff["u_a"] == pytest.approx(0.0)

    # Aggregation.
    records = aggregate_owner_records(
        [grade], display_names={"u_a": "Alice", "u_b": "Bob"}
    )
    assert records["u_a"].net_ktc == pytest.approx(1450.0)
    assert records["u_a"].production_total == pytest.approx(22.0)
    assert records["u_a"].best_trade_id == "tx"
    assert records["u_b"].worst_trade_id == "tx"


# ---------------------------------------------------------------------------
# Unit tests for _assemble_played_matchups helper
# ---------------------------------------------------------------------------


def test_assemble_played_matchups_skips_zero_point_placeholders():
    """Both teams at 0 points signals an unplayed Sleeper placeholder week."""
    from sleeper_dynasty.cli import _assemble_played_matchups

    raw_per_week = {
        # Played game: nonzero on at least one side.
        3: [
            {
                "matchup_id": 1,
                "roster_id": 1,
                "points": 105.5,
                "starters": ["p1"],
                "players": ["p1"],
                "players_points": {"p1": 22.0},
            },
            {
                "matchup_id": 1,
                "roster_id": 2,
                "points": 92.0,
                "starters": ["p2"],
                "players": ["p2"],
                "players_points": {"p2": 14.0},
            },
        ],
        # Unplayed placeholder week (both points == 0).
        4: [
            {
                "matchup_id": 2,
                "roster_id": 1,
                "points": 0.0,
                "starters": ["p1"],
                "players": ["p1"],
                "players_points": {"p1": 0.0},
            },
            {
                "matchup_id": 2,
                "roster_id": 2,
                "points": 0.0,
                "starters": ["p2"],
                "players": ["p2"],
                "players_points": {"p2": 0.0},
            },
        ],
    }
    out = _assemble_played_matchups(raw_per_week, league_id="L")

    # Played week is present.
    assert ("L", 3, 1) in out
    assert ("L", 3, 2) in out
    # Unplayed placeholder is excluded.
    assert ("L", 4, 1) not in out
    assert ("L", 4, 2) not in out


def test_assemble_played_matchups_counts_one_sided_real_game():
    """A real game where one team scored 0 but the other scored >0 still
    counts (e.g., shutout). Only DOUBLE-zero indicates an unplayed
    placeholder."""
    from sleeper_dynasty.cli import _assemble_played_matchups

    raw_per_week = {
        5: [
            {
                "matchup_id": 1,
                "roster_id": 1,
                "points": 80.0,
                "starters": [],
                "players": [],
                "players_points": {},
            },
            {
                "matchup_id": 1,
                "roster_id": 2,
                "points": 0.0,
                "starters": [],
                "players": [],
                "players_points": {},
            },
        ],
    }
    out = _assemble_played_matchups(raw_per_week, league_id="L")
    assert ("L", 5, 1) in out
    assert ("L", 5, 2) in out


def test_assemble_played_matchups_carries_opponent_roster_id():
    """Each roster-week entry records its opponent's roster_id so head-to-head
    records can resolve the opposing owner without re-pairing matchup_ids."""
    from sleeper_dynasty.cli import _assemble_played_matchups

    raw_per_week = {
        6: [
            {"matchup_id": 1, "roster_id": 1, "points": 100.0,
             "starters": [], "players": [], "players_points": {}},
            {"matchup_id": 1, "roster_id": 2, "points": 90.0,
             "starters": [], "players": [], "players_points": {}},
        ],
    }
    out = _assemble_played_matchups(raw_per_week, league_id="L")
    assert out[("L", 6, 1)]["opponent_roster_id"] == 2
    assert out[("L", 6, 2)]["opponent_roster_id"] == 1
