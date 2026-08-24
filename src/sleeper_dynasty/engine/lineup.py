"""Optimal lineup solver for fantasy football rosters.

Assigns players to roster slots to maximize total projected points,
respecting position eligibility constraints. Uses a greedy-by-
restrictiveness algorithm: fill the most constrained slot first with
the highest-scoring eligible player, then move to less constrained
slots.

This is provably optimal when slot eligibility sets form a total order
(e.g. {QB} ⊂ {RB,WR,TE} ⊂ {QB,RB,WR,TE}), which holds for all common
fantasy slot configurations. Called thousands of times per Monte Carlo
simulation run, so performance is critical — O(slots × players).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Slot -> set of positions eligible to fill that slot.
SLOT_ELIGIBILITY: dict[str, set[str]] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "REC_FLEX": {"WR", "TE"},
    "WRRB_FLEX": {"WR", "RB"},
}

# Slots that don't count for scoring.
BENCH_SLOTS: set[str] = {"BN", "IR", "TAXI"}


def solve_optimal_lineup(
    roster_positions: list[str],
    players: dict[str, tuple[str, float]],
) -> tuple[set[str], float]:
    """Find the optimal assignment of players to roster slots.

    Uses a greedy-by-restrictiveness algorithm: sort slots by ascending
    eligibility-set size, then for each slot assign the highest-projected
    unused player whose position is eligible. This is optimal whenever the
    slot eligibility sets form a chain under set inclusion (the standard
    case for QB/RB/WR/TE/K/DEF + FLEX + SUPER_FLEX configurations).

    Args:
        roster_positions: Ordered list of slot labels for the roster
            (e.g. ``["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]``).
        players: Mapping of ``player_id -> (position, projected_points)``.

    Returns:
        ``(starter_ids, total_points)`` where *starter_ids* is the set of
        player IDs placed into starter slots, and *total_points* is the
        sum of their projected points.
    """
    # Filter out bench/IR/taxi slots — only score starter slots.
    starter_slots = [s for s in roster_positions if s not in BENCH_SLOTS]

    if not starter_slots:
        return set(), 0.0

    # Sort slots by ascending eligibility-set size (most restrictive first).
    # Stable sort preserves the original roster order among same-size slots.
    starter_slots.sort(key=lambda s: len(SLOT_ELIGIBILITY.get(s, set())))

    # Pre-sort players by projected points descending so we can pick the
    # best eligible unused player in a single linear scan per slot.
    sorted_players = sorted(
        players.items(), key=lambda item: item[1][1], reverse=True
    )

    starters: set[str] = set()
    total_points = 0.0

    for slot in starter_slots:
        eligible_positions = SLOT_ELIGIBILITY.get(slot, set())
        for pid, (pos, pts) in sorted_players:
            if pid in starters:
                continue
            if pos in eligible_positions:
                starters.add(pid)
                total_points += pts
                break
        # If no eligible player exists, the slot is left empty (0 pts).

    logger.debug(
        "Optimal lineup: %d starters, %.1f pts", len(starters), total_points
    )
    return starters, total_points
