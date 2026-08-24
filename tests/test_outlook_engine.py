import pytest

from sleeper_dynasty.engine.outlook import (
    build_matchup_previews, build_playoff_stakes,
)
from sleeper_dynasty.models.league import MatchupResult, Roster


def _result(mid, rid):
    # Upcoming-week matchups come back with both points 0; we only need the
    # pairing (matchup_id) for previews.
    return MatchupResult(10, mid, rid, 0.0, [], [], {})


def _roster(rid, owner, w, l, pf):
    return Roster(rid, str(rid), owner, [f"p{rid}"], w, l, 0, pf, 0.0)


def test_matchup_previews_set_favorite_by_projected():
    pairings = [_result(1, 1), _result(1, 2)]
    owners = {1: "A", 2: "B"}
    team_projected = {1: 115.0, 2: 102.0}
    previews = build_matchup_previews(pairings, owners, team_projected)
    assert previews[0].favorite == "A"
    assert previews[0].spread == pytest.approx(13.0)


def test_playoff_stakes_flag_cutoff_bubble():
    rosters = [
        _roster(1, "A", 8, 1, 1200), _roster(2, "B", 7, 2, 1100),
        _roster(3, "C", 4, 5, 900),  _roster(4, "D", 1, 8, 700),
    ]
    stakes = build_playoff_stakes(rosters, num_playoff_teams=2,
                                  weeks_remaining=1)
    by_owner = {s.owner: s.status for s in stakes}
    assert by_owner["A"] in ("can-clinch", "in-the-hunt")
    assert by_owner["D"] == "eliminated"


from sleeper_dynasty.engine.outlook import build_bye_trouble
from sleeper_dynasty.models.player import Player


def test_bye_trouble_finds_starters_on_bye_and_replacement():
    # Roster 1: starter p1 (QB, BUF) is on bye; p2 (QB, CHI) is the backup.
    players = {
        "p1": Player("p1", "Josh Allen", "QB", "BUF"),
        "p2": Player("p2", "Backup Guy", "QB", "CHI"),
        "p3": Player("p3", "A Receiver", "WR", "MIA"),
    }
    roster = _roster(1, "Team A", 5, 3, 1000)
    roster.players = ["p1", "p2", "p3"]
    projections = {"p1": 22.0, "p2": 6.0, "p3": 14.0}
    troubles = build_bye_trouble(
        rosters=[roster], owner_by_roster={1: "Team A"},
        players=players, byes={"BUF"},
        roster_positions=["QB", "WR", "BN"], projections=projections,
    )
    assert len(troubles) == 1
    t = troubles[0]
    assert "Josh Allen (QB, BUF)" in t.players_on_bye
    assert t.likely_replacement == "Backup Guy (QB, CHI)"
    assert t.replacement_projected == 6.0
