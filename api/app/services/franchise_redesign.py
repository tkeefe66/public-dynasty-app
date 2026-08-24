"""v2 Franchise-Rating assembly: 0.60 * Results + 0.40 * Assets (no Skill pillar).

Kept separate from leaderboard.py/aggregations.py so the live read path is
untouched while the tree itself is defined here. Reads only persisted
ChainCacheEntry fields — v2 needs no per-trade derivation at all, unlike the
v1 Skill pillar it replaced, which read ``entry.grades`` to build zero-sum
trade-value/production signals.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.aggregations import Year
from app.services.chain_cache import ChainCacheEntry
from sleeper_dynasty.engine.gm_rating import (
    STAGE_SD_FLOOR, V2_KEEPER_SIGNAL_WEIGHTS, V2_PILLAR_WEIGHTS,
    V2_REDRAFT_SIGNAL_WEIGHTS, V2_SIGNAL_WEIGHTS, compute_gm_ratings,
    rating_to_stage,
)
from sleeper_dynasty.engine.results_signals import owners_with_completed_season

LIVE_MODEL = "v2_dynasty"
_MODEL_BY_FORMAT = {"keeper": "v2_keeper", "redraft": "v2_redraft"}
_SIGNALS_BY_MODEL = {
    "v2_dynasty": V2_SIGNAL_WEIGHTS,
    "v2_keeper": V2_KEEPER_SIGNAL_WEIGHTS,
    "v2_redraft": V2_REDRAFT_SIGNAL_WEIGHTS,
}


def model_for(entry: ChainCacheEntry) -> str:
    """Which weight tree this league scores under, from its capabilities.

    Pre-feature cache entries have empty capabilities, which read as full
    dynasty -> v2_dynasty. So existing leagues are unaffected.
    """
    from sleeper_dynasty.engine.capabilities import capabilities_from_dict
    caps = capabilities_from_dict(entry.capabilities)
    return _MODEL_BY_FORMAT.get(caps.format, LIVE_MODEL)


def rated_owners(entry: ChainCacheEntry) -> list[str]:
    """The owners this league may grade: those with a completed season behind
    them, in the entry's own owner order.

    ``entry.season_records`` is the existing record of who played what — the
    Track Record tab already renders it — so the gate reads it rather than
    inventing a second source that could disagree with the page.

    Everyone else is excluded from the *population*, not merely from the
    display. ``results_signals`` emits ``0.0`` for an owner with no rows, and
    on ``expected_wins`` that means "lost every all-play matchup in every week
    of every season", not "unknown": left in, one such owner drags the league
    mean and inflates the sd enough to move every real grade a band or two.
    """
    played = owners_with_completed_season(
        {int(season): rows for season, rows in (entry.season_records or {}).items()}
    )
    return [uid for uid in entry.owners if uid in played]


def build_v2_pillars(
    entry: ChainCacheEntry, owners: list[str] | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    """uid -> {"results", "assets"} signal sub-dicts for compute_gm_ratings.

    Both sub-dicts are read straight off the persisted signal dicts. v2 needs
    no per-trade derivation at all — the Skill pillar it replaced was the only
    thing that did, which is why `trade_skill_signals` and the year filter are
    gone from this module.

    ``owners`` defaults to every owner on the entry; ``live_ratings`` narrows
    it to ``rated_owners`` so the z population carries no thin-evidence zeros.
    """
    owners = list(entry.owners) if owners is None else list(owners)
    outcomes = entry.outcome_signals or {}
    outlook = entry.outlook_signals or {}
    out: dict[str, dict[str, dict[str, float]]] = {}
    for uid in owners:
        oc = outcomes.get(uid, {})
        ol = outlook.get(uid, {})
        out[uid] = {
            "results": {
                "expected_wins": float(oc.get("expected_wins") or 0.0),
                "playoff_success": float(oc.get("playoff_success") or 0.0),
                "luck": float(oc.get("luck") or 0.0),
            },
            "assets": {
                "roster_value_share": float(ol.get("roster_value_share") or 0.0),
                "young_core_share": float(ol.get("young_core_share") or 0.0),
                "draft_capital": float(ol.get("draft_capital") or 0.0),
            },
        }
    return out


def live_ratings(entry: ChainCacheEntry, *, year: Year = "all") -> dict[str, dict]:
    """The live Franchise Rating under this league's v2 tree.

    ``year`` is retained only for call-site compatibility with the leaderboard
    and season-rating callers — v2's signals are all-time-only (no per-trade
    skill signal left to scope to a season), so it is unused here.

    Returns ``{}`` when nobody qualifies. An owner absent from the result is
    unrated, and every surface renders that as an absence (a caption or an em
    dash), never as a letter.
    """
    # Both pillars come from these two dicts, and the refresh stage that fills
    # them is wrapped in a try/except. Empty means the stage failed, not that
    # the league is flat: scoring it anyway puts every owner at exactly 1500
    # and stamps the whole league a C. Render the absence instead — the same
    # mechanism the thin-evidence gate below uses.
    if not (entry.outcome_signals or entry.outlook_signals):
        return {}
    owners = rated_owners(entry)
    if not owners:
        return {}
    model = model_for(entry)
    out = compute_gm_ratings(
        build_v2_pillars(entry, owners),
        pillar_weights=V2_PILLAR_WEIGHTS[model],
        signal_weights=_SIGNALS_BY_MODEL[model],
    )
    for row in out.values():
        row["model"] = model
    _stamp_signal_ranks(out)
    return out


def league_stage_sd(ratings: Mapping[str, Any]) -> float | None:
    """This league's competitive-stage band unit, in rating points.

    The population standard deviation of the league's own realized ratings,
    floored at ``STAGE_SD_FLOOR`` (see the comment on that constant — the floor
    is what stops a flat league grading every owner "Dynasty"). Feed the result
    straight to ``rating_to_stage(rating, sd=...)``.

    Accepts either shape the callers already hold: ``live_ratings``' own output
    (``uid -> {"rating": int, ...}``) or a plain ``uid -> rating`` map.

    THIS IS THE ONLY PLACE THE UNIT IS DERIVED, deliberately. Three surfaces
    render a stage — the standings row, the owner page, and the LLM facts
    packet — and the whole point of banding the stage off the Franchise Rating
    was deleting a second model that could disagree with the first. Three
    copies of this arithmetic would rebuild that problem in miniature.

    Returns ``None`` when there is nothing to measure (fewer than two rated
    owners): one point has no spread, and ``None`` is exactly what
    ``rating_to_stage`` reads as "use the fixed reference bands". Note a
    single-owner league z-scores to BASE anyway, so the two agree there.
    """
    vals: list[float] = []
    for r in ratings.values():
        if isinstance(r, Mapping):
            r = r.get("rating")
        if r is None:
            continue
        vals.append(float(r))
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)   # population sd
    return max(var ** 0.5, STAGE_SD_FLOOR)


def stage_by_owner(entry: ChainCacheEntry) -> dict[str, str]:
    """Every rated owner's competitive stage, banded on this league's own unit.

    ``uid -> "Dynasty" | "Contending" | "Competing" | "Retooling" |
    "Rebuilding"``. An owner absent from ``live_ratings`` (no completed season)
    is absent here too — callers render that absence, never a stage.

    The LLM facts packet's entry point. It exists so the packet reads the same
    two-line derivation the screens do rather than repeating it inline, where
    dropping the ``sd=`` would be invisible to every test.
    """
    ratings = live_ratings(entry)
    sd = league_stage_sd(ratings)
    return {
        uid: rating_to_stage(row["rating"], sd=sd) for uid, row in ratings.items()
    }


def _stamp_signal_ranks(out: dict[str, dict]) -> None:
    """Rank every owner on every signal's RAW value, 1 = best (highest raw).

    Mutates ``out`` in place, on the same dicts ``compute_gm_ratings`` returned,
    so the rank travels with the breakdown it describes and cannot be paired
    with the wrong owner downstream.

    Ties share the lower (better) rank and the next rank is skipped, the way a
    finishing order reads. Read-time only.
    """
    if not out:
        return
    first = next(iter(out.values()))["pillars"]
    for pillar in first:
        for sig in first[pillar]["signals"]:
            ordered = sorted(
                out,
                key=lambda u: out[u]["pillars"][pillar]["signals"][sig]["raw"],
                reverse=True,
            )
            rank = 0
            prev_raw = None
            for i, uid in enumerate(ordered):
                raw = out[uid]["pillars"][pillar]["signals"][sig]["raw"]
                if raw != prev_raw:
                    rank = i + 1
                    prev_raw = raw
                out[uid]["pillars"][pillar].setdefault(
                    "signal_ranks", {})[sig] = rank
