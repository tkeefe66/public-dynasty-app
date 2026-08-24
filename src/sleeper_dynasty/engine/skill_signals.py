"""Pure extractors for the redesigned Franchise Rating's Skill pillar.

- ``lineup_skill_signals``: per-owner weekly lineup efficiency (did the owner
  start their best players?) — Σ actual-started points / Σ optimal points over
  every roster-week. Reuses the production-tested optimal-lineup solver.
- ``trade_skill_signals``: per-owner zero-sum trade skill, averaged per trade
  (volume-independent) with small-sample shrinkage. Non-traders land neutral.
"""

from __future__ import annotations

from sleeper_dynasty.engine.lineup import solve_optimal_lineup


def lineup_skill_signals(
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_positions_by_league: dict[str, list[str]],
    positions: dict[str, str],
    roster_to_user_by_league: dict[str, dict[int, str]],
    owners: list[str],
) -> dict[str, dict[str, float]]:
    """Per-owner lineup efficiency across all roster-weeks.

    ``matchups`` is keyed ``(league_id, week, roster_id)`` with per-entry
    ``starters``/``players``/``players_points`` (see grader_io._assemble_played_matchups).
    Efficiency is ``Σ actual / Σ optimal``; an owner with no scored weeks gets 0.0.
    """
    actual: dict[str, float] = {u: 0.0 for u in owners}
    optimal: dict[str, float] = {u: 0.0 for u in owners}

    for (lg, _week, rid), m in matchups.items():
        uid = (roster_to_user_by_league.get(lg) or {}).get(rid)
        if uid is None:
            continue
        actual.setdefault(uid, 0.0)
        optimal.setdefault(uid, 0.0)
        rpos = roster_positions_by_league.get(lg) or []
        pts = m.get("players_points") or {}
        player_map = {
            pid: (positions[pid], float(pts.get(pid, 0.0) or 0.0))
            for pid in (m.get("players") or [])
            if positions.get(pid)
        }
        _, opt_total = solve_optimal_lineup(rpos, player_map)
        # Keep actual and optimal on the same player universe / week: skip weeks
        # with no solvable optimal (empty rpos or all-unpositioned), and count only
        # positioned starters in actual — else a no-position starter inflates >1.0.
        if opt_total <= 0:
            continue
        act_total = sum(
            float(pts.get(pid, 0.0) or 0.0)
            for pid in (m.get("starters") or [])
            if positions.get(pid)
        )
        actual[uid] += act_total
        optimal[uid] += opt_total

    return {
        u: {"lineup_skill": (actual[u] / optimal[u]) if optimal[u] > 0 else 0.0}
        for u in actual
    }


def trade_skill_signals(
    trades: list[dict],
    owners: list[str],
    *,
    k: float = 2.0,
) -> dict[str, dict[str, float]]:
    """Per-owner zero-sum trade skill, averaged per trade with shrinkage.

    Each trade is ``{"value_swing": {uid: float}, "production": {uid: float}}``:
    ``value_swing`` is the per-side zero-sum market-value swing; ``production`` is
    each side's received production total. Production is recentered per trade
    (``p_uid - mean(p)``) so it is zero-sum across the sides. Per owner we average
    across their trades, then shrink toward neutral by ``n / (n + k)`` to damp
    one-trade spikes. Non-traders get ``{0.0, 0.0}`` — i.e. league-neutral.
    """
    val_sum: dict[str, float] = {u: 0.0 for u in owners}
    prod_sum: dict[str, float] = {u: 0.0 for u in owners}
    n: dict[str, int] = {u: 0 for u in owners}

    for t in trades:
        vs = t.get("value_swing") or {}
        pr = t.get("production") or {}
        sides = set(vs) | set(pr)
        pmean = (sum(pr.values()) / len(pr)) if pr else 0.0
        for uid in sides:
            val_sum.setdefault(uid, 0.0)
            prod_sum.setdefault(uid, 0.0)
            n.setdefault(uid, 0)
            val_sum[uid] += float(vs.get(uid, 0.0) or 0.0)
            prod_sum[uid] += float(pr.get(uid, 0.0) or 0.0) - pmean
            n[uid] += 1

    out: dict[str, dict[str, float]] = {}
    for u in n:
        c = n[u]
        shrink = c / (c + k) if c else 0.0
        out[u] = {
            "trade_value": (val_sum[u] / c * shrink) if c else 0.0,
            "trade_production": (prod_sum[u] / c * shrink) if c else 0.0,
        }
    return out
