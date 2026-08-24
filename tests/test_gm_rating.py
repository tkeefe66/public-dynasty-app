import pytest

from sleeper_dynasty.engine.gm_rating import (
    BASE,
    PILLAR_WEIGHTS,
    SIGNAL_WEIGHTS,
    compute_gm_ratings,
    rating_to_letter,
)
from sleeper_dynasty.engine.gm_rating import (
    compute_gm_ratings, REDESIGN_PILLAR_WEIGHTS, REDESIGN_SIGNAL_WEIGHTS,
)
from sleeper_dynasty.engine.gm_rating import (
    LETTER_BANDS,
    POINTS_PER_SD,
    REFERENCE_COMPOSITE_SD,
    SCALE,
    V2_KEEPER_SIGNAL_WEIGHTS,
    V2_PILLAR_WEIGHTS,
    V2_REDRAFT_SIGNAL_WEIGHTS,
    V2_SIGNAL_WEIGHTS,
)


def test_redesign_weight_configs_are_normalized():
    for model, pw in REDESIGN_PILLAR_WEIGHTS.items():
        # redraft_led drops Outlook (no future picks/roster carryover to
        # measure in a redraft league); every other tree keeps all three.
        expected = {"results", "skill"} if model == "redraft_led" else {"results", "skill", "outlook"}
        assert set(pw) == expected, model
        assert abs(sum(pw.values()) - 1.0) < 1e-9, model
    for pillar, sw in REDESIGN_SIGNAL_WEIGHTS.items():
        assert abs(sum(sw.values()) - 1.0) < 1e-9, pillar
    assert set(REDESIGN_SIGNAL_WEIGHTS["skill"]) == {
        "trade_value", "trade_production", "draft_skill", "lineup_skill"
    }


def test_default_call_unchanged_by_parametrization():
    # Two owners, legacy tree. Passing no weights must equal passing the
    # module defaults explicitly (proves defaults are wired, behavior intact).
    owners = {
        "a": {"outcomes": {"championships": 1.0}, "trade_impact": {"value": 10.0},
              "outlook": {"roster_value": 100.0}},
        "b": {"outcomes": {"championships": 0.0}, "trade_impact": {"value": -10.0},
              "outlook": {"roster_value": 50.0}},
    }
    from sleeper_dynasty.engine.gm_rating import PILLAR_WEIGHTS, SIGNAL_WEIGHTS
    base = compute_gm_ratings(owners)
    explicit = compute_gm_ratings(
        owners, pillar_weights=PILLAR_WEIGHTS, signal_weights=SIGNAL_WEIGHTS)
    assert base == explicit


def test_redesign_tree_runs_and_centers_on_base():
    # A single-owner league has sd==0 everywhere -> every z is 0 -> rating == BASE.
    owners = {
        "solo": {
            "results": {"championships": 1.0, "playoff_depth": 2.0,
                        "made_playoffs": 1.0, "final_seed": 5.0, "points_for_rank": 4.0},
            "skill": {"trade_value": 3.0, "trade_production": 1.0,
                      "draft_skill": 0.5, "lineup_skill": 0.9},
            "outlook": {"roster_value": 100.0, "draft_capital": 10.0, "youth": -25.0},
        }
    }
    out = compute_gm_ratings(
        owners,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["results_primary"],
        signal_weights=REDESIGN_SIGNAL_WEIGHTS)
    assert out["solo"]["rating"] == 1500
    assert set(out["solo"]["pillars"]) == {"results", "skill", "outlook"}


def _owner(outcomes=None, trade_impact=None, outlook=None):
    return {
        "outcomes": outcomes or {},
        "trade_impact": trade_impact or {},
        "outlook": outlook or {},
    }


def test_pillar_weights_constant():
    assert PILLAR_WEIGHTS == {"outcomes": 0.45, "trade_impact": 0.30, "outlook": 0.25}


def test_signal_weights_shape():
    assert set(SIGNAL_WEIGHTS) == {"outcomes", "trade_impact", "outlook"}
    assert set(SIGNAL_WEIGHTS["outcomes"]) == {
        "championships", "playoff_depth", "made_playoffs", "final_seed", "points_for_rank"}
    assert set(SIGNAL_WEIGHTS["trade_impact"]) == {"playoff", "regular", "value", "toilet"}
    assert set(SIGNAL_WEIGHTS["outlook"]) == {"roster_value", "draft_capital", "draft_skill", "youth"}


def test_breakdown_structure():
    out = compute_gm_ratings({"a": _owner(), "b": _owner()})
    r = out["a"]
    assert set(r) == {"rating", "pillars"}
    assert set(r["pillars"]) == {"outcomes", "trade_impact", "outlook"}
    p = r["pillars"]["outcomes"]
    assert set(p) == {"weight", "z", "contribution", "signals"}
    sig = p["signals"]["championships"]
    assert set(sig) == {"raw", "z", "weight", "contribution"}


def test_all_equal_league_everyone_base():
    out = compute_gm_ratings({"a": _owner(), "b": _owner(), "c": _owner()})
    assert all(r["rating"] == BASE for r in out.values())


def test_single_signal_hand_computed():
    # Only championships varies: a=2, b=0 -> z a=+1, b=-1. Other signals 0 (sd 0 -> z 0).
    # outcomes pillar_z(a) = 0.35*1; composite = 0.45*0.35;
    # rating = 1500 + SCALE*0.1575, SCALE = POINTS_PER_SD / REFERENCE_COMPOSITE_SD.
    out = compute_gm_ratings({
        "a": _owner(outcomes={"championships": 2}),
        "b": _owner(outcomes={"championships": 0}),
    })
    assert out["a"]["rating"] == 1563
    assert out["b"]["rating"] == 1437
    champ = out["a"]["pillars"]["outcomes"]["signals"]["championships"]
    assert champ["raw"] == 2
    assert champ["z"] == 1.0
    assert champ["contribution"] == 63           # round(SCALE * 0.45 * 0.35 * 1)


def test_breakdown_sums_to_rating():
    out = compute_gm_ratings({
        "a": _owner(outcomes={"championships": 2, "final_seed": 8},
                    trade_impact={"playoff": 300, "value": 1500},
                    outlook={"roster_value": 50000, "youth": -26}),
        "b": _owner(outcomes={"championships": 0, "final_seed": 3},
                    trade_impact={"playoff": -100, "value": -500},
                    outlook={"roster_value": 30000, "youth": -28}),
        "c": _owner(outcomes={"championships": 1, "final_seed": 5},
                    trade_impact={"playoff": 50, "value": 200},
                    outlook={"roster_value": 40000, "youth": -27}),
    })
    for r in out.values():
        pillar_sum = 0
        for p in r["pillars"].values():
            sig_sum = sum(s["contribution"] for s in p["signals"].values())
            assert abs(sig_sum - p["contribution"]) <= 1        # rounding
            pillar_sum += p["contribution"]
        assert abs((BASE + pillar_sum) - r["rating"]) <= 2      # rounding across pillars


def test_outcomes_pillar_outweighs_trade_impact():
    osigs = SIGNAL_WEIGHTS["outcomes"]
    tsigs = SIGNAL_WEIGHTS["trade_impact"]
    out = compute_gm_ratings({
        "O": _owner(outcomes={s: 1 for s in osigs}, trade_impact={s: 0 for s in tsigs}),
        "T": _owner(outcomes={s: 0 for s in osigs}, trade_impact={s: 1 for s in tsigs}),
    })
    # Each is +1z on its pillar, -1z on the other; outcomes weight 0.45 > 0.30.
    assert out["O"]["rating"] > out["T"]["rating"]


def test_zero_sd_signal_contributes_zero():
    out = compute_gm_ratings({
        "a": _owner(trade_impact={"value": 100, "playoff": 50}),
        "b": _owner(trade_impact={"value": 100, "playoff": -50}),
    })
    assert out["a"]["pillars"]["trade_impact"]["signals"]["value"]["contribution"] == 0
    assert out["a"]["rating"] > out["b"]["rating"]


# --- Franchise Rating letter (fixed bands off the 1500 base; C = average) ---


def test_average_rating_is_c():
    # 1500 is an exactly-average GM in the league; the average grade is C, and
    # the whole C band straddles the base symmetrically (v2 ladder: C spans
    # delta in [-60, 19)).
    assert rating_to_letter(1500) == "C"
    assert rating_to_letter(1510) == "C"
    assert rating_to_letter(1450) == "C"


def test_letter_band_boundaries():
    # Mid-band deltas from BASE -> letter, one per grade (no boundary ambiguity).
    cases = {
        1925: "A+",
        1851: "A",
        1782: "A-",
        1718: "B+",
        1656: "B",
        1592: "B-",
        1540: "C+",
        1480: "C",
        1408: "C-",
        1345: "D+",
        1276: "D",
        1199: "D-",
    }
    for rating, letter in cases.items():
        assert rating_to_letter(rating) == letter, f"{rating} -> {letter}"


def test_letter_band_edges_are_lower_inclusive():
    # A band's threshold belongs to the better grade; one below drops a notch.
    assert rating_to_letter(1560) == "B-"   # delta +60, B- lower edge
    assert rating_to_letter(1559) == "C+"   # delta +59
    assert rating_to_letter(1376) == "C-"   # delta -124, C- lower edge
    assert rating_to_letter(1375) == "D+"   # delta -125, below C- edge (-124)


def test_letter_clamped_extremes():
    assert rating_to_letter(2200) == "A+"   # CLAMP max
    assert rating_to_letter(800) == "D-"    # CLAMP min; no F band


def test_letter_is_monotonic_non_increasing():
    order = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-"]
    prev = 0
    for rating in range(2200, 799, -1):
        idx = order.index(rating_to_letter(rating))
        assert idx >= prev, f"{rating} regressed in grade ladder"
        prev = idx


# --- v2 weight trees and recalibrated SCALE / LETTER_BANDS ---


def test_v2_trees_are_normalized():
    for name, tree in V2_PILLAR_WEIGHTS.items():
        assert sum(tree.values()) == pytest.approx(1.0), name
    for name, tree in (
        ("dynasty", V2_SIGNAL_WEIGHTS),
        ("keeper", V2_KEEPER_SIGNAL_WEIGHTS),
        ("redraft", V2_REDRAFT_SIGNAL_WEIGHTS),
    ):
        for pillar, sigs in tree.items():
            assert sum(sigs.values()) == pytest.approx(1.0), f"{name}/{pillar}"


def test_every_v2_pillar_tree_has_a_matching_signal_tree():
    # compute_gm_ratings indexes signal_weights by pillar name; a mismatch is
    # a KeyError at runtime rather than a bad number.
    pairs = [
        ("v2_dynasty", V2_SIGNAL_WEIGHTS),
        ("v2_keeper", V2_KEEPER_SIGNAL_WEIGHTS),
        ("v2_redraft", V2_REDRAFT_SIGNAL_WEIGHTS),
    ]
    for model, sigs in pairs:
        assert set(V2_PILLAR_WEIGHTS[model]) == set(sigs), model


def test_redraft_scores_results_only():
    assert V2_PILLAR_WEIGHTS["v2_redraft"] == {"results": 1.0}


def test_keeper_assets_drops_young_core_and_renormalizes():
    assets = V2_KEEPER_SIGNAL_WEIGHTS["assets"]
    assert "young_core_share" not in assets
    assert sum(assets.values()) == pytest.approx(1.0)


def test_v2_keeper_assets_preserves_the_surviving_ratio():
    # Same precedent as test_keeper_outlook_preserves_the_surviving_ratio in
    # test_gm_rating_redraft.py: dropping young_core_share must not silently
    # re-rank roster_value_share against draft_capital.
    k = V2_KEEPER_SIGNAL_WEIGHTS["assets"]
    d = V2_SIGNAL_WEIGHTS["assets"]
    kr = k["roster_value_share"] / k["draft_capital"]
    dr = d["roster_value_share"] / d["draft_capital"]
    assert kr == pytest.approx(dr, abs=1e-3)


def test_letter_bands_are_monotone_and_have_no_f():
    deltas = [d for d, _ in LETTER_BANDS]
    assert deltas == sorted(deltas, reverse=True)
    assert "F" not in [letter for _, letter in LETTER_BANDS]
    assert rating_to_letter(BASE - 100_000) == "D-"


def test_c_plus_exists_and_c_straddles_the_base():
    letters = [letter for _, letter in LETTER_BANDS]
    assert "C+" in letters
    assert rating_to_letter(BASE) == "C"


def test_scale_is_derived_from_the_measured_composite_sd():
    # Bands are stated in sd multiples and must convert through SCALE. Assuming
    # composite sd == 1.0 is what made v1's band table disagree with its own
    # sd column.
    assert SCALE == pytest.approx(POINTS_PER_SD / REFERENCE_COMPOSITE_SD)
    # One reference sd of composite is worth exactly POINTS_PER_SD points.
    assert round(SCALE * REFERENCE_COMPOSITE_SD) == POINTS_PER_SD
