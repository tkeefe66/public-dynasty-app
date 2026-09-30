"""Results editions must copy computed facts without editorial inference."""
import pytest

from sleeper_dynasty.engine.recap_results import render_results_recap


def packet():
    return {
        "week": 3,
        "matchups": [
            {"winner": "Alice", "loser": "Bob", "winner_points": 90, "loser_points": 80, "margin": 10},
            {"winner": "Cam", "loser": "Dee", "winner_points": 50, "loser_points": 50, "margin": 0},
        ],
        "lineups": [{"owner": "Alice", "starters": [{"player": "Starter", "points": 30}]}],
        "bench_regret": [{"owner": "Bob", "legal_swaps": [{
            "slot": "QB", "benched_player": {"player": "Bench QB", "points": 20},
            "started_player": {"player": "Starting QB", "points": 5}, "points_gained": 15,
            "matchup_effect": {"team_points": 95, "opponent_points": 90, "result": "win"},
        }]}],
        "standings_race": {"available": True, "teams": [
            {"owner": "Alice", "rank_after": 1, "rank_tied": True, "record_after": [2, 0, 1], "points_for": 250},
            {"owner": "Bob", "rank_after": 1, "rank_tied": True, "record_after": [2, 0, 1], "points_for": 250},
        ]},
        "bets": {"available": True, "as_of": "2026-09-29T09:00:00+00:00", "active": [{
            "side_a": "Alice", "side_b": "Bob", "stake": "$25.00", "terms": "Higher finish", "status": "open",
        }], "resolved": [{"side_a": "Cam", "side_b": "Dee", "stake": "$5.00", "terms": "Week 1",
                            "status": "settled", "winner": "Dee"}]},
    }


def test_results_covers_scores_ties_standings_legal_swap_bets_and_preview():
    # Mutation: call a tie a win, add swaps, invent settlement, or print projected totals as scores.
    text = render_results_recap(packet(), {"week": 4, "matchups": [
        {"home": "Alice", "away": "Bob", "home_projected": 88.2, "away_projected": 85.1,
         "favorite": "Alice", "spread": 3.1},
    ]})
    for expected in ["Week 3 results", "Alice 90.00, Bob 80.00", "Alice won by 10.00",
                     "Cam 50.00, Dee 50.00", "Tied matchup", "Alice: Starter, 30.00",
                     "Tied 1. Alice", "2-0-1", "250.00 points for",
                     "Bench QB (20.00) for Starting QB (5.00)", "+15.00",
                     "95.00 to 90.00 (win)", "independent hindsight scenarios",
                     "$25.00", "Higher finish", "Open; no result recorded",
                     "Recorded winner: Dee", "Ledger snapshot: 2026-09-29",
                     "Week 4 preview", "Alice 88.20, Bob 85.10", "projected edge: Alice by 3.10"]:
        assert expected in text


def test_missing_context_is_unknown_and_names_cannot_inject_markdown():
    # Mutation: treat an unavailable ledger as no bets, or trust arbitrary names as markup.
    facts = packet()
    facts["bets"] = {"available": False}
    facts["standings_race"] = {"available": False}
    facts["matchups"][0]["winner"] = "Alice\n\n## **Forged**"
    text = render_results_recap(facts)
    assert "Bet ledger unavailable" in text
    assert "Standings could not be verified" in text
    assert "Projections were unavailable" in text
    assert "\n## **Forged**" not in text
    assert "**Forged**" not in text
    assert "Tied 1." not in text


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), None])
def test_invalid_scores_never_become_a_published_claim(bad):
    # Mutation: stringify missing/nonfinite points and permanently publish them.
    facts = packet()
    facts["matchups"][0]["winner_points"] = bad
    with pytest.raises(ValueError):
        render_results_recap(facts)
