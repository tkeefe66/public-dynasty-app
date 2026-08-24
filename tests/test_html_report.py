"""Unit tests for the self-contained HTML report renderer."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from sleeper_dynasty.engine.dynasty import (
    AgeProfile,
    DraftCapital,
    DraftNeed,
    DynastyOutlook,
)
from sleeper_dynasty.engine.simulator import (
    MatchupSimResult,
    SimulationResult,
    TeamSimResult,
)
from sleeper_dynasty.models.league import League, Roster
from sleeper_dynasty.models.player import Player
from sleeper_dynasty.output.html_report import (
    HTMLReport,
    _outlook_label,
    _probability_class,
    _slugify,
)


# ---------------------------------------------------------------------------
# Pure-helper tests
# ---------------------------------------------------------------------------


def test_outlook_label_contender():
    assert _outlook_label(75.0) == "Contender"


def test_outlook_label_bubble():
    assert _outlook_label(45.0) == "Bubble"


def test_outlook_label_rebuilding():
    assert _outlook_label(15.0) == "Rebuilding"


def test_probability_class_thresholds():
    assert _probability_class(80.0) == "prob-high"
    assert _probability_class(70.0) == "prob-high"
    assert _probability_class(50.0) == "prob-mid"
    assert _probability_class(30.0) == "prob-mid"
    assert _probability_class(29.9) == "prob-low"
    assert _probability_class(0.0) == "prob-low"


def test_slugify_strips_unsafe_chars():
    assert _slugify("Tom's Dynasty League!") == "tom-s-dynasty-league"
    assert _slugify("  ") == "league"
    assert _slugify("Plain Name") == "plain-name"


# ---------------------------------------------------------------------------
# End-to-end render test
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_league_data():
    """Build the smallest realistic dataset the renderer needs."""
    league = League(
        league_id="lg1",
        name="Test League",
        season=2026,
        total_rosters=2,
        roster_positions=["QB", "RB", "WR"],
        scoring_settings={"rec": 1.0},
        playoff_week_start=15,
        num_playoff_teams=2,
        status="in_season",
    )
    rosters = [
        Roster(
            roster_id=1,
            owner_id="u1",
            owner_name="Alice",
            players=["p1", "p2"],
            wins=2,
            losses=1,
            ties=0,
            points_for=300.0,
            points_against=280.0,
        ),
        Roster(
            roster_id=2,
            owner_id="u2",
            owner_name="Bob",
            players=["p3", "p4"],
            wins=1,
            losses=2,
            ties=0,
            points_for=270.0,
            points_against=290.0,
        ),
    ]
    sim_result = SimulationResult(
        team_results={
            1: TeamSimResult(
                roster_id=1,
                avg_wins=9.0,
                avg_losses=5.0,
                win_low=7.0,
                win_high=11.0,
                playoff_pct=85.0,
                championship_pct=22.0,
                avg_points_for=1500.0,
            ),
            2: TeamSimResult(
                roster_id=2,
                avg_wins=5.0,
                avg_losses=9.0,
                win_low=3.0,
                win_high=7.0,
                playoff_pct=15.0,
                championship_pct=1.0,
                avg_points_for=1300.0,
            ),
        },
        matchup_results=[
            MatchupSimResult(
                week=1,
                roster_id_1=1,
                roster_id_2=2,
                win_pct_1=72.0,
                win_pct_2=28.0,
                avg_score_1=125.0,
                avg_score_2=110.0,
            ),
            MatchupSimResult(
                week=2,
                roster_id_1=2,
                roster_id_2=1,
                win_pct_1=30.0,
                win_pct_2=70.0,
                avg_score_1=108.0,
                avg_score_2=122.0,
            ),
        ],
    )

    alice = Player(player_id="p1", full_name="Alice Star", position="QB", team="KC")
    bob_player = Player(player_id="p3", full_name="Bob Veteran", position="RB", team="NYG")

    dynasty_outlooks = {
        1: DynastyOutlook(
            age_profile=AgeProfile(
                avg_age_by_position={"QB": 24.0},
                aging_risks=[],
                core_young=[alice],
                overall_avg_age=24.0,
            ),
            draft_capital=DraftCapital(
                picks_by_season={2027: 4},
                picks_by_season_round={(2027, 1): 1, (2027, 2): 1, (2027, 3): 1, (2027, 4): 1},
                picks_traded_away=0,
                picks_acquired=0,
                net_vs_average=0.0,
                status="neutral",
            ),
            draft_needs=[
                DraftNeed(position="WR", urgency="developing", reason="Thin depth at WR"),
            ],
        ),
        2: DynastyOutlook(
            age_profile=AgeProfile(
                avg_age_by_position={"RB": 29.0},
                aging_risks=[bob_player],
                core_young=[],
                overall_avg_age=29.0,
            ),
            draft_capital=DraftCapital(
                picks_by_season={2027: 6},
                picks_by_season_round={(2027, 1): 2, (2027, 2): 2, (2027, 3): 1, (2027, 4): 1},
                picks_traded_away=0,
                picks_acquired=2,
                net_vs_average=2.0,
                status="pick-rich",
            ),
            draft_needs=[
                DraftNeed(position="QB", urgency="immediate", reason="No starting QB"),
            ],
        ),
    }

    player_projections = {
        "p1": ("QB", 22.5),
        "p2": ("WR", 14.0),
        "p3": ("RB", 11.0),
        "p4": ("WR", 9.0),
    }
    player_names = {
        "p1": "Alice Star",
        "p2": "Alice Backup",
        "p3": "Bob Veteran",
        "p4": "Bob Rookie",
    }
    player_ages = {"p1": 24, "p2": 26, "p3": 29, "p4": 22}

    return {
        "league": league,
        "rosters": rosters,
        "sim_result": sim_result,
        "dynasty_outlooks": dynasty_outlooks,
        "player_projections": player_projections,
        "player_names": player_names,
        "player_ages": player_ages,
    }


def test_generate_writes_file_and_contains_expected_content(
    tmp_path, monkeypatch, minimal_league_data
):
    # Redirect output to a tmp dir so the test doesn't pollute ~/.
    monkeypatch.setattr(
        "sleeper_dynasty.output.html_report.REPORTS_DIR", tmp_path
    )

    report = HTMLReport(league_name="Test League", season=2026)
    path = report.generate(**minimal_league_data)

    assert path.exists()
    assert path.parent == tmp_path
    assert path.suffix == ".html"

    content = path.read_text(encoding="utf-8")

    # Top-level shell.
    assert content.startswith("<!DOCTYPE html>")
    assert content.rstrip().endswith("</html>")
    assert "<title>Test League - Dynasty Analysis</title>" in content

    # Header + nav.
    assert "Test League" in content
    assert "Projected Standings" in content
    assert "Team Reports" in content
    assert "Matchups" in content

    # Section headers.
    assert "Projected Final Standings" in content
    assert "Weekly Matchup Forecasts" in content

    # Both teams represented.
    assert "Alice" in content
    assert "Bob" in content

    # Probability cell classes are present.
    assert "prob-high" in content
    assert "prob-low" in content

    # Weekly matchups expanded for first week.
    assert "Week 1" in content
    assert "Week 2" in content
    # The first <details> block should be open by default.
    assert 'class="week-block" open' in content


def test_report_renders_without_a_window_chip(
    tmp_path, monkeypatch, minimal_league_data
):
    """The CLI export dropped the Dynasty Window chip permanently: it has no
    Franchise Rating in scope, and a second engine-side stage derivation would
    rebuild the two-models problem this change exists to delete."""
    monkeypatch.setattr(
        "sleeper_dynasty.output.html_report.REPORTS_DIR", tmp_path
    )
    html = HTMLReport(
        league_name="Test League", season=2026
    ).generate(**minimal_league_data).read_text(encoding="utf-8")
    assert "chip-competing" not in html
    assert "Dynasty Window" not in html
    assert "Trajectory:" not in html


def test_generate_handles_special_chars_safely(tmp_path, monkeypatch, minimal_league_data):
    # League name with HTML-special chars should not break rendering.
    monkeypatch.setattr(
        "sleeper_dynasty.output.html_report.REPORTS_DIR", tmp_path
    )
    report = HTMLReport(league_name="A&B <Test> League", season=2026)
    path = report.generate(**minimal_league_data)
    content = path.read_text(encoding="utf-8")

    # Autoescape should encode the unsafe characters.
    assert "A&amp;B &lt;Test&gt; League" in content
    # And the raw form should not appear (would have meant unescaped output).
    assert "A&B <Test> League" not in content
