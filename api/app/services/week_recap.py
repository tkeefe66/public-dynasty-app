"""Per-week recap for the dashboard's in-season lead (followup A2).

`HeadlineMoves` leads with a week recap when the league phase is "regular", and
until now it had no figures to print. This derives them from the same assembled
matchups the standings reconstruction reads — high score, biggest blowout, and
the owner who got the most started points out of trade-acquired players.

Two rules shape every function here:

* **Never an in-progress week.** The recap week is strictly earlier than
  Sleeper's current `nfl_state.week`, so a Sunday-afternoon partial score can
  never be published as a result. The cost is a lag of up to two days after a
  week ends (Sleeper advances `week` on Tuesday); publishing a half-scored
  blowout would be worse.
* **Figures reconcile.** Every number comes from one source — the
  `(league_id, week, roster_id)` matchup entries — so the high score, the
  blowout margin, and the traded-points tally are all consistent with each
  other and with the standings. Nothing is differenced out of a cumulative
  series, and nothing is estimated.

Pure: no I/O, no clock. Computed at refresh time next to `league_phase` (the
dashboard route is sync and cache-only) and persisted on
`ChainCacheEntry.week_recap`.
"""

from __future__ import annotations

from typing import Any

# Sleeper's default when a league doesn't declare one.
DEFAULT_PLAYOFF_START = 15


def latest_completed_regular_week(
    *,
    matchups: dict[tuple[str, int, int], dict],
    league_season_by_id: dict[str, int],
    playoff_start_by_season: dict[int, int],
    nfl_state: dict | None,
) -> tuple[int, int] | None:
    """``(season, week)`` of the most recent COMPLETED regular-season week.

    ``None`` when there isn't one: outside the regular season, before week 2
    (nothing has completed yet), or when no matchups exist for a completed week.
    """
    if not isinstance(nfl_state, dict):
        return None
    if str(nfl_state.get("season_type") or "").strip().lower() != "regular":
        return None
    try:
        season = int(nfl_state.get("season") or 0)
        current_week = int(nfl_state.get("week") or 0)
    except (TypeError, ValueError):
        return None
    if season <= 0 or current_week <= 1:
        return None

    playoff_start = playoff_start_by_season.get(season, DEFAULT_PLAYOFF_START)
    weeks = {
        wk
        for (lg, wk, _rid) in matchups
        # `wk < current_week` is the in-progress guard: the current week is
        # either being played or hasn't kicked off, never "completed".
        if league_season_by_id.get(lg) == season and wk < playoff_start and wk < current_week
    }
    if not weeks:
        return None
    return season, max(weeks)


def traded_pids_by_user(
    resolved: list[dict],
    *,
    season: int,
    week: int,
    league_season_by_id: dict[str, int],
) -> dict[str, set[str]]:
    """user_id → player ids that user received in a trade taking effect by ``week``.

    Matches the production rollups' attribution: a trade's own week is excluded
    (Sleeper trades take effect the following week — see
    ``trade_grader._is_post_trade``), and pick-derived players count, because
    pick resolution has already rewritten them as players on the resolved side.

    Roster membership is NOT checked here — the caller intersects this with the
    week's actual starters, which proves possession far more directly than a
    tenure walk can.
    """
    out: dict[str, set[str]] = {}
    for row in resolved:
        rt = row.get("rt")
        if rt is None:
            continue
        trade = getattr(rt, "trade", None)
        sides = getattr(rt, "sides", None) or {}
        if trade is None:
            continue
        trade_season = league_season_by_id.get(
            getattr(trade, "league_id", ""), getattr(trade, "season", 0)
        )
        try:
            trade_week = int(getattr(trade, "week", 0) or 0)
        except (TypeError, ValueError):
            continue
        if (int(trade_season or 0), trade_week) >= (season, week):
            continue  # same week or later: not yet in effect for this week
        for uid, side in sides.items():
            for asset in getattr(side, "received", None) or []:
                pid = getattr(asset, "player_id", None)
                if pid:
                    out.setdefault(str(uid), set()).add(str(pid))
    return out


def _started_points(entry: dict, pids: set[str]) -> float:
    """Started points this roster-week from ``pids`` only."""
    points = entry.get("players_points") or {}
    return sum(
        float(points.get(pid) or 0.0)
        for pid in (entry.get("starters") or [])
        if pid in pids
    )


def derive_week_recap(
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    league_season_by_id: dict[str, int],
    season: int,
    week: int,
    traded_pids: dict[str, set[str]],
) -> dict[str, Any] | None:
    """The recap payload for one completed week, or ``None`` if it can't be built.

    Shape (JSON-ready, persisted as-is):
    ``{season, week, high_score:{user_id, points},
       blowout:{winner_user_id, loser_user_id, margin},
       traded_points:{user_id, points} | None}``

    ``traded_points`` is ``None`` when no owner started a trade-acquired player
    for points that week — an honest zero reads as "nothing to report", and the
    frontend drops the line rather than printing 0.0.
    """
    rows = [
        (lg, rid, entry)
        for (lg, wk, rid), entry in matchups.items()
        if wk == week and league_season_by_id.get(lg) == season
    ]
    if not rows:
        return None

    def _owner(lg: str, rid: int) -> str | None:
        return (roster_to_user_by_league.get(lg) or {}).get(rid)

    high: tuple[str, float] | None = None
    blowout: tuple[str, str, float] | None = None
    traded: dict[str, float] = {}

    for lg, rid, entry in rows:
        uid = _owner(lg, rid)
        if not uid:
            continue
        tp = entry.get("team_points")
        if tp is None:
            continue
        tp = float(tp)
        if high is None or tp > high[1]:
            high = (uid, tp)

        op = entry.get("opponent_points")
        opp_rid = entry.get("opponent_roster_id")
        if op is not None and opp_rid is not None:
            margin = tp - float(op)
            loser = _owner(lg, int(opp_rid))
            # Only the winning side proposes a blowout, so each game is
            # considered once and `winner`/`loser` can't be swapped.
            if margin > 0 and loser and (blowout is None or margin > blowout[2]):
                blowout = (uid, loser, margin)

        pids = traded_pids.get(uid)
        if pids:
            pts = _started_points(entry, pids)
            if pts:
                traded[uid] = traded.get(uid, 0.0) + pts

    if high is None or blowout is None:
        # A week with no completed game (or no identifiable owners) has no
        # recap. Better no lead than a half-populated one.
        return None

    top_traded = max(traded.items(), key=lambda kv: kv[1], default=None)
    return {
        "season": str(season),
        "week": int(week),
        "high_score": {"user_id": high[0], "points": round(high[1], 2)},
        "blowout": {
            "winner_user_id": blowout[0],
            "loser_user_id": blowout[1],
            "margin": round(blowout[2], 2),
        },
        "traded_points": (
            {"user_id": top_traded[0], "points": round(top_traded[1], 2)}
            if top_traded
            else None
        ),
    }
