import pytest

from sleeper_dynasty.engine.rookie_cohorts import (
    band, build_cohorts, score_season, verdict, verdict_for_row,
)

SCORING = {"pass_yd": 0.04, "pass_td": 6.0, "pass_int": -1.0, "rec": 1.0,
           "rec_yd": 0.1, "rec_td": 6.0, "rush_yd": 0.1, "rush_td": 6.0}


def test_bands_are_continuous_with_no_gaps():
    # ECR is FRACTIONAL. Integer bands with gaps once dumped 32 of 389 players
    # into the bottom cohort and manufactured false hits.
    assert band(4.0) == band(1.0)
    # 8.7 sits between two integer edges. "Continuous, no gaps" means it shares
    # a band with 9.0 (the next edge's territory) and does NOT share one with
    # 8.0 (the previous edge). Integer ranges with gaps once dumped 32 of 389
    # players into the bottom cohort and manufactured false hits.
    assert band(8.7) == band(9.0)
    assert band(8.0) != band(8.7)
    for e in (0.5, 4.0, 4.01, 8.7, 12.5, 18.2, 24.0, 36.9, 60.1, 999.0):
        assert isinstance(band(e), int)
    # Monotone: a worse rank never lands in a better band.
    ranks = [1.0, 4.0, 4.5, 8.0, 8.7, 12.0, 12.5, 18.0, 24.0, 36.0, 60.0, 200.0]
    assert [band(r) for r in ranks] == sorted(band(r) for r in ranks)


def test_score_season_prices_components_with_the_leagues_own_settings():
    stats = {"passing_yards": 4000, "passing_tds": 30, "interceptions": 10}
    # 4000*0.04 + 30*6 - 10 = 160 + 180 - 10
    assert score_season(stats, SCORING) == pytest.approx(330.0)


def test_six_point_pass_tds_score_higher_than_four():
    stats = {"passing_tds": 30}
    assert score_season(stats, {"pass_td": 6.0}) > score_season(stats, {"pass_td": 4.0})


def test_an_absent_component_scores_zero_rather_than_raising():
    assert score_season({"receiving_yards": 100}, {"rec_yd": 0.1}) == pytest.approx(10.0)
    assert score_season({}, SCORING) == 0.0


def _history(n_players: int, per_season_td: float) -> dict:
    # Varied by player index (+ i*0.1) rather than identical for everyone —
    # an identical value across every player makes p25 == p75, and the
    # degenerate-distribution guard (CRITICAL B) now refuses a cell like
    # that on purpose, so a fixture with no spread would silently return {}
    # for reasons unrelated to whatever the test is actually checking.
    return {
        str(i): {"ecr": 2.0, "class": 2021,
                 "seasons": [{"n": 1, "receiving_tds": per_season_td + i * 0.1},
                             {"n": 2, "receiving_tds": per_season_td + i * 0.1}]}
        for i in range(n_players)
    }


def test_cohorts_are_keyed_by_band_and_seasons_held():
    c = build_cohorts(_history(10, 2.0), {"rec_td": 6.0})
    assert f"{band(2.0)}|1" in c
    assert f"{band(2.0)}|2" in c


def test_cumulative_totals_grow_with_seasons_held():
    c = build_cohorts(_history(10, 2.0), {"rec_td": 6.0})
    assert c[f"{band(2.0)}|2"][1] > c[f"{band(2.0)}|1"][1]


def test_a_thin_cell_is_omitted_rather_than_computed_from_too_few_players():
    # A bar from four players is noise wearing a percentile's authority.
    assert build_cohorts(_history(4, 2.0), {"rec_td": 6.0}) == {}


def test_empty_scoring_yields_no_cohorts_not_a_degenerate_all_zero_bar():
    # CRITICAL B: with scoring={}, every cumulative total is 0.0. Without the
    # p25==p75 guard, build_cohorts would still emit cells of (0.0, 0.0, 0.0),
    # and ANY positive total (even 0.5) would then read as "hit" against a bar
    # that cannot discriminate.
    cohorts = build_cohorts(_history(10, 2.0), {})
    assert cohorts == {}
    assert verdict_for_row(
        {"baseline_source": "rookie_ecr", "baseline": 2.0,
         "production_total": 0.5, "seasons_held": 1},
        cohorts,
    ) == ""


def test_a_league_pricing_something_priced_cannot_express_is_refused():
    # IMPORTANT C: bonus_rec_te (TE premium) is real scoring included in a
    # pick's actual production_total, but _PRICED has no column for it, so a
    # cohort bar built here would never see it. The pick reads Hit/Bust
    # against a bar that measured a different game. Refuse rather than
    # silently mismeasure.
    assert build_cohorts(_history(10, 2.0), {"rec_td": 6.0, "bonus_rec_te": 0.5}) == {}
    # A league that prices NOTHING outside _PRICED is unaffected.
    assert build_cohorts(_history(10, 2.0), {"rec_td": 6.0}) != {}


def test_verdict_reads_against_the_cohorts_own_bars():
    cohorts = {"0|1": (10.0, 50.0, 90.0)}
    assert verdict(100.0, 2.0, 1, cohorts) == "hit"
    assert verdict(50.0, 2.0, 1, cohorts) == "average"
    assert verdict(5.0, 2.0, 1, cohorts) == "bust"


def test_verdict_is_empty_when_the_pick_is_unranked_or_the_cell_is_missing():
    cohorts = {"0|1": (10.0, 50.0, 90.0)}
    assert verdict(100.0, None, 1, cohorts) == ""   # unranked
    assert verdict(None, 2.0, 1, cohorts) == ""     # no production figure
    assert verdict(100.0, 2.0, 9, cohorts) == ""    # no cell for 9 seasons held


def test_verdict_falls_back_to_the_nearest_lower_n_with_coverage():
    # A pick held 3 seasons, with cells only for 1 and 2, is judged at 2 —
    # never invented, never silently compared against year-1 bars. 15.0 is
    # chosen deliberately: it is below cell 2's p25 (20.0) but ABOVE cell 1's
    # p25 (10.0), so this only reads "bust" if the fallback actually landed on
    # cell 2 and not cell 1 — a wrong fallback target would silently read
    # "average" instead.
    cohorts = {"0|1": (10.0, 50.0, 90.0), "0|2": (20.0, 100.0, 180.0)}
    assert verdict(200.0, 2.0, 3, cohorts) == "hit"
    assert verdict(15.0, 2.0, 3, cohorts) == "bust"


def test_only_a_rookie_ecr_baseline_is_graded():
    # Redraft/keeper leagues carry a Sleeper ADP baseline (~1-300). Banding it
    # against rookie-ECR cohorts (~1-144) yields a confident, meaningless
    # verdict, which is worse than no verdict at all.
    cohorts = {"0|1": (10.0, 50.0, 90.0)}
    ecr_row = {"baseline_source": "rookie_ecr", "baseline": 2.0,
               "production_total": 100.0, "seasons_held": 1}
    assert verdict_for_row(ecr_row, cohorts) == "hit"
    assert verdict_for_row({**ecr_row, "baseline_source": "sleeper_adp"}, cohorts) == ""
    assert verdict_for_row({**ecr_row, "baseline_source": ""}, cohorts) == ""


def test_a_row_missing_its_fields_is_unjudged_rather_than_zero():
    cohorts = {"0|1": (10.0, 50.0, 90.0)}
    assert verdict_for_row({"baseline_source": "rookie_ecr"}, cohorts) == ""


# A real Sleeper league's scoring_settings, taken verbatim from the reference
# league (9000000000000000001) minus the keys `_PRICED` already expresses. The
# hand-made offense-only dicts above are what let the refusal rule ship looking
# correct: NO real league's settings look like them. Every Sleeper league prices
# a kicker and a defense.
LIVE_UNPRICED = {
    "blk_kick": 2.0, "def_st_ff": 1.0, "def_st_fum_rec": 1.0, "def_st_td": 6.0,
    "def_td": 6.0, "ff": 1.0, "fgm_0_19": 3.0, "fgm_20_29": 3.0,
    "fgm_30_39": 3.0, "fgm_40_49": 4.0, "fgm_50p": 5.0, "fgmiss": -1.0,
    "fum": -1.0, "fum_rec": 2.0, "fum_rec_td": 6.0, "int": 2.0,
    "pts_allow_0": 10.0, "pts_allow_14_20": 1.0, "pts_allow_1_6": 7.0,
    "pts_allow_28_34": -1.0, "pts_allow_35p": -2.0, "pts_allow_7_13": 4.0,
    "sack": 1.0, "safe": 2.0, "st_ff": 1.0, "st_fum_rec": 1.0, "st_td": 6.0,
    "xpm": 1.0, "xpmiss": -1.0,
}


def test_a_real_leagues_kicker_and_defense_scoring_does_not_refuse():
    """Mutation this catches: the guard reverting to `k not in _PRICED_KEYS` —
    i.e. dropping `_IGNORABLE` from the refusal test.

    That was the shipped bug. All 29 keys here are nonzero and outside
    `_PRICED`, so under the old rule `any(...)` is true on the first one and
    the league gets NO cohorts — which is why the Verdict column was empty for
    every league on the board and the owner Draft tab alike. The sibling test
    below only proves a *material* key still refuses, so a rule that refuses
    on EVERYTHING passes it and the rest of the suite.
    """
    cohorts = build_cohorts(_history(10, 2.0), {"rec_td": 6.0, **LIVE_UNPRICED})
    assert cohorts != {}
    # Same bars as the offense-only dict: none of the 29 can price a component
    # in the history, so ignoring them must not perturb a single percentile.
    assert cohorts == build_cohorts(_history(10, 2.0), {"rec_td": 6.0})


def test_a_key_priced_at_zero_never_mattered_either_way():
    """Mutation this catches: dropping the `v and` truthiness test from the
    guard, so a key the league explicitly zeroes starts forcing a refusal.

    `pts_allow_21_27: 0.0` is real — the reference league carries three such
    keys. A key priced at 0 contributes nothing to anyone's total, so it can
    never justify withholding a verdict.
    """
    assert build_cohorts(_history(10, 2.0),
                         {"rec_td": 6.0, "bonus_rec_te": 0.0}) != {}


def test_an_unknown_future_key_still_refuses():
    """Mutation this catches: inverting the fallback from deny-by-default to
    allow-by-default (`k in _MATERIAL` instead of `k not in _IGNORABLE`).

    A key nobody has classified might be worth 60 points a season. Refusing is
    the only safe direction, and an allowlist is the only structure that keeps
    it safe as Sleeper adds settings.
    """
    assert build_cohorts(_history(10, 2.0),
                         {"rec_td": 6.0, "some_2027_setting": 3.0}) == {}


def test_a_material_offensive_key_still_refuses_after_the_widening():
    """Mutation this catches: `bonus_rec_te` (or first downs, or `pass_sack`)
    being swept into `_IGNORABLE` along with the kicker keys.

    TE premium is worth 30-60 points a season to a TE — it is IN the pick's
    real `production_total` and absent from any bar built here. It is the
    reason the refusal exists, and widening the rule must not widen it to this.
    """
    for material in ("bonus_rec_te", "rec_fd", "pass_sack", "bonus_rush_yd_100"):
        assert build_cohorts(
            _history(10, 2.0), {"rec_td": 6.0, material: 0.5},
        ) == {}, f"{material} must still refuse"


def test_no_key_is_both_priced_and_ignored():
    """Mutation this catches: a key landing in `_IGNORABLE` that `_PRICED`
    already expresses — which would read as "ignore it" while `score_season`
    goes on pricing it, so the bar and the rule would disagree about what the
    league scores.
    """
    from sleeper_dynasty.engine.rookie_cohorts import _IGNORABLE, _PRICED_KEYS
    assert _IGNORABLE & _PRICED_KEYS == frozenset()


def test_a_keeper_is_shown_but_never_judged():
    """Mutation this catches: dropping the `is_keeper` guard from
    `verdict_for_row`.

    The row is built to be judgeable in every OTHER respect — rookie-ECR
    baseline, a real total, a cell that covers it — so the only thing that can
    return "" is the keeper rule itself. A row that was unjudgeable anyway
    would pass this test with the guard deleted.

    A keep is not a draft decision. It also has to be excluded HERE, not just
    in the rollup: the board's owner Hit/Bust counts must equal the verdicts
    rendered on the pick rows beneath them, and a keeper carrying a verdict on
    the ledger while sitting outside `scored` breaks that by construction.
    """
    cohorts = {"0|1": (10.0, 50.0, 90.0)}
    row = {"baseline_source": "rookie_ecr", "baseline": 2.0,
           "production_total": 100.0, "seasons_held": 1}
    assert verdict_for_row(row, cohorts) == "hit"          # judgeable but for the keep
    assert verdict_for_row({**row, "is_keeper": True}, cohorts) == ""
