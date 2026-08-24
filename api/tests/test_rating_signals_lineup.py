from app.services.rating_signals import compute_lineup_signals


def test_compute_lineup_signals_reads_supporting_bundle():
    supporting = {
        "matchups": {
            ("L", 1, 1): {
                "starters": ["qb1", "rb1"], "players": ["qb1", "rb1", "wr_b"],
                "players_points": {"qb1": 20.0, "rb1": 15.0, "wr_b": 5.0},
            },
        },
        "roster_positions_by_league": {"L": ["QB", "FLEX", "BN"]},
        "positions": {"qb1": "QB", "rb1": "RB", "wr_b": "WR"},
        "roster_to_user_by_league": {"L": {1: "A"}},
    }
    out = compute_lineup_signals(supporting, owners=["A", "B"])
    assert out["A"]["lineup_skill"] == 1.0       # started optimally
    assert out["B"]["lineup_skill"] == 0.0       # no games


def test_compute_lineup_signals_degrades_without_roster_positions():
    # Missing roster_positions_by_league must not raise; returns zeros.
    out = compute_lineup_signals({"matchups": {}}, owners=["A"])
    assert out == {"A": {"lineup_skill": 0.0}}
