import pytest

from sleeper_dynasty.engine.asset_signals import asset_signals


def test_shares_are_league_relative_and_sum_to_one():
    out = asset_signals(
        current_holders={"p1": "ua", "p2": "ub"},
        value_by_player={"p1": 75.0, "p2": 25.0},
        age_by_player={"p1": 24, "p2": 30},
        owners=["ua", "ub"])
    assert out["ua"]["roster_value_share"] == pytest.approx(0.75)
    assert out["ub"]["roster_value_share"] == pytest.approx(0.25)
    total = sum(o["roster_value_share"] for o in out.values())
    assert total == pytest.approx(1.0)


def test_young_core_share_is_value_weighted_not_a_head_count():
    # One 24-year-old worth 90 and eight veterans worth 10 between them. A mean
    # age would call this an old roster; the value that matters is young.
    holders = {"star": "ua", **{f"vet{i}": "ua" for i in range(8)}}
    values = {"star": 90.0, **{f"vet{i}": 1.25 for i in range(8)}}
    ages = {"star": 24, **{f"vet{i}": 31 for i in range(8)}}
    out = asset_signals(current_holders=holders, value_by_player=values,
                        age_by_player=ages, owners=["ua"])
    assert out["ua"]["young_core_share"] == pytest.approx(0.9)


def test_unknown_age_players_are_excluded_from_both_sides():
    # A player with no birth_date must not sit in the denominator alone —
    # that systematically penalises deep-bench rookies, exactly the owners
    # the signal exists to reward.
    out = asset_signals(
        current_holders={"young": "ua", "mystery": "ua"},
        value_by_player={"young": 50.0, "mystery": 50.0},
        age_by_player={"young": 23},          # no age for "mystery"
        owners=["ua"])
    assert out["ua"]["young_core_share"] == pytest.approx(1.0)
    # ...but an unpriced-age player still counts as owned value.
    assert out["ua"]["roster_value_share"] == pytest.approx(1.0)


def test_empty_roster_is_zero_not_a_division_error():
    out = asset_signals(current_holders={}, value_by_player={},
                        age_by_player={}, owners=["ua"])
    assert out["ua"] == {"roster_value_share": 0.0, "young_core_share": 0.0}


def test_every_requested_owner_gets_a_row():
    out = asset_signals(
        current_holders={"p1": "ua"}, value_by_player={"p1": 10.0},
        age_by_player={"p1": 22}, owners=["ua", "ub"])
    assert set(out) == {"ua", "ub"}
    assert out["ub"]["roster_value_share"] == 0.0
