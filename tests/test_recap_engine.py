import pytest

from sleeper_dynasty.models.league import MatchupResult
from sleeper_dynasty.engine.recap import build_matchup_recaps, OWNER_BY_ROSTER


def _result(week, mid, rid, pts, starters=None, pp=None):
    return MatchupResult(
        week=week, matchup_id=mid, roster_id=rid, points=pts,
        starters=starters or [], players=list((pp or {}).keys()),
        players_points=pp or {},
    )


OWNERS = {1: "Team A", 2: "Team B", 3: "Team C", 4: "Team D"}


def test_pairs_by_matchup_id_and_flags_blowout():
    results = [
        _result(9, 1, 1, 142.3), _result(9, 1, 2, 98.1),
        _result(9, 2, 3, 100.0), _result(9, 2, 4, 97.0),
    ]
    recaps, high, low = build_matchup_recaps(results, OWNERS)
    blowout = next(r for r in recaps if r.winner == "Team A")
    assert blowout.loser == "Team B"
    assert blowout.margin == pytest.approx(44.2)
    assert blowout.blowout is True
    assert blowout.nailbiter is False


def test_flags_nailbiter_and_finds_scorers():
    results = [
        _result(9, 1, 1, 142.3), _result(9, 1, 2, 98.1),
        _result(9, 2, 3, 100.0), _result(9, 2, 4, 97.0),
    ]
    recaps, high, low = build_matchup_recaps(results, OWNERS)
    nail = next(r for r in recaps if r.winner == "Team C")
    assert nail.nailbiter is True
    assert high == {"owner": "Team A", "points": 142.3}
    assert low == {"owner": "Team D", "points": 97.0}


def test_skips_unplayed_both_zero():
    results = [_result(9, 1, 1, 0.0), _result(9, 1, 2, 0.0)]
    recaps, high, low = build_matchup_recaps(results, OWNERS)
    assert recaps == []
    assert high is None and low is None


from sleeper_dynasty.engine.recap import build_bench_regret


def test_bench_regret_finds_points_left_and_culprits():
    # Roster: 1 QB, 1 FLEX. Player positions + week points:
    #   p1 QB started 10  | p2 QB benched 25  (should have started p2)
    #   p3 WR started 4   | p4 WR benched 18
    positions_by_player = {
        "p1": "QB", "p2": "QB", "p3": "WR", "p4": "WR",
    }
    result = MatchupResult(
        week=9, matchup_id=1, roster_id=1, points=14.0,
        starters=["p1", "p3"],
        players=["p1", "p2", "p3", "p4"],
        players_points={"p1": 10.0, "p2": 25.0, "p3": 4.0, "p4": 18.0},
    )
    regret = build_bench_regret(
        result,
        roster_positions=["QB", "FLEX"],
        positions_by_player=positions_by_player,
        owner="Team A",
    )
    # Optimal: p2 (QB 25) + p4 (FLEX/WR 18) = 43; actual started = 14.
    assert regret.points_left_on_bench == pytest.approx(29.0)
    assert regret.benched_hero.player == "p2"
    assert regret.benched_hero.points == 25.0
    assert regret.started_dud.player == "p3"
    assert regret.started_dud.points == 4.0
    assert regret.owner == "Team A"


def test_bench_regret_none_when_lineup_optimal():
    positions_by_player = {"p1": "QB", "p2": "WR"}
    result = MatchupResult(
        week=9, matchup_id=1, roster_id=1, points=30.0,
        starters=["p1", "p2"], players=["p1", "p2"],
        players_points={"p1": 20.0, "p2": 10.0},
    )
    regret = build_bench_regret(
        result, ["QB", "FLEX"], positions_by_player, "Team A"
    )
    assert regret is None


from sleeper_dynasty.engine.recap import build_luck_notes


def test_luck_notes_flag_unlucky_loser_and_lucky_winner():
    # Pairs: A 140 beats B 90 ; C 110 beats D 105 ; E 80 beats F 70
    # Highest loser = D (105) -> unlucky. Lowest winner = E (80) -> lucky.
    results = [
        _result(9, 1, 1, 140.0), _result(9, 1, 2, 90.0),
        _result(9, 2, 3, 110.0), _result(9, 2, 4, 105.0),
        _result(9, 3, 5, 80.0), _result(9, 3, 6, 70.0),
    ]
    owners = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F"}
    lucky, unlucky = build_luck_notes(results, owners)
    assert any(n.owner == "D" for n in unlucky)
    assert any(n.owner == "E" for n in lucky)


def test_luck_notes_empty_when_no_games():
    results = [_result(9, 1, 1, 0.0), _result(9, 1, 2, 0.0)]
    lucky, unlucky = build_luck_notes(results, {1: "A", 2: "B"})
    assert lucky == [] and unlucky == []


from sleeper_dynasty.engine.recap import build_player_beats


def test_heroes_and_goats_rank_starters_only():
    results = [
        MatchupResult(9, 1, 1, 100.0, starters=["p1", "p2"],
                      players=["p1", "p2", "p3"],
                      players_points={"p1": 41.0, "p2": 2.0, "p3": 99.0}),
        MatchupResult(9, 1, 2, 90.0, starters=["p4"], players=["p4"],
                      players_points={"p4": 30.0}),
    ]
    owners = {1: "A", 2: "B"}
    positions = {"p1": "WR", "p2": "RB", "p3": "QB", "p4": "TE"}
    heroes, goats, busts = build_player_beats(
        results, owners, positions, projections={}
    )
    # p3 has 99 but was BENCHED -> excluded. p1 (41) is top hero.
    assert heroes[0].player == "p1"
    assert all(h.player != "p3" for h in heroes)
    # Lowest started = p2 (2.0).
    assert goats[0].player == "p2"


def test_busts_flag_underperformers_vs_projection():
    results = [
        MatchupResult(9, 1, 1, 50.0, starters=["p1"], players=["p1"],
                      players_points={"p1": 4.0}),
    ]
    heroes, goats, busts = build_player_beats(
        results, {1: "A"}, {"p1": "WR"}, projections={"p1": 22.0}
    )
    assert busts[0].player == "p1"
    assert busts[0].projected == 22.0
    assert busts[0].points == 4.0


from sleeper_dynasty.engine.recap import build_standings
from sleeper_dynasty.models.league import Roster


def _roster(rid, owner, w, l, pf):
    return Roster(roster_id=rid, owner_id=str(rid), owner_name=owner,
                  players=[], wins=w, losses=l, ties=0,
                  points_for=pf, points_against=0.0)


def test_standings_sorted_by_wins_then_points():
    rosters = [
        _roster(1, "A", 5, 3, 900.0),
        _roster(2, "B", 7, 1, 1100.0),
        _roster(3, "C", 7, 1, 1200.0),
    ]
    standings = build_standings(rosters)
    assert [s["owner"] for s in standings] == ["C", "B", "A"]
    assert standings[0]["wins"] == 7
    assert standings[0]["points_for"] == 1200.0


from sleeper_dynasty.engine.recap import build_recap_facts
from sleeper_dynasty.models.player import Player
from sleeper_dynasty.models.recap import RecapFacts


def test_build_recap_facts_resolves_names_and_nests():
    players = {
        "p1": Player("p1", "Josh Allen", "QB", "BUF"),
        "p2": Player("p2", "Scrub Guy", "RB", "NYJ"),
        "p3": Player("p3", "Bench Star", "WR", "MIA"),
    }
    results = [
        MatchupResult(9, 1, 1, 45.0, starters=["p1", "p2"],
                      players=["p1", "p2", "p3"],
                      players_points={"p1": 41.0, "p2": 4.0, "p3": 30.0}),
        MatchupResult(9, 1, 2, 30.0, starters=["p1"], players=["p1"],
                      players_points={"p1": 30.0}),
    ]
    rosters = [_roster(1, "Team A", 1, 0, 45.0),
               _roster(2, "Team B", 0, 1, 30.0)]
    facts = build_recap_facts(
        week=9, league_name="Bros", results=results, rosters=rosters,
        owner_by_roster={1: "Team A", 2: "Team B"}, players=players,
        roster_positions=["QB", "FLEX"], weekly_projections={},
    )
    assert isinstance(facts, RecapFacts)
    assert facts.heroes[0].player == "Josh Allen (QB, BUF)"
    # Bench regret hero name resolved too.
    assert facts.bench_regret[0].benched_hero.player == "Bench Star (WR, MIA)"
