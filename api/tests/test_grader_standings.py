from __future__ import annotations

from app.services.grader import GraderService
from app.services.standings_snapshot_store import StandingsSnapshotStore
from sleeper_dynasty.models.league import Roster


def _supporting_single_league():
    # roster 1 (ua): wins both weeks -> 2-0, pf 220.0
    # roster 2 (ub): loses both weeks -> 0-2, pf 170.0
    return {
        "matchups": {
            ("LG", 1, 1): {"team_points": 100.0, "opponent_points": 90.0},
            ("LG", 1, 2): {"team_points": 90.0, "opponent_points": 100.0},
            ("LG", 2, 1): {"team_points": 120.0, "opponent_points": 80.0},
            ("LG", 2, 2): {"team_points": 80.0, "opponent_points": 120.0},
        },
        "roster_to_user_by_league": {"LG": {1: "ua", 2: "ub"}},
        "league_season_by_id": {"LG": 2024},
        "playoff_week_start_by_league": {"LG": 15},
    }


def test_snapshot_standings_writes_history(tmp_path):
    supporting = {
        "matchups": {
            ("LG", 1, 1): {"team_points": 100.0, "opponent_points": 90.0},
            ("LG", 1, 2): {"team_points": 90.0, "opponent_points": 100.0},
            ("LG", 2, 1): {"team_points": 120.0, "opponent_points": 80.0},
            ("LG", 2, 2): {"team_points": 80.0, "opponent_points": 120.0},
        },
        "roster_to_user_by_league": {"LG": {1: "ua", 2: "ub"}},
        "league_season_by_id": {"LG": 2024},
        "playoff_week_start_by_league": {"LG": 15},
    }
    GraderService()._snapshot_standings(
        supporting=supporting, current_league_id="ENTRY", cache_dir=tmp_path,
    )
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    data = store.read("ENTRY")
    assert set(data) == {"2024-01", "2024-02"}
    wk2 = {r["owner_id"]: r for r in data["2024-02"]}
    assert wk2["ua"]["wins"] == 2 and wk2["ua"]["rank"] == 1


def test_snapshot_standings_swallows_errors(tmp_path):
    # Malformed supporting must not raise.
    GraderService()._snapshot_standings(
        supporting={"matchups": None}, current_league_id="X", cache_dir=tmp_path,
    )


def _roster(roster_id, owner_id, wins, losses, pf):
    return Roster(
        roster_id=roster_id, owner_id=owner_id, owner_name=owner_id,
        players=[], wins=wins, losses=losses, ties=0,
        points_for=pf, points_against=0.0,
    )


def test_snapshot_standings_validates_matching_rosters(tmp_path):
    # current_rosters match the reconstructed record exactly -> no raise, snapshot written.
    supporting = _supporting_single_league()
    rosters = [
        _roster(1, "ua", wins=2, losses=0, pf=220.0),
        _roster(2, "ub", wins=0, losses=2, pf=170.0),
    ]
    GraderService()._snapshot_standings(
        supporting=supporting, current_league_id="LG", cache_dir=tmp_path,
        current_rosters=rosters,
    )
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    assert set(store.read("LG")) == {"2024-01", "2024-02"}


def test_snapshot_standings_mismatch_does_not_raise(tmp_path):
    # current_rosters deliberately disagree -> best-effort/logged only, never raises.
    supporting = _supporting_single_league()
    rosters = [
        _roster(1, "ua", wins=0, losses=2, pf=10.0),
        _roster(2, "ub", wins=2, losses=0, pf=999.0),
    ]
    GraderService()._snapshot_standings(
        supporting=supporting, current_league_id="LG", cache_dir=tmp_path,
        current_rosters=rosters,
    )
    store = StandingsSnapshotStore(cache_dir=tmp_path)
    assert set(store.read("LG")) == {"2024-01", "2024-02"}
