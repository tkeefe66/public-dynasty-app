import json
from datetime import date

import pytest

from sleeper_dynasty.engine.outlook_build import (
    ktc_position_rankings, roster_value_ranks,
    build_outlooks_by_owner, outlook_to_dict, league_avg_age_by_position,
)
from sleeper_dynasty.models.league import Roster
from sleeper_dynasty.models.player import Player


def _roster(rid, players, owner=None):
    owner = owner or f"u{rid}"
    return Roster(roster_id=rid, owner_id=owner, owner_name=owner,
                  players=players,
                  wins=0, losses=0, ties=0, points_for=0.0, points_against=0.0)


def test_ktc_position_rankings_orders_by_value_desc():
    rosters = [_roster(1, ["wr1", "wr2"], "uA"), _roster(2, ["wr3"], "uB")]
    positions = {"wr1": "WR", "wr2": "WR", "wr3": "WR"}
    ktc = {"wr1": 100.0, "wr2": 900.0, "wr3": 500.0}
    rankings = ktc_position_rankings(rosters, positions, ktc)
    assert rankings["WR"] == ["wr2", "wr3", "wr1"]


def test_roster_value_ranks_one_based_with_total():
    ranks = roster_value_ranks({"uA": 300.0, "uB": 100.0, "uC": 200.0})
    assert ranks["uA"] == {"rank": 1, "of": 3}
    assert ranks["uB"] == {"rank": 3, "of": 3}


def _player(pid, pos, birth):
    return Player(player_id=pid, full_name=pid.upper(), position=pos,
                  team="X", birth_date=birth)


def _kwargs():
    rosters = [_roster(1, ["rb1", "wr1"], "uA"), _roster(2, ["qb1"], "uB")]
    players = {
        "rb1": _player("rb1", "RB", date(1990, 1, 1)),   # old RB -> aging risk
        "wr1": _player("wr1", "WR", date(2003, 1, 1)),   # young WR -> core young
        "qb1": _player("qb1", "QB", date(1998, 1, 1)),
    }
    positions = {"rb1": "RB", "wr1": "WR", "qb1": "QB"}
    ktc = {"rb1": 200.0, "wr1": 800.0, "qb1": 500.0}
    return dict(
        rosters=rosters, players=players, traded_picks=[], positions=positions,
        ktc_value_by_player=ktc, roster_to_user={1: "uA", 2: "uB"},
        total_rosters=2, num_rounds=4)


def test_build_and_serialize_outlook_is_json_safe():
    outlooks, _ = build_outlooks_by_owner(**_kwargs())
    assert set(outlooks) == {"uA", "uB"}
    d = outlook_to_dict(outlooks["uA"], as_of=date(2026, 1, 1))
    # round-trips through JSON (no date objects, no tuple keys)
    json.dumps(d)
    assert isinstance(d["age_profile"]["aging_risks"], list)
    assert any(p["player_id"] == "rb1" for p in d["age_profile"]["aging_risks"])
    assert any(p["player_id"] == "wr1" for p in d["age_profile"]["core_young"])
    assert d["draft_capital"]["status"] in ("pick-rich", "neutral", "pick-poor")
    for dead in ("window", "trajectory", "strength_score",
                 "trajectory_score", "window_breakdown"):
        assert dead not in d, f"{dead} survived the deletion"


def _players(spec: dict) -> dict:
    """pid -> Player, from {pid: (position, age-as-of-2026-01-01)}."""
    return {
        pid: _player(pid, pos, date(2026 - age, 1, 1))
        for pid, (pos, age) in spec.items()
    }


def test_league_mean_age_is_the_LEAGUE_s_not_one_owner_s():
    """Two owners whose per-position means differ. The league figure must be
    neither owner's own — it is pooled over every rostered player at that
    position, the same way an owner's own avg_age_by_position is pooled over
    theirs. One definition of "mean age at a position", not two."""
    means = league_avg_age_by_position(
        rosters=[_roster(1, ["rb22", "rb24"]), _roster(2, ["rb30"])],
        players=_players({"rb22": ("RB", 22), "rb24": ("RB", 24),
                          "rb30": ("RB", 30)}),
        as_of=date(2026, 1, 1),
    )
    assert means["RB"] == pytest.approx((22 + 24 + 30) / 3)
    assert means["RB"] != 23.0      # owner 1's mean
    assert means["RB"] != 30.0      # owner 2's mean


def test_league_mean_age_skips_k_and_def():
    means = league_avg_age_by_position(
        rosters=[_roster(1, ["k1", "def1", "wr1"])],
        players=_players({"k1": ("K", 30), "def1": ("DEF", 30),
                          "wr1": ("WR", 24)}),
        as_of=date(2026, 1, 1),
    )
    assert set(means) == {"WR"}


def test_build_outlooks_by_owner_returns_the_league_map_alongside():
    outlooks, league_ages = build_outlooks_by_owner(**_kwargs())
    assert isinstance(outlooks, dict) and isinstance(league_ages, dict)


def test_outlook_to_dict_emits_the_league_map_and_the_need_keys():
    outlooks, league_ages = build_outlooks_by_owner(**_kwargs())
    d = outlook_to_dict(
        outlooks["uA"], as_of=date(2026, 1, 1),
        league_avg_age_by_position=league_ages,
    )
    assert d["age_profile"]["league_avg_age_by_position"] == league_ages
    for n in d["draft_needs"]:
        assert {"position", "urgency", "reason", "held", "ideal", "kind"} <= set(n)


def test_outlook_to_dict_without_the_map_emits_an_empty_one():
    """The CLI never computes it. An empty dict is a real reading ("no league
    comparison available"); a missing key would KeyError in owner_view."""
    outlooks, _ = build_outlooks_by_owner(**_kwargs())
    d = outlook_to_dict(outlooks["uA"], as_of=date(2026, 1, 1))
    assert d["age_profile"]["league_avg_age_by_position"] == {}
