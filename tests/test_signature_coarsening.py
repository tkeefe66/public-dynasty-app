"""The coarsened skip-hash must be stable against per-refresh drift but still
change on material change. These tests pin that contract directly on the three
facts-hash functions (the only place the skip decision is computed)."""

from __future__ import annotations

from sleeper_dynasty.models._signature import _coarsen, signature_hash
from sleeper_dynasty.models.franchise_outlook import (
    FranchiseFacts, franchise_facts_hash,
)
from sleeper_dynasty.models.gm_rating_blurb import (
    OwnerRatingFacts, rating_facts_hash,
)
from sleeper_dynasty.models.trade_story import TradeStoryFacts, facts_hash


# --- low-level coarsener -------------------------------------------------

def test_band_collapses_sub_band_drift():
    # KTC width is 400: 1500 vs 1560 land in the same bucket.
    assert _coarsen("net_ktc", 1500.0) == _coarsen("net_ktc", 1560.0)
    # points width is 50: 100 vs 108 collapse, 100 vs 180 do not.
    assert _coarsen("points_total", 100.0) == _coarsen("points_total", 108.0)
    assert _coarsen("points_total", 100.0) != _coarsen("points_total", 180.0)


def test_significant_bands_tolerate_wider_drift():
    # Widened "significant" grid: points=50, ktc=400, rating=150. Drift the old
    # (25/250/100) grid split into separate buckets now collapses to one, so a
    # blurb no longer regenerates on a single good week or a modest value tick.
    assert _coarsen("points_total", 100.0) == _coarsen("points_total", 120.0)
    assert _coarsen("net_ktc", 1500.0) == _coarsen("net_ktc", 1700.0)
    assert _coarsen("rating", 1480) == _coarsen("rating", 1560)
    # A genuinely significant move still busts the bucket and triggers regen.
    assert _coarsen("points_total", 100.0) != _coarsen("points_total", 180.0)
    assert _coarsen("net_ktc", 1500.0) != _coarsen("net_ktc", 2100.0)


def test_weekly_counters_dropped():
    a = {"player": "X", "starter_weeks": 3, "benched_weeks": 1, "points_total": 100.0}
    b = {"player": "X", "starter_weeks": 9, "benched_weeks": 4, "points_total": 100.0}
    assert _coarsen("", a) == _coarsen("", b)


def test_discrete_and_categorical_kept_exact():
    # rank (int, not drifty) and a string label are material → kept.
    assert _coarsen("rank", 1) != _coarsen("rank", 2)
    assert _coarsen("winner_user_id", "u1") != _coarsen("winner_user_id", "u2")
    # bool is kept exact (and never banded).
    assert _coarsen("flipped", True) != _coarsen("flipped", False)


def test_drifty_rating_int_is_banded():
    # rating is recomputed each refresh; a 4-point move must not bust the hash.
    assert _coarsen("rating", 1523) == _coarsen("rating", 1527)
    assert _coarsen("rating", 1523) != _coarsen("rating", 1700)


# --- trade story ---------------------------------------------------------

def _trade_facts(**over) -> TradeStoryFacts:
    base = dict(
        trade_id="t1", season=2025, is_offseason=False,
        winner_user_id="u1", lopsidedness=0.42,
        margins={"ktc": 1500.0, "production": 100.0,
                 "points_started": 80.0, "playoff_points": 20.0},
        sides=[{"user_id": "u1", "player_arcs": [
            {"player": "Player A", "points_total": 100.0, "starter_weeks": 3,
             "flipped": False, "dropped": False}]}],
        owners={"u1": {"net_ktc": 1500.0, "tilt": "win-now"}},
    )
    base.update(over)
    return TradeStoryFacts(**base)


def test_trade_story_hash_stable_under_drift():
    a = _trade_facts()
    # KTC ticked, a started-point total nudged, a week counter advanced.
    b = _trade_facts(
        margins={"ktc": 1555.0, "production": 104.0,
                 "points_started": 84.0, "playoff_points": 22.0},
        sides=[{"user_id": "u1", "player_arcs": [
            {"player": "Player A", "points_total": 106.0, "starter_weeks": 7,
             "flipped": False, "dropped": False}]}],
        owners={"u1": {"net_ktc": 1560.0, "tilt": "win-now"}},
    )
    assert facts_hash(a) == facts_hash(b)


def test_trade_story_hash_changes_on_winner_flip():
    assert facts_hash(_trade_facts()) != facts_hash(_trade_facts(winner_user_id="u2"))


def test_trade_story_hash_changes_when_flip_resolves():
    resolved = _trade_facts(sides=[{"user_id": "u1", "player_arcs": [
        {"player": "Player A", "points_total": 100.0, "starter_weeks": 3,
         "flipped": True, "dropped": False}]}])
    assert facts_hash(_trade_facts()) != facts_hash(resolved)


# --- GM blurb ------------------------------------------------------------

def _rating_facts(rating: int, rank: int = 1) -> OwnerRatingFacts:
    f = OwnerRatingFacts(
        user_id="u1", owner_name="Al", team_name="T", scope_label="career",
        rank=rank, rating=rating,
        pillars=[{"label": "Outcomes", "weight": 0.45, "contribution": 80.0}],
        made_playoffs_rate=0.5,
    )
    return f


def test_gm_blurb_hash_stable_under_rating_drift():
    assert rating_facts_hash(_rating_facts(1523)) == rating_facts_hash(_rating_facts(1527))


def test_gm_blurb_hash_changes_on_rank_move():
    assert rating_facts_hash(_rating_facts(1523, rank=1)) != \
        rating_facts_hash(_rating_facts(1523, rank=2))


# --- franchise outlook ---------------------------------------------------

def _fr_facts(**over) -> FranchiseFacts:
    base = dict(
        user_id="u1", owner_name="Al", team_name="T", league_format="dynasty",
        window="contender", young_core_share=0.52, roster_rank=2, roster_of=12,
        young_core=["A"], aging_risks=[], draft_capital_status="rich",
        draft_capital_net=1500.0, top_need="WR", signature_trade="received X",
    )
    base.update(over)
    return FranchiseFacts(**base)


def test_franchise_hash_stable_under_value_drift():
    a = _fr_facts()
    b = _fr_facts(young_core_share=0.53, draft_capital_net=1560.0)
    assert franchise_facts_hash(a) == franchise_facts_hash(b)


def test_franchise_hash_changes_on_window_shift():
    assert franchise_facts_hash(_fr_facts()) != \
        franchise_facts_hash(_fr_facts(window="rebuild"))


def test_signature_hash_is_16_chars():
    assert len(signature_hash({"a": 1})) == 16


# --- churn leaks: int-typed banded fields, list ordering -------------------

def test_int_typed_banded_field_is_banded_like_float():
    # KTC values arrive as ints from the API; a field listed in FIELD_BANDS
    # must band regardless of numeric type, else daily market ticks churn
    # the hash (observed in prod: ~130 regens/day in the dead offseason).
    assert _coarsen("net_ktc", 1500) == _coarsen("net_ktc", 1560)
    assert _coarsen("net_ktc", 1500) != _coarsen("net_ktc", 2100)


def test_int_and_float_representations_hash_identically():
    # 1500 vs 1500.0 is a representation detail, never a material change.
    assert _coarsen("net_ktc", 1500) == _coarsen("net_ktc", 1500.0)
    assert signature_hash({"net_ktc": 1500}) == signature_hash({"net_ktc": 1500.0})


def test_unbanded_ints_still_kept_exact():
    # rank / counts / season stay exact — they only change on real events.
    assert _coarsen("rank", 1) != _coarsen("rank", 2)
    assert _coarsen("championships", 1) != _coarsen("championships", 2)


def test_string_list_order_insensitive():
    # Value-ordered lists (young_core, aging_risks) reshuffle on daily KTC
    # drift; ordering is not narrative-material, membership is.
    assert _coarsen("young_core", ["A", "B"]) == _coarsen("young_core", ["B", "A"])
    assert _coarsen("young_core", ["A", "B"]) != _coarsen("young_core", ["A", "C"])


def test_dict_lists_keep_order():
    # Lists of dicts (player_arcs, sides) are not reordered by the coarsener.
    a = [{"player": "A"}, {"player": "B"}]
    b = [{"player": "B"}, {"player": "A"}]
    assert _coarsen("player_arcs", a) != _coarsen("player_arcs", b)


def test_franchise_hash_stable_when_young_core_reorders():
    a = _fr_facts(young_core=["A", "B"])
    b = _fr_facts(young_core=["B", "A"])
    assert franchise_facts_hash(a) == franchise_facts_hash(b)
    # A membership change is material and must still regenerate.
    c = _fr_facts(young_core=["A", "B", "C"])
    assert franchise_facts_hash(a) != franchise_facts_hash(c)
