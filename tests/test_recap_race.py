from dataclasses import replace

from sleeper_dynasty.models.league import League, Roster


def roster(i, wins, losses, points, ties=0):
    return Roster(i, str(i), f"Owner {i}", [], wins, losses, ties, points, 0)


def league():
    return League("test", "League", 2026, 4, ["QB"], {}, 15, 2, "in_season")


def test_results_erase_lead_and_change_cutoff_position():
    # Mutation: reuse after standings as before, or ignore points-for tiebreak.
    from sleeper_dynasty.engine.recap_race import build_race_context
    before = [roster(1, 7, 2, 1100), roster(2, 5, 4, 900), roster(3, 4, 5, 920), roster(4, 2, 7, 800)]
    after = [replace(before[0], wins=8), replace(before[1], losses=5, points_for=1000),
             replace(before[2], wins=5, points_for=1040), replace(before[3], losses=8)]
    race = build_race_context(before, after, league(), 10)
    rows = {r["owner"]: r for r in race["teams"]}
    assert rows["Owner 3"]["rank_before"] == 3
    assert rows["Owner 3"]["rank_after"] == 2
    assert rows["Owner 2"]["rank_after"] == 3
    assert any(c["side_a"] == "Owner 3" and c["side_b"] == "Owner 2"
               and c["gap_before"] == -1 and c["gap_after"] == 0 for c in race["changed_gaps"])
    assert race["emphasis"] == "playoff_race"


def test_week_one_has_no_fake_rank_movement_and_ties_are_not_broken_arbitrarily():
    # Mutation: assign week-zero positions by roster order, or break exact ties by ID.
    from sleeper_dynasty.engine.recap_race import build_race_context
    before = [roster(i, 0, 0, 0) for i in range(1, 5)]
    after = [roster(1, 1, 0, 100), roster(2, 1, 0, 100), roster(3, 0, 1, 90), roster(4, 0, 1, 80)]
    race = build_race_context(before, after, league(), 1)
    assert race["emphasis"] == "early_trends"
    assert all(r["rank_before"] is None for r in race["teams"])
    assert [r["rank_after"] for r in race["teams"][:2]] == [1, 1]
    assert all(r["rank_tied"] for r in race["teams"][:2])


def test_clinch_and_elimination_require_strict_record_bounds():
    # Mutation: treat a reachable tie as a clinch or elimination.
    from sleeper_dynasty.engine.recap_race import build_race_context
    rows = [roster(1, 10, 3, 1000), roster(2, 8, 5, 900), roster(3, 7, 6, 800), roster(4, 3, 10, 700)]
    race = build_race_context(rows, rows, league(), 13)
    statuses = {r["owner"]: r["playoff_status"] for r in race["teams"]}
    assert statuses == {"Owner 1": "clinched_by_record", "Owner 2": "in_race", "Owner 3": "in_race", "Owner 4": "eliminated_by_record"}


def test_nonstandard_or_unverified_records_do_not_get_playoff_claims():
    # Mutation: apply standard-head-to-head playoff math to median/division rules.
    from sleeper_dynasty.engine.recap_race import build_race_context
    lg = league()
    lg.standings_settings = {"league_average_match": 1}
    rows = [roster(i, 1, 0, 100) for i in range(1, 5)]
    assert build_race_context(rows, rows, lg, 1)["available"] is False
    assert build_race_context(rows, rows, league(), 1, verified=False)["available"] is False


def test_upcoming_opponents_get_conditional_gaps_and_middle_season_emphasis():
    # Mutation: predict the next winner, reverse signed gaps, or use late-season weight all year.
    from sleeper_dynasty.engine.recap_race import build_race_context
    from sleeper_dynasty.models.league import MatchupResult
    rows = [roster(1, 3, 2, 600), roster(2, 2, 3, 500), roster(3, 1, 4, 400), roster(4, 4, 1, 700)]
    pairings = [MatchupResult(6, 1, i, 0, [], [], {}) for i in (1, 2)]
    race = build_race_context(rows, rows, league(), 5, upcoming=pairings)
    assert race["emphasis"] == "developing_race"
    game = race["upcoming_matchups"][0]
    assert game["current_gap"] == 1
    assert game["gap_if_side_a_wins"] == 2
    assert game["gap_if_side_b_wins"] == 0


def test_tied_games_count_half_a_win_before_points_for():
    # Mutation: sort only by wins and let points override the extra tie.
    from sleeper_dynasty.engine.recap_race import build_race_context
    rows = [roster(1, 2, 2, 1000, ties=1), roster(2, 2, 3, 1100), roster(3, 1, 4, 700), roster(4, 4, 1, 1200)]
    race = build_race_context(rows, rows, league(), 5)
    assert [r["owner"] for r in race["teams"]] == ["Owner 4", "Owner 1", "Owner 2", "Owner 3"]
