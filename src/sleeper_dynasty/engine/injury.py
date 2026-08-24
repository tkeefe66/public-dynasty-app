"""Classify a received player's injury-missed games by phase, over their owned weeks."""

from __future__ import annotations

from typing import Callable


def games_missed_by_phase(
    player_id: str,
    owned_weeks: set[tuple[int, int]],
    played_weeks: set[tuple[int, int]],
    injury_map: dict[tuple[str, int, int], dict],
    phase_fn: Callable[[int, int], str],
) -> dict:
    """A missed-to-injury game = a week the player was on the owner's roster, did NOT play,
    and is injury-flagged. Counted into the week's phase. ``phase_fn(season, week) ->
    'regular'|'playoff'|'toilet'|'dropped'`` (dropped/None weeks are ignored).

    Returns {"games_missed": {regular, playoff, toilet}, "missed_weeks": [((season,week), info)]}.
    """
    counts = {"regular": 0, "playoff": 0, "toilet": 0}
    missed: list[tuple[tuple[int, int], dict]] = []
    for (season, week) in owned_weeks:
        if (season, week) in played_weeks:
            continue
        info = injury_map.get((player_id, season, week))
        if not info or not info.get("missed"):
            continue
        phase = phase_fn(season, week)
        if phase not in counts:
            continue
        counts[phase] += 1
        missed.append(((season, week), info))
    missed.sort(key=lambda m: m[0])
    return {"games_missed": counts, "missed_weeks": missed}
