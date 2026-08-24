from statistics import pstdev, stdev

import pytest

from app.services.chain_cache import ChainCacheEntry
from app.services.franchise_redesign import (
    LIVE_MODEL, build_v2_pillars, league_stage_sd, live_ratings, stage_by_owner,
)
from sleeper_dynasty.engine.gm_rating import (
    STAGE_SD_FLOOR, V2_PILLAR_WEIGHTS, V2_SIGNAL_WEIGHTS, compute_gm_ratings,
    rating_to_stage,
)


def _entry() -> ChainCacheEntry:
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[
            {"trade": {"transaction_id": "t1", "season": 2024}},
        ],
        grades={"t1": {
            "snapshot_value_swing": {"A": 30.0, "B": -30.0},
            "production_total": {"A": 80.0, "B": 20.0},
        }},
        owners={"A": {}, "B": {}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="2026-06-26T00:00:00Z",
        outcome_signals={
            "A": {"expected_wins": 0.65, "playoff_success": 0.80, "luck": 0.10},
            "B": {"expected_wins": 0.35, "playoff_success": 0.10, "luck": -0.10},
        },
        outlook_signals={
            "A": {"roster_value_share": 0.60, "young_core_share": 0.55, "draft_capital": 0.70},
            "B": {"roster_value_share": 0.40, "young_core_share": 0.20, "draft_capital": 0.30},
        },
        # Both owners have a completed season, so both clear the thin-evidence
        # gate in live_ratings (franchise_redesign.rated_owners).
        season_records={
            "2024": {
                "A": {"wins": 10, "losses": 4, "ties": 0},
                "B": {"wins": 4, "losses": 10, "ties": 0},
            },
        },
    )


def test_build_v2_pillars_shapes_results_and_assets_from_persisted_signals():
    entry = _entry()
    pillars = build_v2_pillars(entry)
    assert set(pillars["A"]) == {"results", "assets"}
    assert set(pillars["A"]["results"]) == {"expected_wins", "playoff_success", "luck"}
    assert set(pillars["A"]["assets"]) == {"roster_value_share", "young_core_share", "draft_capital"}
    assert pillars["A"]["results"]["expected_wins"] == 0.65


def test_live_ratings_uses_v2_dynasty_and_ranks_a_over_b():
    assert LIVE_MODEL == "v2_dynasty"
    entry = _entry()
    out = live_ratings(entry)
    assert set(out["A"]["pillars"]) == {"results", "assets"}
    assert out["A"]["model"] == "v2_dynasty"
    # A is built up everywhere B is down (results + assets both), so A outranks B.
    assert out["A"]["rating"] > out["B"]["rating"]
    # Matches compute_gm_ratings directly under the same tree.
    direct = compute_gm_ratings(
        build_v2_pillars(entry),
        pillar_weights=V2_PILLAR_WEIGHTS["v2_dynasty"],
        signal_weights=V2_SIGNAL_WEIGHTS,
    )
    assert out["A"]["rating"] == direct["A"]["rating"]
    # `live_ratings` adds exactly one thing on top of the raw tree: the
    # read-time `signal_ranks` stamp. Nothing the tree computed may move.
    stripped = {
        p: {k: v for k, v in pd.items() if k != "signal_ranks"}
        for p, pd in out["A"]["pillars"].items()
    }
    assert stripped == direct["A"]["pillars"]
    assert set(out["A"]["pillars"]["assets"]["signal_ranks"]) == {
        "roster_value_share", "young_core_share", "draft_capital"}


# --- league_stage_sd: the ONE derivation of the stage band unit ------------

def test_league_stage_sd_accepts_both_caller_shapes():
    """aggregations holds {uid: int}; grader holds live_ratings' own rows.
    One helper must read both, or the "one derivation" property is a fiction."""
    ints = {"a": 1200, "b": 1400, "c": 1600, "d": 1800}
    rows = {u: {"rating": r, "pillars": {}} for u, r in ints.items()}
    assert league_stage_sd(ints) == league_stage_sd(rows)


def test_league_stage_sd_is_the_population_sd():
    ratings = {"a": 1200, "b": 1400, "c": 1600, "d": 1800}
    expected = pstdev(ratings.values())          # 223.6..., clear of the floor
    assert expected > STAGE_SD_FLOOR
    assert league_stage_sd(ratings) == pytest.approx(expected)
    # Population, NOT sample: stdev() would give 258.2 and widen every band.
    assert league_stage_sd(ratings) != pytest.approx(stdev(ratings.values()))


def test_league_stage_sd_floors_a_flat_league():
    """THE TRAP, at the helper. A league of identical owners has sd 0, and an
    unfloored 0 collapses every band edge to 0 -> everyone grades Dynasty."""
    flat = {u: 1500 for u in "abcdefghijkl"}
    assert pstdev(flat.values()) == 0.0
    assert league_stage_sd(flat) == STAGE_SD_FLOOR
    assert {rating_to_stage(r, sd=league_stage_sd(flat)) for r in flat.values()} == {
        "Competing"}


def test_league_stage_sd_returns_none_when_there_is_no_spread_to_measure():
    """None is 'use the fixed reference bands', which is what one point or no
    points honestly warrants — not a fabricated spread."""
    assert league_stage_sd({}) is None
    assert league_stage_sd({"a": 1500}) is None
    assert league_stage_sd({"a": {"rating": 1500}}) is None
    # A None rating is skipped, not read as 0 (which would invent a huge sd).
    assert league_stage_sd({"a": {"rating": 1500}, "b": {"pillars": {}}}) is None


def test_league_stage_sd_is_idempotent_through_rating_to_stage():
    """The helper floors and rating_to_stage floors again. Double-flooring must
    be a no-op, or the two guards disagree about the unit."""
    for ratings in ({"a": 1500, "b": 1500}, {"a": 1200, "b": 1800}):
        sd = league_stage_sd(ratings)
        assert all(
            rating_to_stage(r, sd=sd) == rating_to_stage(r, sd=max(sd, STAGE_SD_FLOOR))
            for r in range(800, 2201, 13)
        )


# --- stage_by_owner: what the LLM facts packet reads -----------------------

def test_stage_by_owner_bands_on_the_leagues_own_unit(monkeypatch):
    """WIRING. The facts packet's stage must match the screens' exactly — same
    unit, same centre — or the prose puts a different word on a franchise than
    the standings row shows for it.

    Spying on the argument, not comparing outputs: a two-owner fixture lands on
    the same rung under either unit, so an output assertion computed the same
    way the code computes it survives dropping `sd=` entirely. (Verified: that
    mutant lived.)
    """
    import app.services.franchise_redesign as fr

    entry = _entry()
    expected = league_stage_sd(live_ratings(entry))
    assert expected is not None

    seen: list[float | None] = []
    real = fr.rating_to_stage
    monkeypatch.setattr(
        fr, "rating_to_stage",
        lambda rating, *, sd=None: (seen.append(sd), real(rating, sd=sd))[1],
    )
    stages = stage_by_owner(entry)
    assert stages, "no owner was staged — the spy proved nothing"
    assert set(seen) == {expected}, (
        f"packet banded on {set(seen)}, not the league's own unit {expected}")


def test_stage_by_owner_omits_unrated_owners_rather_than_guessing():
    """Absent, not "Rebuilding": an owner with no completed season has no
    stage, and the packet prunes the empty string the caller substitutes."""
    entry = _entry()
    entry.season_records = {}
    assert stage_by_owner(entry) == {}


def test_stage_by_owner_is_the_only_arithmetic_the_packet_needs():
    """Every value is a real rung — no None, no empty string leaking through."""
    stages = stage_by_owner(_entry())
    assert stages
    assert set(stages.values()) <= {
        "Dynasty", "Contending", "Competing", "Retooling", "Rebuilding"}
