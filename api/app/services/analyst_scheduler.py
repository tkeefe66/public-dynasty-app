"""Check completed-week editions without waiting for full league grading."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)
CHECK_INTERVAL_SECONDS = 15 * 60


async def generate_member_editions(cache_dir: Path) -> None:
    from app.services.generation.scheduler import enqueue_members
    await enqueue_members(kind="analyst_refresh")


async def analyst_loop(cache_dir: Path) -> None:
    """Publication starts after the upstream week rollover and complete results.

    Check every 15 minutes, including overnight Monday/Tuesday. AI failures
    publish a results edition while bounded retries pursue a reviewed roast.
    """
    try:
        await asyncio.sleep(2)
        while True:
            try:
                await generate_member_editions(cache_dir)
            except Exception:
                log.exception("Analyst scheduler cycle failed; retry in 15 minutes")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        log.info("Analyst scheduler cancelled")
        raise
