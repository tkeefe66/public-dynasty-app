"""GraderService — async orchestrator for the full grader pipeline.

Wraps the existing build_trade_history + grade_trade + aggregate_owner_records
pipeline with progress reporting + serializable output suitable for
ChainCacheEntry.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.services.at_trade import compute_at_trade
from app.services.chain_cache import ChainCacheEntry
from app.services.ktc_snapshot_store import KtcSnapshotStore
from app.services.league_raw_cache import LeagueRawCache
from app.services.name_override_store import NameOverrideStore

# The grader engine + aggregator from the existing package.
from sleeper_dynasty.engine.trade_grader import grade_trade
from sleeper_dynasty.engine.trade_history import build_trade_history

log = logging.getLogger(__name__)

# Re-scraped weekly by DynastyProcess; a ~1MB plain CSV (never the parquet or
# the frozen .csv.gz — see rookie_board.py / extract_rookie_boards.py).
_ROOKIE_ECR_LATEST_CSV_URL = (
    "https://github.com/dynastyprocess/data/raw/master/files/"
    "db_fpecr_latest.csv"
)

ProgressCallback = Callable[..., Awaitable[None]]


def llm_pass_throttled(
    *,
    now: datetime,
    prev_llm_at: str | None,
    interval_seconds: int,
    incremental_reuse: bool,
    force: bool,
) -> bool:
    """One decision: reuse all cached prose this pass?

    True on either independent reason: the offseason gate (incremental reuse
    engaged — offseason + no new trades, so no facts packet can have
    materially moved) or the time throttle (within interval_seconds of the
    last LLM pass). force defeats both. Brand-new trades still generate
    regardless — the generators only reuse entries that already have prose.
    """
    if force:
        return False
    if incremental_reuse:
        return True
    if interval_seconds > 0 and prev_llm_at:
        try:
            elapsed = (now - datetime.fromisoformat(prev_llm_at)).total_seconds()
            return 0 <= elapsed < interval_seconds
        except ValueError:
            return False
    return False


def _to_dict(obj: Any) -> Any:
    """Best-effort conversion of grader dataclasses to plain dicts.

    Recurses through nested dataclasses (Trade, ResolvedTrade, TradeSide,
    PlayerAsset, etc.) so the result is JSON-serializable.
    """
    if is_dataclass(obj):
        return {k: _to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_dict(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def compute_production_series_payload(
    *,
    resolved_dicts: list[dict],
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
    league_season_by_id: dict[str, int],
    current_holders: dict[str, str],
    drop_index: dict[tuple[str, str], str],
    phase_by_lwr: dict[tuple[str, int, int], str],
    playoff_week_start_by_league: dict[str, int],
    names: dict[str, str],
) -> dict:
    """Pure builder for the production-timeline payload cached on ChainCacheEntry.

    Returns ``trade_production_series`` (tx -> uid -> metric -> [[season, week, val]]),
    ``trade_production_verdict`` (tx -> metric -> verdict), ``owner_production_series``
    (uid -> {"received"|"given"} -> metric -> series), ``owner_production_verdict``
    (uid -> metric -> verdict), and ``production_week_axis`` ([[season, week], ...]).
    """
    from sleeper_dynasty.engine.lineage import side_value_tenures, terminal_assets
    from sleeper_dynasty.engine.production_series import (
        METRIC_GATES, week_axis, cumulative, merge_week_points,
        head_to_head_verdict, aggregate_production_verdict,
    )
    from sleeper_dynasty.engine.trade_grader import player_week_points

    axis = week_axis(matchups, league_season_by_id)
    metrics = list(METRIC_GATES)
    rt_by_tx = {r["trade"]["transaction_id"]: r["rt"] for r in resolved_dicts if r.get("rt")}

    def _wp(pid, owner, rt, starters_only, phase_filter):
        return player_week_points(
            pid, owner, matchups=matchups,
            roster_to_user_by_league=roster_to_user_by_league, rt=rt,
            league_season_by_id=league_season_by_id, starters_only=starters_only,
            phase_filter=phase_filter, phase_by_lwr=phase_by_lwr,
            playoff_week_start_by_league=playoff_week_start_by_league,
        )

    def _received_player_ids(tx, uid):
        tenures = side_value_tenures(resolved_dicts, tx, uid, which="received",
                                     current_holders=current_holders, drop_index=drop_index)
        return [t.player_id for t in tenures if t.kind == "player" and t.player_id]

    def _chain_player_ids(tx, uid, terms):
        """Every player in this side's lineage chain: the original received
        players PLUS what any flipped asset became (terminal players). Summing
        each one's production-while-owned gives the full-chain line — a traded
        player's points until the trade, then the players received for him."""
        recv = _received_player_ids(tx, uid)
        term_pids = [a["player_id"] for a in terms.get(uid, [])
                     if a.get("kind") == "player" and a.get("player_id")]
        seen, out = set(), []
        for p in [*recv, *term_pids]:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def _given_player_ids(tx, uid):
        tenures = side_value_tenures(resolved_dicts, tx, uid, which="given",
                                     current_holders=current_holders, drop_index=drop_index)
        return [t.player_id for t in tenures if t.kind == "player" and t.player_id]

    def _trade_week_key(r):
        lg = r["trade"].get("league_id")
        return (league_season_by_id.get(lg, 0), int(r["trade"].get("week") or 0))

    axis_index = {sw: i for i, sw in enumerate(axis)}

    def _last_owned_idx(pids, uid):
        """Axis index of the latest week any of `pids` was on uid's roster. A held
        player reaches the last week; a side whose players all left ends earlier.
        Used to truncate the line so it stops when the side has no players left."""
        last_sw = None
        pidset = set(pids)
        for (lg, wk, rid), entry in matchups.items():
            if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
                continue
            if pidset.isdisjoint(entry.get("players") or []):
                continue
            sw = (league_season_by_id.get(lg, 0), wk)
            if last_sw is None or sw > last_sw:
                last_sw = sw
        return axis_index.get(last_sw, len(axis) - 1) if last_sw else len(axis) - 1

    trade_series, trade_verdict = {}, {}
    trade_players: dict[str, dict[str, list]] = {}  # tx -> uid -> [{"player_id", "byMetric"}]
    owner_trades: dict[str, list] = {}              # uid -> [{"trade_id", "byMetric"}]
    owner_acc = {}  # uid -> {"received": {metric: [dicts]}, "given": {metric: [dicts]}}

    for r in resolved_dicts:
        tx = r["trade"]["transaction_id"]
        rt = rt_by_tx.get(tx)
        if rt is None:
            continue
        trade_wk = _trade_week_key(r)
        n = sum(1 for wk in axis if wk > trade_wk)
        terms = terminal_assets(resolved_dicts, tx)
        per_side = {}
        per_metric_totals = {m: {} for m in metrics}
        for uid in (r.get("sides") or {}):
            recv_pids = _chain_player_ids(tx, uid, terms)
            per_side[uid] = {}
            for m in metrics:
                so, pf = METRIC_GATES[m]
                merged = merge_week_points([_wp(p, uid, rt, so, pf) for p in recv_pids])
                series = cumulative(merged, axis)
                per_side[uid][m] = [[s, w, v] for (s, w), v in series]
                per_metric_totals[m][uid] = series[-1][1] if series else 0.0
                owner_acc.setdefault(uid, {"received": {}, "given": {}})
                owner_acc[uid]["received"].setdefault(m, []).append(merged)
            # End the line at the last week the side still had a received player
            # (a flat tail after everyone's gone is misleading — the line stops there).
            end_idx = _last_owned_idx(recv_pids, uid)
            for m in metrics:
                per_side[uid][m] = per_side[uid][m][: end_idx + 1]
            # Per-player drill: each received player's cumulative series per metric.
            players_out = []
            for pid in recv_pids:
                by_metric = {}
                for m in metrics:
                    so, pf = METRIC_GATES[m]
                    s = cumulative(_wp(pid, uid, rt, so, pf), axis)
                    by_metric[m] = [[sy, w, v] for (sy, w), v in s]
                players_out.append({"player_id": pid, "byMetric": by_metric})
            trade_players.setdefault(tx, {})[uid] = players_out
            # Per-trade drill: this trade's received series for each metric.
            owner_trades.setdefault(uid, []).append({
                "trade_id": tx,
                "byMetric": {m: per_side[uid][m] for m in metrics},
            })
            given_pids = _given_player_ids(tx, uid)
            for m in metrics:
                so, pf = METRIC_GATES[m]
                given_merged = merge_week_points([
                    _wp(p, current_holders.get(p, ""), rt, so, pf)
                    for p in given_pids if current_holders.get(p)
                ])
                owner_acc.setdefault(uid, {"received": {}, "given": {}})
                owner_acc[uid]["given"].setdefault(m, []).append(given_merged)
        trade_series[tx] = per_side
        trade_verdict[tx] = {
            m: head_to_head_verdict(totals=per_metric_totals[m], n_games=n, metric=m, names=names)
            for m in metrics
        }

    trades_by_owner, earliest = {}, {}
    for r in resolved_dicts:
        wk = _trade_week_key(r)
        for uid in (r.get("sides") or {}):
            trades_by_owner[uid] = trades_by_owner.get(uid, 0) + 1
            if uid not in earliest or wk < earliest[uid]:
                earliest[uid] = wk

    owner_series, owner_verdict = {}, {}
    for uid, sides in owner_acc.items():
        owner_series[uid] = {"received": {}, "given": {}}
        for side in ("received", "given"):
            for m in metrics:
                merged = merge_week_points(sides[side].get(m, []))
                series = cumulative(merged, axis)
                owner_series[uid][side][m] = [[s, w, v] for (s, w), v in series]
        n = sum(1 for wk in axis if wk > earliest.get(uid, (9999, 99)))
        owner_verdict[uid] = {}
        for m in metrics:
            rt_tot = owner_series[uid]["received"][m][-1][2] if owner_series[uid]["received"][m] else 0.0
            gv_tot = owner_series[uid]["given"][m][-1][2] if owner_series[uid]["given"][m] else 0.0
            owner_verdict[uid][m] = aggregate_production_verdict(
                received_total=rt_tot, given_total=gv_tot, n_games=n, metric=m,
                n_trades=trades_by_owner.get(uid, 0),
            )

    # Per-week postseason flag for the chart's playoff highlight: a week is
    # "post" once it reaches that season's playoff start (per-league, default 15).
    playoff_start_by_season: dict[int, int] = {}
    for lg, season in league_season_by_id.items():
        start = playoff_week_start_by_league.get(lg, 15)
        playoff_start_by_season[season] = min(playoff_start_by_season.get(season, start), start)
    week_phases = ["post" if w >= playoff_start_by_season.get(s, 15) else "regular"
                   for (s, w) in axis]

    return {
        "trade_production_series": trade_series,
        "trade_production_verdict": trade_verdict,
        "owner_production_series": owner_series,
        "owner_production_verdict": owner_verdict,
        "production_week_axis": [[s, w] for (s, w) in axis],
        "production_week_phases": week_phases,
        "trade_production_players": trade_players,
        "owner_production_trades": owner_trades,
    }


def compute_injury_payload(
    *,
    resolved_dicts: list[dict],
    matchups: dict,
    roster_to_user_by_league: dict,
    league_season_by_id: dict,
    current_holders: dict,
    drop_index: dict,
    phase_by_lwr: dict,
    playoff_week_start_by_league: dict,
    injury_map: dict,
    raw_players: dict,
) -> dict:
    """Per-trade per-side per-received-player injury block.

    Returns {"trade_injury": tx -> uid -> player_id -> {
        games_missed:{regular,playoff,toilet}, missed_weeks:[[season,week,confidence]],
        currently_out:bool, out_detail:str|None }}.

    Players with no historical missed games AND not currently out are omitted
    from the payload to keep the output sparse.
    """
    from sleeper_dynasty.engine.lineage import side_value_tenures
    from sleeper_dynasty.engine.injury import games_missed_by_phase
    from sleeper_dynasty.engine.injury_live import live_injury

    def _received_tenures(tx: str, uid: str):
        """Return [(player_id, terminal)] for received players on this side."""
        tens = side_value_tenures(
            resolved_dicts, tx, uid, which="received",
            current_holders=current_holders, drop_index=drop_index,
        )
        return [(t.player_id, t.terminal) for t in tens if t.kind == "player" and t.player_id]

    def _owned_played(pid: str, uid: str, trade_sw: tuple[int, int], terminal: str):
        """Return (owned_weeks, played_weeks, phase_fn) for pid while on uid's roster.

        Ownership is derived from the player's tenure span (post-trade -> terminal)
        rather than from ``players[]`` membership, so IR weeks (where Sleeper drops
        the player from the weekly array) are still counted.

        - active: weeks where pid appears in players[] (on-field or bench)
        - played: weeks where pid actually SCORED (> 0). A 0-point / absent week is
          NOT "played" — Sleeper lists IR/inactive players in players_points as 0.0,
          so a presence check would wrongly mark an injury week as played.
        - uid_weeks: all weeks uid fielded any roster entry (tenure upper bound for held)
        - upper bound: for held players -> latest uid week; for flipped/dropped -> last active week
        - injury_weeks: injury-flagged weeks within the tenure span, post-trade
        - owned = active weeks (post-trade) ∪ injury_weeks
        """
        active: set[tuple[int, int]] = set()
        played: set[tuple[int, int]] = set()
        phase_by_sw: dict[tuple[int, int], str] = {}
        uid_weeks: set[tuple[int, int]] = set()

        for (lg, wk, rid), entry in matchups.items():
            if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
                continue
            season = league_season_by_id.get(lg, 0)
            ps = playoff_week_start_by_league.get(lg, 15)
            phase = "regular" if wk < ps else phase_by_lwr.get((lg, wk, rid), "dropped")
            sw = (season, wk)
            phase_by_sw[sw] = phase
            uid_weeks.add(sw)
            if pid in (entry.get("players") or []):
                active.add(sw)
            if ((entry.get("players_points") or {}).get(pid) or 0) > 0:
                played.add(sw)

        # Upper tenure bound: held -> latest week uid had any roster; else -> last active week
        if terminal == "held":
            upper = max(uid_weeks) if uid_weeks else None
        else:
            upper = max(active) if active else None

        # Injury-flagged weeks within tenure, post-trade, covering IR absences
        injury_weeks = {
            sw for sw in uid_weeks
            if sw > trade_sw and (upper is None or sw <= upper)
            and injury_map.get((pid, sw[0], sw[1]), {}).get("missed")
        }

        owned = {sw for sw in active if sw > trade_sw} | injury_weeks
        return owned, played, (lambda s, w: phase_by_sw.get((s, w), "dropped"))

    trade_injury: dict = {}
    trade_departures: dict = {}  # received players that left the roster (dropped/traded)
    for r in resolved_dicts:
        tx = r["trade"]["transaction_id"]
        lg_id = r["trade"].get("league_id")
        trade_sw = (
            league_season_by_id.get(lg_id, 0),
            int(r["trade"].get("week") or 0),
        )
        for uid in (r.get("sides") or {}):
            for pid, terminal in _received_tenures(tx, uid):
                owned, played, phase_fn = _owned_played(pid, uid, trade_sw, terminal)
                # Mark where the player left the roster, at their last week on it.
                # A drop stops that player's points; a trade is annotated but the
                # line continues with what the asset became (the lineage chain).
                if terminal in ("dropped", "flipped") and owned:
                    ds, dw = max(owned)
                    trade_departures.setdefault(tx, {}).setdefault(uid, []).append({
                        "player_id": pid, "season": ds, "week": dw,
                        "kind": "dropped" if terminal == "dropped" else "traded",
                    })
                gm = games_missed_by_phase(pid, owned, played, injury_map, phase_fn)
                total_missed = sum(gm["games_missed"].values())
                li = live_injury(raw_players.get(pid) or {})
                if total_missed == 0 and not li["currently_out"]:
                    continue  # healthy — omit to keep payload sparse
                out_detail = None
                if li["currently_out"]:
                    bp = f" ({li['body_part']})" if li.get("body_part") else ""
                    since = f" since {li['since']}" if li.get("since") else ""
                    out_detail = f"{li['status']}{bp}{since}".strip()
                trade_injury.setdefault(tx, {}).setdefault(uid, {})[pid] = {
                    "games_missed": gm["games_missed"],
                    "missed_weeks": [
                        [s, w, info["confidence"]]
                        for (s, w), info in gm["missed_weeks"]
                    ],
                    "currently_out": li["currently_out"],
                    "out_detail": out_detail,
                }
    return {"trade_injury": trade_injury, "trade_departures": trade_departures}


def observed_pick_assets(resolved: list) -> bool:
    """Did any trade in this chain actually carry a draft-pick asset?

    Checked on the ORIGINAL trade, not the resolved sides — pick resolution
    rewrites a drafted PickAsset into a PlayerAsset, so resolved sides would
    under-report. Both received and given are checked: in a 3+ team leg a pick
    can appear on only one of them.
    """
    from sleeper_dynasty.models.trade import PickAsset
    for rt in resolved:
        for side in rt.trade.sides.values():
            for asset in (*side.received, *side.given):
                if isinstance(asset, PickAsset):
                    return True
    return False


class GraderService:
    """Async orchestrator: chain walk → grader → ChainCacheEntry."""

    async def run(
        self,
        *,
        client,
        current_league_id: str,
        progress_cb: ProgressCallback,
        cache_dir: Path | None = None,
        force: bool = False,
        skip_llm: bool = False,
        _build_trade_history: Callable[..., Awaitable[tuple[list, dict]]] = build_trade_history,
        _pull_supporting_data: Callable[..., Awaitable[dict]] | None = None,
        _story_writer=None,
        _blurb_writer=None,
        _franchise_writer=None,
        _nfl_state: dict | None = None,
    ) -> ChainCacheEntry:
        """Run the full pipeline, emitting progress along the way.

        ``_build_trade_history`` and ``_pull_supporting_data`` are injection
        points used by tests to swap in mocks.
        """
        if _pull_supporting_data is None:
            from app.services.grader_io import pull_supporting_data
            _pull_supporting_data = pull_supporting_data

        league_cache = (
            LeagueRawCache(cache_dir=cache_dir, force=force)
            if cache_dir is not None else None
        )

        from app.config import get_settings as _get_settings
        _llm_model_override: str | None = _get_settings().llm_model

        # Detected once, up front: with no key configured, every prose stage
        # below (trade stories, GM blurbs, franchise outlooks) would otherwise
        # construct a real writer, fail the call with
        # `TypeError: Could not resolve authentication method...` (the
        # Anthropic SDK's error when neither an api_key nor ANTHROPIC_API_KEY
        # is present), and burn up to `max_attempts` retry rounds before
        # giving up -- ~15s of wasted time and a traceback wall on an
        # otherwise clean refresh. A key that IS present but rejected,
        # rate-limited, or over budget is a different failure and must still
        # surface and retry as before; this flag only fires on absence.
        _llm_key_missing = not os.environ.get("ANTHROPIC_API_KEY")
        if _llm_key_missing:
            log.info(
                "ANTHROPIC_API_KEY not set: skipping LLM prose generation "
                "(trade stories, GM rating blurbs, franchise outlooks) for "
                "%s. Graded data is unaffected.", current_league_id)

        from sleeper_dynasty.llm.cost_store import LlmCostStore
        _cost_store = LlmCostStore(cache_dir) if cache_dir is not None else None

        await progress_cb("chain", "Walking league history")
        chain = await client.walk_league_history(current_league_id)

        # KtcSnapshotStore is one store per install (not per league), and it
        # holds dynasty KTC prices only. A redraft chain must never touch it —
        # match()/value_extremes() would silently hand dynasty prices to
        # at-trade valuation, price providers, and pick analysis. Keeping the
        # store None for redraft chains disables those call sites (they all
        # already gate on `snapshot_store is not None`).
        #
        # The accepted cost is bigger than at-trade/aged valuation alone, and
        # is deliberately listed in full because every item is a visible
        # difference from how a dynasty league reads:
        #   1. at-trade valuation (`compute_at_trade`) — no "what it was worth
        #      the day of the trade" figure;
        #   2. aged valuation (`aged_value_swing`) — no drift-since-the-trade;
        #   3. REALIZED repricing (`compute_realized` / `make_price_providers`,
        #      further down in this same method) — `received_ktc` and each
        #      `breakdown[].ktc` keep their *today, full-value* reading instead
        #      of being repriced to what the owner actually realized (held →
        #      today, flipped → flip-date price, dropped → 0).
        #
        # Redraft now gets its own namespaced store rather than None, so those
        # three read from redraft-priced history instead of dynasty's. **This
        # accrues forward and cannot be backfilled**: FantasyCalc publishes no
        # historical endpoint, and `capture()` only ever writes today. Until a
        # redraft league has snapshots older than a given trade, `match()`
        # returns nothing and every call site falls back to live values — the
        # same reading it had when the store was None. So this is safe on day
        # one and improves on its own as days accumulate.
        #
        # Redraft pick values are still 0 before that season's draft — see the
        # coverage warning in grader_io.pull_supporting_data.
        from app.services.grader_io import is_redraft_chain
        snapshot_store = (
            KtcSnapshotStore(
                cache_dir=cache_dir,
                source="redraft" if is_redraft_chain(chain) else "dynasty",
            )
            if cache_dir is not None
            else None
        )
        chain_summary = [
            {
                "league_id": lg.league_id, "season": lg.season,
                "name": lg.name, "total_rosters": lg.total_rosters,
                "playoff_week_start": lg.playoff_week_start,
            }
            for lg in chain
        ]

        await progress_cb("players", "Loading Sleeper players")
        raw_players = await client.get_players()
        player_names = {
            pid: (raw.get("full_name")
                  or f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip()
                  or pid)
            for pid, raw in raw_players.items()
            if isinstance(raw, dict)
        }

        await progress_cb("trades", "Normalizing trades")
        resolved, drop_index = await _build_trade_history(
            client, current_league_id=current_league_id, player_names=player_names,
            league_cache=league_cache, return_drops=True,
        )

        # NFL state, fetched once and reused by three later stages: the
        # incremental-reuse gate just below, the completed-seasons gate for
        # draft verdicts (an in-progress NFL season must not count as a whole
        # season on either side of the seasons-held/cohort comparison — see
        # the drafted-pick-results block further down), and league-phase
        # derivation at the end of this method. Wrapped in its own try so a
        # transport failure degrades every one of those three to its safe
        # default instead of raising mid-refresh.
        if _nfl_state is None:
            try:
                _get_state = getattr(client, "get_nfl_state", None)
                _nfl_state = await _get_state() if _get_state else None
            except Exception:
                log.exception("nfl_state fetch failed; incremental-reuse, "
                               "completed-seasons, and league-phase all "
                               "degrade to their safe defaults")

        # --- Incremental reuse decision (frozen historical rollups) ---
        # When offseason/between-weeks AND no new trades since the last build,
        # the production/injury/historical-signal rollups are unchanged, so we
        # reuse them from the prior entry and recompute only the value layer.
        from app.services.nfl_state import scoring_in_progress
        from app.services.refresh_delta import new_transaction_ids

        _reuse_prior = None
        if cache_dir is not None and not force:
            from app.services.chain_cache import ChainCache as _CC
            _candidate = _CC(cache_dir=cache_dir).read(
                current_league_id, max_age_seconds=10 ** 9)
            if _candidate is not None:
                _resolved_dicts_for_delta = [
                    {"trade": {"transaction_id": rt.trade.transaction_id}}
                    for rt in resolved
                ]
                if (not scoring_in_progress(_nfl_state)
                        and not new_transaction_ids(
                            _resolved_dicts_for_delta, _candidate)):
                    _reuse_prior = _candidate
        if _reuse_prior is not None:
            log.info("incremental reuse: frozen rollups reused for %s "
                     "(offseason, no new trades)", current_league_id)

        await progress_cb("supporting", "Fetching matchups + values")
        supporting = await _pull_supporting_data(
            client, chain, players=raw_players, league_cache=league_cache,
            snapshot_store=snapshot_store,
        )

        # Current rosters -> holders + roster-strength tiers (early/mid/late).
        # Computed before grading so grade_trade can tier snapshot pick values.
        from sleeper_dynasty.engine.draft_signals import strength_tiers
        current_holders: dict[str, str] = {}
        current_rosters: list = []
        tier_by_user: dict[str, str] = {}
        try:
            current_rosters = await client.get_rosters(current_league_id)
            for r in current_rosters:
                for pid in (r.players or []):
                    current_holders[pid] = r.owner_id
            ktc_now = supporting["ktc_by_player_id"]
            rv: dict[str, float] = {}
            for r in current_rosters:
                total = 0.0
                for pid in (r.players or []):
                    v = ktc_now.get(pid)
                    if v is not None and v.superflex_value is not None:
                        total += float(v.superflex_value)
                rv[r.owner_id] = total
            tier_by_user = strength_tiers(rv)
        except Exception:
            log.exception("could not fetch current rosters / compute tiers")

        await progress_cb("grading", f"Grading {len(resolved)} trades")
        grades = {}
        for rt in resolved:
            g = grade_trade(
                rt,
                ktc_values=supporting["ktc_by_player_id"],
                matchups=supporting["matchups"],
                roster_to_user_by_league=supporting["roster_to_user_by_league"],
                playoff_week_start_by_league=supporting["playoff_week_start_by_league"],
                phase_by_lwr=supporting["phase_by_lwr"],
                league_season_by_id=supporting["league_season_by_id"],
                fmt="superflex",
                pick_values=supporting["pick_value_table"],
                tier_by_user=tier_by_user,
                tiered_values=supporting.get("pick_value_table_tiered") or {},
                nfl_points=supporting.get("nfl_points") or {},
            )
            grades[rt.trade.transaction_id] = _to_dict(g)

        if snapshot_store is not None:
            at_trade = compute_at_trade(resolved, raw_players, snapshot_store)
            for rt in resolved:
                tx = rt.trade.transaction_id
                info = at_trade.get(tx) or {}
                g = grades.get(tx)
                if g is None:
                    continue
                g["at_trade_value_swing"] = info.get("at_trade_value_swing")
                g["at_trade_approx"] = info.get("at_trade_approx", False)
                g["at_trade_snapshot_date"] = info.get("at_trade_snapshot_date")
                at = info.get("at_trade_value_swing")
                today = g.get("snapshot_value_swing") or {}
                g["aged_value_swing"] = (
                    {uid: float(today.get(uid, 0.0)) - float(at[uid]) for uid in at}
                    if at else None
                )

        resolved_dicts = [_to_dict(rt) for rt in resolved]

        # Realized Trade Value: reprice each side's received haul to what the
        # owner actually realized (held → today, flipped → flip date, dropped → 0).
        # Overwrites received_ktc + per-asset breakdown ktc; snapshot_value_swing
        # stays as a mark-to-market diagnostic.
        # Placeholder pricers — only used if snapshot_store is None, in which case
        # snapshot_dates is empty and the value-series / realized stages early-exit,
        # so these zero-returning stubs are never actually priced against.
        price_player = lambda pid, d: 0.0  # overwritten below when snapshot_store is set
        price_pick = lambda s, r, d: 0.0   # overwritten below when snapshot_store is set
        if snapshot_store is not None:
            from app.services.realized_value import compute_realized, make_price_providers
            price_player, price_pick = make_price_providers(
                store=snapshot_store, raw_players=raw_players,
                today_ktc_by_pid=supporting["ktc_by_player_id"],
                today_pick_table=supporting["pick_value_table"],
            )
            realized_by_tx = compute_realized(
                resolved_dicts, current_holders=current_holders,
                price_player=price_player, price_pick=price_pick)
            for tx, by_uid in realized_by_tx.items():
                g = grades.get(tx)
                if g is None:
                    continue
                g["received_ktc"] = {uid: float(sum(vals)) for uid, vals in by_uid.items()}
                for uid, vals in by_uid.items():
                    rows = (g.get("breakdown") or {}).get(uid) or []
                    # vals is index-aligned with breakdown rows (same _asset_id
                    # filter — see realized_received_values docstring).
                    for i, v in enumerate(vals):
                        if i < len(rows):
                            rows[i]["ktc"] = float(v)

        # --- LLM-regeneration gate (cost control) ---
        # Reuse cached stories/blurbs verbatim (brand-new trades still
        # generate) when either the offseason gate or the time throttle says
        # nothing material can have changed. Caps regen cadence on top of the
        # coarsened skip-hash.
        _now = datetime.now(tz=timezone.utc)
        _llm_interval = _get_settings().llm_min_interval_seconds
        _prev_llm_at = None
        if cache_dir is not None:
            from app.services.chain_cache import ChainCache
            _prev_entry = ChainCache(cache_dir=cache_dir).read(
                current_league_id, max_age_seconds=10 ** 9)
            _prev_llm_at = (getattr(_prev_entry, "llm_generated_at", None)
                            if _prev_entry else None)
        _throttled = llm_pass_throttled(
            now=_now,
            prev_llm_at=_prev_llm_at,
            interval_seconds=_llm_interval,
            incremental_reuse=_reuse_prior is not None,
            force=force,
        )
        if _throttled:
            log.info("LLM regen gated for %s (%s); reusing cached prose",
                     current_league_id,
                     "offseason, no new trades" if _reuse_prior is not None
                     else f"last pass {_prev_llm_at}")
        _llm_generated_at = _prev_llm_at if _throttled else _now.isoformat()

        # No key + no test-injected writer -> clean skip, same shape as the
        # budget guard, rather than constructing a real writer that can only
        # fail. A test-injected `_story_writer` still runs regardless of the
        # environment (it never touches the network).
        _no_key_stories = _llm_key_missing and _story_writer is None
        if skip_llm or _no_key_stories:
            # Budget guard or no API key configured: generate no new prose;
            # reuse whatever was last cached.
            _prev_s = (
                ChainCache(cache_dir=cache_dir).read(
                    current_league_id, max_age_seconds=10 ** 9)
                if cache_dir else None
            )
            trade_stories = (getattr(_prev_s, "trade_stories", None) or {}) if _prev_s else {}
            owner_dossiers = (getattr(_prev_s, "owner_dossiers", None) or {}) if _prev_s else {}
            if skip_llm:
                supporting.setdefault("warnings", []).append(
                    "LLM skipped: monthly budget reached")
                await progress_cb("stories", "Skipping trade stories (LLM budget reached)")
            else:
                await progress_cb("stories", "Skipping trade stories (no ANTHROPIC_API_KEY)")
        else:
            await progress_cb("stories", "Writing trade stories")
            try:
                from app.services.story_gen import generate_stories
                writer = _story_writer
                if writer is None:
                    from sleeper_dynasty.llm.trade_story_writer import TradeStoryWriter
                    writer = TradeStoryWriter(model=_llm_model_override) if _llm_model_override else TradeStoryWriter()  # reads ANTHROPIC_API_KEY
                prior = {}
                if cache_dir is not None:
                    from app.services.chain_cache import ChainCache
                    prev = ChainCache(cache_dir=cache_dir).read(
                        current_league_id, max_age_seconds=10 ** 9)
                    prior = prev.trade_stories if prev else {}
                _name_overrides = (
                    NameOverrideStore(cache_dir=cache_dir).read(current_league_id)
                    if cache_dir else {}
                )
                supporting["owners_display"] = {
                    uid: (_name_overrides.get(uid) or o.get("owner_name") or uid)
                    for uid, o in supporting["owners"].items()
                }
                trade_stories, owner_dossiers = await generate_stories(
                    resolved=resolved, grades=grades, supporting=supporting,
                    prior_stories=prior, writer=writer, progress_cb=progress_cb,
                    resolved_dicts=resolved_dicts, current_holders=current_holders,
                    cost_store=_cost_store, league_id=current_league_id,
                    reuse_prior_on_throttle=_throttled,
                )
            except Exception as e:  # never fail refresh on story errors
                log.exception("trade story stage failed")
                trade_stories, owner_dossiers = {}, {}
                supporting.setdefault("warnings", []).append(
                    f"trade stories skipped: {e}")

        # Draft inputs (best-effort: empty -> signals 0).
        traded_picks: list = []
        rookie_picks: list = []
        draft_classes: list = []
        adp_by_draft: dict[str, dict[str, float]] = {}
        rookie_ecr_by_draft: dict[str, dict[str, float]] = {}
        # Pre-initialized here, not inside the rookie-ECR try below: a failure
        # anywhere in that try (including cohort-building itself) must leave
        # this bound to {} rather than raise a NameError at the verdict-
        # stamping loop further down, which would silently drop every
        # drafted-pick result, not just the Verdict column.
        rookie_cohorts: dict[str, tuple[float, float, float]] = {}
        # Pre-initialized for the same reason, one level up: the ADP/
        # projection try below is the block that ASSIGNS `scoring` (from
        # `latest.scoring_settings`), but the rookie-ECR try further down
        # READS it to price the committed cohort history. If the ADP block
        # raised before reaching that assignment, `scoring` would be unbound
        # and the rookie-ECR block's own read of it would NameError — caught
        # by that block's blanket `except Exception`, so it would look like a
        # clean "those columns drop" degrade instead of the bug it is.
        scoring: dict = {}
        projected_by_player: dict[str, float] = {}
        num_draft_rounds = 4
        current_league_drafts: list = []  # for the league-phase draft window
        # Pre-initialized (not just declared inside the try below) because the
        # ADP block further down reads it across a separate try/except: if
        # this block raises before its own assignment (e.g. get_traded_picks
        # or the empty-chain min() call), an unbound drafts_by_league would
        # raise UnboundLocalError there instead of degrading to a clean no-op.
        drafts_by_league: dict[str, list] = {}
        try:
            from sleeper_dynasty.engine.draft_class import (
                build_draft_classes, build_draft_picks,
            )
            from app.services.grader_io import is_redraft_chain

            traded_picks = await client.get_traded_picks(current_league_id)
            origin_season = min(lg.season for lg in chain)
            latest = max(chain, key=lambda lg: lg.season)
            league_format = getattr(latest, "format", "dynasty") or "dynasty"

            picks_by_draft_id: dict[str, list] = {}
            for lg in chain:
                drafts = await client.get_drafts(lg.league_id)
                drafts_by_league[lg.league_id] = drafts
                if lg.league_id == current_league_id:
                    current_league_drafts = drafts

            draft_classes = build_draft_classes(
                drafts_by_league=drafts_by_league,
                league_format=league_format,
                origin_season=origin_season,
            )
            for cls in draft_classes:
                picks_by_draft_id[cls.draft_id] = \
                    await client.get_draft_picks(cls.draft_id)

            rookie_picks = build_draft_picks(
                classes=draft_classes,
                picks_by_draft_id=picks_by_draft_id,
                roster_to_user_by_league=supporting["roster_to_user_by_league"],
            )
            if draft_classes:
                newest = max(draft_classes, key=lambda c: c.season)
                for d in drafts_by_league.get(newest.league_id, []):
                    if d.get("draft_id") == newest.draft_id:
                        num_draft_rounds = int(
                            (d.get("settings") or {}).get("rounds", 4))
        except Exception:
            log.exception("draft inputs fetch failed; draft signals will be 0")

        # ADP + projected points (best-effort: absent -> those columns drop).
        try:
            from sleeper_dynasty.engine.draft_baselines import (
                adp_field_for, parse_all_adp, parse_projected_points,
                points_field_for,
            )
            from app.services.adp_snapshot_store import AdpSnapshotStore

            latest = max(chain, key=lambda lg: lg.season)
            scoring = getattr(latest, "scoring_settings", {}) or {}
            rec_points = float(scoring.get("rec") or 0.0)
            roster_positions = list(
                getattr(latest, "roster_positions", []) or [])
            superflex = (
                "SUPER_FLEX" in roster_positions
                or roster_positions.count("QB") > 1
            )

            # Projections change at most daily; a refresh runs far more often
            # than that. Cache through FileCache on the same day-keyed pattern
            # the injury map uses, so the scheduler does not re-pull a ~9,400
            # player payload every interval. FileCache.read defaults to a
            # one-day max age, so no explicit TTL is needed here.
            from sleeper_dynasty.cache import FileCache

            _fc = FileCache(cache_dir) if cache_dir is not None else None
            # The `.json` suffix is load-bearing: FileCache.invalidate_all only
            # unlinks *.json, so a suffix-less key survives a cache clear.
            _proj_key = f"sleeper_projections_{latest.season}.json"
            if _fc is not None:
                # Sweep the pre-suffix file this key used to write. It is
                # unreadable (the key now carries .json) and unreachable from
                # invalidate_all, so without this it sits on the prod volume
                # forever. Safe to delete once every install has refreshed.
                _fc.invalidate(f"sleeper_projections_{latest.season}")
            raw_proj = _fc.read(_proj_key) if _fc is not None else None
            if not raw_proj:
                raw_proj = await client.get_projections(latest.season)
                if _fc is not None and raw_proj:
                    _fc.write(_proj_key, raw_proj)

            # This league's own scoring picks the variant it READS back. The
            # daily capture writes every variant, so the shared cache dir
            # never pins one league's scoring for another's.
            _adp_field = adp_field_for(
                rec_points=rec_points, superflex=superflex)
            live_adp_by_variant = parse_all_adp(raw_proj)

            # Daily capture is unconditional, then each class resolves its own
            # baseline against ITS OWN draft day. Live ADP is never used for
            # grading directly — only for the daily capture. Keyed per
            # draft_id (not flattened into one player_id -> adp map): a player
            # drafted in more than one season must grade against each season's
            # own market, or an older row silently regrades against a newer
            # snapshot the moment two coexist.
            import datetime as _dt

            adp_store = (
                AdpSnapshotStore(cache_dir) if cache_dir is not None else None
            )
            if adp_store is not None:
                # Unconditional, and for every scoring variant: we cannot know
                # which day a league will draft (nor which league's refresh
                # will be the day's first), and that day's ADP is
                # unrecoverable afterwards.
                adp_store.capture_daily(
                    live_adp_by_variant, _dt.datetime.now(timezone.utc).date())

                # Each draft resolves against ITS OWN day's market. A league
                # drafting Aug 1 and one drafting Aug 26 are grading against
                # genuinely different boards.
                last_picked_by_draft: dict[str, int] = {}
                for _lg_id, _drafts in drafts_by_league.items():
                    for _d in _drafts:
                        lp = _d.get("last_picked") or _d.get("start_time")
                        if lp:
                            last_picked_by_draft[str(_d.get("draft_id"))] = \
                                int(lp)

                for cls in draft_classes:
                    # Dynasty rookie classes have no market baseline: Sleeper's
                    # `adp_rookie` is unpopulated, and the overall-NFL ADP that
                    # IS published would grade a 1.01 rookie against ~30th
                    # overall and print a 29-pick reach. The design's format
                    # matrix says so outright ("ADP baseline — dynasty: no").
                    if cls.axis != "production":
                        continue
                    lp_ms = last_picked_by_draft.get(cls.draft_id)
                    if not lp_ms:
                        continue
                    drafted_on = _dt.datetime.fromtimestamp(
                        lp_ms / 1000, tz=timezone.utc).date()
                    snap = adp_store.resolve_for_draft(
                        cls.draft_id, drafted_on, field=_adp_field)
                    if snap:
                        adp_by_draft[cls.draft_id] = snap

            # Projections are the same format story as ADP (matrix: "Projection
            # baseline — dynasty: no"), and they are a flat per-player map, so
            # the gate has to sit here rather than per class.
            if any(c.axis == "production" for c in draft_classes):
                projected_by_player = parse_projected_points(
                    raw_proj, field=points_field_for(rec_points=rec_points))
        except Exception:
            log.exception("ADP/projection fetch skipped; those columns drop")

        # Rookie ECR baseline (best-effort, independent of the ADP/projection
        # fetch above). Committed history (`rookie_ecr.json.gz`) needs no
        # network call at all, so a timeout on Sleeper's `get_projections`
        # must never take the ECR columns down with it — that shared-`try`
        # coupling used to make a projections timeout empty
        # `rookie_ecr_by_draft`, blank `baseline_label`, and vanish the ECR /
        # Slot +/- columns from the dynasty board for that refresh. Depends
        # only on `cache_dir`/`draft_classes`/`drafts_by_league`/`scoring`,
        # all of which are pre-initialized above the draft-inputs try
        # (`scoring` right alongside `rookie_cohorts`), so a failure there
        # still leaves this block a clean no-op rather than a NameError.
        try:
            if cache_dir is not None:
                from app.services.rookie_board_store import RookieBoardStore

                # Each class resolves against ITS OWN draft day — recomputed
                # here rather than reused because it must not depend on the
                # ADP block above having run (or having succeeded).
                last_picked_by_draft: dict[str, int] = {}
                for _lg_id, _drafts in drafts_by_league.items():
                    for _d in _drafts:
                        lp = _d.get("last_picked") or _d.get("start_time")
                        if lp:
                            last_picked_by_draft[str(_d.get("draft_id"))] = \
                                int(lp)

                # The rookie fork. A dynasty class is axis "blend", which is
                # why the ADP loop above skips it: Sleeper's `adp_rookie` is
                # unpopulated and its overall-NFL ADP would grade a 1.01
                # against ~30th overall. FantasyPros' dynasty ROOKIE
                # consensus is the baseline that class actually has, and
                # unlike ADP it has dated history, so past classes grade too
                # — not going-forward only.
                rookie_store = RookieBoardStore.rookie(cache_dir)

                # Weekly capture, before any class resolves against the
                # timeline: a draft completing today must be able to pin
                # today's board rather than the stalest committed one.
                from sleeper_dynasty.api.player_ids import (
                    fetch_fantasypros_to_sleeper,
                )
                from sleeper_dynasty.cache import FileCache
                from sleeper_dynasty.engine.injury_data import _fetch_csv_rows
                from sleeper_dynasty.engine.rookie_board import (
                    parse_latest_board,
                )

                # Cache the CSV fetch through FileCache on the same day-keyed
                # pattern the projections fetch above uses. The `.json`
                # suffix is load-bearing: FileCache.invalidate_all only
                # unlinks *.json, so a suffix-less key survives a cache clear
                # forever.
                _ecr_fc = FileCache(cache_dir)
                _ecr_key = "fantasypros_rookie_latest.json"
                _ecr_rows = _ecr_fc.read(_ecr_key)
                if not _ecr_rows:
                    _ecr_rows = _fetch_csv_rows(_ROOKIE_ECR_LATEST_CSV_URL)
                    if _ecr_rows:
                        _ecr_fc.write(_ecr_key, _ecr_rows)

                if _ecr_rows:
                    _fp_crosswalk = await fetch_fantasypros_to_sleeper(_ecr_fc)
                    _latest = parse_latest_board(_ecr_rows, _fp_crosswalk)
                    if _latest is not None:
                        # Keyed by the board's OWN scrape_date, not today: the
                        # board is the consensus as of the day it was
                        # scraped, and filing a stale latest.csv under today
                        # could let a draft resolve against a board that did
                        # not exist yet on its draft day.
                        _board_day, _board = _latest
                        rookie_store.capture_daily(
                            _board, date.fromisoformat(_board_day))

                for cls in draft_classes:
                    if cls.kind != "rookie":
                        continue
                    lp_ms = last_picked_by_draft.get(cls.draft_id)
                    if not lp_ms:
                        continue
                    drafted_on = datetime.fromtimestamp(
                        lp_ms / 1000, tz=timezone.utc).date()
                    board = rookie_store.resolve_for_draft(
                        cls.draft_id, drafted_on)
                    if board:
                        rookie_ecr_by_draft[cls.draft_id] = board

                # Cohort bars, priced with THIS league's scoring. The committed
                # history carries raw components precisely so that 6-point
                # passing touchdowns and 4-point ones do not share a bar.
                import gzip as _gz
                import json
                from importlib.resources import files as _files

                from sleeper_dynasty.engine.rookie_cohorts import build_cohorts

                _blob = _files("sleeper_dynasty.data").joinpath(
                    "rookie_stats.json.gz").read_bytes()
                rookie_cohorts = build_cohorts(
                    json.loads(_gz.decompress(_blob)), scoring)
        except Exception:
            log.exception("rookie ECR fetch skipped; those columns drop")

        became_grades = await self._compute_became(
            resolved=resolved,
            resolved_dicts=resolved_dicts,
            supporting=supporting,
            current_league_id=current_league_id,
            cache_dir=cache_dir,
            progress_cb=progress_cb,
        )

        if _reuse_prior is not None:
            production_payload = {
                "trade_production_series": _reuse_prior.trade_production_series,
                "trade_production_verdict": _reuse_prior.trade_production_verdict,
                "owner_production_series": _reuse_prior.owner_production_series,
                "owner_production_verdict": _reuse_prior.owner_production_verdict,
                "production_week_axis": _reuse_prior.production_week_axis,
                "production_week_phases": _reuse_prior.production_week_phases,
                "trade_production_players": _reuse_prior.trade_production_players,
                "owner_production_trades": _reuse_prior.owner_production_trades,
            }
        else:
            production_payload = {
                "trade_production_series": {}, "trade_production_verdict": {},
                "owner_production_series": {}, "owner_production_verdict": {},
                "production_week_axis": [], "production_week_phases": [],
                "trade_production_players": {}, "owner_production_trades": {},
            }
            try:
                for d, rt in zip(resolved_dicts, resolved):
                    d["rt"] = rt
                production_payload = compute_production_series_payload(
                    resolved_dicts=resolved_dicts,
                    matchups=supporting["matchups"],
                    roster_to_user_by_league=supporting["roster_to_user_by_league"],
                    league_season_by_id=supporting["league_season_by_id"],
                    current_holders=current_holders,
                    drop_index=drop_index,
                    phase_by_lwr=supporting.get("phase_by_lwr") or {},
                    playoff_week_start_by_league=supporting.get("playoff_week_start_by_league") or {},
                    names=supporting.get("owners_display") or {},
                )
            except Exception:  # never fail refresh on production errors
                log.exception("production-series stage failed")
            finally:
                for d in resolved_dicts:
                    d.pop("rt", None)

        if _reuse_prior is not None:
            injury_payload = {
                "trade_injury": _reuse_prior.trade_injury,
                "trade_departures": _reuse_prior.trade_departures,
            }
        else:
            injury_payload = {"trade_injury": {}, "trade_departures": {}}
            try:
                from sleeper_dynasty.engine.injury_data import build_injury_map
                from sleeper_dynasty.cache import FileCache
                _file_cache = FileCache(cache_dir) if cache_dir is not None else None
                _seasons = sorted({s for s in supporting["league_season_by_id"].values() if s})
                _injury_map = build_injury_map(
                    _seasons, cache=_file_cache,
                    current_season=max(_seasons) if _seasons else None,
                )
                injury_payload = compute_injury_payload(
                    resolved_dicts=resolved_dicts,
                    matchups=supporting["matchups"],
                    roster_to_user_by_league=supporting["roster_to_user_by_league"],
                    league_season_by_id=supporting["league_season_by_id"],
                    current_holders=current_holders,
                    drop_index=drop_index,
                    phase_by_lwr=supporting.get("phase_by_lwr") or {},
                    playoff_week_start_by_league=supporting.get("playoff_week_start_by_league") or {},
                    injury_map=_injury_map,
                    raw_players=raw_players,
                )
            except Exception:
                log.exception("injury-context stage failed")

        self._snapshot_standings(
            supporting=supporting,
            current_league_id=current_league_id,
            cache_dir=cache_dir,
            current_rosters=current_rosters,
        )
        outcome_signals, outlook_signals, draft_skill_by_season, season_records_from_signals = {}, {}, {}, {}
        try:
            from app.services.rating_signals import compute_rating_signals
            # DraftClass already answered "what does this format grade
            # against" — read it rather than re-deriving format -> axis here,
            # which is exactly the drift draft_class.py exists to prevent
            # ("every format question about a draft is answered here and
            # nowhere else"). All classes on a chain share one axis; "blend"
            # is the dynasty default when the draft stage produced nothing.
            _draft_axis = draft_classes[0].axis if draft_classes else "blend"
            outcome_signals, outlook_signals, draft_skill_by_season, season_records_from_signals = compute_rating_signals(
                supporting, current_holders,
                traded_picks=traded_picks, rookie_picks=rookie_picks,
                num_draft_rounds=num_draft_rounds, axis=_draft_axis)
        except Exception as e:
            log.exception("GM-rating signal computation skipped")
            # Both v2 pillars come from this one call, so a silent failure is a
            # league where every owner scores exactly 1500 and every letter is
            # a C — indistinguishable from a genuinely flat league. Warn like
            # every neighbouring stage does (`entry.warnings` is fed from
            # supporting["warnings"] when the entry is built below).
            supporting.setdefault("warnings", []).append(
                f"Franchise Rating signals unavailable: {e}")

        lineup_signals: dict[str, dict[str, float]] = {}
        try:
            from app.services.rating_signals import compute_lineup_signals
            lineup_signals = compute_lineup_signals(
                supporting, list(supporting["owners"]))
        except Exception:
            log.exception("lineup-skill signal computation skipped")

        # --- Chain-wide head-to-head records (owner vs each league-mate). ---
        head_to_head: dict[str, dict[str, dict]] = {}
        try:
            from app.services.head_to_head_signals import compute_head_to_head
            head_to_head = compute_head_to_head(supporting)
        except Exception:
            log.exception("head-to-head computation skipped")

        if _reuse_prior is not None:
            # Historical pillars don't change without new games/trades; reuse them.
            # outlook_signals stays freshly computed (current roster value/youth).
            outcome_signals = _reuse_prior.outcome_signals or outcome_signals
            lineup_signals = _reuse_prior.lineup_signals or lineup_signals
            draft_skill_by_season = _reuse_prior.draft_skill_by_season or draft_skill_by_season
            season_records_from_signals = _reuse_prior.season_records or season_records_from_signals
            head_to_head = _reuse_prior.head_to_head or head_to_head

        # --- Per-pick draft results for the Future & Draft tab. ---
        drafted_picks: list[dict] = []
        try:
            from sleeper_dynasty.engine.draft_results import (
                build_drafted_pick_results, started_points_while_on_roster,
                started_games_while_on_roster, seasons_held_while_on_roster,
            )
            ktc_now = supporting["ktc_by_player_id"]
            ktc_floats_dp = {
                pid: float(v.superflex_value)
                for pid, v in ktc_now.items()
                if v is not None and v.superflex_value is not None
            }
            normalized_name_by_pid = {
                pid: v.normalized_name for pid, v in ktc_now.items() if v is not None
            }
            positions_dp = supporting.get("positions") or {}
            extremes = (
                snapshot_store.value_extremes() if snapshot_store is not None else {}
            )
            # A pick is "via trade" if the drafter received it (or the player it
            # became) in any resolved trade. Resolved sides are asdict(PlayerAsset|
            # PickAsset) — there is NO "kind" discriminator — so detect by shape:
            # a resolved pick that drafted a player carries drafted_player_id; a
            # player that originated from a pick carries via_pick + player_id.
            acquired_set: set[tuple[str, str]] = set()
            traded_away_set: set[tuple[str, str]] = set()
            for rt in resolved_dicts:
                for uid, side in (rt.get("sides") or {}).items():
                    for a in (side.get("received") or []):
                        if a.get("drafted_player_id"):
                            acquired_set.add((uid, a["drafted_player_id"]))
                        elif a.get("via_pick") and a.get("player_id"):
                            acquired_set.add((uid, a["player_id"]))
                    for a in (side.get("given") or []):
                        if a.get("player_id"):
                            traded_away_set.add((uid, a["player_id"]))
                        if a.get("drafted_player_id"):
                            traded_away_set.add((uid, a["drafted_player_id"]))

            def _points(pid: str, uid: str, phase: str) -> float:
                return started_points_while_on_roster(
                    pid, uid, phase=phase,
                    matchups=supporting["matchups"],
                    roster_to_user_by_league=supporting["roster_to_user_by_league"],
                    phase_by_lwr=supporting["phase_by_lwr"],
                    playoff_week_start_by_league=supporting["playoff_week_start_by_league"],
                )

            def _games(pid: str, uid: str) -> int:
                return started_games_while_on_roster(
                    pid, uid,
                    matchups=supporting["matchups"],
                    roster_to_user_by_league=supporting["roster_to_user_by_league"],
                )

            # The cohort's own `n` (CRITICAL A) only ever counts COMPLETE
            # seasons — the committed history has no notion of a partial
            # year. seasons_held must match that, or one played week of a
            # new NFL season (a few points on the pick's side) inflates its
            # cell from n to n+1 (a much higher bar on the cohort's side) and
            # flips Hit to Bust for the entire league until that season
            # actually finishes. `completed_seasons` (nfl_state.py) confirms
            # the chain's newest season is actually over by MATCHING YEARS
            # against live `state["season"]`, not merely by asking "is the
            # NFL playing something right now" — a chain that has not yet
            # rolled over to a new league year must not read its
            # already-finished newest season as still live just because a
            # LATER NFL season has since kicked off.
            from app.services.nfl_state import completed_seasons as _completed_seasons_for

            _completed_seasons = _completed_seasons_for(
                {s for s in supporting["league_season_by_id"].values() if s},
                _nfl_state,
            )

            def _seasons(pid: str, uid: str) -> int:
                return seasons_held_while_on_roster(
                    pid, uid,
                    matchups=supporting["matchups"],
                    roster_to_user_by_league=supporting["roster_to_user_by_league"],
                    league_season_by_id=supporting["league_season_by_id"],
                    completed_seasons=_completed_seasons,
                )

            drafted_picks = build_drafted_pick_results(
                rookie_picks,
                ktc_floats=ktc_floats_dp,
                normalized_name_by_pid=normalized_name_by_pid,
                names=player_names,
                positions=positions_dp,
                extremes_by_name=extremes,
                acquired_set=acquired_set,
                points_fn=_points,
                games_fn=_games,
                current_holders=current_holders,
                traded_away_set=traded_away_set,
                adp_by_draft=adp_by_draft,
                projected_by_player=projected_by_player,
                rookie_ecr_by_draft=rookie_ecr_by_draft,
                seasons_fn=_seasons,
            )

            # Verdict is stamped here rather than inside the engine builder: the
            # builder knows nothing about cohorts, and keeping it that way stops
            # a display metric leaking into a pure engine function. Eligibility
            # (only a rookie-ECR baseline is comparable) lives in
            # rookie_cohorts.verdict_for_row, next to the cohort logic that
            # defines what a comparison even means.
            from sleeper_dynasty.engine.rookie_cohorts import verdict_for_row

            for _row in drafted_picks:
                _row["verdict"] = verdict_for_row(_row, rookie_cohorts)
        except Exception:
            log.exception("drafted-pick results computation skipped")

        # --- Dynasty outlooks + roster-value ranks (offseason-safe). ---
        dynasty_outlooks: dict[str, dict] = {}
        roster_ranks: dict[str, dict] = {}
        try:
            from sleeper_dynasty.engine.outlook_build import (
                build_outlooks_by_owner, outlook_to_dict, roster_value_ranks,
            )
            from sleeper_dynasty.models.player import build_players
            players_obj = build_players(raw_players)
            positions = supporting.get("positions") or {}
            ktc_now = supporting["ktc_by_player_id"]
            ktc_floats = {
                pid: float(v.superflex_value)
                for pid, v in ktc_now.items()
                if v is not None and v.superflex_value is not None
            }
            r2u_current = {r.roster_id: r.owner_id for r in current_rosters}
            # rv recomputed here: the earlier rv lives inside a separate try
            # block and may be unset/empty if that block threw.
            rv = {
                r.owner_id: sum(
                    float(ktc_now[p].superflex_value)
                    for p in (r.players or [])
                    if ktc_now.get(p) is not None
                    and ktc_now[p].superflex_value is not None)
                for r in current_rosters
            }
            outlooks, league_ages = build_outlooks_by_owner(
                rosters=current_rosters, players=players_obj,
                traded_picks=traded_picks, positions=positions,
                ktc_value_by_player=ktc_floats, roster_to_user=r2u_current,
                total_rosters=len(current_rosters),
                num_rounds=num_draft_rounds,
            )
            dynasty_outlooks = {
                uid: outlook_to_dict(ol, league_avg_age_by_position=league_ages)
                for uid, ol in outlooks.items()}
            roster_ranks = roster_value_ranks(rv)
        except Exception:
            log.exception("dynasty outlook stage skipped")

        # League-calendar phase (dashboard lead selector). As-of-today value
        # layer: always recomputed, even on the incremental-reuse path.
        from app.services.league_phase import derive_league_phase
        if _nfl_state is None:
            try:
                _get_state = getattr(client, "get_nfl_state", None)
                _nfl_state = await _get_state() if _get_state else None
            except Exception:
                log.exception("nfl_state fetch failed; league phase degrades "
                              "to draft/offseason rules")
        league_phase = derive_league_phase(
            nfl_state=_nfl_state,
            playoff_weeks_by_league=supporting["playoff_weeks_by_league"],
            league_season_by_id=supporting["league_season_by_id"],
            current_season=max((lg.season for lg in chain), default=0),
            drafts=current_league_drafts,
        )

        # What this league supports (redraft/keeper/dynasty + evidence-based
        # booleans). Same value-layer tier as league_phase: always recomputed,
        # even on the incremental-reuse path. Best-effort: an empty dict here
        # reads back as full dynasty (capabilities_from_dict), so a derivation
        # failure degrades gracefully instead of failing the whole refresh.
        capabilities: dict = {}
        try:
            from sleeper_dynasty.engine.capabilities import (
                capabilities_to_dict, derive_capabilities,
            )
            _current_league = next(
                (lg for lg in chain if lg.league_id == current_league_id), None)
            # Fallback is chain[0] — walk_league_history builds the chain
            # newest -> oldest (api/sleeper.py), so chain[0] is the *current*
            # season. chain[-1] would be the league's origin season, which on a
            # league that converted formats disagrees with is_redraft_chain
            # (grader_io.py), which judges by max(season). Both must name the
            # same league or the value layer and the weight tree diverge.
            if chain:
                capabilities = capabilities_to_dict(
                    derive_capabilities(
                        _current_league or chain[0],
                        chain_length=len(chain),
                        observed_pick_assets=observed_pick_assets(resolved),
                    )
                )
        except Exception:
            log.exception("capabilities derivation skipped; reads as full dynasty")

        # Draft needs ("Going in" panel): reconstructs each owner's roster as
        # it stood on the newest draft's day, decides which starting slots
        # were open holes against a league-relative ECR replacement line, and
        # checks whether the draft addressed them. Same value-layer tier as
        # capabilities/league_phase -- always recomputed, never frozen (see
        # ChainCacheEntry.draft_needs). Inferred, not measured, so it must
        # NEVER feed Franchise Rating.
        #
        # ONLY THE NEWEST GRADEABLE DRAFT CLASS IS EVER RECONSTRUCTED, and
        # `draft_needs` is rebuilt from scratch (`{}`) every refresh below --
        # never merged with the prior entry's dict. Why: the newest class is
        # the draft window, which is the whole point of this panel, and
        # reconstruction needs a real `get_roster_transactions` fetch (an
        # 18-week walk per league id), unlike the rest of this stage, which
        # is microseconds. Walking every season on every refresh would
        # multiply that fetch by chain length for a season nobody is asking
        # about.
        #
        # Consequence, stated plainly because it is easy to miss: the moment
        # a new draft becomes the newest, the PREVIOUS season's
        # already-computed, already-served panel is dropped -- not merely
        # "not recomputed for old seasons", but actively removed from what a
        # viewer previously saw. This is deliberate, not an oversight:
        # carrying a stale season forward would mean persisting output from
        # this module's hole-detection logic indefinitely, with no way to
        # tell a season graded by since-corrected logic apart from a fresh
        # one (see ChainCacheEntry.draft_needs for the full reasoning and
        # what a future per-season-retention fix would need).
        #
        # Gate: format == "dynasty" (NOT "keeper") AND roster_continuity AND
        # multiyear_history AND at least one gradeable draft class.
        #
        # Keeper looked includable at design time -- "two or three carried
        # players is a real starting position and a real set of holes" --
        # but the reconstruction that reasoning depends on cannot actually
        # be built for keeper leagues, so the exclusion is about what this
        # code can deliver, not about the question being meaningless. In a
        # keeper league, keepers enter the new season THROUGH THE DRAFT
        # (that is what `is_keeper` on a drafted pick means), and there is
        # no transaction representing the annual release of every other
        # roster spot. `roster_asof` below seeds from the prior season's
        # final-week matchup roster and mutates it only via transactions --
        # for a keeper league that returns the whole ~25-man prior roster as
        # the draft-day roster: every slot is full, nothing falls below the
        # replacement line, and the panel reads "-- . -- . --" for the whole
        # league. Confidently wrong, not absent. `_CONTINUOUS_FORMATS`
        # (`{"dynasty", "keeper"}` in engine/capabilities.py) deliberately
        # stays as-is -- other features rely on it -- so this gate adds its
        # own dynasty-only check rather than narrowing that set.
        #
        # THE OBVIOUS FIX DOES NOT WORK -- measured 2026-08-18, and this note
        # replaces the one that proposed it. "Derive the kept set from
        # `is_keeper` picks and seed `roster_asof` from that" sounds right and
        # produces the SAME empty panel, by the opposite mechanism. The
        # replacement line is `pool_sorted[min(n, len(pool)) - 1]`
        # (draft_needs.py) with no minimum-population guard, and the pool is
        # built FROM the rosters passed in. Seed with kept players only and a
        # position's pool shrinks to roughly its own demand, so the index
        # collapses onto the worst player in the pool and nobody is ever
        # strictly below it. Run directly against the engine with 12 owners
        # and one keeper each (`max_keepers` is 1 on all three real leagues):
        # 0 of 12 owners get a hole, against 6 of 12 for the same harness
        # given dynasty-shaped full rosters.
        #
        # A working version has to decouple the two populations: the SEED (who
        # is on my roster going in) can be the kept set, but the POOL the line
        # is drawn from has to stay the league's full pre-draft player universe
        # -- the prior season's rosters, which is what everyone is actually
        # drafting out of. That is a signature change to `build_draft_needs`
        # (it derives the pool from `rosters` today), not a different seed, and
        # it wants a real keeper league to validate against. None of the three
        # cached leagues is one: `settings.type` reads 2, 2, 0 -- two dynasty
        # and one redraft, no keeper (type 1).
        #
        # multiyear_history still matters on top of the format check: a
        # first-season startup dynasty league has roster_continuity=True but
        # no prior season to reconstruct a seed from -- identical to
        # redraft, and multiyear_history (chain_length > 1) is what
        # distinguishes it.
        #
        # "newest GRADEABLE draft class" -- an auction's pick_no is
        # chronological, not positional, so it is ingested with
        # gradeable=False and must never be selected as the needs class.
        draft_needs: dict[str, list[dict]] = {}
        try:
            _gradeable_draft_classes = [c for c in draft_classes if c.gradeable]
            if (capabilities.get("format") == "dynasty"
                    and capabilities.get("roster_continuity")
                    and capabilities.get("multiyear_history")
                    and _gradeable_draft_classes):
                from sleeper_dynasty.engine.draft_needs import build_draft_needs
                from sleeper_dynasty.engine.roster_asof import roster_asof
                from app.services.rookie_board_store import EcrBoardStore

                _needs_class = max(_gradeable_draft_classes, key=lambda c: c.season)
                _prior_lg = max(
                    (lg for lg in chain if lg.season < _needs_class.season),
                    key=lambda lg: lg.season, default=None,
                )
                # TWO instants, deliberately, because they answer two
                # different questions about the same draft.
                #
                # `_draft_start_dt` -- when the draft OPENED. This is what the
                # roster reconstruction below rewinds to, because the panel's
                # claim is "what this owner went in with". A slow-clock rookie
                # draft runs for DAYS (measured on the reference league: 83
                # hours in 2026 and again in 2025, 47 in 2024), and what
                # managers do during those days is clear bench room for the
                # picks they are about to make. Rewinding to `last_picked`
                # instead applied that cleanup FIRST and then read the holes:
                # 17 drops across 7 of 12 rosters inside the 2026 window --
                # Najee Harris, Cooper Kupp, Brandon Aiyuk, Mike Evans, Jaylen
                # Waddle among them, all plausible starters -- so the roster
                # came out thinner than the owner ever actually had it and
                # every slot those players vacated read as a hole they "went
                # in with". Overstating the panel's headline column.
                #
                # `_last_picked_dt` -- when the draft FINISHED, kept for the
                # ECR board pin only. That path (`resolve_for_draft`) freezes
                # write-once per draft_id and is already frozen for every
                # graded draft, so moving it would be a no-op today while
                # diverging from `adp_snapshot_store`, which pins the same
                # way off the same instant.
                _draft_start_dt: datetime | None = None
                _last_picked_dt: datetime | None = None
                for _d in drafts_by_league.get(_needs_class.league_id, []):
                    if _d.get("draft_id") == _needs_class.draft_id:
                        _lp = _d.get("last_picked") or _d.get("start_time")
                        if _lp:
                            _last_picked_dt = datetime.fromtimestamp(
                                int(_lp) / 1000, tz=timezone.utc)
                        # Reversed fallback: a draft still in progress has a
                        # start_time and only a partial last_picked, and an
                        # older one may carry last_picked alone.
                        _st = _d.get("start_time") or _d.get("last_picked")
                        if _st:
                            _draft_start_dt = datetime.fromtimestamp(
                                int(_st) / 1000, tz=timezone.utc)
                        break

                if _prior_lg is not None and _last_picked_dt is not None and cache_dir is not None:
                    _prior_league_id = _prior_lg.league_id
                    _r2u_prior = supporting["roster_to_user_by_league"].get(
                        _prior_league_id, {})

                    # Seed: the highest PLAYED week present for the PRIOR
                    # season's league, per roster, from matchups' "players" --
                    # NOT get_rosters, which is Sleeper's LIVE state and would
                    # already reflect offseason moves this reconstruction is
                    # about to apply a second time.
                    _latest_week_by_roster: dict[int, int] = {}
                    for (_lg_id, _wk, _rid) in supporting["matchups"]:
                        if _lg_id != _prior_league_id:
                            continue
                        if _wk > _latest_week_by_roster.get(_rid, -1):
                            _latest_week_by_roster[_rid] = _wk
                    _seed: dict[str, set[str]] = {}
                    for (_lg_id, _wk, _rid), _m in supporting["matchups"].items():
                        if (_lg_id != _prior_league_id
                                or _wk != _latest_week_by_roster.get(_rid)):
                            continue
                        _owner = _r2u_prior.get(_rid)
                        if _owner is None:
                            continue
                        _seed[_owner] = set(_m.get("players") or [])

                    if _seed:
                        # Every completed transaction on or before draft day,
                        # across BOTH the prior and the draft's own league id
                        # -- a rolled-over dynasty league's preseason waiver
                        # moves land under the NEW league id before week 1.
                        # `sorted(...)` over the two-element set: iteration
                        # order over a raw set is process-dependent, and
                        # while two transactions colliding on exact
                        # epoch-millis across leagues is practically
                        # unreachable, sorting costs nothing and removes the
                        # last hash-seed dependence in this stage.
                        #
                        # Sealed seasons: read `raw_roster_txs` back off the
                        # LeagueRawCache trade bundle instead of walking the
                        # client again. `_fetch_league_season_data` already
                        # fetched and cached this exact feed for any sealed
                        # league in the chain (trade_history.py) -- calling
                        # the client here unconditionally would re-do a full
                        # 18-week walk per sealed league-season on every
                        # refresh, forever, which is exactly the doubling the
                        # bundle/memo exist to prevent. Only fall back to the
                        # client when no cached bundle is available: the
                        # current/incomplete season (never cached), or a
                        # sealed season cached before `raw_roster_txs`
                        # existed (`read_trade_bundle` treats that as a miss
                        # rather than handing back zero transactions).
                        _needs_txs: list[dict] = []
                        for _lid in sorted({_prior_league_id, _needs_class.league_id}):
                            _cached_bundle = (
                                league_cache.read_trade_bundle(_lid)
                                if league_cache is not None else None
                            )
                            if _cached_bundle is not None:
                                _needs_txs.extend(_cached_bundle["raw_roster_txs"])
                                continue
                            try:
                                _needs_txs.extend(
                                    await client.get_roster_transactions(_lid))
                            except Exception:
                                log.exception(
                                    "roster transactions fetch failed for %s "
                                    "(draft-needs reconstruction)", _lid)

                        # Roster ids are not guaranteed stable across a chain
                        # rollover, but in the ordinary case (no membership
                        # churn at rollover) they are -- the draft's own
                        # season's mapping wins on any id both leagues share.
                        _r2u_needs = dict(_r2u_prior)
                        _r2u_needs.update(
                            supporting["roster_to_user_by_league"].get(
                                _needs_class.league_id, {}))

                        # The draft's OPEN, not its close -- see the two-instant
                        # note above. `_draft_start_dt` is non-None wherever
                        # `_last_picked_dt` is (they share both fallbacks), so
                        # the guard on the latter still covers this.
                        _rosters_asof = roster_asof(
                            _seed, _needs_txs, _r2u_needs,
                            as_of=_draft_start_dt or _last_picked_dt)

                        _needs_roster_positions = list(
                            supporting["roster_positions_by_league"].get(
                                _needs_class.league_id) or [])
                        _superflex_for_needs = (
                            "SUPER_FLEX" in _needs_roster_positions)
                        _board_store = (
                            EcrBoardStore.dynasty_superflex(cache_dir)
                            if _superflex_for_needs
                            else EcrBoardStore.dynasty_overall(cache_dir)
                        )
                        _board = _board_store.resolve_for_draft(
                            _needs_class.draft_id, _last_picked_dt.date())

                        if _board:
                            _picks_by_owner: dict[str, list[tuple[str, str]]] = {}
                            _started_by_pick: dict[str, int] = {}
                            _production_by_pick: dict[str, float] = {}
                            # Sorted by pick_no ascending: the capacity-capped
                            # drafted_into/started credit in
                            # engine/draft_needs.py walks each owner's picks
                            # in draft order to decide WHICH pick gets
                            # credited when a position has fewer hole slots
                            # than picks -- that only holds if this list is
                            # actually in that order. Sleeper's own API
                            # happens to return picks in pick order already,
                            # but nothing enforced it here.
                            for _row in sorted(
                                drafted_picks,
                                key=lambda r: int(r.get("pick_no") or 0),
                            ):
                                if int(_row.get("draft_season") or 0) != _needs_class.season:
                                    continue
                                # Keepers are excluded, auction picks are NOT.
                                # A keeper is a player the owner already had
                                # -- he is in the reconstructed roster AND in
                                # this pick list, so if he sits below the
                                # replacement line he CREATES the hole;
                                # counting him as having "drafted into" it
                                # would credit the owner for a decision he
                                # didn't make this draft. `gradeable=False`
                                # (auction) is a different axis entirely --
                                # it says pick_no is chronological, not that
                                # the pick didn't address a real need -- so
                                # auction picks stay in this list on purpose.
                                if _row.get("is_keeper"):
                                    continue
                                _uid = str(_row.get("drafter_id") or "")
                                _pid = str(_row.get("player_id") or "")
                                _picks_by_owner.setdefault(_uid, []).append(
                                    (_pid, str(_row.get("position") or "")))
                                _started_by_pick[_pid] = int(
                                    _row.get("games_started") or 0)
                                _production_by_pick[_pid] = float(
                                    _row.get("production_total") or 0.0)

                            # Prior-season points, in this league's own
                            # scoring -- the replacement line draws on this
                            # when present (engine/draft_needs.py's
                            # "Revision" docstring section). MUST be the
                            # PRIOR league id (`_prior_league_id`, the same
                            # one the seed above uses), never the draft's
                            # own season: for a still-unplayed season,
                            # reading it later in the year would silently
                            # become hindsight -- the exact trap ADP
                            # date-pinning already exists to avoid. Summed
                            # across every week present for that league id:
                            # `supporting["matchups"]` is keyed by
                            # (league_id, week, roster_id), one entry per
                            # roster that actually held the player that
                            # week, so a player traded mid-season accrues
                            # what he scored while rostered without any
                            # double-count. `players_points` only covers
                            # players rostered IN THIS LEAGUE that season --
                            # deliberately not widened; that's exactly why
                            # `build_draft_needs` keeps the ECR fallback.
                            _prior_points: dict[str, float] = {}
                            for (_lg_id, _wk, _rid), _m in supporting["matchups"].items():
                                if _lg_id != _prior_league_id:
                                    continue
                                for _pid, _pts in (_m.get("players_points") or {}).items():
                                    _prior_points[_pid] = (
                                        _prior_points.get(_pid, 0.0) + float(_pts or 0.0))

                            _owner_needs = build_draft_needs(
                                rosters=_rosters_asof,
                                board=_board,
                                positions=supporting.get("positions") or {},
                                roster_positions=_needs_roster_positions,
                                picks_by_owner=_picks_by_owner,
                                started_by_pick=_started_by_pick,
                                points=_prior_points,
                                production_by_pick=_production_by_pick,
                            )
                            draft_needs[str(_needs_class.season)] = [
                                {
                                    "user_id": n.user_id,
                                    "holes": n.holes,
                                    "drafted_into": n.drafted_into,
                                    "started": n.started,
                                    "drafted_into_count": n.drafted_into_count,
                                    "production": n.production,
                                    "slots": [
                                        {
                                            "slot": s.slot,
                                            "position": s.position,
                                            "margin": s.margin,
                                            "is_hole": s.is_hole,
                                            "vetoed": s.vetoed,
                                        }
                                        for s in n.slots
                                    ],
                                }
                                for n in _owner_needs
                            ]
        except Exception:
            log.exception("draft-needs computation skipped")

        # Week recap for the in-season lead (A2). Same tier as league_phase:
        # as-of-today value layer, recomputed on the incremental-reuse path too,
        # and computed from `matchups` directly rather than differenced out of
        # the (possibly frozen) production series — a figure in the lead has to
        # reconcile with the standings on the same page.
        week_recap: dict = {}
        if league_phase.get("phase") == "regular":
            try:
                from app.services.league_phase import playoff_start_by_season
                from app.services.week_recap import (
                    derive_week_recap, latest_completed_regular_week, traded_pids_by_user,
                )
                _ps_by_season = playoff_start_by_season(
                    supporting["playoff_weeks_by_league"], supporting["league_season_by_id"],
                )
                _target = latest_completed_regular_week(
                    matchups=supporting["matchups"],
                    league_season_by_id=supporting["league_season_by_id"],
                    playoff_start_by_season=_ps_by_season,
                    nfl_state=_nfl_state,
                )
                if _target:
                    _season, _week = _target
                    week_recap = derive_week_recap(
                        matchups=supporting["matchups"],
                        roster_to_user_by_league=supporting["roster_to_user_by_league"],
                        league_season_by_id=supporting["league_season_by_id"],
                        season=_season,
                        week=_week,
                        traded_pids=traded_pids_by_user(
                            resolved_dicts, season=_season, week=_week,
                            league_season_by_id=supporting["league_season_by_id"],
                        ),
                    ) or {}
            except Exception:
                log.exception("week recap stage skipped; lead keeps its placeholder")

        # Live title-path state for the postseason lead. Value layer, never
        # frozen: who is alive changes every playoff week, so reusing a prior
        # entry's copy would stall the bracket mid-postseason. Computed only
        # during the playoffs — the lead is the sole consumer, and out of
        # season the bracket is either absent or already settled.
        bracket_watch: dict = {}
        if league_phase.get("phase") == "post":
            try:
                from sleeper_dynasty.engine.playoff_phase import build_bracket_watch
                _season = int(league_phase.get("season") or 0)
                # The chain league whose season is the one being played.
                _lid = next(
                    (lid for lid, s in supporting["league_season_by_id"].items()
                     if int(s) == _season),
                    None,
                )
                if _lid:
                    # Regular-season rank as the seed. Safe to read from the
                    # frozen-rollup copy: seeding is settled before the
                    # bracket starts and cannot move during the playoffs.
                    _seeds = {
                        uid: rec.get("rank")
                        for uid, rec in
                        ((season_records_from_signals or {}).get(str(_season)) or {}).items()
                        if rec.get("rank")
                    }
                    _watch = build_bracket_watch(
                        (supporting.get("winners_bracket_by_league") or {}).get(_lid) or [],
                        (supporting.get("roster_to_user_by_league") or {}).get(_lid) or {},
                        seed_by_user=_seeds,
                    )
                    if _watch:
                        bracket_watch = {"season": _season, **_watch}
            except Exception:
                log.exception("bracket watch stage skipped; lead keeps its placeholder")

        await progress_cb("done", "Building dashboard payload")
        entry = ChainCacheEntry(
            league_id=current_league_id,
            chain=chain_summary,
            resolved_trades=resolved_dicts,
            grades=grades,
            owners=supporting["owners"],
            playoff_weeks_by_league=supporting["playoff_weeks_by_league"],
            roster_to_user_by_league=supporting["roster_to_user_by_league"],
            league_name_by_id=supporting["league_name_by_id"],
            league_season_by_id=supporting["league_season_by_id"],
            cached_at=datetime.now(tz=timezone.utc).isoformat(),
            warnings=supporting.get("warnings", []),
            trade_stories=trade_stories,
            owner_dossiers=owner_dossiers,
            current_holders=current_holders,
            became_grades=became_grades,
            outcome_signals=outcome_signals,
            outlook_signals=outlook_signals,
            lineup_signals=lineup_signals,
            draft_skill_by_season=draft_skill_by_season,
            season_records=season_records_from_signals,
            head_to_head=head_to_head,
            dynasty_outlooks=dynasty_outlooks,
            roster_ranks=roster_ranks,
            drafted_picks=drafted_picks,
            draft_needs=draft_needs,
            trade_production_series=production_payload["trade_production_series"],
            trade_production_verdict=production_payload["trade_production_verdict"],
            owner_production_series=production_payload["owner_production_series"],
            owner_production_verdict=production_payload["owner_production_verdict"],
            production_week_axis=production_payload["production_week_axis"],
            production_week_phases=production_payload["production_week_phases"],
            trade_production_players=production_payload["trade_production_players"],
            owner_production_trades=production_payload["owner_production_trades"],
            trade_injury=injury_payload["trade_injury"],
            trade_departures=injury_payload["trade_departures"],
            league_phase=league_phase,
            capabilities=capabilities,
            week_recap=week_recap,
            bracket_watch=bracket_watch,
            llm_generated_at=_llm_generated_at,
        )

        _no_key_blurbs = _llm_key_missing and _blurb_writer is None
        if skip_llm or _no_key_blurbs:
            _prev_b = (
                ChainCache(cache_dir=cache_dir).read(
                    current_league_id, max_age_seconds=10 ** 9)
                if cache_dir else None
            )
            entry.owner_rating_blurbs = (
                (getattr(_prev_b, "owner_rating_blurbs", None) or {}) if _prev_b else {}
            )
            if not skip_llm:
                await progress_cb(
                    "owner_blurbs", "Skipping GM profiles (no ANTHROPIC_API_KEY)")
        else:
            await progress_cb("owner_blurbs", "Writing GM profiles")
            try:
                from app.services.blurb_gen import (
                    generate_owner_rating_blurbs, owner_rating_facts_by_scope,
                )
                blurb_writer = _blurb_writer
                if blurb_writer is None:
                    from sleeper_dynasty.llm.gm_rating_blurb_writer import GmRatingBlurbWriter
                    blurb_writer = GmRatingBlurbWriter(model=_llm_model_override) if _llm_model_override else GmRatingBlurbWriter()  # reads ANTHROPIC_API_KEY
                prior_blurbs: dict = {}
                if cache_dir is not None:
                    from app.services.chain_cache import ChainCache
                    prev_b = ChainCache(cache_dir=cache_dir).read(
                        current_league_id, max_age_seconds=10 ** 9)
                    prior_blurbs = prev_b.owner_rating_blurbs if prev_b else {}
                facts_by_scope = owner_rating_facts_by_scope(entry)
                entry.owner_rating_blurbs = await generate_owner_rating_blurbs(
                    facts_by_scope=facts_by_scope, prior_blurbs=prior_blurbs,
                    writer=blurb_writer, progress_cb=progress_cb,
                    cost_store=_cost_store, league_id=current_league_id,
                    reuse_prior_on_throttle=_throttled,
                )
            except Exception as e:  # never fail refresh on blurb errors
                log.exception("owner rating blurb stage failed")
                entry.warnings.append(f"owner blurbs skipped: {e}")

        await progress_cb("franchise_blurbs", "Writing franchise outlooks")
        try:
            from app.services.aggregations import _format_assets_short
            from app.services.franchise_blurb_gen import generate_franchise_blurbs
            from sleeper_dynasty.engine.franchise_outlook import build_franchise_facts

            # No key + no test-injected writer -> clean skip below, same shape
            # as the budget guard. Constructing the real writer is deferred
            # into that branch so a missing key never builds one that can
            # only fail the call.
            _no_key_franchise = _llm_key_missing and _franchise_writer is None

            # Signature trade per owner = highest realized received_ktc.
            best_by_uid: dict[str, tuple[float, str]] = {}
            for rt in resolved_dicts:
                tx = rt["trade"]["transaction_id"]
                grade = grades.get(tx) or {}
                for uid, val in (grade.get("received_ktc") or {}).items():
                    v = float(val or 0)
                    if uid not in best_by_uid or v > best_by_uid[uid][0]:
                        my_side = (rt.get("sides") or {}).get(uid) or {}
                        sig = (f"received {_format_assets_short(my_side)} "
                               f"({'+' if v >= 0 else ''}{round(v)})")
                        best_by_uid[uid] = (v, sig)

            # Market value per player, so the packet's young-core / aging-risk
            # lists can be cut to the three that matter rather than the first
            # three off an arbitrarily-ordered roster walk.
            from app.services.rating_signals import _ktc_value
            fr_values = {
                pid: _ktc_value(v)
                for pid, v in (supporting.get("ktc_by_player_id") or {}).items()
            }
            # Stating the format is what stops the writer importing rules from
            # some other fantasy game (this league has no salary cap).
            fr_format = (capabilities or {}).get("format") or "dynasty"

            # The stage is derived from this league's own Franchise Rating —
            # there is no second window model any more — and banded on this
            # league's OWN realized rating spread, by the one shared helper the
            # standings row and the owner page also go through. `entry` is
            # already constructed above. An owner with no completed season is
            # absent from the map and gets "", which FranchiseFacts.to_dict
            # prunes.
            from app.services.franchise_redesign import stage_by_owner
            try:
                _fr_stage = stage_by_owner(entry)
            except Exception:
                log.exception("stage derivation skipped; packets carry no window")
                _fr_stage = {}

            facts_by_owner = {}
            for uid, ol in dynasty_outlooks.items():
                owner = entry.owners.get(uid, {})
                facts_by_owner[uid] = build_franchise_facts(
                    user_id=uid,
                    owner_name=owner.get("owner_name") or uid,
                    team_name=owner.get("team_name"),
                    outlook=ol,
                    roster_rank=roster_ranks.get(uid),
                    signature_trade=(best_by_uid.get(uid) or (0, None))[1],
                    window=_fr_stage.get(uid, ""),
                    league_format=fr_format,
                    # The same signal the Assets pillar scores — so the prose
                    # and the grade can never disagree about who is young.
                    young_core_share=(
                        outlook_signals.get(uid) or {}).get("young_core_share"),
                    value_by_player=fr_values)

            prior_fr: dict = {}
            if cache_dir is not None:
                from app.services.chain_cache import ChainCache
                prev_fr = ChainCache(cache_dir=cache_dir).read(
                    current_league_id, max_age_seconds=10 ** 9)
                prior_fr = prev_fr.franchise_blurbs if prev_fr else {}

            if skip_llm or _no_key_franchise:
                # Budget guard or no API key configured: reuse prior
                # franchise prose, generate nothing.
                entry.franchise_blurbs = prior_fr
                if not skip_llm:
                    await progress_cb(
                        "franchise_blurbs",
                        "Skipping franchise outlooks (no ANTHROPIC_API_KEY)")
            else:
                fr_writer = _franchise_writer
                if fr_writer is None:
                    from sleeper_dynasty.llm.franchise_outlook_writer import (
                        FranchiseOutlookWriter,
                    )
                    fr_writer = FranchiseOutlookWriter(model=_llm_model_override) if _llm_model_override else FranchiseOutlookWriter()  # reads ANTHROPIC_API_KEY
                entry.franchise_blurbs = await generate_franchise_blurbs(
                    facts_by_owner=facts_by_owner, prior_blurbs=prior_fr,
                    writer=fr_writer, progress_cb=progress_cb,
                    cost_store=_cost_store, league_id=current_league_id,
                    reuse_prior_on_throttle=_throttled,
                )
        except Exception as e:  # never fail refresh on blurb errors
            log.exception("franchise blurb stage failed")
            entry.warnings.append(f"franchise blurbs skipped: {e}")

        return entry

    async def _compute_became(
        self,
        *,
        resolved: list,
        resolved_dicts: list[dict],
        supporting: dict[str, Any],
        current_league_id: str,
        cache_dir: Path | None,
        progress_cb: ProgressCallback,
    ) -> dict[str, dict[str, Any]]:
        """Compute the per-trade "became" grade (value + production of the
        bounded walk's terminal players), mirroring the trade-stories stage:
        eager during refresh, cached, and incrementally skipped when a trade's
        terminal set is unchanged. Best-effort — a failure logs and leaves that
        trade's became empty; it never fails the refresh.
        """
        await progress_cb("became", "Grading what trades became")
        try:
            import hashlib
            import json as _json

            from sleeper_dynasty.engine.lineage import terminal_assets
            from sleeper_dynasty.engine.regrade import build_became_grade

            prior: dict[str, dict] = {}
            if cache_dir is not None:
                from app.services.chain_cache import ChainCache
                prev = ChainCache(cache_dir=cache_dir).read(
                    current_league_id, max_age_seconds=10 ** 9)
                prior = prev.became_grades if prev else {}

            became: dict[str, dict[str, Any]] = {}
            for rt in resolved:
                tx = rt.trade.transaction_id
                try:
                    terms = terminal_assets(resolved_dicts, tx)
                    # Include current pick values for any terminal picks in the
                    # hash so a price-table update invalidates the cache entry.
                    pick_table = supporting.get("pick_value_table") or {}
                    pick_vals = {
                        f"{t['season']},{t['round']}": getattr(
                            pick_table.get((t["season"], t["round"])),
                            "superflex_value", None)
                        for uid_terms in terms.values()
                        for t in uid_terms
                        if t.get("kind") == "pick"
                           and t.get("season") is not None
                           and t.get("round") is not None
                    }
                    blob = _json.dumps(
                        {"terms": terms, "pick_vals": pick_vals},
                        sort_keys=True).encode()
                    h = hashlib.sha256(blob).hexdigest()[:16]
                    prev_entry = prior.get(tx)
                    if prev_entry and prev_entry.get("terminal_hash") == h:
                        became[tx] = prev_entry  # incremental skip
                        continue
                    trade_dict = next(
                        r for r in resolved_dicts
                        if r["trade"]["transaction_id"] == tx)
                    grades = build_became_grade(
                        trade_dict, resolved_dicts,
                        matchups=supporting["matchups"],
                        roster_to_user_by_league=supporting["roster_to_user_by_league"],
                        phase_by_lwr=supporting["phase_by_lwr"],
                        playoff_week_start_by_league=supporting["playoff_week_start_by_league"],
                        league_season_by_id=supporting["league_season_by_id"],
                        ktc_values=supporting["ktc_by_player_id"],
                        pick_values=supporting["pick_value_table"],
                        fmt="superflex",
                    )
                    became[tx] = {"terminal_hash": h, "grades": grades}
                except Exception:
                    log.exception("became grade failed for trade %s", tx)
                    became[tx] = {"terminal_hash": "", "grades": {}}
            return became
        except Exception as e:  # never fail refresh on became errors
            log.exception("became grade stage failed")
            supporting.setdefault("warnings", []).append(
                f"became grades skipped: {e}")
            return {}

    def _snapshot_standings(
        self,
        *,
        supporting: dict,
        current_league_id: str,
        cache_dir,
        current_rosters: list | None = None,
    ) -> None:
        """Reconstruct per-week regular-season standings for every league-season in
        the chain and persist them under the entry league. Best-effort: any failure
        logs and is swallowed so refresh never fails on standings.

        When ``current_rosters`` (Sleeper's authoritative ``Roster`` records for the
        current league) are supplied, the current league's latest reconstructed week
        is validated against them and any deltas are logged (never raised) — a safety
        net for leagues whose standings need extra handling (median/division scoring).
        """
        if cache_dir is None:
            return
        try:
            from sleeper_dynasty.engine.standings import (
                standings_history,
                validate_against_roster,
            )

            from app.services.standings_snapshot_store import StandingsSnapshotStore

            matchups = supporting.get("matchups") or {}
            r2u_by_league = supporting.get("roster_to_user_by_league") or {}
            season_by_league = supporting.get("league_season_by_id") or {}
            pws_by_league = supporting.get("playoff_week_start_by_league") or {}

            merged: dict[str, list[dict]] = {}
            current_league_rows_by_key: dict[str, list] = {}
            for league_id, season in season_by_league.items():
                hist = standings_history(
                    matchups,
                    league_id=league_id,
                    season=int(season),
                    playoff_week_start=int(pws_by_league.get(league_id, 15)),
                    roster_to_user=r2u_by_league.get(league_id, {}),
                )
                for week_key, rows in hist.items():
                    merged[week_key] = [asdict(r) for r in rows]
                if league_id == current_league_id:
                    current_league_rows_by_key = hist

            if merged:
                StandingsSnapshotStore(cache_dir=cache_dir).write_many(
                    current_league_id, merged
                )
                log.info(
                    "snapshotted standings for league %s (%d weeks)",
                    current_league_id, len(merged),
                )

            # Best-effort current-league validation against Sleeper's records.
            if current_rosters and current_league_rows_by_key:
                latest_key = max(current_league_rows_by_key)
                latest_rows = current_league_rows_by_key[latest_key]
                if latest_rows:
                    deltas = validate_against_roster(latest_rows, current_rosters)
                    if deltas:
                        log.warning(
                            "standings reconstruction mismatch for league %s: %s",
                            current_league_id, deltas,
                        )
        except Exception:
            log.exception("standings snapshot skipped for league %s", current_league_id)
