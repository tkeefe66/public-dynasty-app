"""Wire KtcSnapshotStore into the engine's realized-value price providers.

Builds two memoized callables — price_player / price_pick — that the engine's
``realized_received_values`` uses to value an asset at a flip date (or today).
Dated snapshots are resolved once per distinct date. When no snapshot exists for
a flip date (e.g. before the snapshot history began), falls back to today's
tables — the best available price — accepting that pre-history flips can't be
frozen exactly.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from app.services.at_trade import BACKFILL_CUTOFF
from app.services.grader_io import resolve_ktc_to_player_id
from sleeper_dynasty.api.ktc import build_pick_value_table
from sleeper_dynasty.engine.lineage import realized_received_values


def _sf(v) -> float:
    if v is None:
        return 0.0
    sf = getattr(v, "superflex_value", None)
    return float(sf) if sf is not None else 0.0


def make_price_providers(
    *, store, raw_players, today_ktc_by_pid, today_pick_table, cutoff=None,
) -> tuple[Callable[[str, str | None], float], Callable[[int, int, str | None], float]]:
    if cutoff is None:
        cutoff = BACKFILL_CUTOFF
    cache: dict[date, tuple[dict, dict]] = {}

    def _tables(d_iso: str | None):
        if d_iso is None:
            return today_ktc_by_pid, today_pick_table
        d = date.fromisoformat(d_iso[:10])
        if d not in cache:
            snap, _, _ = store.match(d, cutoff)
            if snap is None:
                cache[d] = (today_ktc_by_pid, today_pick_table)  # fallback to today
            else:
                cache[d] = (resolve_ktc_to_player_id(snap, raw_players),
                            build_pick_value_table(snap))
        return cache[d]

    def price_player(pid: str, d_iso: str | None) -> float:
        ktc, _ = _tables(d_iso)
        return _sf(ktc.get(pid))

    def price_pick(season: int, rnd: int, d_iso: str | None) -> float:
        _, pick_table = _tables(d_iso)
        return _sf(pick_table.get((season, rnd)))

    return price_player, price_pick


def compute_realized(
    resolved_dicts: list[dict],
    *,
    current_holders: dict[str, str],
    price_player: Callable[[str, str | None], float],
    price_pick: Callable[[int, int, str | None], float],
) -> dict[str, dict[str, list[float]]]:
    """Compute per-asset realized values for every trade in resolved_dicts.

    Returns ``{transaction_id: {user_id: [per-received-asset realized value, ...]}}``.
    """
    out: dict[str, dict[str, list[float]]] = {}
    # realized_received_values rebuilds the given-index per call; that's O(N) per
    # trade, O(N^2) over the chain. Fine for real chains (tens–low-hundreds of
    # trades); revisit only if chains grow large.
    for rt in resolved_dicts:
        tx = rt["trade"]["transaction_id"]
        out[tx] = realized_received_values(
            resolved_dicts, tx, current_holders, price_player, price_pick)
    return out
