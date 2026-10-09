"""Threshold awards require weekly facts, exact boundaries, and whole groups."""

from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal

import pytest

from sleeper_dynasty.api.projections import normalize_projection
from sleeper_dynasty.engine.nfl_actuals import score_week
from sleeper_dynasty.engine.scoring import score_week_stats
from sleeper_dynasty.engine.scoring_leaders import build_scoring_rows
from sleeper_dynasty.models.league import League
from sleeper_dynasty.models.scoring import ThresholdBonus


@pytest.mark.parametrize("yards, expected", [(299.99, "12.00"), (300, "15.00"),
                                                   (399.99, "19.00"), (400, "24.00")])
def test_threshold_boundaries_are_inclusive_and_awards_stack(yards, expected):
    bonuses = [ThresholdBonus(("pass_yd",), 300, 3),
               ThresholdBonus(("pass_yd",), 400, 5)]
    assert score_week_stats({"pass_yd": yards}, {"pass_yd": .04}, bonuses=bonuses) == Decimal(expected)


def test_compound_bonus_is_awarded_once_after_summing_components():
    bonuses = [ThresholdBonus(("kr_yd", "pr_yd"), 100, 3)]
    # Both components individually miss the threshold but their combined stat
    # reaches it. When both clear it, this is still only one bonus.
    assert score_week_stats({"kr_yd": 60, "pr_yd": 40}, {}, bonuses=bonuses) == 3
    assert score_week_stats({"kr_yd": 100, "pr_yd": 120}, {}, bonuses=bonuses) == 3
    assert score_week_stats({"kr_yd": 100}, {}, bonuses=bonuses) == 3
    assert score_week_stats({"kr_yd": 99}, {}, bonuses=bonuses) == 0


def test_decimal_comparison_negative_awards_and_rounding_happen_once():
    bonuses = [ThresholdBonus(("a", "b"), .3, -.125)]
    assert score_week_stats({"a": .1, "b": .2}, {}, bonuses=bonuses) == Decimal("-.13")
    assert score_week_stats({"a": 1, "b": 1}, {"a": .005, "b": .005}) == Decimal(".01")


@pytest.mark.parametrize("stats", [{}, {"gp": 0, "rec": 0}, {"gp": 0, "rec": 8},
                                   {"gms_active": 1, "pos_rank_ppr": 999}])
def test_zero_target_never_awards_inactive_or_placeholder_weeks(stats):
    assert score_week_stats(stats, {}, bonuses=[ThresholdBonus(("rec",), 0, 5)]) == 0


def test_zero_target_requires_an_observed_component_even_in_a_played_week():
    bonuses = [ThresholdBonus(("rec",), 0, 5)]
    assert score_week_stats({"gp": 1}, {}, bonuses=bonuses) == 0
    assert score_week_stats({"gp": 1, "rec": 0}, {}, bonuses=bonuses) == 5
    assert score_week_stats({"gp": 1, "rec": 5}, {},
                            bonuses=[ThresholdBonus(("sack",), 0, 5)]) == 0


def test_legacy_stat_flags_and_position_premiums_are_preserved_without_mutation():
    stats = {"gp": 1, "rec": 5, "bonus_rec_te": 5, "bonus_rec_yd_100": 1, "rec_yd": 100}
    before = deepcopy(stats)
    result = score_week_stats(stats, {"rec": 1, "bonus_rec_te": .5, "bonus_rec_yd_100": 2},
                              position="TE", bonuses=[ThresholdBonus(("rec_yd",), 100, 3)])
    assert result == Decimal("12.50")
    assert stats == before
    assert score_week_stats({"rec": 5}, {"rec": 1, "bonus_rec_te": .5}, position="TE") == Decimal("7.50")


@pytest.mark.parametrize("field, bad", [
    ("target", True), ("target", float("nan")), ("target", float("inf")), ("target", -1),
    ("points", False), ("points", float("nan")), ("points", float("-inf")), ("points", "3"),
    ("stat_keys", ()), ("stat_keys", ("",)), ("stat_keys", ("rec", "rec")), ("stat_keys", "rec"),
])
def test_bonus_model_rejects_malformed_rules(field, bad):
    values = {"stat_keys": ("rec",), "target": 5, "points": 3}
    values[field] = bad
    with pytest.raises(ValueError):
        ThresholdBonus(**values)


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "5"])
def test_actual_scorer_rejects_nonfinite_or_nonnumeric_components_and_weights(bad):
    with pytest.raises(ValueError):
        score_week_stats({"rec": bad}, {"rec": 1})
    with pytest.raises(ValueError):
        score_week_stats({"rec": 1}, {"rec": bad})
    with pytest.raises(ValueError):
        score_week_stats({"rec": bad}, {}, bonuses=[ThresholdBonus(("rec",), 5, 3)])


def test_league_bonus_serialization_retains_compound_rules_and_defaults():
    league = League("1", "Example", 2026, 2, ["QB"], {"pass_yd": .04}, 15, 2, "in_season")
    other = League("2", "Other", 2026, 2, ["QB"], {}, 15, 2, "in_season")
    bonus = ThresholdBonus(["kr_yd", "pr_yd"], 100, 3)
    league.scoring_bonuses.append(bonus)
    saved = asdict(league)
    assert [ThresholdBonus(**item) for item in saved["scoring_bonuses"]] == [bonus]
    assert other.scoring_bonuses == []


def test_actuals_and_scoring_leaders_score_each_week_before_summing():
    bonuses = [ThresholdBonus(("pass_yd",), 300, 3)]
    weeks = {1: {"qb": {"gp": 1, "pass_yd": 310}},
             2: {"qb": {"gp": 1, "pass_yd": 310}},
             3: {"qb": {"gp": 1, "pass_yd": 290}}}
    points = [score_week(raw, {"pass_yd": .04}, bonuses=bonuses)["qb"] for raw in weeks.values()]
    rows = build_scoring_rows(weeks, {"qb": {"position": "QB"}}, {"pass_yd": .04}, 3,
                              bonuses=bonuses)
    assert sum(points) == pytest.approx(42.4)
    assert rows[0]["points"] == 42.4
    # Aggregate projection normalization stays linear. Awarding one bonus on
    # 910 projected season yards would neither count nor estimate bonus weeks.
    assert normalize_projection({"pass_yd": 910}, {"pass_yd": .04}) == 36.4
