"""Build an OwnerRatingFacts packet from a single owner's per-scope pillar
breakdown (the same numbers the /gm panel renders), plus non-scoring career
facts (championships, made-playoffs rate) sourced separately from the
persisted outcome_signals rollup — see build_owner_rating_facts."""

from __future__ import annotations

from typing import Any

from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts

PILLAR_LABELS = {
    "results": "Results",
    "assets": "Assets",
}
# The v2 tree's six signal keys, exactly as engine/gm_rating.py's
# V2_SIGNAL_WEIGHTS emits them. Labels match the web side's OverviewTab
# vocabulary (furniture-styling) so a signal never carries two names for the
# same number between the LLM prompt and the page.
SIGNAL_LABELS = {
    "expected_wins": "Expected Wins", "playoff_success": "Playoff Success",
    "luck": "Close Games",
    "roster_value_share": "Roster Value", "young_core_share": "Young Core",
    "draft_capital": "Draft Capital",
}
_PILLAR_ORDER = ["results", "assets"]


def _labeled(signals: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"label": SIGNAL_LABELS.get(k, k), "contribution": int(s["contribution"])}
        for k, s in signals.items()
    ]


def build_owner_rating_facts(
    *,
    scope_label: str,
    owner_name: str,
    team_name: str | None,
    rank: int,
    rating: int,
    pillars: dict[str, dict[str, Any]],
    outcome_signals: dict[str, float] | None = None,
) -> OwnerRatingFacts:
    pillar_facts: list[dict[str, Any]] = []
    for pk in _PILLAR_ORDER:
        p = pillars.get(pk)
        if not p:
            continue
        labeled = _labeled(p.get("signals", {}))
        top = sorted(
            (s for s in labeled if s["contribution"] > 0),
            key=lambda s: s["contribution"], reverse=True,
        )[:3]
        worst = sorted(
            (s for s in labeled if s["contribution"] < 0),
            key=lambda s: s["contribution"],
        )[:2]
        pillar_facts.append({
            "label": PILLAR_LABELS.get(pk, pk),
            "weight": round(float(p["weight"]), 2),
            "contribution": int(p["contribution"]),
            "top_signals": top,
            "worst_signals": worst,
        })

    # championships/made_playoffs were dropped from the v2 Results signal set
    # (engine/gm_rating.py's V2_SIGNAL_WEIGHTS carries only expected_wins/
    # playoff_success/luck) but deliberately kept in the persisted
    # outcome_signals rollup for non-scoring consumers like this one. Read
    # them from there, not from the pillar breakdown, and never re-add them
    # to a scoring tree. This is this owner's flat outcome-signal dict
    # (uid already resolved by the caller), so a missing/absent owner is
    # just an empty dict rather than a KeyError.
    outcome = outcome_signals or {}
    champs = int(outcome.get("championships") or 0)
    made_rate = float(outcome.get("made_playoffs") or 0.0)

    return OwnerRatingFacts(
        user_id="",  # filled by the caller if needed; not used by the writer
        owner_name=owner_name,
        team_name=team_name,
        scope_label=scope_label,
        rank=rank,
        rating=rating,
        pillars=pillar_facts,
        championships=champs,
        made_playoffs_rate=made_rate,
        draft_capital_counted=True,
    )
