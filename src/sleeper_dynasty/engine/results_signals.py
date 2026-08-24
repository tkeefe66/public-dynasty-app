"""The Results pillar: luck-adjusted winning, recency-weighted.

Three signals replace the five that v1 used. Four of those five
(``championships``, ``playoff_depth``, ``made_playoffs``, ``final_seed``)
encoded one binary — did you make the playoffs — and correlated pairwise at
r +0.61 to +0.91, so an owner who never made the field was charged for it four
times. Here the berth is worth half a round win inside one signal, and
``points_for_rank`` is subsumed by ``expected_wins``, which measures the same
scoring quality at weekly rather than seasonal resolution.

Pure: no I/O, no clock.
"""

from __future__ import annotations

HALF_LIFE_SEASONS = 2.0

# A season needs this many completed games before it can anchor the decay.
# Without it the whole chain re-anchors in week 2 of a new season and every
# owner's grade jumps for reasons unrelated to their play.
MIN_ANCHOR_WEEKS = 4

BERTH_CREDIT = 0.5
ROUND_CREDIT = 1.0
TITLE_CREDIT = 1.5


def season_weight(
    season: int, latest_played_season: int, half_life: float = HALF_LIFE_SEASONS
) -> float:
    """Recency weight for one season, halving every ``half_life`` seasons.

    Clamped at 1.0. A season *ahead* of the anchor — a rookie class already
    drafted for a season nobody has played — must never outweigh the anchor.
    """
    return min(1.0, 0.5 ** ((latest_played_season - season) / half_life))


def decayed_mean(by_season: dict[int, float], latest_played_season: int) -> float:
    """Recency-weighted mean of a per-season quantity. Empty -> 0.0."""
    num = 0.0
    den = 0.0
    for season, value in by_season.items():
        w = season_weight(int(season), latest_played_season)
        num += w * float(value)
        den += w
    return (num / den) if den else 0.0


def _games(rec: dict) -> int:
    return int(rec.get("wins", 0)) + int(rec.get("losses", 0)) + int(rec.get("ties", 0))


def latest_played_season(
    season_records: dict[int, dict[str, dict]], min_weeks: int = MIN_ANCHOR_WEEKS
) -> int | None:
    """The most recent season with real games behind it, or None.

    None means the league has played nothing yet; callers must render an
    absence rather than grade it.
    """
    played = [
        int(season)
        for season, rows in season_records.items()
        if any(_games(rec) >= min_weeks for rec in rows.values())
    ]
    return max(played) if played else None


def owners_with_completed_season(
    season_records: dict[int, dict[str, dict]], min_weeks: int = MIN_ANCHOR_WEEKS
) -> set[str]:
    """Owners with real games behind them — the only ones a rating may describe.

    Shares ``min_weeks`` with ``latest_played_season`` on purpose: a season too
    thin to anchor the decay is also too thin to grade an owner on. An owner
    outside this set has no Results evidence at all, and a ``0.0`` on
    ``expected_wins`` would read as "lost every all-play matchup", not
    "unknown" — so callers must drop them from the rating (and from the z
    population, which their zeros would otherwise skew for everyone else)
    rather than grade them.
    """
    return {
        uid
        for rows in season_records.values()
        for uid, rec in rows.items()
        if _games(rec) >= min_weeks
    }


def _win_pct(rec: dict) -> float:
    n = _games(rec)
    if not n:
        return 0.0
    return (int(rec.get("wins", 0)) + 0.5 * int(rec.get("ties", 0))) / n


def _playoff_points(rec: dict) -> float:
    return (
        (BERTH_CREDIT if rec.get("made_playoffs") else 0.0)
        + ROUND_CREDIT * float(rec.get("rounds_won", 0) or 0)
        + (TITLE_CREDIT if rec.get("champion") else 0.0)
    )


def results_signals(
    *,
    all_play_by_season: dict[int, dict[str, float]],
    season_records: dict[int, dict[str, dict]],
    owners: list[str],
    latest_played_season: int,
) -> dict[str, dict[str, float]]:
    """uid -> {expected_wins, playoff_success, luck}, each recency-weighted.

    ``luck`` is ``actual_wins - expected_wins`` and is therefore orthogonal to
    ``expected_wins`` by construction. It replaces raw ``actual_wins``, which
    was expected wins plus schedule noise and re-injected the very thing the
    pillar exists to remove.
    """
    out: dict[str, dict[str, float]] = {}
    for uid in owners:
        expected: dict[int, float] = {}
        actual: dict[int, float] = {}
        playoff: dict[int, float] = {}
        for season, rows in season_records.items():
            rec = rows.get(uid)
            if rec is None or _games(rec) == 0:
                continue
            s = int(season)
            actual[s] = _win_pct(rec)
            playoff[s] = _playoff_points(rec)
            ap = (all_play_by_season.get(s) or {}).get(uid)
            if ap is not None:
                expected[s] = float(ap)

        exp = decayed_mean(expected, latest_played_season)
        act = decayed_mean(actual, latest_played_season)
        out[uid] = {
            "expected_wins": exp,
            "playoff_success": decayed_mean(playoff, latest_played_season),
            "luck": act - exp,
        }
    return out
