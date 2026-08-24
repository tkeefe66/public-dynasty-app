"""NFL-wide weekly actuals: score any player's week to the league, and sum a
dropped player's production over a rolling post-drop window. Pure — no I/O."""

from __future__ import annotations

from sleeper_dynasty.api.projections import normalize_projection


def score_week(
    raw_stats: dict[str, dict], scoring: dict[str, float]
) -> dict[str, float]:
    """{player_id: league fantasy points} for one NFL week's stats.

    `raw_stats` is Sleeper's per-week stats keyed by player_id:
    {player_id: {stat: value}}. Players with empty/missing stats are skipped.
    """
    out: dict[str, float] = {}
    for pid, stats in (raw_stats or {}).items():
        if not pid or not stats:
            continue
        out[pid] = normalize_projection(stats, scoring)
    return out


def next_n_weeks(
    start: tuple[int, int], n: int, weeks_per_season: int = 18
) -> list[tuple[int, int]]:
    """The n (season, week) keys strictly after `start`, rolling across the
    season boundary (after (Y, weeks_per_season) comes (Y+1, 1))."""
    out: list[tuple[int, int]] = []
    season, week = start
    for _ in range(n):
        week += 1
        if week > weeks_per_season:
            season += 1
            week = 1
        out.append((season, week))
    return out


def points_after_drop(
    pid: str,
    last_week: tuple[int, int],
    nfl_points: dict[tuple[int, int], dict[str, float]],
    window: int = 10,
) -> float:
    """League points `pid` scored over the `window` NFL weeks after `last_week`."""
    total = 0.0
    for wk in next_n_weeks(last_week, window):
        total += float((nfl_points.get(wk) or {}).get(pid) or 0.0)
    return round(total, 2)
