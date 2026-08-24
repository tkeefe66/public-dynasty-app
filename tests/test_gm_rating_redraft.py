from sleeper_dynasty.engine.gm_rating import (
    REDESIGN_PILLAR_WEIGHTS,
    REDESIGN_SIGNAL_WEIGHTS,
    REDRAFT_SIGNAL_WEIGHTS,
    compute_gm_ratings,
)


def _owners():
    """Six owners with spread-out signals in every pillar."""
    out = {}
    for i in range(6):
        f = float(i)
        out[f"u{i}"] = {
            "results": {
                "championships": f, "playoff_depth": f, "made_playoffs": f,
                "final_seed": f, "points_for_rank": f,
            },
            "skill": {
                "trade_value": f, "trade_production": f,
                "draft_skill": f, "lineup_skill": f,
            },
            "outlook": {"roster_value": f, "draft_capital": f, "youth": f},
        }
    return out


def _sd(xs):
    mean = sum(xs) / len(xs)
    return (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5


def test_keeper_tree_keeps_all_three_pillars():
    """A keeper league does carry rosters and picks — Outlook still means
    something. Only the signal mix inside it changes."""
    from sleeper_dynasty.engine.gm_rating import REDESIGN_PILLAR_WEIGHTS as P
    assert set(P["keeper_led"]) == {"results", "skill", "outlook"}
    assert P["keeper_led"] == P["results_led"]


def test_keeper_outlook_drops_youth_and_renormalizes():
    """Two or three keepers is not a young roster — youth measures nothing."""
    from sleeper_dynasty.engine.gm_rating import (
        KEEPER_SIGNAL_WEIGHTS as K, REDESIGN_SIGNAL_WEIGHTS as D,
    )
    assert "youth" not in K["outlook"]
    assert abs(sum(K["outlook"].values()) - 1.0) < 1e-9
    # Results and Skill are untouched — only Outlook is re-mixed.
    assert K["results"] == D["results"]
    assert K["skill"] == D["skill"]


def test_keeper_outlook_preserves_the_surviving_ratio():
    """Dropping youth must not silently re-rank roster_value against capital."""
    from sleeper_dynasty.engine.gm_rating import (
        KEEPER_SIGNAL_WEIGHTS as K, REDESIGN_SIGNAL_WEIGHTS as D,
    )
    k = K["outlook"]["roster_value"] / K["outlook"]["draft_capital"]
    d = D["outlook"]["roster_value"] / D["outlook"]["draft_capital"]
    assert abs(k - d) < 1e-9


def test_keeper_does_not_compress_the_grade_spread():
    """Same guard as redraft: a short-summing tree squashes every owner
    toward 1500 while leaving the mean untouched."""
    from sleeper_dynasty.engine.gm_rating import (
        KEEPER_SIGNAL_WEIGHTS, REDESIGN_PILLAR_WEIGHTS, REDESIGN_SIGNAL_WEIGHTS,
    )
    owners = _owners()
    dyn = compute_gm_ratings(
        owners,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["results_led"],
        signal_weights=REDESIGN_SIGNAL_WEIGHTS,
    )
    kee = compute_gm_ratings(
        owners,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["keeper_led"],
        signal_weights=KEEPER_SIGNAL_WEIGHTS,
    )
    dyn_sd = _sd([v["rating"] for v in dyn.values()])
    kee_sd = _sd([v["rating"] for v in kee.values()])
    assert dyn_sd > 0
    assert abs(kee_sd - dyn_sd) / dyn_sd < 0.02


def test_redraft_tree_exists_and_drops_outlook():
    tree = REDESIGN_PILLAR_WEIGHTS["redraft_led"]
    assert set(tree) == {"results", "skill"}


def test_every_pillar_tree_sums_to_one():
    for name, tree in REDESIGN_PILLAR_WEIGHTS.items():
        assert abs(sum(tree.values()) - 1.0) < 1e-9, name


def test_every_signal_tree_sums_to_one():
    for tree in (REDESIGN_SIGNAL_WEIGHTS, REDRAFT_SIGNAL_WEIGHTS):
        for pillar, sigs in tree.items():
            assert abs(sum(sigs.values()) - 1.0) < 1e-9, pillar


def test_redraft_signal_weights_have_no_outlook_pillar():
    assert "outlook" not in REDRAFT_SIGNAL_WEIGHTS


def test_redraft_signal_weights_are_the_dynasty_ones_minus_outlook():
    """The parity pin. Every other test here only checks that the redraft tree
    sums to 1.0 per pillar — so any permutation of the within-pillar weights
    would pass while ranking redraft owners differently from dynasty owners on
    identical Results/Skill data. Redraft drops a pillar; it does not reweight
    the two it keeps."""
    assert REDRAFT_SIGNAL_WEIGHTS == {
        k: v for k, v in REDESIGN_SIGNAL_WEIGHTS.items() if k != "outlook"
    }


def test_redraft_preserves_results_to_skill_ratio():
    tree = REDESIGN_PILLAR_WEIGHTS["redraft_led"]
    dynasty = REDESIGN_PILLAR_WEIGHTS["results_led"]
    assert abs(
        tree["results"] / tree["skill"] - dynasty["results"] / dynasty["skill"]
    ) < 1e-9


def test_redraft_does_not_compress_the_grade_spread():
    """The renormalization guard. A tree summing to <1.0 would squash every
    owner toward 1500 while leaving the mean untouched."""
    owners = _owners()
    dyn = compute_gm_ratings(
        owners,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["results_led"],
        signal_weights=REDESIGN_SIGNAL_WEIGHTS,
    )
    red = compute_gm_ratings(
        owners,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["redraft_led"],
        signal_weights=REDRAFT_SIGNAL_WEIGHTS,
    )
    dyn_sd = _sd([v["rating"] for v in dyn.values()])
    red_sd = _sd([v["rating"] for v in red.values()])
    assert dyn_sd > 0
    assert abs(red_sd - dyn_sd) / dyn_sd < 0.02


def test_redraft_output_has_no_outlook_pillar():
    red = compute_gm_ratings(
        _owners(),
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["redraft_led"],
        signal_weights=REDRAFT_SIGNAL_WEIGHTS,
    )
    assert "outlook" not in red["u0"]["pillars"]
    assert set(red["u0"]["pillars"]) == {"results", "skill"}
