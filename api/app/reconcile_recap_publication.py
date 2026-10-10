"""Dry-run-first legacy authority migration; never changes tokens or media files."""
import argparse
import asyncio
import json
from pathlib import Path

from app.db.engine import get_sessionmaker, dispose_engine
from app.services.generation.store import Held
from app.services.recap_video.publication import reconcile_legacy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    parser.add_argument('--serving-epoch', default='')
    args = parser.parse_args()
    async def run():
        try:
            async with get_sessionmaker().begin() as db:
                return await reconcile_legacy(db, args.cache_dir, apply=args.apply,
                    expected_digest=args.expected_digest, epoch=args.serving_epoch)
        finally:
            await dispose_engine()
    try:
        result = asyncio.run(run())
    except (Held, OSError, ValueError):
        parser.exit(1, 'Legacy reconciliation did not apply. Run dry-run again, quarantine public serving, '
            'then supply its exact digest and a fresh external serving epoch. Never switch back to legacy after DB activation.\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
