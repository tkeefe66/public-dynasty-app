from app.services.rating_signals import compute_rating_signals
from sleeper_dynasty.models.player import KTCValue


def _ktc(v):
    return KTCValue(name="x", normalized_name="x", position="RB", superflex_value=v)


def test_compute_rating_signals():
    supporting = {
        "matchups": {
            ("L", 1, 1): {"team_points": 100.0, "opponent_points": 90.0},
            ("L", 1, 2): {"team_points": 90.0, "opponent_points": 100.0},
        },
        "roster_to_user_by_league": {"L": {1: "A", 2: "B"}},
        "league_season_by_id": {"L": 2024},
        "playoff_week_start_by_league": {"L": 15},
        "winners_bracket_by_league": {
            "L": [{"r": 1, "m": 1, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1}]},
        "num_playoff_teams_by_league": {"L": 2},
        "ktc_by_player_id": {"pa": _ktc(5000), "pb": _ktc(3000)},
        "player_ages": {"pa": 24, "pb": 30},
        "owners": {"A": {}, "B": {}},
    }
    current_holders = {"pa": "A", "pb": "B"}
    osig, olsig, _, _ = compute_rating_signals(supporting, current_holders)

    assert osig["A"]["championships"] == 1
    assert osig["B"]["championships"] == 0
    assert osig["A"]["final_seed"] == 2.0      # 1st of 2 -> inverted 2
    assert osig["B"]["final_seed"] == 1.0
    assert olsig["A"]["roster_value"] == 5000.0
    assert olsig["A"]["youth"] == -24.0
    assert olsig["B"]["youth"] == -30.0
    assert olsig["A"]["draft_capital"] == 0.0  # deferred
