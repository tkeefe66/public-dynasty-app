"""Compare Franchise Rating models for one league chain.

Prints every owner's rating + letter under the current (legacy) rating and the
two redesign candidates (Results-primary, Two-equal-axes), sorted by Model 1.

The league must already be refreshed locally on schema 15+ (so the cached entry
carries lineup_signals). Run a refresh first if the lineup column reads 0.

Usage:
    python scripts/compare_franchise_models.py <league_id> [--cache-dir DIR]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.services.chain_cache import ChainCache
from app.services.franchise_redesign import compute_redesign_ratings
from app.services.identity import owner_name
from app.services.leaderboard import all_time_ratings
from sleeper_dynasty.engine.gm_rating import rating_to_letter


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("league_id")
    ap.add_argument(
        "--cache-dir",
        default=os.environ.get(
            "TRADE_GRADER_CACHE_DIR",
            str(Path.home() / ".sleeper-dynasty" / "cache"),
        ),
    )
    args = ap.parse_args()

    entry = ChainCache(cache_dir=Path(args.cache_dir)).read(
        args.league_id, max_age_seconds=10**12
    )
    if entry is None:
        raise SystemExit(
            f"No cached chain for league {args.league_id} on the current schema. "
            f"Refresh the league first (GET /api/league/{args.league_id}/refresh)."
        )

    current = all_time_ratings(entry)
    m1 = compute_redesign_ratings(entry, "results_primary")
    m2 = compute_redesign_ratings(entry, "equal_axes")

    def cell(uid: str, ratings: dict) -> str:
        if uid not in ratings:
            return "    —    "
        r = ratings[uid]["rating"] if isinstance(ratings[uid], dict) else ratings[uid]
        return f"{r:>4} {rating_to_letter(r):<2}"

    rows = sorted(
        entry.owners, key=lambda u: m1[u]["rating"] if u in m1 else 0, reverse=True
    )
    header = f"{'Owner':<22}{'Current':>11}{'Model1 R-prim':>15}{'Model2 Equal':>15}"
    print(header)
    print("-" * len(header))
    for uid in rows:
        name = (owner_name(entry, uid) or uid)[:21]
        print(f"{name:<22}{cell(uid, current):>11}{cell(uid, m1):>15}{cell(uid, m2):>15}")


if __name__ == "__main__":
    main()
