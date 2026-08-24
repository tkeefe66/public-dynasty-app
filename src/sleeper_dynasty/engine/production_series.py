"""Pure helpers behind the production-over-tenure timeline.

The production analog of ``value_series``'s pure math. Callers (the grader) build
per-(season, week) point dicts via ``trade_grader.player_week_points`` and use these
to align them to a shared calendar axis and accumulate them. Dependency-free and
trivially testable. ``WeekKey`` is ``(season, week)``; the global axis is the sorted
union of weeks present in the chain's matchups.
"""

from __future__ import annotations

WeekKey = tuple[int, int]

# metric -> (starters_only, phase_filter) for trade_grader.player_week_points.
METRIC_GATES: dict[str, tuple[bool, str | None]] = {
    "started": (True, None),
    "total": (False, None),
    "regular": (True, "regular"),
    "playoff": (True, "playoff"),
    "toilet": (True, "toilet"),
}


def week_axis(
    matchups: dict[tuple[str, int, int], dict],
    league_season_by_id: dict[str, int],
) -> list[WeekKey]:
    """Sorted unique ``(season, week)`` across all matchup entries."""
    keys = {
        (league_season_by_id.get(lg, 0), wk)
        for (lg, wk, _rid) in matchups
    }
    return sorted(keys)


def cumulative(week_points: dict[WeekKey, float], axis: list[WeekKey]) -> list[tuple[WeekKey, float]]:
    """Running total of ``week_points`` over ``axis``; flat across weeks with no points."""
    running = 0.0
    out: list[tuple[WeekKey, float]] = []
    for wk in axis:
        running += week_points.get(wk, 0.0)
        out.append((wk, running))
    return out


def merge_week_points(dicts: list[dict[WeekKey, float]]) -> dict[WeekKey, float]:
    """Element-wise sum of per-week point dicts."""
    out: dict[WeekKey, float] = {}
    for d in dicts:
        for wk, pts in d.items():
            out[wk] = out.get(wk, 0.0) + pts
    return out


MIN_GAMES_FOR_VERDICT = 3
# A margin under this fraction of the leader's total reads as "dead even".
_EVEN_FRACTION = 0.02

_METRIC_NOUN = {
    "started": "started points",
    "total": "total points",
    "regular": "regular-season points",
    "playoff": "playoff points",
    "toilet": "toilet-bowl points",
}


def _too_early(metric: str, extra: dict) -> dict:
    return {
        "label": "Too early.",
        "sentence": f"Too early to tell — not enough games yet to judge {_METRIC_NOUN[metric]}.",
        "tone": "neutral",
        **extra,
    }


def head_to_head_verdict(
    *,
    totals: dict[str, float],
    n_games: int,
    metric: str,
    names: dict[str, str] | None = None,
) -> dict:
    """Who won the production battle for one trade, on one metric.

    ``totals`` is uid -> final cumulative points. Returns
    ``{"label", "sentence", "tone", "winner_uid", "totals"}``.
    """
    names = names or {}
    base = {"winner_uid": None, "totals": {u: float(v) for u, v in totals.items()}}
    if n_games < MIN_GAMES_FOR_VERDICT or not totals:
        return _too_early(metric, base)
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    (top_uid, top_val) = ranked[0]
    runner_val = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = top_val - runner_val
    noun = _METRIC_NOUN[metric]
    if top_val <= 0 or margin < _EVEN_FRACTION * (top_val or 1):
        return {
            "label": "Dead even.",
            "sentence": f"Both sides have produced about the same {noun} so far.",
            "tone": "neutral", **base,
        }
    name = names.get(top_uid, "One side")
    big = margin >= 0.25 * top_val
    return {
        "label": "Won the production battle." if not big else "Lopsided.",
        "sentence": f"{name} is ahead by {round(margin):,} {noun}.",
        "tone": "good",
        "winner_uid": top_uid,
        "totals": base["totals"],
    }


def aggregate_production_verdict(
    *,
    received_total: float,
    given_total: float,
    n_games: int,
    metric: str,
    n_trades: int = 0,
) -> dict:
    """Owner-wide: did their hauls out-produce what they shipped out, on one metric.

    Returns ``{"label", "sentence", "tone", "received_total", "given_total"}``.
    """
    base = {"received_total": float(received_total), "given_total": float(given_total)}
    if n_games < MIN_GAMES_FOR_VERDICT:
        return _too_early(metric, base)
    margin = received_total - given_total
    noun = _METRIC_NOUN[metric]
    trades = f"{n_trades} trade{'s' if n_trades != 1 else ''}"
    if abs(margin) < _EVEN_FRACTION * (max(received_total, given_total) or 1):
        return {
            "label": "Break-even.",
            "sentence": f"Across {trades}, your hauls have produced about as much {noun} as what you shipped out.",
            "tone": "neutral", **base,
        }
    if margin > 0:
        return {
            "label": "Net positive.",
            "sentence": f"Across {trades}, your hauls have produced +{round(margin):,} {noun} more than what you shipped out.",
            "tone": "good", **base,
        }
    return {
        "label": "Net negative.",
        "sentence": f"Across {trades}, what you shipped out has produced {round(abs(margin)):,} more {noun} than your hauls.",
        "tone": "bad", **base,
    }
