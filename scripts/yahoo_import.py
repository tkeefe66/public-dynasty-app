"""Run a private, local Yahoo import without AI calls or production writes.

Set YAHOO_DEV_TOKEN_FILE and YAHOO_DEV_LEAGUE_KEY after yahoo_dev_token.py.
By default only the current season is imported. --seasons N follows N renewals;
--all-history follows the complete chain. Yahoo can hide manager identities,
so historical teams remain separate unless a stable manager ID is available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "api"), str(ROOT / "scripts")]

from app.services.chain_cache import ChainCache
from app.services.franchise_redesign import model_for
from app.services.grader import GraderService
from app.services.leaderboard import all_time_ratings, compute_season_ratings
from record_yahoo_fixtures import load_access_token

from sleeper_dynasty.api.yahoo import (
    YahooAdapter,
    YahooAuthenticationError,
    YahooDataError,
)


async def run_import(token, league_key, *, seasons=1):
    # Every output belongs to a new private directory, never production cache.
    cache_dir = Path(tempfile.mkdtemp(prefix="yahoo-grade-"))
    os.chmod(cache_dir, 0o700)
    print(f"Private import directory: {cache_dir}", flush=True)
    client = YahooAdapter(token, max_seasons=seasons)

    async def progress(stage, message, **extra):
        print(f"{stage}: {message}", flush=True)

    try:
        entry = await GraderService().run(
            client=client,
            current_league_id=league_key,
            cache_dir=cache_dir,
            progress_cb=progress,
            skip_llm=True,
        )
        entry.season_ratings = compute_season_ratings(entry)
        # The shared grader labels skip_llm as budget exhaustion; this command
        # disabled AI deliberately, independent of the account's real budget.
        entry.warnings = [
            w for w in entry.warnings if w != "LLM skipped: monthly budget reached"
        ]
        entry.warnings.append("AI prose disabled for this local import.")
        ChainCache(cache_dir).write(league_key, entry)
        persisted = ChainCache(cache_dir).read(league_key)
        if persisted is None:
            raise YahooDataError("The local import could not be read back from disk.")
        print(
            json.dumps(
                {
                    "seasons": len(persisted.chain),
                    "teams_across_seasons": len(persisted.owners),
                    "trades": len(persisted.resolved_trades),
                    "draft_picks": len(persisted.drafted_picks),
                    "capabilities": persisted.capabilities,
                    "rating_model": model_for(persisted),
                    "rated_owners": len(all_time_ratings(persisted)),
                    "lineup_metrics": len(persisted.lineup_signals),
                    "warnings": persisted.warnings,
                },
                indent=2,
            )
        )
        return cache_dir
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seasons", type=int, default=1)
    group.add_argument("--all-history", action="store_true")
    args = parser.parse_args()
    if args.seasons < 1:
        parser.error("--seasons must be positive")
    key = os.environ.get("YAHOO_DEV_LEAGUE_KEY", "").strip()
    if not re.fullmatch(r"\d+\.l\.\d+", key):
        parser.error(
            "Set YAHOO_DEV_LEAGUE_KEY to the numeric game/league key returned by yahoo_dev_token.py."
        )
    token = load_access_token()
    if not token:
        parser.error(
            "Set YAHOO_DEV_TOKEN_FILE after running scripts/yahoo_dev_token.py."
        )
    os.umask(0o077)
    try:
        asyncio.run(
            run_import(token, key, seasons=None if args.all_history else args.seasons)
        )
    except (YahooDataError, YahooAuthenticationError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
