"""Invariants that a weight change must not break.

These exist because v1 shipped three separate fixes that were each cancelled
by the layer beneath them. A guard that cannot fail is worse than no guard, so
each of these is written to actually go red on the mistake it names.
"""

import statistics

import pytest

from sleeper_dynasty.engine.gm_rating import (
    BASE, V2_PILLAR_WEIGHTS, V2_SIGNAL_WEIGHTS, compute_gm_ratings,
)


def _league(n: int = 12) -> dict:
    """n owners with spread-out, deterministic signal values."""
    return {
        f"u{i}": {
            "results": {
                "expected_wins": 0.30 + 0.04 * i,
                "playoff_success": float(i % 5),
                "luck": 0.05 - 0.01 * (i % 7),
            },
            "assets": {
                "roster_value_share": 0.05 + 0.005 * i,
                "young_core_share": 0.20 + 0.03 * (i % 6),
                "draft_capital": 20_000.0 + 900.0 * (i % 8),
            },
        }
        for i in range(n)
    }


def _rate():
    return compute_gm_ratings(
        _league(), pillar_weights=V2_PILLAR_WEIGHTS["v2_dynasty"],
        signal_weights=V2_SIGNAL_WEIGHTS)


def test_signal_contributions_sum_to_their_pillar():
    # OverviewTab reconciles 1500 + sum(contributions) against the rating on
    # screen and shows a visible "gap" note when they disagree.
    for row in _rate().values():
        for pillar in row["pillars"].values():
            total = sum(s["contribution"] for s in pillar["signals"].values())
            assert abs(total - pillar["contribution"]) <= 1


def test_base_plus_pillar_contributions_equals_the_rating():
    for row in _rate().values():
        total = BASE + sum(p["contribution"] for p in row["pillars"].values())
        assert abs(total - row["rating"]) <= 2


def test_realized_pillar_variance_share_matches_the_stated_weight():
    rows = _rate()
    uids = list(rows)
    composite = [rows[u]["rating"] - BASE for u in uids]
    var = statistics.pvariance(composite)
    for pillar, weight in V2_PILLAR_WEIGHTS["v2_dynasty"].items():
        contrib = [rows[u]["pillars"][pillar]["contribution"] for u in uids]
        mc = statistics.mean(contrib)
        mk = statistics.mean(composite)
        cov = sum((a - mc) * (b - mk) for a, b in zip(contrib, composite)) / len(uids)
        share = cov / var
        # Convention: share = cov(pillar_contribution, composite) / var(composite).
        # Loose bound - the point is to catch a pillar that has silently become
        # twice or half its stated influence, not to pin a decimal.
        assert weight - 0.20 <= share <= weight + 0.20, (pillar, share)


def test_a_league_of_identical_owners_does_not_spread():
    flat = {f"u{i}": _league(1)["u0"] for i in range(12)}
    rows = compute_gm_ratings(
        flat, pillar_weights=V2_PILLAR_WEIGHTS["v2_dynasty"],
        signal_weights=V2_SIGNAL_WEIGHTS)
    assert {r["rating"] for r in rows.values()} == {BASE}


def test_a_small_but_real_difference_still_separates():
    # The complement of the identical-owners guard above: the relative sd
    # floor in _stats() must not be loose enough to also flatten a genuine,
    # narrow spread. One owner is perturbed by 0.3% of the signal's own
    # scale -- far above float dust (~1e-16 relative) and far above the
    # 1e-9 relative floor, but small in absolute terms -- at two very
    # different magnitudes (expected_wins ~0.3, draft_capital ~20,000) so
    # the RELATIVE-ness of the floor is what's pinned, not one lucky
    # constant at one scale.
    base = _league(1)["u0"]
    flat = {f"u{i}": {
        "results": dict(base["results"]),
        "assets": dict(base["assets"]),
    } for i in range(12)}
    flat["u0"] = {
        "results": {
            **base["results"],
            "expected_wins": base["results"]["expected_wins"] * 1.003,
        },
        "assets": {
            **base["assets"],
            "draft_capital": base["assets"]["draft_capital"] * 1.003,
        },
    }
    rows = compute_gm_ratings(
        flat, pillar_weights=V2_PILLAR_WEIGHTS["v2_dynasty"],
        signal_weights=V2_SIGNAL_WEIGHTS)
    assert rows["u0"]["pillars"]["results"]["signals"]["expected_wins"]["z"] != 0.0
    assert rows["u0"]["pillars"]["assets"]["signals"]["draft_capital"]["z"] != 0.0
    assert rows["u0"]["rating"] != rows["u1"]["rating"]
