"""Yahoo threshold rules and source envelopes, independent of recorded points.

Envelope variants below are synthetic parser cases. Threshold semantics come
from Yahoo Help SLN6442: awards are cumulative and added to category points.
"""

from decimal import Decimal

import pytest

from sleeper_dynasty.api.yahoo import YahooDataError, scoring_rules
from sleeper_dynasty.engine.scoring import score_week_stats


def settings(*stats):
    return {"stat_modifiers": {"stats": [{"stat": stat} for stat in stats]}}


def stat(stat_id=4, value="0.04", bonuses=None):
    return {"stat_id": stat_id, "value": value, "bonuses": bonuses}


@pytest.mark.parametrize("envelope", [
    [{"bonus": {"target": "300", "points": "3"}}],
    {"bonus": {"target": "300", "points": "3"}},
    {"bonus": [{"target": "300", "points": "3"}]},
    {"0": {"bonus": {"target": "300", "points": "3"}}, "count": 1},
    {"0": {"target": "300", "points": "3"}, "count": "1"},
    {"target": "300", "points": "3"},
    {"bonus": [{"target": "300"}, {"points": "3"}]},
])
def test_single_bonus_envelopes_have_the_same_exact_boundary(envelope):
    weights, bonuses = scoring_rules(settings(stat(bonuses=envelope)))
    assert weights == {"pass_yd": 0.04}
    assert len(bonuses) == 1
    assert bonuses[0].stat_keys == ("pass_yd",)
    assert score_week_stats({"pass_yd": 299}, weights, bonuses=bonuses) == Decimal("11.96")
    assert score_week_stats({"pass_yd": 300}, weights, bonuses=bonuses) == Decimal("15.00")
    assert score_week_stats({"pass_yd": 301}, weights, bonuses=bonuses) == Decimal("15.04")


def test_arbitrary_milestones_are_cumulative_and_keep_base_points():
    weights, bonuses = scoring_rules(settings(stat(9, "0.1", [
        {"bonus": {"target": "100", "points": "3"}},
        {"bonus": {"target": "150", "points": "7"}},
        {"bonus": {"target": "200", "points": "11"}},
    ])))
    # 25 ordinary points + every reached milestone (3 + 7 + 11).
    assert score_week_stats({"rush_yd": 250}, weights, bonuses=bonuses) == Decimal("46.00")


def test_a_combined_return_bonus_uses_total_kick_and_punt_yards_once():
    weights, bonuses = scoring_rules(settings(stat(14, "0.04", {
        "bonus": {"target": 250, "points": 3},
    })))
    assert bonuses[0].stat_keys == ("kr_yd", "pr_yd")
    assert score_week_stats({"kr_yd": 125, "pr_yd": 125}, weights, bonuses=bonuses) == Decimal("13.00")
    # Both components alone reach the target; it is still one combined award.
    assert score_week_stats({"kr_yd": 250, "pr_yd": 250}, weights, bonuses=bonuses) == Decimal("23.00")


@pytest.mark.parametrize(("stat_id", "keys", "raw"), [
    (2, ("pass_cmp",), {"pass_cmp": 10}),
    (8, ("rush_att",), {"rush_att": 10}),
    (11, ("rec",), {"rec": 10}),
    (12, ("rec_yd",), {"rec_yd": 10}),
    (16, ("pass_2pt", "rush_2pt", "rec_2pt"), {"pass_2pt": 4, "rush_2pt": 3, "rec_2pt": 3}),
    (23, ("fgm_50p",), {"fgm_50p": 10}),
    (32, ("sack",), {"sack": 10}),
    (33, ("int",), {"int": 10}),
    (74, ("yds_allow_300_349", "yds_allow_350_399"), {"yds_allow_350_399": 10}),
])
def test_thresholds_apply_to_every_kind_of_mapped_category(stat_id, keys, raw):
    weights, bonuses = scoring_rules(settings(stat(stat_id, "0", {
        "bonus": {"target": "10", "points": "2.5"},
    })))
    assert bonuses[0].stat_keys == keys
    assert score_week_stats(raw, weights, bonuses=bonuses) == Decimal("2.50")


def test_zero_base_multiplier_still_imports_fractional_and_negative_bonuses():
    weights, bonuses = scoring_rules(settings(stat(12, "0", [
        {"bonus": {"target": "99.5", "points": "2.25"}},
        {"bonus": {"target": "125.5", "points": "-0.5"}},
    ])))
    assert score_week_stats({"rec_yd": 125.5}, weights, bonuses=bonuses) == Decimal("1.75")


@pytest.mark.parametrize("envelope", [None, [], {}, {"count": 0}, {"bonus": []}])
def test_empty_bonus_collections_preserve_existing_linear_scoring(envelope):
    weights, bonuses = scoring_rules(settings(stat(bonuses=envelope)))
    assert bonuses == []
    assert score_week_stats({"pass_yd": 300}, weights) == Decimal("12.00")


def test_single_stat_collection_is_supported():
    weights, bonuses = scoring_rules({"stat_modifiers": {"stats": {"stat": stat()}}})
    assert (weights, bonuses) == ({"pass_yd": 0.04}, [])


def test_unknown_stat_with_zero_base_and_active_bonus_is_not_discarded():
    data = settings(stat(999, "0", {"bonus": {"target": 1, "points": 3}}))
    data["stat_categories"] = {"stats": [{"stat": {"stat_id": 999, "name": "New category"}}]}
    with pytest.raises(YahooDataError, match=r"999 \(New category\).*1 active bonuses"):
        scoring_rules(data)


def test_an_unscored_unknown_category_with_zero_bonus_does_not_block_import():
    weights, bonuses = scoring_rules(settings(stat(), stat(999, "0", {
        "bonus": {"target": 1, "points": 0},
    })))
    assert weights == {"pass_yd": 0.04}
    assert bonuses == []


@pytest.mark.parametrize("envelope", [
    {"bonus": {"points": 3}},
    {"bonus": {"target": 300}},
    {"bonus": {"from": 300, "to": 399, "points": 3}},
    {"0": {"bonus": {"target": 300, "points": 3}}, "count": 2},
    {"count": 1},
    {"other": {"target": 300, "points": 3}},
    "not a bonus", True,
])
def test_malformed_and_unknown_bonus_shapes_fail_with_the_stat_id(envelope):
    with pytest.raises(YahooDataError, match="stat 4"):
        scoring_rules(settings(stat(bonuses=envelope)))


@pytest.mark.parametrize("field", ["target", "points"])
@pytest.mark.parametrize("value", [True, None, "", "NaN", "Infinity", "-Infinity", "1e999", [], {}])
def test_invalid_bonus_numbers_never_enter_a_scoring_model(field, value):
    bonus = {"target": 300, "points": 3, field: value}
    with pytest.raises(YahooDataError, match="scoring stat 4"):
        scoring_rules(settings(stat(bonuses={"bonus": bonus})))


def test_negative_targets_and_duplicate_stat_records_are_rejected():
    with pytest.raises(YahooDataError, match="negative bonus target"):
        scoring_rules(settings(stat(bonuses={"bonus": {"target": -1, "points": 3}})))
    with pytest.raises(YahooDataError, match="duplicate scoring stat 4"):
        scoring_rules(settings(stat(), stat()))


def test_repeated_milestone_awards_coalesce_without_losing_points():
    weights, bonuses = scoring_rules(settings(stat(bonuses=[
        {"bonus": {"target": "300", "points": "3"}},
        {"bonus": {"target": 300.0, "points": "5"}},
    ])))
    assert len(bonuses) == 1
    assert bonuses[0].points == 8
    assert score_week_stats({"pass_yd": 300}, weights, bonuses=bonuses) == 20


def test_repeated_milestone_sum_must_remain_finite():
    with pytest.raises(YahooDataError, match="combined bonus points"):
        scoring_rules(settings(stat(bonuses=[
            {"bonus": {"target": 300, "points": "1e308"}},
            {"bonus": {"target": 300, "points": "1e308"}},
        ])))


def test_unverified_zero_thresholds_are_rejected():
    with pytest.raises(YahooDataError, match="unsupported zero bonus target"):
        scoring_rules(settings(stat(bonuses={"bonus": {"target": 0, "points": 3}})))


@pytest.mark.parametrize(("stat_id", "counter"), [
    (0, "gp"), (31, "pts_allow"),
    (59, "pass_cmp_40p"), (60, "pass_td_40p"),
    (61, "rush_40p"), (62, "rush_td_40p"),
    (63, "rec_40p"), (64, "rec_td_40p"),
    (67, "def_4_and_stop"), (68, "tkl_loss"), (69, "yds_allow"),
    (77, "def_3_and_out"), (78, "rec_tgt"),
    (79, "pass_fd"), (80, "rec_fd"), (81, "rush_fd"),
    (84, "fgm_yds"), (85, "fgm"), (86, "fgmiss"),
])
def test_additional_verified_categories_use_event_counters(stat_id, counter):
    weights, bonuses = scoring_rules(settings(stat(stat_id, "2", {
        "bonus": {"target": 2, "points": 3},
    })))
    assert weights == {counter: 2}
    assert bonuses[0].stat_keys == (counter,)
    assert score_week_stats({counter: 2}, weights, bonuses=bonuses) == Decimal("7.00")


def test_defense_return_yards_are_one_combined_bonus():
    weights, bonuses = scoring_rules(settings(stat(48, "0.04", {
        "bonus": {"target": 100, "points": 3},
    })))
    assert bonuses[0].stat_keys == ("def_kr_yd", "def_pr_yd")
    # Real 2025 week-one Denver source counters: 82 kick + 47 punt yards.
    assert score_week_stats({"def_kr_yd": 82, "def_pr_yd": 47}, weights, bonuses=bonuses) == Decimal("8.16")


@pytest.mark.parametrize("value", [True, None, "NaN", "Infinity", "1e999"])
def test_invalid_base_multiplier_cannot_poison_scores(value):
    with pytest.raises(YahooDataError, match="scoring stat 4"):
        scoring_rules(settings(stat(value=value)))


@pytest.mark.asyncio
async def test_import_keeps_bonuses_separate_and_preserves_yahoo_recorded_scores():
    from tests.test_yahoo_adapter import LK, Replay, fixture
    from sleeper_dynasty.api.yahoo_json import merge_fragments

    raw = fixture("league_settings")
    meta = merge_fragments(raw["fantasy_content"]["league"])
    config = merge_fragments(meta["settings"])
    config["stat_modifiers"]["stats"][0]["stat"]["bonuses"] = {
        "bonus": {"target": "300", "points": "3"},
    }
    meta["settings"] = config
    original = Replay()
    adapter = Replay({f"/league/{LK}/settings": {"fantasy_content": {"league": [meta]}}})
    try:
        league, _ = await adapter.get_league(LK)
        assert league.scoring_settings["pass_yd"] == 0.04
        assert len(league.scoring_bonuses) == 1
        assert league.scoring_bonuses[0].target == 300
        # The provider totals are authoritative. Never add a parsed bonus a
        # second time to a score Yahoo has already calculated.
        assert await adapter.get_raw_matchups(LK, 1) == await original.get_raw_matchups(LK, 1)
    finally:
        await original.close()
        await adapter.close()
