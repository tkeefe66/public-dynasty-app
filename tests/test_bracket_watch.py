from sleeper_dynasty.engine.playoff_phase import build_bracket_watch

# A 6-team bracket. Seeds 1 and 2 have round-1 byes, so they first appear in
# round 2 — which is exactly why entrants are collected across every round
# rather than from round 1 alone.
R1 = [
    {"m": 1, "r": 1, "t1": 3, "t2": 6, "w": 3, "l": 6},
    {"m": 2, "r": 1, "t1": 4, "t2": 5, "w": 5, "l": 4},
]
R2 = [
    {"m": 3, "r": 2, "t1": 1, "t2": {"w": 1}, "w": 1, "l": 3},
    {"m": 4, "r": 2, "t1": 2, "t2": {"w": 2}, "w": 5, "l": 2},
]
R3_PENDING = [
    {"m": 5, "p": 1, "r": 3, "t1": 1, "t2": 5},
    {"m": 6, "p": 3, "r": 3, "t1": 3, "t2": 2},
]

ROSTER_TO_USER = {i: f"u{i}" for i in range(1, 13)}
SEEDS = {f"u{i}": i for i in range(1, 13)}


def test_no_bracket_is_no_watch():
    assert build_bracket_watch([], ROSTER_TO_USER) is None


def test_round_one_only_has_everyone_still_alive_except_the_two_losers():
    watch = build_bracket_watch(R1, ROSTER_TO_USER)
    assert set(watch["alive"]) == {"u3", "u5"}
    assert set(watch["eliminated"]) == {"u6", "u4"}


def test_bye_teams_count_as_entrants_even_before_they_play():
    """Seeds 1 and 2 never appear in round 1. Collecting entrants from round 1
    alone would report a 4-team bracket and call the top seed eliminated."""
    watch = build_bracket_watch(R1 + R2, ROSTER_TO_USER)
    assert watch["entered"] == 6
    assert "u1" in watch["alive"]


def test_semifinal_losers_are_eliminated():
    watch = build_bracket_watch(R1 + R2, ROSTER_TO_USER)
    assert set(watch["alive"]) == {"u1", "u5"}
    assert watch["alive_count"] == 2


def test_a_pending_game_eliminates_nobody():
    """w/l are null until a game is played — an unplayed final must not
    eliminate either finalist."""
    watch = build_bracket_watch(R1 + R2 + R3_PENDING, ROSTER_TO_USER)
    assert set(watch["alive"]) == {"u1", "u5"}


def test_losing_a_placement_game_does_not_eliminate():
    """Third-place and fifth-place games are off the title path. Their losers
    were already out; counting them again would double-eliminate and, worse,
    a placement WINNER must never read as still alive for the title."""
    played = R1 + R2 + [
        {"m": 5, "p": 1, "r": 3, "t1": 1, "t2": 5},
        {"m": 6, "p": 3, "r": 3, "t1": 3, "t2": 2, "w": 3, "l": 2},
    ]
    watch = build_bracket_watch(played, ROSTER_TO_USER)
    assert set(watch["alive"]) == {"u1", "u5"}
    assert "u3" not in watch["alive"]


def test_a_finished_bracket_leaves_the_champion_alone():
    done = R1 + R2 + [{"m": 5, "p": 1, "r": 3, "t1": 1, "t2": 5, "w": 5, "l": 1}]
    watch = build_bracket_watch(done, ROSTER_TO_USER)
    assert watch["alive"] == ["u5"]
    assert watch["alive_count"] == 1


def test_top_seed_is_the_best_surviving_seed():
    watch = build_bracket_watch(R1 + R2, ROSTER_TO_USER, seed_by_user=SEEDS)
    assert watch["top_seed_user_id"] == "u1"
    assert watch["top_seed"] == 1


def test_top_seed_follows_survival_not_the_bracket():
    """Once the 1 seed is knocked out the cell must name whoever is actually
    left, not keep printing the highest seed that entered."""
    upset = R1 + [
        {"m": 3, "r": 2, "t1": 1, "t2": {"w": 1}, "w": 3, "l": 1},
        {"m": 4, "r": 2, "t1": 2, "t2": {"w": 2}, "w": 5, "l": 2},
    ]
    watch = build_bracket_watch(upset, ROSTER_TO_USER, seed_by_user=SEEDS)
    assert set(watch["alive"]) == {"u3", "u5"}
    assert watch["top_seed_user_id"] == "u3"
    assert watch["top_seed"] == 3


def test_missing_seeds_leave_the_top_seed_unnamed_rather_than_guessed():
    watch = build_bracket_watch(R1 + R2, ROSTER_TO_USER)
    assert watch["top_seed_user_id"] is None
    assert watch["top_seed"] is None


def test_a_roster_with_no_owner_is_skipped_not_rendered_as_an_id():
    """A bracket can name a roster the owner map doesn't cover (a deleted
    co-owner). Leaking the raw roster id into the lead would print a number
    where a name belongs."""
    watch = build_bracket_watch(R1, {3: "u3"})
    assert watch["alive"] == ["u3"]
    assert watch["eliminated"] == []


def test_alive_is_ordered_deterministically():
    a = build_bracket_watch(R1 + R2, ROSTER_TO_USER, seed_by_user=SEEDS)
    for _ in range(5):
        assert build_bracket_watch(R1 + R2, ROSTER_TO_USER, seed_by_user=SEEDS) == a
