"""Select a checked media stage using an existing API-recorded preview approval."""
import argparse
import json
import asyncio
from app.db.engine import get_sessionmaker, dispose_engine
from app.services.generation.store import Held, Conflict
from app.services.recap_video.publication import select_publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episode-id')
    parser.add_argument('--expected-authority-revision', type=int)
    parser.add_argument('--media-id', help='Succeeded media_check stage ID with checked public derivatives')
    parser.add_argument('--approval-id', help='Persisted current finished-preview approval ID')
    for old in ('cache-dir','league-id','season','week','revision','duration-seconds','bundle'):
        parser.add_argument('--'+old, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (not args.episode_id or args.expected_authority_revision is None or not args.media_id or not args.approval_id
            or any(getattr(args, old) is not None for old in ('cache_dir','league_id','season','week','revision','duration_seconds','bundle'))):
        parser.error('Folder publication is retired. Existing published bundles use app.reconcile_recap_publication. '
            'For new media, finish the API media_check stage and obtain a scoped preview approval; pass '
            '--episode-id, --expected-authority-revision, --media-id and --approval-id. No paid regeneration is required for reconciliation.')
    async def publish():
        try:
            async with get_sessionmaker().begin() as db:
                return await select_publication(db, args.episode_id, args.expected_authority_revision,
                    args.media_id, {'approval_id':args.approval_id})
        finally:
            await dispose_engine()
    try:
        manifest = asyncio.run(publish())
    except (Held, Conflict, OSError, ValueError) as error:
        parser.exit(1, f'Media was not selected: {error}\nReload the current preview, authority revision and approval.\n')
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
