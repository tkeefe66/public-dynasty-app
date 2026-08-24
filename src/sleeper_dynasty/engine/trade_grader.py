"""Trade grader.

Five value/points views, computed independently per trade:

  Trade Value   — snapshot KTC value swing (today's market value; zero-sum)
  Total Points  — received-only production (bench included)
  Regular/Playoff/Toilet — received-only started production, by bracket phase

Only Trade Value is a swing (received − given). Production metrics are
received-only: points scored by the assets a side received, while on that
side's roster, tagged with that side's bracket phase.
Per-owner aggregation rolls each grade across that owner's entire history.
"""

from __future__ import annotations

import logging

from sleeper_dynasty.engine.nfl_actuals import points_after_drop as _pad
from sleeper_dynasty.models.player import KTCValue
from sleeper_dynasty.models.trade import (
    AssetLine,
    OwnerTradeRecord,
    PickAsset,
    PlayerAsset,
    ResolvedTrade,
    TradeAsset,
    TradeGrade,
)

log = logging.getLogger(__name__)


def _ktc_value(
    asset: TradeAsset,
    ktc: dict[str, KTCValue],
    fmt: str,
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
    ignore_drafted_player: bool = False,
    tier_by_user: dict[str, str] | None = None,
    tiered_values: dict[tuple[int, int, str], KTCValue] | None = None,
) -> float:
    """KTC value of an asset for snapshot grading.

    PlayerAsset: today's KTC value (Superflex or 1QB per fmt).
    PickAsset annotated with a drafted player: today's KTC of that player
        (so a flipped pick telescopes against its resolution trade).
        When ``ignore_drafted_player`` is True, the drafted-player path is
        skipped and the round-level pick table is used instead (for at-trade
        valuation where the pick had not yet been drafted).
    PickAsset without a drafted player (future/undrafted): round-level pick
        value from ``pick_values`` if available, else 0.
    FaabAsset: 0.
    """
    def _from_ktc(v: KTCValue | None) -> float:
        if v is None:
            return 0.0
        raw = v.superflex_value if fmt == "superflex" else v.one_qb_value
        return float(raw) if raw is not None else 0.0

    if isinstance(asset, PlayerAsset):
        v = ktc.get(asset.player_id)
        if v is None:
            log.warning("No KTC value for player %s (%s)", asset.player_id, asset.name)
        return _from_ktc(v)
    if isinstance(asset, PickAsset):
        if asset.drafted_player_id is not None and not ignore_drafted_player:
            v = ktc.get(asset.drafted_player_id)
            if v is None:
                log.warning(
                    "No KTC value for drafted pick player %s (%s, %d round %d)",
                    asset.drafted_player_id, asset.drafted_player_name,
                    asset.season, asset.round,
                )
            return _from_ktc(v)
        table = pick_values or {}
        # Snapshot value of an unresolved future pick: tier by the original
        # team's current strength. At-trade (ignore_drafted_player) stays
        # round-average (no historical roster strength).
        if not ignore_drafted_player and tier_by_user is not None:
            tier = tier_by_user.get(asset.original_owner_user_id, "")
            tv = (tiered_values or {}).get((asset.season, asset.round, tier))
            if tv is not None:
                return _from_ktc(tv)
        return _from_ktc(table.get((asset.season, asset.round)))
    return 0.0


def grade_snapshot_value(
    rt: ResolvedTrade,
    ktc_values: dict[str, KTCValue],
    fmt: str = "superflex",
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
    ignore_drafted_player: bool = False,
    tier_by_user: dict[str, str] | None = None,
    tiered_values: dict[tuple[int, int, str], KTCValue] | None = None,
) -> dict[str, float]:
    """Compute snapshot KTC value swing per side."""
    swings: dict[str, float] = {}
    for uid, side in rt.sides.items():
        received = sum(_ktc_value(a, ktc_values, fmt, pick_values, ignore_drafted_player,
                                  tier_by_user, tiered_values) for a in side.received)
        given = sum(_ktc_value(a, ktc_values, fmt, pick_values, ignore_drafted_player,
                               tier_by_user, tiered_values) for a in side.given)
        swings[uid] = received - given
    return swings


def _is_post_trade(
    league_id: str,
    week: int,
    rt: ResolvedTrade,
    league_season_by_id: dict[str, int] | None = None,
) -> bool:
    """True if (league_id, week) is strictly after the trade's (season, week).

    Trade week itself is excluded — Sleeper trades typically take effect
    the following week.
    """
    trade_season = rt.trade.season
    trade_week = rt.trade.week
    season_map = league_season_by_id or {}
    matchup_season = season_map.get(league_id)
    if matchup_season is None:
        # Unknown season — be conservative: only count if the matchup's
        # league_id matches the trade's league_id and week is after.
        return league_id == rt.trade.league_id and week > trade_week
    if matchup_season > trade_season:
        return True
    if matchup_season < trade_season:
        return False
    # Same season: trade week excluded; later weeks count.
    return week > trade_week


def grade_hindsight_production(
    rt: ResolvedTrade,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    league_season_by_id: dict[str, int] | None = None,
    starters_only: bool = False,
    phase_filter: str | None = None,
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
) -> dict[str, float]:
    """Sum points received per side, post-trade.

    Args:
        rt: Resolved trade to grade.
        matchups: ``(league_id, week, roster_id) -> matchup-entry-dict``
            covering the entire chain post-trade. Each entry carries
            ``players`` (list of player_ids on the roster that week),
            ``starters`` (the started lineup that week), and
            ``players_points`` (per-player scoring).
        roster_to_user_by_league: per-league roster_id → user_id mapping.
        league_season_by_id: optional mapping of league_id → season year,
            used to correctly exclude matchups from prior seasons.
        starters_only: when True, count a player's points only in weeks they
            were in the starting lineup (gate on ``starters`` instead of
            ``players``). This yields the "started" production swing; the
            default (False) counts all roster weeks, bench included.
        phase_filter: when set, restrict to weeks with the given phase:
            ``"regular"`` (pre-playoff), ``"playoff"`` (winners-bracket
            title-path game), or ``"toilet"`` (losers-bracket game). Requires
            ``phase_by_lwr`` and ``playoff_week_start_by_league`` for
            non-regular phases. When None, all post-trade weeks are included.
        phase_by_lwr: ``(league_id, week, roster_id) -> "playoff" | "toilet"``
            map produced by ``classify_playoff_phases``. Weeks absent from
            this map that fall on or after playoff_week_start are considered
            "dropped" (bye, placement game) and excluded when phase_filter is
            set.
        playoff_week_start_by_league: per-league playoff start week (default
            15), used to classify weeks < playoff_start as "regular".

    Returns:
        ``user_id -> received-only production`` (points scored by received assets
        while on the acquiring roster; no phantom subtraction).
    """
    league_season_by_id = league_season_by_id or {}
    phase_by_lwr = phase_by_lwr or {}
    playoff_week_start_by_league = playoff_week_start_by_league or {}
    roster_field = "starters" if starters_only else "players"

    def _phase(lg: str, wk: int, rid: int) -> str:
        """Classify (league, week, roster) into regular / playoff / toilet / dropped."""
        ps = playoff_week_start_by_league.get(lg, 15)
        if wk < ps:
            return "regular"
        return phase_by_lwr.get((lg, wk, rid), "dropped")

    def _received_points(pid: str, target_uid: str) -> float:
        """Sum points scored by pid while owned by target_uid, post-trade."""
        total = 0.0
        for (lg, wk, rid), entry in matchups.items():
            if not _is_post_trade(lg, wk, rt, league_season_by_id):
                continue
            if phase_filter and _phase(lg, wk, rid) != phase_filter:
                continue
            user_map = roster_to_user_by_league.get(lg, {})
            owner = user_map.get(rid)
            if owner != target_uid:
                continue
            if pid not in (entry.get(roster_field) or []):
                continue
            total += float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
        return total

    totals: dict[str, float] = {}
    for uid, side in rt.sides.items():
        received = 0.0
        for a in side.received:
            if isinstance(a, PlayerAsset):
                received += _received_points(a.player_id, uid)
        totals[uid] = received
        log.debug("Received-only production for %s: %.1f", uid, received)
    return totals


def player_week_points(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    rt: ResolvedTrade,
    league_season_by_id: dict[str, int] | None = None,
    starters_only: bool = False,
    phase_filter: str | None = None,
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
) -> dict[tuple[int, int], float]:
    """Points ``pid`` scored each (season, week) while owned by ``uid``, post-trade,
    optionally gated on a bracket phase. Keys are ``(season, week)``; weeks with no
    qualifying entry are omitted. The per-week basis behind the production timeline;
    ``_points_while_owned`` is its sum."""
    league_season_by_id = league_season_by_id or {}
    phase_by_lwr = phase_by_lwr or {}
    playoff_week_start_by_league = playoff_week_start_by_league or {}
    roster_field = "starters" if starters_only else "players"
    out: dict[tuple[int, int], float] = {}
    for (lg, wk, rid), entry in matchups.items():
        if not _is_post_trade(lg, wk, rt, league_season_by_id):
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
        season = league_season_by_id.get(lg, 0)
        pts = float((entry.get("players_points") or {}).get(pid, 0.0) or 0.0)
        out[(season, wk)] = out.get((season, wk), 0.0) + pts
    return out


def _points_while_owned(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    rt: ResolvedTrade,
    league_season_by_id: dict[str, int] | None = None,
    starters_only: bool = False,
    phase_filter: str | None = None,
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
) -> float:
    """Points ``pid`` scored while owned by ``uid``, post-trade, optionally
    gated on a bracket phase. Sum of ``player_week_points``."""
    return sum(player_week_points(
        pid, uid, matchups=matchups, roster_to_user_by_league=roster_to_user_by_league,
        rt=rt, league_season_by_id=league_season_by_id, starters_only=starters_only,
        phase_filter=phase_filter, phase_by_lwr=phase_by_lwr,
        playoff_week_start_by_league=playoff_week_start_by_league,
    ).values())


def _points_after_owned(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    rt: ResolvedTrade,
    league_season_by_id: dict[str, int] | None = None,
    nfl_points: dict[tuple[int, int], dict[str, float]] | None = None,
    **_ignore,
) -> float:
    """League points ``pid`` scored over the 10 NFL weeks after the last week
    ``uid`` rostered him post-trade — the drop-regret figure. 0 without nfl_points."""
    if not nfl_points:
        return 0.0
    league_season_by_id = league_season_by_id or {}
    owned = player_week_points(
        pid, uid, matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        rt=rt, league_season_by_id=league_season_by_id,
    )
    last_week = max(owned.keys()) if owned else (rt.trade.season, rt.trade.week)
    return _pad(pid, last_week, nfl_points, window=10)


def _pick_ordinal(season: int, rnd: int) -> str:
    """``2027 1st`` — a pick's season + ordinal round, no draftee."""
    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(rnd, f"{rnd}th")
    return f"{season} {ordinal}"


def _pick_label(a: PickAsset) -> str:
    """Human label for a received pick, e.g. ``2027 1st`` (or with the drafted
    player when the pick has resolved)."""
    base = _pick_ordinal(a.season, a.round)
    if getattr(a, "drafted_player_name", None):
        return f"{base} ({a.drafted_player_name})"
    return base


def build_asset_breakdown(
    rt: ResolvedTrade,
    *,
    ktc_values: dict[str, KTCValue],
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    league_season_by_id: dict[str, int] | None = None,
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    playoff_week_start_by_league: dict[str, int] | None = None,
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
    fmt: str = "superflex",
    tier_by_user: dict[str, str] | None = None,
    tiered_values: dict[tuple[int, int, str], KTCValue] | None = None,
    nfl_points: dict[tuple[int, int], dict[str, float]] | None = None,
) -> dict[str, list[AssetLine]]:
    """Per-side, per-received-asset stat lines. Player rows carry received-only
    production per phase; pick rows carry KTC only. Row columns sum to the
    side's per-metric totals."""
    league_season_by_id = league_season_by_id or {}
    out: dict[str, list[AssetLine]] = {}
    for uid, side in rt.sides.items():
        rows: list[AssetLine] = []
        for a in side.received:
            ktc = _ktc_value(a, ktc_values, fmt, pick_values, False,
                             tier_by_user, tiered_values)
            if isinstance(a, PlayerAsset):
                common = dict(
                    matchups=matchups,
                    roster_to_user_by_league=roster_to_user_by_league,
                    rt=rt, league_season_by_id=league_season_by_id,
                    phase_by_lwr=phase_by_lwr,
                    playoff_week_start_by_league=playoff_week_start_by_league,
                )
                via = getattr(a, "via_pick", None)
                rows.append(AssetLine(
                    label=a.name, kind="player", player_id=a.player_id, ktc=ktc,
                    from_pick=(_pick_ordinal(via.season, via.round) if via else None),
                    from_pick_owner_uid=(via.original_owner_user_id if via else None),
                    production_total=_points_while_owned(a.player_id, uid, **common),
                    production_regular=_points_while_owned(
                        a.player_id, uid, starters_only=True, phase_filter="regular", **common),
                    production_playoff=_points_while_owned(
                        a.player_id, uid, starters_only=True, phase_filter="playoff", **common),
                    production_toilet=_points_while_owned(
                        a.player_id, uid, starters_only=True, phase_filter="toilet", **common),
                    production_started=_points_while_owned(
                        a.player_id, uid, starters_only=True, **common),
                    production_after_drop=_points_after_owned(
                        a.player_id, uid, nfl_points=nfl_points, **common),
                ))
            elif isinstance(a, PickAsset):
                rows.append(AssetLine(
                    label=_pick_label(a), kind="pick", player_id=None, ktc=ktc,
                    production_total=0.0, production_regular=0.0,
                    production_playoff=0.0, production_toilet=0.0,
                    production_started=0.0,
                ))
            # FaabAsset: skip — zero value, not a roster contributor.
        out[uid] = rows
    return out


def grade_trade(
    rt: ResolvedTrade,
    ktc_values: dict[str, KTCValue],
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    playoff_week_start_by_league: dict[str, int],
    phase_by_lwr: dict[tuple[str, int, int], str] | None = None,
    league_season_by_id: dict[str, int] | None = None,
    fmt: str = "superflex",
    pick_values: dict[tuple[int, int], KTCValue] | None = None,
    tier_by_user: dict[str, str] | None = None,
    tiered_values: dict[tuple[int, int, str], KTCValue] | None = None,
    nfl_points: dict[tuple[int, int], dict[str, float]] | None = None,
) -> TradeGrade:
    """Compute every value/points view for a single trade.

    Args:
        rt: Resolved trade to grade.
        ktc_values: player_id → KTCValue for snapshot valuation.
        matchups: (league_id, week, roster_id) → matchup entry dict.
        roster_to_user_by_league: per-league roster_id → user_id mapping.
        playoff_week_start_by_league: per-league playoff start week.
        phase_by_lwr: (league_id, week, roster_id) → "playoff" | "toilet"
            from classify_playoff_phases. Empty dict disables bracket-aware
            phase splitting (playoff/toilet will return 0).
        league_season_by_id: optional league_id → season year for cross-season
            gating.
        fmt: KTC format — "superflex" or "1qb".
        pick_values: optional pick-round valuation table.
    """
    league_season_by_id = league_season_by_id or {}
    common = dict(
        matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        league_season_by_id=league_season_by_id,
    )
    snapshot = grade_snapshot_value(rt, ktc_values, fmt=fmt, pick_values=pick_values,
                                    tier_by_user=tier_by_user, tiered_values=tiered_values)
    total = grade_hindsight_production(rt, **common)
    started_common = dict(
        starters_only=True,
        phase_by_lwr=phase_by_lwr or {},
        playoff_week_start_by_league=playoff_week_start_by_league,
        **common,
    )
    breakdown = build_asset_breakdown(
        rt, ktc_values=ktc_values, matchups=matchups,
        roster_to_user_by_league=roster_to_user_by_league,
        league_season_by_id=league_season_by_id,
        phase_by_lwr=phase_by_lwr or {},
        playoff_week_start_by_league=playoff_week_start_by_league,
        pick_values=pick_values, fmt=fmt,
        tier_by_user=tier_by_user, tiered_values=tiered_values,
        nfl_points=nfl_points,
    )
    received_ktc = {uid: sum(r.ktc for r in rows) for uid, rows in breakdown.items()}
    return TradeGrade(
        trade_id=rt.trade.transaction_id,
        snapshot_value_swing=snapshot,
        production_total=total,
        production_regular=grade_hindsight_production(
            rt, phase_filter="regular", **started_common
        ),
        production_playoff=grade_hindsight_production(
            rt, phase_filter="playoff", **started_common
        ),
        production_toilet=grade_hindsight_production(
            rt, phase_filter="toilet", **started_common
        ),
        production_started=grade_hindsight_production(rt, **started_common),
        received_ktc=received_ktc,
        breakdown=breakdown,
    )


def aggregate_owner_records(
    grades: list[TradeGrade],
    display_names: dict[str, str],
) -> dict[str, OwnerTradeRecord]:
    """Roll grades across all trades into per-owner records."""
    records: dict[str, OwnerTradeRecord] = {}
    best_swing: dict[str, float] = {}
    worst_swing: dict[str, float] = {}
    for g in grades:
        for uid, swing in g.snapshot_value_swing.items():
            rec = records.setdefault(
                uid,
                OwnerTradeRecord(
                    user_id=uid,
                    display_name=display_names.get(uid, uid),
                ),
            )
            rec.trades += 1
            rec.net_ktc += swing
            rec.production_total += g.production_total.get(uid, 0.0)
            rec.production_regular += g.production_regular.get(uid, 0.0)
            rec.production_playoff += g.production_playoff.get(uid, 0.0)
            rec.production_toilet += g.production_toilet.get(uid, 0.0)
            if uid not in best_swing or swing > best_swing[uid]:
                best_swing[uid] = swing
                rec.best_trade_id = g.trade_id
            if uid not in worst_swing or swing < worst_swing[uid]:
                worst_swing[uid] = swing
                rec.worst_trade_id = g.trade_id
    return records
