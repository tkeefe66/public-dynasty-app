"""Members submit durable free refreshes; GET only observes saved progress."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from app.auth.deps import require_league_member
from app.config import get_settings
from app.db.models import YahooConnection, YahooLeagueGrant
from app.db.session import get_db
from app.ratelimit import limiter
from app.services.generation.commands import submit_refresh
from app.services.generation.models import GenerationOperation, stamp
from app.services.generation.policy import StrictModel
from app.services.generation.store import Conflict

router = APIRouter()


class RefreshRequest(StrictModel):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


def public_job(job):
    progress = json.loads(job.progress_json)
    return {"id": job.id, "state": job.state, "reason": job.reason,
            "created_at": job.created_at, "updated_at": job.updated_at,
            "progress": {key: progress[key] for key in ("stage", "message", "done", "total") if key in progress}}


@router.get("/api/league/{league_id}/refresh")
async def legacy_refresh(league_id: str):
    raise HTTPException(410, "Refresh now uses durable jobs. Reload the app and submit a refresh.")


@router.post("/api/league/{league_id}/refresh-jobs", status_code=202)
@limiter.limit(get_settings().rate_limit_discovery)
async def submit(request: Request, league_id: str, body: RefreshRequest,
                 user: Annotated[object, Depends(require_league_member)],
                 db: Annotated[object, Depends(get_db)]):
    if ".l." in league_id:
        connection = await db.get(YahooConnection, user.id)
        grant = await db.get(YahooLeagueGrant, (user.id, league_id))
        if not connection or connection.status != "connected":
            raise HTTPException(409, "Yahoo connection needs verification. Reconnect from Add a league.")
        if not grant or grant.generation != connection.generation or grant.expires_at <= stamp():
            from app.services.yahoo_connection import YahooConnectionService
            await YahooConnectionService(db).ensure_grant(user.id, league_id)
    try:
        job = await submit_refresh(db, league_id, user.id, idempotency_key=body.idempotency_key)
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return public_job(job)


@router.get("/api/league/{league_id}/refresh-jobs/{job_id}")
async def status(league_id: str, job_id: str, db: Annotated[object, Depends(get_db)]):
    job = await db.get(GenerationOperation, job_id)
    if not job or job.league_id != league_id or job.kind not in ("refresh", "analyst_refresh"):
        raise HTTPException(404, "Refresh job not found for this league")
    return public_job(job)
