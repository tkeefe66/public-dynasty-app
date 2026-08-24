import pytest

from sleeper_dynasty.engine.draft_signals import (
    DraftedPick, draft_skill, pick_holdings_value,
    strength_tiers, tiered_pick_value,
)
from sleeper_dynasty.models.league import DraftPick


# --- pick_holdings_value (Draft Capital) ---

def test_default_slate_valued_by_ktc():
    pv = {(2027, 1): 1000.0, (2027, 2): 400.0}
    val = pick_holdings_value(
        traded_picks=[], roster_ids=[1, 2], seasons=[2027], num_rounds=2, pick_values=pv)
    assert val[1] == 1400.0 and val[2] == 1400.0


def test_traded_away_moves_value_to_acquirer():
    pv = {(2027, 1): 1000.0, (2027, 2): 400.0}
    tp = [DraftPick(season=2027, round=1, original_owner_id=1, current_owner_id=2)]
    val = pick_holdings_value(
        traded_picks=tp, roster_ids=[1, 2], seasons=[2027], num_rounds=2, pick_values=pv)
    assert val[1] == 400.0
    assert val[2] == 2400.0


def test_reacquired_own_pick_not_double_counted():
    pv = {(2027, 1): 1000.0}
    tp = [DraftPick(season=2027, round=1, original_owner_id=1, current_owner_id=1)]
    val = pick_holdings_value(
        traded_picks=tp, roster_ids=[1, 2], seasons=[2027], num_rounds=1, pick_values=pv)
    assert val[1] == 1000.0 and val[2] == 1000.0


def test_missing_pick_value_is_zero():
    pv = {(2027, 1): 1000.0}
    val = pick_holdings_value(
        traded_picks=[], roster_ids=[1], seasons=[2027, 2028], num_rounds=1, pick_values=pv)
    assert val[1] == 1000.0


# --- draft_skill ---

def _legacy_pick(draft, rnd, slot, teams, pid, who):
    return DraftedPick(draft_id=draft, round=rnd, slot=slot, picks_in_round=teams,
                       player_id=pid, drafter_id=who)


def test_draft_skill_rewards_beating_the_tier():
    picks = [
        _legacy_pick("d", 1, 1, 6, "bust", "uB"),
        _legacy_pick("d", 1, 2, 6, "ok1", "uC"),
        _legacy_pick("d", 1, 3, 6, "ok2", "uC"),
        _legacy_pick("d", 1, 4, 6, "ok3", "uC"),
        _legacy_pick("d", 1, 5, 6, "steal", "uA"),
        _legacy_pick("d", 1, 6, 6, "ok4", "uC"),
    ]
    ktc = {"steal": 9000, "bust": 100, "ok1": 3000, "ok2": 3000, "ok3": 3000, "ok4": 3000}
    prod = {"steal": 1800, "bust": 0, "ok1": 600, "ok2": 600, "ok3": 600, "ok4": 600}
    sk = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert sk["uA"] > 0
    assert sk["uB"] < 0
    assert sk["uA"] > sk["uB"]


def test_draft_skill_shrinks_small_samples():
    picks = [_legacy_pick("d", 1, 1, 2, "p1", "uA"), _legacy_pick("d", 1, 2, 2, "p2", "uB")]
    ktc = {"p1": 5000, "p2": 1000}
    prod = {"p1": 1000, "p2": 200}
    sk = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod, shrink_k=3.0)
    assert sk["uA"] > 0 and sk["uB"] < 0


def test_draft_skill_empty_is_empty():
    assert draft_skill(picks=[], ktc_by_player={}, production_by_player={}) == {}


# --- strength_tiers + tiered_pick_value (Task 2) ---

def test_strength_tiers_thirds_by_rank():
    vals = {f"u{i}": v for i, v in enumerate([100, 90, 80, 70, 60, 50])}
    t = strength_tiers(vals)
    assert t["u0"] == "late" and t["u1"] == "late"
    assert t["u2"] == "mid" and t["u3"] == "mid"
    assert t["u4"] == "early" and t["u5"] == "early"


def test_strength_tiers_tiny_league_all_mid():
    assert strength_tiers({"a": 5, "b": 3}) == {"a": "mid", "b": "mid"}


def test_tiered_pick_value_falls_back_to_round_avg():
    tiered = {(2027, 1, "early"): 9000.0}
    rnd = {(2027, 1): 6500.0}
    assert tiered_pick_value(2027, 1, "early", tiered, rnd) == 9000.0
    assert tiered_pick_value(2027, 1, "late", tiered, rnd) == 6500.0
    assert tiered_pick_value(2028, 1, "early", tiered, rnd) == 0.0


# --- pick_holdings_value tiering (Task 3) ---

def test_pick_holdings_value_tiers_by_original_team():
    pv = {(2027, 1): 6500.0}
    tiered = {(2027, 1, "early"): 9000.0, (2027, 1, "late"): 4000.0}
    tiers = {1: "early", 2: "late"}
    val = pick_holdings_value(
        traded_picks=[], roster_ids=[1, 2], seasons=[2027], num_rounds=1,
        pick_values=pv, tier_by_roster=tiers, tiered_values=tiered)
    assert val[1] == 9000.0
    assert val[2] == 4000.0


def test_pick_holdings_value_backcompat_round_average():
    pv = {(2027, 1): 6500.0}
    val = pick_holdings_value(
        traded_picks=[], roster_ids=[1], seasons=[2027], num_rounds=1, pick_values=pv)
    assert val[1] == 6500.0


# --- draft_skill opportunity-aware (games_by_player) ---

def test_draft_skill_backward_compat_no_games_arg():
    """Without games_by_player, behavior is identical to treating all picks as played."""
    picks = [
        _legacy_pick("d", 1, 1, 6, "steal", "uA"),
        _legacy_pick("d", 1, 5, 6, "bust", "uB"),
    ]
    ktc = {"steal": 9000, "bust": 100}
    prod = {"steal": 1800, "bust": 0}

    sk_no_games = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod)
    sk_all_played = draft_skill(
        picks=picks, ktc_by_player=ktc, production_by_player=prod,
        games_by_player={"steal": 20, "bust": 20})

    assert sk_no_games["uA"] == pytest.approx(sk_all_played["uA"])
    assert sk_no_games["uB"] == pytest.approx(sk_all_played["uB"])


def test_draft_skill_unplayed_judged_by_value_not_production():
    """When both picks are unplayed (<17 games), the higher-KTC pick wins —
    even if the lower-KTC pick accumulated more production in partial games.

    Old code (no games_by_player) treats both as played: KTC and production
    z-scores cancel to a tie (0.0 = 0.0). New code uses value only for
    unplayed picks, so the KTC difference decides.
    """
    picks = [
        _legacy_pick("d", 1, 1, 2, "pA", "uA"),  # HIGH KTC, 0 production
        _legacy_pick("d", 1, 2, 2, "pB", "uB"),  # LOW  KTC, some partial-season production
    ]
    ktc = {"pA": 8000.0, "pB": 1000.0}
    prod = {"pA": 0.0, "pB": 300.0}
    games = {"pA": 5, "pB": 5}  # both well under 17 → unplayed

    sk = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod,
                     games_by_player=games)

    # KTC advantage drives the verdict; production is not penalised/rewarded
    assert sk["uA"] > sk["uB"]


def test_draft_skill_unplayed_zeros_dont_pollute_played_distribution():
    """A played pick with strong production scores positively vs its played peers
    even when several unplayed (0-production) picks exist in the same pool.

    Picks in slots 5-8 of a 12-team draft land in tier 1 together; the two
    unplayed picks' zero production is excluded from the z-score distribution.
    """
    picks = [
        _legacy_pick("d2", 1, 5, 12, "pA", "uA"),   # played, strong production
        _legacy_pick("d2", 1, 6, 12, "pB", "uB"),   # played, weak production
        _legacy_pick("d2", 1, 7, 12, "pC", "uC"),   # unplayed, 0 production
        _legacy_pick("d2", 1, 8, 12, "pD", "uD"),   # unplayed, 0 production
    ]
    ktc = {"pA": 3000.0, "pB": 3000.0, "pC": 3000.0, "pD": 3000.0}  # same → zk=0
    prod = {"pA": 800.0, "pB": 200.0, "pC": 0.0, "pD": 0.0}
    games = {"pA": 20, "pB": 20, "pC": 5, "pD": 5}

    sk = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod,
                     games_by_player=games)

    # Strong-production played pick beats tier average
    assert sk["uA"] > 0
    # Production ordering among played picks is preserved
    assert sk["uA"] > sk["uB"]


def test_draft_skill_floor_boundary_17_vs_16_games():
    """Exactly min_games (17) counts as played (production matters);
    16 does not (value only → outcome = zk = 0 when all KTC are equal).
    """
    picks = [
        _legacy_pick("d3", 1, 1, 3, "pA", "uA"),   # always played (17)
        _legacy_pick("d3", 1, 2, 3, "pB", "uB"),   # boundary player — tested at 16 vs 17
        _legacy_pick("d3", 1, 3, 3, "pC", "uC"),   # always played (17), low production
    ]
    ktc = {"pA": 3000.0, "pB": 3000.0, "pC": 3000.0}  # same → zk=0 for all
    prod = {"pA": 100.0, "pB": 100.0, "pC": 0.0}

    games_16 = {"pA": 17, "pB": 16, "pC": 17}  # pB just below threshold
    games_17 = {"pA": 17, "pB": 17, "pC": 17}  # pB exactly at threshold

    sk_16 = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod,
                        games_by_player=games_16)
    sk_17 = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod,
                        games_by_player=games_17)

    # At 16 games: pB is unplayed → outcome=zk=0, expected=0 → skill=0
    assert sk_16["uB"] == pytest.approx(0.0)
    # At 17 games: pB is played → gets positive production z (same prod as pA) → skill>0
    assert sk_17["uB"] > 0.0
    # The threshold creates a measurable difference
    assert sk_17["uB"] != pytest.approx(sk_16["uB"])


# --- keeper exclusion + grading axis ---

def _pick(pid, uid, *, rnd=1, slot=1, keeper=False, draft_id="d1", teams=4,
          gradeable=True):
    return DraftedPick(
        draft_id=draft_id, round=rnd, slot=slot, picks_in_round=teams,
        player_id=pid, drafter_id=uid, draft_season=2025,
        pick_no=(rnd - 1) * teams + slot, draft_kind="full", is_keeper=keeper,
        gradeable=gradeable)


def test_keeper_picks_do_not_score_for_their_owner():
    picks = [
        _pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2),
        _pick("p3", "u3", slot=3), _pick("p4", "u4", slot=4),
    ]
    ktc = {"p1": 100.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}
    prod = {"p1": 100.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}
    graded = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert graded["u1"] > 0  # baseline: a strong pick scores

    picks[0] = _pick("p1", "u1", slot=1, keeper=True)
    kept = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert "u1" not in kept


def test_keeper_picks_do_not_drag_the_peer_baseline():
    """A kept star in round 1 must not raise what round 1 is expected to
    return, which would unfairly penalise everyone who actually picked."""
    others = [_pick("p2", "u2", slot=2), _pick("p3", "u3", slot=3),
              _pick("p4", "u4", slot=4)]
    ktc = {"p1": 1000.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}
    prod = {"p1": 1000.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}

    without = draft_skill(
        picks=others, ktc_by_player=ktc, production_by_player=prod)
    with_keeper = draft_skill(
        picks=[_pick("p1", "u1", slot=1, keeper=True)] + others,
        ktc_by_player=ktc, production_by_player=prod)
    assert with_keeper["u2"] == pytest.approx(without["u2"])


def test_non_gradeable_picks_do_not_score_for_their_owner():
    """Auction drafts (gradeable=False): pick_no is chronological, not
    positional, so results-only picks must never enter a grade."""
    picks = [
        _pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2),
        _pick("p3", "u3", slot=3), _pick("p4", "u4", slot=4),
    ]
    ktc = {"p1": 100.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}
    prod = {"p1": 100.0, "p2": 50.0, "p3": 50.0, "p4": 50.0}
    graded = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert graded["u1"] > 0  # baseline: a strong pick scores

    picks[0] = _pick("p1", "u1", slot=1, gradeable=False)
    ungraded = draft_skill(picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert "u1" not in ungraded


def test_production_axis_ignores_value_entirely():
    """Redraft: two picks identical on production, wildly different on value.
    Under the production axis they must grade the same."""
    picks = [_pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2)]
    prod = {"p1": 100.0, "p2": 100.0}
    ktc = {"p1": 5000.0, "p2": 0.0}
    out = draft_skill(
        picks=picks, ktc_by_player=ktc, production_by_player=prod,
        axis="production")
    assert out["u1"] == pytest.approx(out["u2"])


def test_production_axis_still_separates_on_production():
    picks = [_pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2)]
    out = draft_skill(
        picks=picks, ktc_by_player={"p1": 0.0, "p2": 0.0},
        production_by_player={"p1": 300.0, "p2": 10.0}, axis="production")
    assert out["u1"] > out["u2"]


def test_production_axis_does_not_exempt_unplayed_picks():
    """Under the blend axis an unplayed rookie is judged on value alone. In
    redraft a pick that never played scored nothing, and that is the answer."""
    picks = [_pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2)]
    out = draft_skill(
        picks=picks, ktc_by_player={"p1": 5000.0, "p2": 0.0},
        production_by_player={"p1": 0.0, "p2": 200.0},
        games_by_player={"p1": 0, "p2": 17}, axis="production")
    assert out["u2"] > out["u1"]


def test_blend_axis_is_unchanged_for_dynasty():
    picks = [_pick("p1", "u1", slot=1), _pick("p2", "u2", slot=2)]
    ktc = {"p1": 100.0, "p2": 0.0}
    prod = {"p1": 0.0, "p2": 0.0}
    explicit = draft_skill(
        picks=picks, ktc_by_player=ktc, production_by_player=prod, axis="blend")
    default = draft_skill(
        picks=picks, ktc_by_player=ktc, production_by_player=prod)
    assert explicit == default


def test_all_keeper_class_grades_nobody():
    picks = [_pick("p1", "u1", slot=1, keeper=True),
             _pick("p2", "u2", slot=2, keeper=True)]
    assert draft_skill(
        picks=picks, ktc_by_player={}, production_by_player={}) == {}
