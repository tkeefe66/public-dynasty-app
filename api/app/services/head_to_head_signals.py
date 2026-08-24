"""Compute chain-wide head-to-head records from refresh data.

Bridges the refresh ``supporting`` bundle to the pure engine rollup: per-league
regular-season records (``head_to_head_records``) aggregated across the chain by
owner id (``aggregate_head_to_head``). Returns plain nested dicts so the result
serializes straight onto the ChainCache JSON blob.
"""

from __future__ import annotations

from dataclasses import asdict

from sleeper_dynasty.engine.head_to_head import (
    aggregate_head_to_head,
    head_to_head_records,
)


def compute_head_to_head(supporting: dict) -> dict[str, dict[str, dict]]:
    """Return ``owner_id -> {opponent_owner_id: record-dict}`` across the chain."""
    matchups = supporting.get("matchups") or {}
    r2u_by_league = supporting.get("roster_to_user_by_league") or {}
    season_by_league = supporting.get("league_season_by_id") or {}
    pws_by_league = supporting.get("playoff_week_start_by_league") or {}

    per_league = [
        head_to_head_records(
            matchups, league_id=lg,
            roster_to_user=r2u_by_league.get(lg, {}),
            playoff_week_start=int(pws_by_league.get(lg, 15)),
        )
        for lg in season_by_league
    ]
    aggregated = aggregate_head_to_head(per_league)
    return {
        owner: {opp: asdict(rec) for opp, rec in opps.items()}
        for owner, opps in aggregated.items()
    }
