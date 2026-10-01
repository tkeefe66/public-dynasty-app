"""Import saved prose with paid work paused; prints counts, hashes and conflicts."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


async def run(cache_dir):
    from app.services.generation.migration import reconcile_legacy
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    url = os.environ.get("TRADE_GRADER_DATABASE_URL")
    if not url:
        raise ValueError("Set TRADE_GRADER_DATABASE_URL to the explicit migration target first")
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine).begin() as db:
            return await reconcile_legacy(db, cache_dir)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run(args.cache_dir))
    print(json.dumps(report, indent=2))
    raise SystemExit(1 if report["blocked"] or report["conflicts"] else 0)
