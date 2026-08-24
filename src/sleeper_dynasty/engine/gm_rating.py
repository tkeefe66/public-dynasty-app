"""Transparent, league-relative GM Rating from three pillars.

Each owner is scored on three pillars, each a weighted blend of league-z-scored
signals:

  - Outcomes     (0.45): season results — championships, playoff depth,
                         made-playoffs rate, final seed, points-for rank
  - Trade Impact (0.30): realized output of trades — playoff/regular/value/toilet
  - Outlook      (0.25): future franchise health — roster value, draft capital, draft skill, youth

The pillar z-scores are blended by PILLAR_WEIGHTS into a composite, then scaled
to a 1500-centered rating (BASE ± SCALE, clamped). The return carries a full
breakdown so every rating point is traceable: pillar -> signal -> (raw, z,
weight, contribution). Pure + fully unit-testable.
"""

from __future__ import annotations

PILLAR_WEIGHTS = {"outcomes": 0.45, "trade_impact": 0.30, "outlook": 0.25}

SIGNAL_WEIGHTS = {
    "outcomes": {
        "championships": 0.35, "playoff_depth": 0.25, "made_playoffs": 0.15,
        "final_seed": 0.15, "points_for_rank": 0.10,
    },
    "trade_impact": {"playoff": 0.40, "regular": 0.30, "value": 0.22, "toilet": 0.08},
    "outlook": {"roster_value": 0.35, "draft_capital": 0.25, "draft_skill": 0.20, "youth": 0.20},
}

# --- Redesign (Results / Skill / Outlook). Additive: the live read path still
# uses the legacy PILLAR_WEIGHTS/SIGNAL_WEIGHTS above. Pass these explicitly to
# compute_gm_ratings to score the new tree. Weights are tunable v1 starting points.
REDESIGN_SIGNAL_WEIGHTS = {
    "results": {
        "championships": 0.35, "playoff_depth": 0.25, "made_playoffs": 0.15,
        "final_seed": 0.15, "points_for_rank": 0.10,
    },
    "skill": {
        "trade_value": 0.25, "trade_production": 0.20,
        "draft_skill": 0.30, "lineup_skill": 0.25,
    },
    "outlook": {"roster_value": 0.45, "draft_capital": 0.30, "youth": 0.25},
}

# Redraft: no future picks and no roster carryover, so the Outlook pillar has
# nothing real to measure. Dropped entirely rather than zeroed — a zeroed
# pillar still consumes its weight and would compress every grade toward the
# 1500 base. Results and Skill are renormalized over 0.80, preserving their
# 0.50 : 0.30 ratio exactly.
REDRAFT_SIGNAL_WEIGHTS = {
    "results": {
        "championships": 0.35, "playoff_depth": 0.25, "made_playoffs": 0.15,
        "final_seed": 0.15, "points_for_rank": 0.10,
    },
    "skill": {
        "trade_value": 0.25, "trade_production": 0.20,
        "draft_skill": 0.30, "lineup_skill": 0.25,
    },
}

# Keeper: rosters and picks DO carry, so unlike redraft the Outlook pillar
# still measures something and keeps its full 0.20. What it cannot measure is
# youth — a keeper league carries two or three players, so "how young is the
# roster" is noise rather than a strategy. Dropped and the survivors
# renormalized over 0.75, preserving their 0.45 : 0.30 ratio exactly.
KEEPER_SIGNAL_WEIGHTS = {
    "results": {
        "championships": 0.35, "playoff_depth": 0.25, "made_playoffs": 0.15,
        "final_seed": 0.15, "points_for_rank": 0.10,
    },
    "skill": {
        "trade_value": 0.25, "trade_production": 0.20,
        "draft_skill": 0.30, "lineup_skill": 0.25,
    },
    "outlook": {"roster_value": 0.60, "draft_capital": 0.40},
}

REDESIGN_PILLAR_WEIGHTS = {
    "results_primary": {"results": 0.55, "skill": 0.30, "outlook": 0.15},
    "equal_axes": {"results": 0.43, "skill": 0.43, "outlook": 0.14},
    "results_led": {"results": 0.50, "skill": 0.30, "outlook": 0.20},
    # Same pillar split as results_led — keeper differs only inside Outlook.
    "keeper_led": {"results": 0.50, "skill": 0.30, "outlook": 0.20},
    "redraft_led": {"results": 0.625, "skill": 0.375},
}

# --- v2: winning + building. Skill is dropped from scoring (nothing in it
# persisted year to year: draft r~+0.10, lineup r~+0.04, and both trade signals
# were NEGATIVELY self-correlated) and is measured through its consequences
# instead. Growth (asset-share trajectory) arrives in v2.1 and takes its weight
# out of Assets.
V2_PILLAR_WEIGHTS = {
    "v2_dynasty": {"results": 0.60, "assets": 0.40},
    # Same split as dynasty; keeper differs only inside Assets.
    "v2_keeper": {"results": 0.60, "assets": 0.40},
    # Nothing carries over, so Assets has no subject. Dropped, not zeroed.
    "v2_redraft": {"results": 1.00},
}

_V2_RESULTS = {"expected_wins": 0.55, "playoff_success": 0.30, "luck": 0.15}

V2_SIGNAL_WEIGHTS = {
    "results": dict(_V2_RESULTS),
    "assets": {
        "roster_value_share": 0.45, "young_core_share": 0.35, "draft_capital": 0.20,
    },
}

# Two or three keepers is not a young roster, so young-core share is noise.
# Dropped and the survivors renormalized over 0.65, preserving their 0.45 :
# 0.20 ratio exactly (0.45/0.65, 0.20/0.65) rather than rounding to a tidier
# split that would quietly re-rank roster_value_share against draft_capital.
V2_KEEPER_SIGNAL_WEIGHTS = {
    "results": dict(_V2_RESULTS),
    "assets": {"roster_value_share": 0.6923, "draft_capital": 0.3077},
}

V2_REDRAFT_SIGNAL_WEIGHTS = {"results": dict(_V2_RESULTS)}

BASE = 1500

# One reference standard deviation of composite is worth this many rating
# points. Bands below are stated in sd multiples and convert through it.
POINTS_PER_SD = 275

# Measured 2026-08-17 on the reference league (12 owners, seasons 2023-25),
# rebuilt at SCHEMA_VERSION 17 and scored under `v2_dynasty`.
#
# It replaces a 0.906 stand-in that was the Results-pillar sd of the OLD tree.
# That was an over-estimate *by construction*, not by accident: a 0.60/0.40
# blend of two imperfectly-correlated pillars has a strictly smaller sd than
# either pillar alone. Reading a single pillar's spread as the composite's cost
# roughly a quarter of the ladder — the league graded out across 5 distinct
# letters instead of 7, with four owners sharing the bottom band.
#
# The constant exists at all because v1 assumed 1.0 while its real value was
# 0.70, which is why its `C` band spanned +/-0.10 sd and ~30% of any league
# graded D+ or worse by construction.
#
# One league, n=12. This is honestly measured, not proven to generalise —
# re-measure with the `franchise-rating-calibration` skill whenever the tree,
# the signals, or the bands move.
REFERENCE_COMPOSITE_SD = 0.6854

SCALE = POINTS_PER_SD / REFERENCE_COMPOSITE_SD

CLAMP = (800, 2200)

# (sd multiple, letter), high to low. No F: a twelve-owner league spans roughly
# +/-1.75 sd, so an F could only ever fire by construction or never. The scale
# runs A+ to D- and says so.
_BAND_SD: list[tuple[float, str]] = [
    (1.40, "A+"), (1.15, "A"), (0.90, "A-"),
    (0.68, "B+"), (0.45, "B"), (0.22, "B-"),
    (0.07, "C+"), (-0.22, "C"), (-0.45, "C-"),
    (-0.68, "D+"), (-0.95, "D"),
]

LETTER_BANDS: list[tuple[int, str]] = [
    (round(mult * POINTS_PER_SD), letter) for mult, letter in _BAND_SD
]


def rating_to_letter(rating: int) -> str:
    """Map a league-relative Franchise Rating to a letter grade via fixed,
    sd-derived bands. The scale runs A+ down to D- (no F): a twelve-owner
    league spans roughly +/-1.75 sd of composite, so an F band could only
    ever fire by construction or never fire at all.
    """
    delta = rating - BASE
    for lo, letter in LETTER_BANDS:
        if delta >= lo:
            return letter
    return "D-"


# (sd multiple, stage), high to low. The competitive-window rail, banded on
# the SAME composite `rating_to_letter` bands and converted through the same
# POINTS_PER_SD, so the two scales cannot drift and no second prior is
# introduced. `else` is "Rebuilding".
#
# Monotone by construction: the rung is a function of one scalar, so a better
# composite can never land on a lower rung. The v1 model this replaces mixed a
# level test with the RELATION `assets_z >= results_z` and put the result on an
# ordered rail, which let a league-average team (+0.1 / +0.2) outrank a
# +1.9 / +1.8 one. Relation rules cannot be monotone on a rail.
#
# Populations against a normal composite (verified 2026-08-18):
# 18.4 / 19.8 / 23.6 / 19.8 / 18.4 % -- 2.2 to 2.8 owners of twelve per rung,
# symmetric. That check is the point of stating it: the F-band note above
# records a band that "could only ever fire by construction or never", and a
# five-rung rail is exactly where that recurs.
#
# One edge coincides with the letter scale and the rest do not, so state it
# precisely: Dynasty and A- are both cut at 0.90 sd, so at sd=None they share
# an edge exactly (delta 248 either way). Competing COVERS the letters C-
# through B- -- containing all of the C band that is league-average by
# definition -- but its own edges sit INSIDE those bands, not on them: its
# lower edge is delta -82 against C-'s -124, its upper edge delta 81 against
# B-'s 60. An earlier version of this comment claimed "the edges align with
# the letter scale exactly", which is true only of Dynasty/A-.
#
# And note the whole comparison assumes sd=None. Every shipped call site
# passes the LEAGUE's own spread, so the two rails share their sd multiples,
# not their rating-point edges, and coincide only where a league's spread
# equals the reference.
#
# Same caveat as LETTER_BANDS: honestly derived from REFERENCE_COMPOSITE_SD,
# but n=12, one league. Re-measure with the `franchise-rating-calibration`
# skill whenever the tree or the bands move.
_STAGE_SD: list[tuple[float, str]] = [
    (0.90, "Dynasty"), (0.30, "Contending"),
    (-0.30, "Competing"), (-0.90, "Retooling"),
]

STAGE_BANDS: list[tuple[int, str]] = [
    (round(mult * POINTS_PER_SD), stage) for mult, stage in _STAGE_SD
]

# The band UNIT may instead be supplied per league — `rating_to_stage(r,
# sd=...)` passes that league's own realized rating spread, so a league that
# has separated hard gets wide rungs and a tight one gets narrow rungs, rather
# than every league inheriting the spread of the single reference league that
# POINTS_PER_SD was measured on. This floor is the guard on that unit.
#
# THE FAILURE IT EXISTS TO STOP: as sd -> 0 every edge below collapses to 0,
# and the scan's `delta >= lo` then matches the FIRST rung — so a league whose
# owners all rate identically (everyone at exactly BASE, which is what a flat
# league z-scores to) would grade every one of them "Dynasty". Same family as
# the `_SD_RELATIVE_FLOOR` failure recorded further down (a flat twelve-owner
# league grading 1725 instead of 1500): an arithmetic that is correct
# everywhere except at zero spread, where it returns the loudest available
# answer instead of the neutral one.
#
# 0.5 * POINTS_PER_SD is a CHOSEN PRIOR, not a measured one — like the
# two-season half-life in the rating's recency decay, and unlike
# REFERENCE_COMPOSITE_SD above, which is measured (n=12, one league). It
# encodes a judgement: a league flatter than half the reference spread has not
# separated yet, and its middling owners are not thereby contenders. It binds
# only below 137.5 rating points, so it does NOT bind on the reference league
# (realized rating sd ~251).
STAGE_SD_FLOOR = 0.5 * POINTS_PER_SD


def rating_to_stage(rating: int, *, sd: float | None = None) -> str:
    """Map a league-relative Franchise Rating to its competitive-window stage.

    One of Dynasty / Contending / Competing / Retooling / Rebuilding, high to
    low. This is the ONLY producer of a window stage: the independent
    Strength x Trajectory model that used to answer this question is retired,
    so an owner cannot read one stage on the standings row and another on the
    franchise page.

    ``sd`` is the band unit: this league's OWN realized rating standard
    deviation, derived once per league by
    ``api/app/services/franchise_redesign.py::league_stage_sd`` and floored at
    ``STAGE_SD_FLOOR``. ``None`` — the default — keeps the fixed reference
    unit ``POINTS_PER_SD``, so any caller that has no league to calibrate
    against reads exactly the bands this function has always returned.

    The CENTRE stays ``BASE`` either way, never the league's mean rating. The
    composite is mean-zero by construction, so a league's mean rating is
    already ~1500; it drifts only where the 800-2200 clamp bites (the
    reference league's mean is 1491.8 because one owner is pinned at 2200).
    BASE is the stabler centre, and it keeps the stage rail anchored to the
    same point as the letter scale.

    Like the letter, the stage is a PERCENTILE WITHIN YOUR LEAGUE, not an
    absolute or cross-league scale.
    """
    delta = rating - BASE
    bands = STAGE_BANDS if sd is None else [
        (round(mult * max(float(sd), STAGE_SD_FLOOR)), stage)
        for mult, stage in _STAGE_SD
    ]
    for lo, stage in bands:
        if delta >= lo:
            return stage
    return "Rebuilding"


# A league of identical owners on a real signal (e.g. everyone at 0 trades
# before the season starts) must z-score to exactly 0, not to whatever
# rounding dust `sum(xs) / n` happens to leave behind. `sum([0.3] * 12) / 12`
# is not bit-exact `0.3` under IEEE-754, so `_stats` was returning a spurious
# sd ~5.5e-17 instead of 0.0 for identical inputs, and the downstream
# `z = (raw - mean) / sd` divided one epsilon-scale rounding error by
# another and landed on an arbitrary z around 1.0 (see
# tests/test_gm_rating_guards.py::test_a_league_of_identical_owners_does_not_spread,
# which caught this: a flat twelve-owner league graded 1725, not 1500). The
# floor below must be RELATIVE to the values' own magnitude, not a fixed
# epsilon, because this model's signals span several orders of magnitude in
# the same call (`roster_value_share` ~0.08, `draft_capital` ~30,000) — a
# fixed epsilon that zeroes dust at one scale either misses it at the other
# or swallows real narrow spreads. 1e-9 is ~1e7x looser than float dust
# (~1e-16 relative) and ~1e6x tighter than "a few parts in a thousand" (the
# smallest genuine spread this model is expected to care about), so there is
# room on both sides.
_SD_RELATIVE_FLOOR = 1e-9


def _stats(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n      # population sd
    sd = var ** 0.5
    scale = max((abs(x) for x in xs), default=0.0) or 1.0
    if sd <= _SD_RELATIVE_FLOOR * scale:
        sd = 0.0
    return mean, sd


def _raw(owners: dict, uid: str, pillar: str, sig: str) -> float:
    return float((owners[uid].get(pillar) or {}).get(sig, 0.0) or 0.0)


def compute_gm_ratings(
    owners: dict[str, dict[str, dict[str, float]]],
    *,
    pillar_weights: dict[str, float] | None = None,
    signal_weights: dict[str, dict[str, float]] | None = None,
) -> dict[str, dict]:
    """Three-pillar GM rating with a full transparency breakdown.

    Input: ``uid -> {"outcomes": {sig: raw}, "trade_impact": {...}, "outlook": {...}}``.
    Output: ``uid -> {"rating": int, "pillars": {pillar: {"weight", "z",
    "contribution", "signals": {sig: {"raw", "z", "weight", "contribution"}}}}}``.

    Each signal is z-scored across the league; a pillar's z is the weighted sum of
    its signal z-scores; the composite is the weighted sum of pillar z-scores;
    ``rating = clamp(BASE + SCALE * composite)``. Signal contributions sum (up to
    rounding) to the pillar contribution, and BASE + pillar contributions sum to
    the rating.

    Pass ``pillar_weights`` and ``signal_weights`` to score an alternative tree
    (e.g. the redesign weights). When both are ``None``, behavior is identical to
    the legacy defaults.
    """
    pw = pillar_weights if pillar_weights is not None else PILLAR_WEIGHTS
    sw = signal_weights if signal_weights is not None else SIGNAL_WEIGHTS
    uids = list(owners)
    stats = {
        (pillar, sig): _stats([_raw(owners, u, pillar, sig) for u in uids])
        for pillar, sigs in sw.items()
        for sig in sigs
    }

    out: dict[str, dict] = {}
    for u in uids:
        pillars: dict[str, dict] = {}
        composite = 0.0
        for pillar, w in pw.items():
            pillar_z = 0.0
            signals: dict[str, dict] = {}
            for sig, w2 in sw[pillar].items():
                mean, sd = stats[(pillar, sig)]
                raw = _raw(owners, u, pillar, sig)
                z = 0.0 if sd == 0 else (raw - mean) / sd
                pillar_z += w2 * z
                signals[sig] = {
                    "raw": raw, "z": z, "weight": w2,
                    "contribution": round(SCALE * w * w2 * z),
                }
            pillars[pillar] = {
                "weight": w, "z": pillar_z,
                "contribution": round(SCALE * w * pillar_z),
                "signals": signals,
            }
            composite += w * pillar_z
        rating = round(BASE + SCALE * composite)
        rating = max(CLAMP[0], min(CLAMP[1], rating))
        out[u] = {"rating": rating, "pillars": pillars}
    return out
