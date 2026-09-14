from sleeper_dynasty.engine.recap import build_matchup_recaps, build_luck_notes
from sleeper_dynasty.models.league import MatchupResult


def test_tie_is_not_a_lucky_win_or_unlucky_loss():
    # Mutation: use >= to silently designate a winner in a tied matchup.
    results = [MatchupResult(1, 1, rid, 100, [], [], {}) for rid in (1, 2)]
    recaps, _, _ = build_matchup_recaps(results, {1: "Alice", 2: "Bob"})
    assert recaps[0].to_dict()["tied"] is True
    assert build_luck_notes(results, {1: "Alice", 2: "Bob"}) == ([], [])
