"""Points Above Round — how much more a pick returned than its round's average.

Ranking a draft class by raw Total Points ranks draft POSITION: whoever picked
first tends to win, which is not a measure of anything the owner did. PAR
subtracts what a pick in the same round of the same class typically returned,
so it is **zero-sum within a class** and rewards drafting well from a bad slot.

Round-average rather than a per-slot expectation curve: with one observation
per slot, "the average at that slot" is that pick itself and every delta
collapses to zero. Rounds give a real sample. It is also the grouping
``build_drafted_pick_results`` already uses for ``avg_slot_value``.

Keepers and auction picks are excluded from BOTH the average and the sum — a
keep is not a draft decision, and an auction's ``pick_no`` is the order money
changed hands. Leaving either in would move the yardstick every real pick is
measured against.

Pure. No I/O.
"""

from __future__ import annotations

from collections import defaultdict


def _scored(rows: list[dict]) -> list[dict]:
    """Only picks this draft is answerable for.

    ``gradeable`` is absent on pre-feature rows, which predate auction support
    and were all snake/linear — default True rather than silently emptying them.
    """
    return [r for r in rows
            if not r.get("is_keeper") and r.get("gradeable", True)]


def round_averages(rows: list[dict]) -> dict[int, float]:
    """``{round: mean production_total}`` over scored picks.

    A round with no scored picks is absent rather than 0.0 — there is no
    yardstick for it, and 0.0 would read as one.
    """
    by_round: dict[int, list[float]] = defaultdict(list)
    for r in _scored(rows):
        by_round[int(r.get("round") or 0)].append(
            float(r.get("production_total") or 0.0))
    return {rnd: sum(v) / len(v) for rnd, v in by_round.items() if v}


def pick_par(row: dict, averages: dict[int, float]) -> float:
    """One pick's production minus its own round's average.

    A round absent from ``averages`` yields 0.0: the pick is unmeasured, and
    crediting or debiting it against a yardstick that does not exist would be
    an invention.
    """
    rnd = int(row.get("round") or 0)
    if rnd not in averages:
        return 0.0
    return float(row.get("production_total") or 0.0) - averages[rnd]


def points_above_round(rows: list[dict]) -> dict[str, float]:
    """``{drafter_id: summed PAR}`` over scored picks. Sums to ~0 per class."""
    averages = round_averages(rows)
    out: dict[str, float] = defaultdict(float)
    for r in _scored(rows):
        uid = str(r.get("drafter_id") or "")
        if not uid:
            continue
        out[uid] += pick_par(r, averages)
    return dict(out)
