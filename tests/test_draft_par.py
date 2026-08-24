import pytest

from sleeper_dynasty.engine.draft_par import (
    pick_par, points_above_round, round_averages,
)


def row(rnd, total, uid="u1", **over):
    r = {"round": rnd, "production_total": total, "drafter_id": uid,
         "is_keeper": False, "gradeable": True}
    r.update(over)
    return r


ROWS = [
    row(1, 200.0, "a"), row(1, 100.0, "b"), row(1, 0.0, "c"),   # r1 avg 100
    row(2, 60.0, "a"), row(2, 30.0, "b"), row(2, 0.0, "c"),     # r2 avg 30
]


def test_round_averages_are_per_round():
    assert round_averages(ROWS) == {1: 100.0, 2: 30.0}


def test_pick_par_is_production_minus_its_own_rounds_average():
    avgs = round_averages(ROWS)
    assert pick_par(row(1, 200.0), avgs) == 100.0
    assert pick_par(row(2, 0.0), avgs) == -30.0


def test_par_sums_to_zero_across_the_class():
    # The property that makes it fair: it is zero-sum, so it measures drafting
    # well rather than picking early.
    assert sum(points_above_round(ROWS).values()) == pytest.approx(0.0)


def test_par_is_summed_per_owner():
    par = points_above_round(ROWS)
    assert par["a"] == pytest.approx(130.0)   # +100 (r1) +30 (r2)
    assert par["c"] == pytest.approx(-130.0)  # -100 (r1) -30 (r2)


def test_keeper_and_auction_picks_are_excluded_from_both_the_average_and_the_sum():
    # A keep is not a draft decision, and an auction's pick_no is the order
    # money changed hands. Leaving either in would move the yardstick every
    # real pick is measured against.
    rows = ROWS + [row(1, 900.0, "d", is_keeper=True),
                   row(1, 900.0, "e", gradeable=False)]
    assert round_averages(rows) == {1: 100.0, 2: 30.0}
    par = points_above_round(rows)
    assert "d" not in par and "e" not in par


def test_a_round_with_no_scorable_picks_is_absent_rather_than_zero():
    assert round_averages([row(3, 0.0, "a", is_keeper=True)]) == {}


def test_empty_input_is_empty_not_an_error():
    assert round_averages([]) == {}
    assert points_above_round([]) == {}
