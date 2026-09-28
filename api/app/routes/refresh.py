from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.auth.deps import require_league_member
from app.config import get_settings
from app.db.session import get_db
from app.deps import get_cache_dir
from app.ratelimit import limiter
from app.services.platform_client import YahooCredentialsMissing, connected_client
from app.services.refresh_service import refresh_league
from sleeper_dynasty.api.yahoo import YahooRateLimitError

log = logging.getLogger(__name__)
router = APIRouter()


def _cache_dir() -> Path:
    return get_cache_dir()


@router.get("/api/league/{league_id}/refresh")
@limiter.limit(get_settings().rate_limit_discovery)
async def refresh(
    request: Request, league_id: str,
    user: Annotated[object, Depends(require_league_member)],
    db: Annotated[object, Depends(get_db)],
    force: bool = Query(False),
) -> EventSourceResponse:
    try:
        client = await connected_client(league_id, db=db, user_id=user.id)
    except YahooCredentialsMissing as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_stream():
        # Live progress: the grader pushes events onto the queue as they happen
        # and this generator forwards them immediately (no buffering), so the
        # client's progress modal ticks through stages in real time.
        queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()

        async def progress_cb(stage: str, message: str, **extra):
            await queue.put(
                {"event": "progress",
                 "data": json.dumps({"stage": stage, "message": message, **extra})}
            )

        async def run():
            try:
                await refresh_league(
                    client, league_id, cache_dir=_cache_dir(),
                    force=force, progress_cb=progress_cb,
                )
                await queue.put(
                    {"event": "done", "data": json.dumps({"stage": "done"})}
                )
            except YahooRateLimitError:
                log.warning("refresh paused by Yahoo request limit for %s", league_id)
                await queue.put(
                    {"event": "error", "data": json.dumps(
                        {"stage": "error", "error_code": "yahoo_rate_limited"}
                    )}
                )
            except Exception as e:  # noqa: BLE001 — surfaced to the client
                log.exception("refresh failed")
                await queue.put(
                    {"event": "error",
                     "data": json.dumps({"stage": "error", "message": str(e)})}
                )
            finally:
                await queue.put(_DONE)

        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is _DONE:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()
            await client.close()

    return EventSourceResponse(event_stream())
