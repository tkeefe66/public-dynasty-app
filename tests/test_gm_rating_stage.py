"""Band edges, rounding, and monotonicity for rating_to_stage.

Every edge is tested from BOTH sides. A one-sided edge test passes on an
off-by-one, which is the whole class of bug these bands can have.
"""

import pytest

from sleeper_dynasty.engine.gm_rating import (
    BASE, LETTER_BANDS, POINTS_PER_SD, STAGE_BANDS, STAGE_SD_FLOOR, _STAGE_SD,
    rating_to_letter, rating_to_stage,
)

STAGES = ["Rebuilding", "Retooling", "Competing", "Contending", "Dynasty"]


def test_band_edges_from_both_sides():
    assert rating_to_stage(1748) == "Dynasty"
    assert rating_to_stage(1747) == "Contending"
    assert rating_to_stage(1582) == "Contending"
    assert rating_to_stage(1581) == "Competing"
    assert rating_to_stage(1418) == "Competing"
    assert rating_to_stage(1417) == "Retooling"
    assert rating_to_stage(1252) == "Retooling"
    assert rating_to_stage(1251) == "Rebuilding"


def test_bands_use_bankers_rounding_and_are_symmetric():
    """Every sd multiple lands on an exact .5 of a point.

    round(82.5) == 82, not 83; a naive int(x + 0.5) gives 83 / -82 and breaks
    the symmetry. The offsets must mirror exactly around BASE.
    """
    offsets = [lo for lo, _ in STAGE_BANDS]
    assert offsets == [248, 82, -82, -248]
    assert offsets[0] == -offsets[3]
    assert offsets[1] == -offsets[2]
    # And they are derived, not typed: 0.90 * 275 == 247.5 -> 248.
    assert round(0.30 * POINTS_PER_SD) == 82
    assert round(0.90 * POINTS_PER_SD) == 248


def test_every_stage_is_reachable():
    """The F-band failure recorded in gm_rating.py, checked for this rail."""
    seen = {rating_to_stage(r) for r in range(800, 2201)}
    assert seen == set(STAGES)


def test_monotone_across_the_whole_clamp_range():
    """rating + 1 can never yield a LOWER rung. This is the invariant rev 1's
    z-pair rule broke: a league-average team outranked a +1.9sd one."""
    prev = -1
    for r in range(800, 2201):
        i = STAGES.index(rating_to_stage(r))
        assert i >= prev, f"rating {r} dropped a rung"
        prev = i


def test_aligned_with_the_letter_scale():
    """The bands are the letter bands' own units, so the alignment is exact,
    not approximate — the Dynasty edge IS the A- edge, and Competing spans
    C- through B-."""
    assert rating_to_letter(1748) == "A-"
    assert rating_to_stage(1748) == "Dynasty"
    assert {rating_to_letter(r) for r in range(1418, 1582)} == {"C-", "C", "C+", "B-"}
    assert {rating_to_stage(r) for r in range(1418, 1582)} == {"Competing"}
    # Shared mechanism: both tables convert sd multiples through POINTS_PER_SD
    # with the same round().
    assert all(isinstance(lo, int) for lo, _ in LETTER_BANDS)


@pytest.mark.parametrize("rating", [800, 2200])
def test_clamp_extremes_resolve(rating):
    assert rating_to_stage(rating) in STAGES


# --- League-specific band unit (rating_to_stage(..., sd=...)) ---------------
#
# The unit is that league's OWN realized rating spread instead of the single
# reference league's POINTS_PER_SD. The centre stays BASE either way.


def test_sd_none_reproduces_the_fixed_bands_at_every_edge():
    """The default must be byte-identical to the pre-change function, edge by
    edge from both sides — otherwise every existing caller silently re-bands."""
    for lo, stage in STAGE_BANDS:
        assert rating_to_stage(BASE + lo, sd=None) == stage
        assert rating_to_stage(BASE + lo) == stage
    # And across the whole clamp range, not just at the edges.
    assert all(
        rating_to_stage(r, sd=None) == rating_to_stage(r)
        for r in range(800, 2201)
    )


def test_a_wider_league_gets_proportionally_wider_bands():
    """A league that has separated harder than the reference must need MORE
    rating points to reach a rung, not the same number."""
    wide = 2 * POINTS_PER_SD          # 550, well clear of the floor
    assert [round(m * wide) for m, _ in _STAGE_SD] == [495, 165, -165, -495]
    # An owner comfortably Dynasty on the fixed bands is only Contending here.
    assert rating_to_stage(BASE + 300) == "Dynasty"
    assert rating_to_stage(BASE + 300, sd=wide) == "Contending"
    # Both edges, from both sides.
    assert rating_to_stage(BASE + 495, sd=wide) == "Dynasty"
    assert rating_to_stage(BASE + 494, sd=wide) == "Contending"
    assert rating_to_stage(BASE - 495, sd=wide) == "Retooling"
    assert rating_to_stage(BASE - 496, sd=wide) == "Rebuilding"


def test_a_narrower_league_gets_the_floor_not_its_own_spread():
    """Below half the reference spread the floor takes over, so the bands stop
    narrowing. STAGE_SD_FLOOR is a chosen prior, not a measured one."""
    assert STAGE_SD_FLOOR == 137.5
    floored = [round(m * STAGE_SD_FLOOR) for m, _ in _STAGE_SD]
    assert floored == [124, 41, -41, -124]
    for tiny in (0.0, 1.0, 50.0, 137.4):
        assert [rating_to_stage(BASE + d, sd=tiny) for d in
                (200, 100, 0, -100, -200)] == [
            rating_to_stage(BASE + d, sd=STAGE_SD_FLOOR) for d in
            (200, 100, 0, -100, -200)], f"sd={tiny} did not clamp to the floor"
    # Just above the floor it does NOT clamp — the floor is a floor, not a mode.
    assert round(0.90 * 200.0) == 180
    assert rating_to_stage(BASE + 150, sd=200.0) == "Contending"
    assert rating_to_stage(BASE + 150, sd=100.0) == "Dynasty"


def test_a_flat_league_does_not_grade_everyone_dynasty():
    """THE TRAP. With sd -> 0 every edge collapses to 0 and `delta >= 0`
    returns the FIRST rung, so a league of identical owners would grade every
    one of them Dynasty. A flat league z-scores to exactly BASE (see
    _SD_RELATIVE_FLOOR), so BASE is the rating under test."""
    flat = [BASE] * 12
    stages = [rating_to_stage(r, sd=0.0) for r in flat]
    assert set(stages) == {"Competing"}, stages
    assert "Dynasty" not in stages
    # Not just at exactly 0.0 — anywhere in the collapse neighbourhood.
    for tiny in (0.0, 1e-12, 1e-6, 0.5, 5.0):
        assert rating_to_stage(BASE, sd=tiny) == "Competing"
    # And the neutral answer is the same one the fixed bands give.
    assert rating_to_stage(BASE) == "Competing"


def test_negative_or_absurd_sd_cannot_invert_the_rail():
    """Defensive: a caller handing a nonsense unit must still get a monotone
    rail, never an inverted one."""
    for sd in (-1.0, -1000.0, 0.0):
        prev = -1
        for r in range(800, 2201, 7):
            i = STAGES.index(rating_to_stage(r, sd=sd))
            assert i >= prev
            prev = i


def test_monotone_and_reachable_for_an_arbitrary_league_unit():
    for sd in (137.5, 180.0, 251.2954, 275.0, 400.0):
        prev = -1
        for r in range(800, 2201):
            i = STAGES.index(rating_to_stage(r, sd=sd))
            assert i >= prev, f"sd={sd} rating={r} dropped a rung"
            prev = i
        assert {rating_to_stage(r, sd=sd) for r in range(800, 2201)} == set(STAGES)
