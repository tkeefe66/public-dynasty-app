from sleeper_dynasty.engine.injury import games_missed_by_phase


def _phase_fn(season, week):
    return "playoff" if (season, week) == (2024, 16) else "regular"


def test_counts_missed_by_phase_within_owned_weeks():
    owned_weeks = {(2024, 14), (2024, 15), (2024, 16)}
    played_weeks = {(2024, 14)}
    injury_map = {
        ("p1", 2024, 15): {"missed": True, "confidence": "high", "source": "roster_status:RES"},
        ("p1", 2024, 16): {"missed": True, "confidence": "high", "source": "roster_status:RES"},
    }
    res = games_missed_by_phase("p1", owned_weeks, played_weeks, injury_map, _phase_fn)
    assert res["games_missed"] == {"regular": 1, "playoff": 1, "toilet": 0}
    assert sorted((w, c["confidence"]) for w, c in res["missed_weeks"]) == \
        [((2024, 15), "high"), ((2024, 16), "high")]


def test_played_week_not_counted_even_if_flagged():
    owned_weeks = {(2024, 14)}
    played_weeks = {(2024, 14)}
    injury_map = {("p1", 2024, 14): {"missed": True, "confidence": "soft", "source": "snap_count:0"}}
    res = games_missed_by_phase("p1", owned_weeks, played_weeks, injury_map, _phase_fn)
    assert res["games_missed"] == {"regular": 0, "playoff": 0, "toilet": 0}
