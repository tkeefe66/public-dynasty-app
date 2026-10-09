"""Yahoo bonus semantics through both weekly scoring consumers.

Payloads here are synthetic. The cumulative rule is documented by Yahoo:
https://help.yahoo.com/kb/fantasy-football/scoring-categories-plays-faq-fantasy-football-sln6442.html
"""

from decimal import Decimal

import pytest

from sleeper_dynasty.api.yahoo import YahooDataError, scoring_settings
from sleeper_dynasty.engine.nfl_actuals import score_week
from sleeper_dynasty.engine.scoring_leaders import build_scoring_rows, score_player_week
from sleeper_dynasty.models.scoring import threshold_bonus_key, weekly_scoring_stats


def bonus(target, points):
    return {"bonus": {"target": target, "points": points}}


def settings(bonuses=None, *, stat_id="9", value="0.1"):
    return {"stat_modifiers": {"stats": [
        {"stat": {"stat_id": stat_id, "value": value, "bonuses": bonuses}}
    ]}}


@pytest.mark.parametrize("wrapped", [
    [bonus("100", "3")],
    {"0": bonus("100", "3"), "count": 1},
    bonus("100", "3"),
    [{"bonus": [{"target": "100"}, {"points": "3"}]}],
])
def test_bonus_collection_shapes_preserve_scoring_rules(wrapped):
    assert scoring_settings(settings(wrapped)) == {
        "rush_yd": .1, "bonus_gte:rush_yd:100": 3,
    }


@pytest.mark.parametrize("yards, expected", [
    (-1, -.1), (0, 0), (99, 9.9), (100, 11), (149, 15.9),
    (150, 21), (199, 25.9), (200, 41), (250, 46),
])
def test_each_reached_threshold_is_inclusive_and_cumulative(yards, expected):
    # Mutation: use only the highest bonus, award it repeatedly per 100 yards,
    # or replace Yahoo's cumulative targets with Sleeper's exclusive bands.
    scoring = scoring_settings(settings([
        bonus(100, 1), bonus(150, 5), bonus(200, 15),
    ]))
    stats = {"gp": 1, "rush_yd": yards}
    assert score_week({"p": stats}, scoring) == {"p": expected}
    assert score_player_week(stats, scoring, "RB") == Decimal(str(expected))


def test_arbitrary_threshold_and_zero_base_weight_are_supported():
    scoring = scoring_settings(settings([bonus("125.5", "2.5")], value="0"))
    assert score_week({"below": {"rush_yd": 125.49}, "at": {"rush_yd": 125.5}}, scoring) == {
        "below": 0, "at": 2.5,
    }


def test_passing_rushing_and_receiving_targets_apply_to_their_own_stat():
    raw = {"stat_modifiers": {"stats": [
        {"stat": {"stat_id": "4", "value": ".04", "bonuses": [bonus(300, 3)]}},
        {"stat": {"stat_id": "9", "value": ".1", "bonuses": [bonus(100, 5)]}},
        {"stat": {"stat_id": "12", "value": ".1", "bonuses": [bonus(100, 7)]}},
    ]}}
    scoring = scoring_settings(raw)
    stats = {"pass_yd": 300, "rush_yd": 100, "rec_yd": 99}
    assert score_week({"p": stats}, scoring) == {"p": 39.9}
    assert score_player_week(stats, scoring, "QB") == Decimal("39.90")


def test_compound_bonus_uses_combined_stat_once():
    # Yahoo return yards combine kick and punt returns. Neither individual
    # component needs to cross the target, and two that do still award it once.
    scoring = scoring_settings(settings([bonus(100, 3)], stat_id="14", value="0.1"))
    raw = {"split": {"kr_yd": 60, "pr_yd": 50}, "both": {"kr_yd": 110, "pr_yd": 120}}
    assert score_week(raw, scoring) == {"split": 14, "both": 26}
    assert score_player_week(raw["split"], scoring, "WR") == Decimal("14.00")
    assert raw["split"] == {"kr_yd": 60, "pr_yd": 50}


def test_repeated_bonus_slots_at_same_target_add_their_declared_points_once():
    scoring = scoring_settings(settings([bonus("100", 2), bonus("1e2", 3)]))
    assert scoring == {"rush_yd": .1, "bonus_gte:rush_yd:100": 5}
    # Existing/pre-derived indicators cannot be added a second time.
    assert score_week({"p": {"rush_yd": 100, "bonus_gte:rush_yd:100": 1}}, scoring) == {"p": 15}


def test_bonus_thresholds_reset_for_each_week():
    scoring = scoring_settings(settings([bonus(100, 3)]))
    weeks = {1: {"p": {"gp": 1, "rush_yd": 60}}, 2: {"p": {"gp": 1, "rush_yd": 60}}}
    rows = build_scoring_rows(weeks, {"p": {"position": "RB"}}, scoring, 2)
    assert rows[0]["points"] == 12  # Never a bonus on season aggregate 120 yards.


def test_missing_stat_cannot_earn_bonus_and_signed_penalty_is_preserved():
    scoring = scoring_settings(settings([bonus(3, -1)], stat_id="6", value="-2"))
    assert score_week({"missing": {"gp": 1}, "three": {"pass_int": 3}}, scoring) == {
        "missing": 0, "three": -7,
    }


def test_sleeper_bonus_flags_and_position_premiums_keep_existing_behavior():
    scoring = {"rush_yd": .1, "bonus_rush_yd_100": 2, "bonus_rush_yd_200": 4}
    assert score_week({"p": {"rush_yd": 200, "bonus_rush_yd_100": 0, "bonus_rush_yd_200": 1}}, scoring) == {
        "p": 24,
    }
    assert score_player_week({"gp": 1, "rec": 4, "bonus_rec_te": 4}, {
        "rec": 1, "bonus_rec_te": .5,
    }, "TE") == Decimal("6.00")


@pytest.mark.parametrize("raw", [None, [], {}, {"count": 0}])
def test_empty_bonus_collection_keeps_base_scoring(raw):
    assert scoring_settings(settings(raw)) == {"rush_yd": .1}


@pytest.mark.parametrize("raw", [
    "unknown", True, False, 1,
    {"count": 1}, {"0": bonus(100, 3), "count": 2},
    {"rules": [bonus(100, 3)]},
    [{"target": 100, "points": 3}],
    [{"bonus": {"target": 100}}],
    [{"bonus": {"points": 3}}],
    [{"bonus": {"target": 100, "points": 3, "position": "RB"}}],
    [{"bonus": [{"target": 100}, {"points": 3}, "unknown"]}],
    [{"bonus": [{"target": 100}, {"target": 200}, {"points": 3}]}],
    [bonus(0, 3)], [bonus(-100, 3)], [bonus("bad", 3)],
    [bonus("NaN", 3)], [bonus("Infinity", 3)], [bonus(True, 3)],
    [bonus(100, "NaN")], [bonus(100, "Infinity")], [bonus(100, None)],
    [bonus(100, True)],
])
def test_unknown_or_invalid_bonus_rules_fail_without_dropping_points(raw):
    with pytest.raises(YahooDataError, match="bonus"):
        scoring_settings(settings(raw))


@pytest.mark.parametrize("value", ["NaN", "Infinity", "bad", None, True])
def test_invalid_base_weights_fail_explicitly(value):
    with pytest.raises(YahooDataError, match="multiplier"):
        scoring_settings(settings(value=value))


@pytest.mark.parametrize("stat_id", [None, True, 4.5, "4.5", {}, -4])
def test_invalid_stat_id_is_not_coerced_to_another_scoring_rule(stat_id):
    with pytest.raises(YahooDataError, match="scoring stat"):
        scoring_settings(settings(stat_id=stat_id))


def test_unknown_bonus_stat_cannot_hide_behind_zero_base_weight():
    with pytest.raises(YahooDataError, match="stat 999"):
        scoring_settings(settings([bonus(100, 3)], stat_id="999", value=0))


def test_duplicate_scoring_stat_is_not_silently_overwritten():
    raw = settings([bonus(100, 3)])
    raw["stat_modifiers"]["stats"].append({"stat": {"stat_id": "9", "value": ".2"}})
    with pytest.raises(YahooDataError, match="duplicate scoring stat"):
        scoring_settings(raw)


@pytest.mark.parametrize("value", ["NaN", "Infinity", None, True, "bad"])
def test_invalid_weekly_bonus_stat_fails_in_both_consumers(value):
    scoring = scoring_settings(settings([bonus(100, 3)]))
    with pytest.raises(ValueError, match="threshold scoring"):
        score_week({"p": {"rush_yd": value}}, scoring)
    with pytest.raises(ValueError, match="threshold scoring"):
        score_player_week({"rush_yd": value}, scoring, "RB")


def test_threshold_namespace_is_validated_when_read_from_saved_scoring():
    for key in ("bonus_gte:rush_yd:-1", "bonus_gte:rush_yd:NaN", "bonus_gte:rush_yd"):
        with pytest.raises(ValueError):
            weekly_scoring_stats({"rush_yd": 120}, {key: 3})
    assert threshold_bonus_key(("pr_yd", "kr_yd"), "100.00") == "bonus_gte:kr_yd+pr_yd:100"


def test_season_aggregate_cohorts_do_not_invent_weekly_bonus_counts():
    from sleeper_dynasty.engine.rookie_cohorts import build_cohorts

    scoring = scoring_settings(settings([bonus(100, 3)]))
    history = {"p": {"ecr": 1, "seasons": [{"n": 1, "rushing_yards": 120}]}}
    assert build_cohorts(history, scoring, min_n=1) == {}
