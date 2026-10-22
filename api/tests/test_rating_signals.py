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


def test_season_record_uses_provider_record_including_median_games():
    # Mutation: H2H reconstruction replaces authoritative median W/L/T.
    # Sanitized observed mismatch: six H2H games yield 5-1, provider says 10-2.
    matchups = {}
    for week in range(1, 7):
        a, b = (100.0, 90.0) if week < 6 else (80.0, 110.0)
        matchups[("L", week, 1)] = {"team_points": a, "opponent_points": b}
        matchups[("L", week, 2)] = {"team_points": b, "opponent_points": a}
    supporting = {
        "matchups": matchups,
        "roster_to_user_by_league": {"L": {1: "A", 2: "B"}},
        "league_season_by_id": {"L": 2026},
        "playoff_week_start_by_league": {"L": 15},
        "owners": {"A": {}, "B": {}},
        "roster_records_by_league": {"L": {
            "1": {"wins": 10, "losses": 2, "ties": 0,
                  "points_for": 878.54, "points_against": 800.0},
            "2": {"wins": 2, "losses": 9, "ties": 1,
                  "points_for": 751.24, "points_against": 900.0},
        }},
    }
    _, _, _, records = compute_rating_signals(supporting, {})
    assert (records["2026"]["A"]["wins"], records["2026"]["A"]["losses"]) == (10, 2)
    assert (records["2026"]["B"]["wins"], records["2026"]["B"]["losses"],
            records["2026"]["B"]["ties"]) == (2, 9, 1)
    from app.services.aggregations import _fmt_record
    assert _fmt_record("A", 2026, records)[0] == "10-2"
    assert records["2026"]["A"]["weeks_played"] == 6
