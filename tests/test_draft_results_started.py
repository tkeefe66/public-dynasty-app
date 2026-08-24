from sleeper_dynasty.engine.draft_results import started_points_while_on_roster

# One owner (u1 owns roster 1 in league "L"), one player "p".
# wk 1  regular season, started, 10.0
# wk 15 playoff window, started, 20.0, classified "playoff"
# wk 16 playoff window, started, 30.0, classified NOTHING — a bye. This is the
#       week the old formula lost.
# wk 17 playoff window, BENCHED, 40.0, classified "playoff"
MATCHUPS = {
    ("L", 1, 1): {"starters": ["p"], "players": ["p"], "players_points": {"p": 10.0}},
    ("L", 15, 1): {"starters": ["p"], "players": ["p"], "players_points": {"p": 20.0}},
    ("L", 16, 1): {"starters": ["p"], "players": ["p"], "players_points": {"p": 30.0}},
    ("L", 17, 1): {"starters": [], "players": ["p"], "players_points": {"p": 40.0}},
}
R2U = {"L": {1: "u1"}}
PHASES = {("L", 15, 1): "playoff", ("L", 17, 1): "playoff"}
PWS = {"L": 15}


def _pts(phase):
    return started_points_while_on_roster(
        "p", "u1", phase=phase, matchups=MATCHUPS, roster_to_user_by_league=R2U,
        phase_by_lwr=PHASES, playoff_week_start_by_league=PWS)


def test_total_is_bench_inclusive_across_every_week():
    assert _pts("total") == 100.0


def test_started_counts_every_started_week_regardless_of_phase():
    # 10 (regular) + 20 (playoff) + 30 (BYE — belongs to no phase) = 60.
    # The benched 40 is excluded because it was never started.
    assert _pts("started") == 60.0


def test_the_phase_tallies_still_exclude_the_bye_week():
    assert _pts("regular") == 10.0
    assert _pts("playoff") == 20.0
    assert _pts("toilet") == 0.0


def test_phases_sum_to_less_than_started_and_the_gap_is_the_bye():
    phases = _pts("regular") + _pts("playoff") + _pts("toilet")
    assert phases == 30.0
    assert _pts("started") - phases == 30.0  # exactly the bye week


def test_started_is_owner_gated_like_every_other_phase():
    assert started_points_while_on_roster(
        "p", "someone-else", phase="started", matchups=MATCHUPS,
        roster_to_user_by_league=R2U, phase_by_lwr=PHASES,
        playoff_week_start_by_league=PWS) == 0.0
