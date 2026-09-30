"""Check completed-week editions without waiting for full league grading."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

from app.services.analyst import generate_analyst
from app.services.refresh_service import _member_league_ids
from sleeper_dynasty.api.sleeper import SleeperClient

log = logging.getLogger(__name__)
CHECK_INTERVAL_SECONDS = 15 * 60


async def generate_member_editions(cache_dir: Path) -> None:
    ids = [lid for lid in await _member_league_ids() if lid.isdigit()]
    limit = asyncio.Semaphore(3)

    async def generate(lid):
        async with limit:
            client = SleeperClient()
            try:
                await generate_analyst(client, SimpleNamespace(league_id=lid), cache_dir)
            except Exception:
                log.exception("Analyst scheduler failed for league=%s; retry on next check", lid)
            finally:
                try:
                    await client.close()
                except Exception:
                    log.exception("Analyst scheduler client cleanup failed for league=%s", lid)

    await asyncio.gather(*(generate(lid) for lid in ids))


async def analyst_loop(cache_dir: Path) -> None:
    """Publication starts after the upstream week rollover and complete results.

    Check every 15 minutes, including overnight Monday/Tuesday. AI failures
    publish a results edition; saved editions are never regenerated.
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
