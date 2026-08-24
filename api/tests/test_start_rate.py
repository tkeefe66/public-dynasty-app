import pytest
from app.services.start_rate import start_rate


def test_ratio_of_started_to_total():
    assert start_rate(60.0, 100.0) == pytest.approx(0.6)
    assert start_rate(100.0, 100.0) == pytest.approx(1.0)


def test_none_when_nothing_has_played():
    """NOT 0.0. A haul that has not played has no start rate, and 0% reads as
    'you benched everything' — the most damning reading of the least data."""
    assert start_rate(0.0, 0.0) is None


def test_none_on_a_negative_denominator():
    # A swing-style caller could pass one; a negative denominator makes the
    # ratio meaningless rather than merely unknown.
    assert start_rate(10.0, -5.0) is None


def test_zero_started_against_real_points_is_a_real_zero():
    """Distinct from the None case: points WERE scored and none were started.
    That is the bench-miss reading at its most extreme and must survive."""
    assert start_rate(0.0, 80.0) == 0.0
