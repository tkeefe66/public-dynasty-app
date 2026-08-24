"""The "became" grade — value + production of a trade's terminal players.

Parallel to the direct grade in ``engine/trade_grader.py``: where the direct
grade scores what each side *received*, the became-grade scores what that haul
ultimately *became* under the bounded lineage walk (``engine/lineage.py``):

  - a received player follows exactly one flip (its result players are terminal);
  - a pick is followed through every flip/draft until it becomes players;
  - derived players are terminal (never followed).

Each terminal player is valued at current KTC and scored for the points he put
up *while this side owned him* (the same matchup walk
``grade_hindsight_production`` uses, anchored on the terminal player and this
side's ownership weeks). A terminal branch that still ends on an undrafted pick
is valued at the round-level pick table, with zero production.

Per-side totals (NOT a zero-sum swing): "what your haul became."
"""

from __future__ import annotations

import logging
from typing import Any

from sleeper_dynasty.engine.lineage import terminal_assets
from sleeper_dynasty.models.player import KTCValue

log = logging.getLogger(__name__)


def _from_ktc(v: KTCValue | None, fmt: str) -> float:
    if v is None:
        return 0.0
    raw = v.superflex_value if fmt == "superflex" else v.one_qb_value
    return float(raw) if raw is not None else 0.0


def _is_post_trade(
    league_id: str,
    week: int,
    trade: dict,
    league_season_by_id: dict[str, int],
) -> bool:
    """True if (league_id, week) is strictly after the trade's (season, week).

    Mirrors ``trade_grader._is_post_trade`` for the dict-form trade. The trade
    week itself is excluded — Sleeper trades take effect the following week.
    """
    trade_season = trade["season"]
    trade_week = trade["week"]
    matchup_season = league_season_by_id.get(league_id)
    if matchup_season is None:
        return league_id == trade["league_id"] and week > trade_week
    if matchup_season > trade_season:
        return True
    if matchup_season < trade_season:
        return False
    return week > trade_week


def _production_while_owned(
    pid: str,
    uid: str,
    *,
    trade: dict,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    league_season_by_id: dict[str, int],
    starters_only: bool,
    phase_filter: str | None = None,
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
) -> float:
    """Sum points pid scored on uid's roster, post the (root) trade.

    The same matchup walk ``grade_hindsight_production`` does, but anchored on a
    single terminal player and a single owner (no phantom-given subtraction —
    the became-grade is a per-side total, not a swing).

    ``phase_filter`` gates on a bracket phase: None (all weeks), "regular",
    "playoff", or "toilet".  Requires ``phase_by_lwr`` and
    ``playoff_week_start_by_league`` when set.
    """
    phase_by_lwr = phase_by_lwr or {}
    playoff_week_start_by_league = playoff_week_start_by_league or {}
    roster_field = "starters" if starters_only else "players"
    total = 0.0
    for (lg, wk, rid), entry in matchups.items():
        if not _is_post_trade(lg, wk, trade, league_season_by_id):
            continue
        if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
            continue
        if phase_filter:
            ps = playoff_week_start_by_league.get(lg, 15)
            phase = "regular" if wk < ps else phase_by_lwr.get((lg, wk, rid), "dropped")
            if phase != phase_filter:
                continue
        if pid not in (entry.get(roster_field) or []):
            continue
        total += float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
    return total


def build_became_grade(
    trade: dict,
    resolved_trades: list[dict],
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
    league_season_by_id: dict[str, int] | None = None,
    ktc_values: dict[str, KTCValue],
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
    fmt: str = "superflex",
) -> dict[str, dict[str, Any]]:
    """Per-side became-grade for one trade.

    Returns ``{user_id: {"ktc", "production", "regular", "playoff", "toilet",
    "terminal_labels"}}``.

    - ``production``: bench-inclusive total across all weeks.
    - ``regular``: started points, regular-season weeks only.
    - ``playoff``: started points, playoff-bracket weeks only.
    - ``toilet``: started points, toilet-bracket weeks only.
    """
    league_season_by_id = league_season_by_id or {}
    pick_values = pick_values or {}
    root_trade = trade["trade"]
    terms = terminal_assets(resolved_trades, root_trade["transaction_id"])

    out: dict[str, dict[str, Any]] = {}
    for uid, assets in terms.items():
        ktc = 0.0
        production = regular = playoff = toilet = 0.0
        labels: list[str] = []
        rows: list[dict[str, Any]] = []
        for a in assets:
            labels.append(a["label"])
            if a["kind"] == "player":
                pid = a["player_id"]
                v = ktc_values.get(pid)
                if v is None:
                    log.warning("became: no KTC value for terminal player %s", pid)
                a_ktc = _from_ktc(v, fmt)
                common = dict(
                    trade=root_trade, matchups=matchups,
                    roster_to_user_by_league=roster_to_user_by_league,
                    league_season_by_id=league_season_by_id,
                    phase_by_lwr=phase_by_lwr,
                    playoff_week_start_by_league=playoff_week_start_by_league,
                )
                p_total = _production_while_owned(pid, uid, starters_only=False, phase_filter=None, **common)
                p_started = _production_while_owned(pid, uid, starters_only=True, phase_filter=None, **common)
                p_reg = _production_while_owned(pid, uid, starters_only=True, phase_filter="regular", **common)
                p_ply = _production_while_owned(pid, uid, starters_only=True, phase_filter="playoff", **common)
                p_toi = _production_while_owned(pid, uid, starters_only=True, phase_filter="toilet", **common)
                ktc += a_ktc
                production += p_total
                regular += p_reg
                playoff += p_ply
                toilet += p_toi
                rows.append({
                    "label": a["label"], "kind": "player", "player_id": pid,
                    "ktc": a_ktc, "production_total": p_total,
                    "production_started": p_started,
                    "production_regular": p_reg, "production_playoff": p_ply,
                    "production_toilet": p_toi,
                })
            else:  # undrafted pick: value only
                a_ktc = _from_ktc(pick_values.get((a["season"], a["round"])), fmt)
                ktc += a_ktc
                rows.append({
                    "label": a["label"], "kind": "pick", "player_id": None,
                    "ktc": a_ktc, "production_total": 0.0, "production_regular": 0.0,
                    "production_playoff": 0.0, "production_toilet": 0.0,
                })
        out[uid] = {
            "ktc": ktc,
            "production": production,
            "regular": regular,
            "playoff": playoff,
            "toilet": toilet,
            "terminal_labels": labels,
            "breakdown": rows,
        }
    return out
