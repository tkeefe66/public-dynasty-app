"""Validate saved GM profile recovery; pass --apply to publish without AI calls."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


async def run(args: argparse.Namespace) -> list[dict]:
    from app.db.engine import get_sessionmaker
    from app.services.generation.saved_profiles import recover_saved_profile

    reports = []
    async with get_sessionmaker()() as db, db.begin():
        for spec in args.job:
            job_id, generation = spec.rsplit(":", 1)
            artifact = await recover_saved_profile(
                db,
                job_id,
                expected_generation=int(generation),
                actor=args.actor,
                reason=args.reason,
            )
            payload = json.loads(artifact.payload_json)
            reports.append(
                {
                    "job_id": job_id,
                    "applied": args.apply,
                    "artifact_id": artifact.id if args.apply else None,
                    "payload": payload,
                    "new_requests": 0,
                }
            )
        if not args.apply:
            await db.rollback()
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--job", action="append", required=True, metavar="ID:GENERATION"
    )
    parser.add_argument("--actor", required=True, help="Existing admin user ID")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(run(args)), indent=2))
    except Exception as exc:
        logging.getLogger(__name__).exception(
            "Saved profile recovery did not finish cleanly"
        )
        parser.exit(
            1,
            f"Saved profile recovery failed: {exc}. Inspect current jobs and receipts before trying again.\n",
        )
