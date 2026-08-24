from sleeper_dynasty.engine.gm_signals import outcome_signals
from sleeper_dynasty.engine.standings import StandingRow


def _row(uid, rank, pf):
    return StandingRow(owner_id=uid, roster_id=rank, wins=0, losses=0, ties=0,
                       points_for=pf, points_against=0.0, rank=rank)


def test_outcome_signals_aggregate_career():
    standings = {
        2023: [_row("A", 1, 1500), _row("B", 2, 1400), _row("C", 3, 1000)],
        2024: [_row("A", 1, 1600), _row("B", 2, 1450), _row("C", 3, 1100)],
    }
    brackets = {
        2023: {"A": {"champion": True, "runner_up": False, "rounds_won": 2},
               "B": {"champion": False, "runner_up": True, "rounds_won": 1}},
        2024: {"A": {"champion": True, "runner_up": False, "rounds_won": 2}},
    }
    pw = {2023: 2, 2024: 2}
    sig = outcome_signals(
        standings_by_season=standings, bracket_results_by_season=brackets,
        num_playoff_teams_by_season=pw, owners=["A", "B", "C"])

    assert sig["A"]["championships"] == 2
    assert sig["B"]["championships"] == 0
    assert sig["C"]["championships"] == 0
    # made-playoffs RATE over participated seasons (rank <= 2).
    assert sig["A"]["made_playoffs"] == 1.0
    assert sig["B"]["made_playoffs"] == 1.0
    assert sig["C"]["made_playoffs"] == 0.0
    # playoff depth = sum of rounds won.
    assert sig["A"]["playoff_depth"] == 4
    assert sig["B"]["playoff_depth"] == 1
    # final seed inverted (total 3 teams): 1st -> 3, 2nd -> 2, 3rd -> 1; averaged.
    assert sig["A"]["final_seed"] == 3.0
    assert sig["B"]["final_seed"] == 2.0
    assert sig["C"]["final_seed"] == 1.0
    # points-for rank inverted: A highest pf both seasons -> 3.
    assert sig["A"]["points_for_rank"] == 3.0
    assert sig["C"]["points_for_rank"] == 1.0


def test_outcome_signals_every_owner_present_with_defaults():
    standings = {2024: [_row("A", 1, 100), _row("B", 2, 90)]}
    sig = outcome_signals(
        standings_by_season=standings, bracket_results_by_season={},
        num_playoff_teams_by_season={2024: 1}, owners=["A", "B", "Z"])
    # Z never played -> all-zero defaults, no crash.
    assert sig["Z"] == {"championships": 0.0, "playoff_depth": 0.0, "made_playoffs": 0.0,
                        "final_seed": 0.0, "points_for_rank": 0.0}


def test_bracket_results_identifies_champion_and_depth():
    from sleeper_dynasty.engine.gm_signals import bracket_results
    # 4-team bracket: round1 (r1) two semis, round2 (r2) final p=1.
    wb = [
        {"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
        {"r": 1, "m": 2, "t1": 2, "t2": 3, "w": 2, "l": 3},
        {"r": 2, "m": 3, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1},   # championship
        {"r": 2, "m": 4, "t1": 4, "t2": 3, "w": 3, "l": 4, "p": 3},   # 3rd place (consolation)
    ]
    r2u = {1: "A", 2: "B", 3: "C", 4: "D"}
    res = bracket_results(wb, r2u)
    assert res["A"] == {"champion": True, "runner_up": False, "rounds_won": 2}
    assert res["B"] == {"champion": False, "runner_up": True, "rounds_won": 1}
    # C only appears via the consolation game (skipped) -> not in results.
    assert "C" not in res or res["C"]["rounds_won"] == 0


def test_bracket_placements_full_finish_order():
    from sleeper_dynasty.engine.gm_signals import bracket_placements
    wb = [
        {"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
        {"r": 1, "m": 2, "t1": 2, "t2": 3, "w": 2, "l": 3},
        {"r": 2, "m": 3, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1},   # championship
        {"r": 2, "m": 4, "t1": 4, "t2": 3, "w": 3, "l": 4, "p": 3},   # 3rd-place game
    ]
    r2u = {1: "A", 2: "B", 3: "C", 4: "D"}
    pl = bracket_placements(wb, r2u)
    # Every participant placed, including the first-round losers.
    assert set(pl) == {"A", "B", "C", "D"}
    assert pl["A"]["place"] == 1 and pl["A"]["champion"] is True
    assert pl["B"]["place"] == 2 and pl["B"]["runner_up"] is True
    assert pl["C"]["place"] == 3 and pl["C"]["champion"] is False
    assert pl["D"]["place"] == 4


def test_bracket_placements_losers_bracket_is_draft_order():
    """Toilet bracket: place 1 = toilet champion = the 1.01 draft pick."""
    from sleeper_dynasty.engine.gm_signals import bracket_placements
    lb = [
        {"r": 1, "m": 1, "t1": 7, "t2": 8, "w": 7, "l": 8},
        {"r": 2, "m": 2, "t1": 9, "t2": 7, "w": 9, "l": 7, "p": 1},   # toilet final
        {"r": 2, "m": 3, "t1": 8, "t2": 10, "w": 8, "l": 10, "p": 3},
    ]
    r2u = {7: "G", 8: "H", 9: "I", 10: "J"}
    pl = bracket_placements(lb, r2u)
    assert pl["I"]["place"] == 1   # toilet champ -> 1.01
    assert pl["G"]["place"] == 2
    assert pl["H"]["place"] == 3
    assert pl["J"]["place"] == 4
