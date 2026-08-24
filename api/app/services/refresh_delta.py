"""Cheap delta detection between a prior ChainCacheEntry and a fresh trade pull.

Used to decide whether a refresh can reuse the prior entry's frozen historical
rollups (production series, injury, historical rating signals) instead of
recomputing them. Trades are keyed by stable Sleeper transaction_id.
"""
from __future__ import annotations

from app.services.chain_cache import ChainCacheEntry


def prior_transaction_ids(prior: ChainCacheEntry | None) -> set[str]:
    if prior is None:
        return set()
    out: set[str] = set()
    for rt in prior.resolved_trades or []:
        tx = (rt.get("trade") or {}).get("transaction_id")
        if tx:
            out.add(str(tx))
    return out


def new_transaction_ids(
    resolved_dicts: list[dict], prior: ChainCacheEntry | None
) -> set[str]:
    prior_ids = prior_transaction_ids(prior)
    out: set[str] = set()
    for rt in resolved_dicts:
        tx = (rt.get("trade") or {}).get("transaction_id")
        if tx and str(tx) not in prior_ids:
            out.add(str(tx))
    return out
