"""Pageview telemetry capture. User-scoped (get_current_user, which also stamps
active-days), NOT league-gated. Fed by the web app's client beacon."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.ratelimit import limiter
from app.repositories import events

router = APIRouter()


class EventReq(BaseModel):
    path: str


@router.post("/api/events", status_code=204)
@limiter.limit(get_settings().rate_limit_default)
async def capture_event(
    request: Request,
    body: EventReq,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    path = (body.path or "").strip()
    if path:
        await events.record_event(db, user_id=user.id, path=path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
