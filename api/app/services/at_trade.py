"""At-trade KTC valuation: value each trade against the snapshot matched to its date."""

from __future__ import annotations

from datetime import date

from app.services.grader_io import resolve_ktc_to_player_id
from sleeper_dynasty.api.ktc import build_pick_value_table
from sleeper_dynasty.engine.trade_grader import grade_snapshot_value

# Trades on/after this date may be backfilled with today's snapshot (post-draft,
# values settled). Earlier trades stay blank — FA + the NFL draft moved KTC.
BACKFILL_CUTOFF = date(2026, 5, 1)


def compute_at_trade(resolved_trades, raw_players, store, cutoff=None):
    """Return {transaction_id: {at_trade_value_swing|None, at_trade_approx, at_trade_snapshot_date}}.

    Picks are valued as picks (dated pick table), never the drafted player.
    Dated tables are built once per distinct trade date.

    ``cutoff`` defaults to the module-level ``BACKFILL_CUTOFF`` resolved at call
    time (so it stays patchable in tests).
    """
    if cutoff is None:
        cutoff = BACKFILL_CUTOFF
    by_date: dict[date, tuple] = {}
    out: dict[str, dict] = {}
    for rt in resolved_trades:
        d = rt.trade.traded_at.date()
        if d not in by_date:
            snap, snap_date, approx = store.match(d, cutoff)
            if snap is None:
                by_date[d] = (None, None, None, False)
            else:
                ktc_by_pid = resolve_ktc_to_player_id(snap, raw_players)
                pick_table = build_pick_value_table(snap)
                by_date[d] = (ktc_by_pid, pick_table, snap_date, approx)
        ktc_by_pid, pick_table, snap_date, approx = by_date[d]
        tx = rt.trade.transaction_id
        if ktc_by_pid is None:
            out[tx] = {"at_trade_value_swing": None, "at_trade_approx": False,
                       "at_trade_snapshot_date": None}
        else:
            swing = grade_snapshot_value(rt, ktc_by_pid, fmt="superflex",
                                         pick_values=pick_table, ignore_drafted_player=True)
            out[tx] = {"at_trade_value_swing": swing, "at_trade_approx": approx,
                       "at_trade_snapshot_date": snap_date.isoformat()}
    return out
