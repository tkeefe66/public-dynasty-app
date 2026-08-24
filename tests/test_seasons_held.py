from sleeper_dynasty.engine.draft_results import seasons_held_while_on_roster

MATCHUPS = {
    ("L25", 1, 1): {"players": ["p"], "starters": [], "players_points": {}},
    ("L25", 9, 1): {"players": ["p"], "starters": [], "players_points": {}},
    ("L26", 3, 1): {"players": ["p"], "starters": [], "players_points": {}},
    ("L26", 4, 2): {"players": ["p"], "starters": [], "players_points": {}},
}
R2U = {"L25": {1: "u1"}, "L26": {1: "u1", 2: "u2"}}
SEASONS = {"L25": 2025, "L26": 2026}


def _held(uid):
    return seasons_held_while_on_roster(
        "p", uid, matchups=MATCHUPS, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS)


def test_counts_distinct_seasons_not_weeks():
    # Two weeks in 2025 and one in 2026 is TWO seasons, not three.
    assert _held("u1") == 2


def test_a_week_on_another_owners_roster_does_not_count():
    assert _held("u2") == 1


def test_a_player_never_held_counts_zero():
    assert seasons_held_while_on_roster(
        "nobody", "u1", matchups=MATCHUPS, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS) == 0


def test_one_week_is_a_whole_season():
    # A pick traded away in week 2 was still held THAT season; judging him
    # against a zero-season cohort is not possible, and against a full-season
    # cohort is the honest comparison for the time he was there.
    single = {("L25", 2, 1): {"players": ["p"], "starters": [], "players_points": {}}}
    assert seasons_held_while_on_roster(
        "p", "u1", matchups=single, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS) == 1
    # Still true when L25 is explicitly marked COMPLETE — one week is a whole
    # season for a season that has actually finished.
    assert seasons_held_while_on_roster(
        "p", "u1", matchups=single, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS, completed_seasons={2025}) == 1


def test_an_in_progress_season_does_not_count_until_it_completes():
    # CRITICAL A: held all of L25 (2025, complete) plus one week of L26
    # (2026, still in progress) is ONE season, not two — matching the
    # cohort's own `n`, which only ever counts COMPLETE seasons. Without this,
    # one played week and a handful of points bumps the pick from cell n to
    # n+1 (a much higher bar) and can flip Hit to Bust for the whole league
    # until that season actually finishes.
    assert _held("u1") == 2  # unrestricted: both seasons count
    assert seasons_held_while_on_roster(
        "p", "u1", matchups=MATCHUPS, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS, completed_seasons={2025}) == 1
    # Once 2026 also completes, it counts too.
    assert seasons_held_while_on_roster(
        "p", "u1", matchups=MATCHUPS, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS, completed_seasons={2025, 2026}) == 2
    # completed_seasons=None (the default) is unaffected — existing callers
    # keep counting every season held.
    assert seasons_held_while_on_roster(
        "p", "u1", matchups=MATCHUPS, roster_to_user_by_league=R2U,
        league_season_by_id=SEASONS, completed_seasons=None) == 2
