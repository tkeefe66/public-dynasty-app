from sleeper_dynasty.engine.playoff_phase import weeks_for_round, classify_playoff_phases


def test_weeks_for_round_type0_one_week_each():
    assert weeks_for_round(1, 15, 0) == [15]
    assert weeks_for_round(3, 15, 0) == [17]


def test_weeks_for_round_type2_two_weeks_each():
    assert weeks_for_round(1, 15, 2) == [15, 16]
    assert weeks_for_round(2, 15, 2) == [17, 18]


def test_weeks_for_round_type1_two_week_final_only():
    assert weeks_for_round(1, 15, 1, total_rounds=3) == [15]
    assert weeks_for_round(3, 15, 1, total_rounds=3) == [17, 18]


WINNERS_2025 = [
    {"m": 1, "r": 1, "t1": 6, "t2": 12, "w": 6, "l": 12},
    {"m": 2, "r": 1, "t1": 2, "t2": 5, "w": 5, "l": 2},
    {"m": 3, "r": 2, "t1": 1, "t2": 6, "w": 1, "l": 6},
    {"m": 4, "r": 2, "t1": 10, "t2": 5, "w": 10, "l": 5},
    {"m": 5, "p": 5, "r": 2, "t1": 12, "t2": 2, "w": 12, "l": 2},
    {"m": 6, "p": 1, "r": 3, "t1": 1, "t2": 10, "w": 1, "l": 10},
    {"m": 7, "p": 3, "r": 3, "t1": 6, "t2": 5, "w": 5, "l": 6},
]
LOSERS_2025 = [
    {"m": 1, "r": 1, "t1": 9, "t2": 8, "w": 9, "l": 8},
    {"m": 2, "r": 1, "t1": 4, "t2": 3, "w": 3, "l": 4},
    {"m": 3, "r": 2, "t1": 11, "t2": 9, "w": 11, "l": 9},
    {"m": 4, "r": 2, "t1": 7, "t2": 3, "w": 7, "l": 3},
    {"m": 5, "p": 5, "r": 2, "t1": 8, "t2": 4, "w": 4, "l": 8},
    {"m": 6, "p": 1, "r": 3, "t1": 11, "t2": 7, "w": 7, "l": 11},
    {"m": 7, "p": 3, "r": 3, "t1": 9, "t2": 3, "w": 9, "l": 3},
]


def test_classify_real_2025():
    phases = classify_playoff_phases(WINNERS_2025, LOSERS_2025, 15, 0)
    assert phases[(15, 6)] == "playoff"
    assert phases[(15, 12)] == "playoff"
    assert phases[(15, 2)] == "playoff"
    assert phases[(15, 5)] == "playoff"
    assert (15, 1) not in phases   # bye
    assert (15, 10) not in phases  # bye
    assert phases[(16, 1)] == "playoff"
    assert phases[(16, 10)] == "playoff"
    assert (16, 12) not in phases  # 5th-place placement
    assert (16, 2) not in phases
    assert phases[(17, 1)] == "playoff"
    assert phases[(17, 10)] == "playoff"
    assert (17, 6) not in phases   # 3rd-place placement
    assert (17, 5) not in phases
    assert phases[(15, 9)] == "toilet"
    assert phases[(15, 8)] == "toilet"
    assert phases[(16, 11)] == "toilet"
    assert phases[(17, 7)] == "toilet"


def test_classify_skips_unresolved_and_empty():
    wb = [{"m": 1, "r": 1, "t1": 3, "t2": None}]
    phases = classify_playoff_phases(wb, [], 15, 0)
    assert phases == {(15, 3): "playoff"}
    assert classify_playoff_phases([], [], 15, 0) == {}
