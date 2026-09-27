"""Signed-in user's Yahoo connection; callback exchange is server-to-server."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.config import get_settings
from app.db.models import User, YahooConnection
from app.db.session import get_db
from app.ratelimit import limiter
from app.repositories import memberships
from app.services.yahoo_connection import YahooConnectionService, configured
from app.services.yahoo_discovery import discover

router = APIRouter(prefix="/api/me/yahoo")


class Callback(BaseModel):
    state: str = Field(min_length=32, max_length=256)
    code: str = Field(min_length=1, max_length=4096)


@router.get("/status")
async def status(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not configured():
        return {"configured": False, "status": "unavailable"}
    row = await db.get(YahooConnection, user.id)
    return {"configured": True, "status": row.status if row else "disconnected"}


@router.post("/start")
@limiter.limit(get_settings().rate_limit_discovery)
async def start(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return {"authorization_url": await YahooConnectionService(db).start(user.id)}


@router.post("/complete")
@limiter.limit(get_settings().rate_limit_discovery)
async def complete(
    request: Request,
    body: Callback,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await YahooConnectionService(db).complete(user.id, body.state, body.code)
    return {"status": "connected"}


@router.delete("/connection")
async def disconnect(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await YahooConnectionService(db).disconnect(user.id)
    return {"status": "disconnected"}


@router.get("/leagues")
@limiter.limit(get_settings().rate_limit_discovery)
async def leagues(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await discover(db, user.id)
    imported = {m.league_id for m in await memberships.list_for_user(db, user.id)}
    return [
        {**league, "already_imported": league["league_id"] in imported}
        for league in result
    ]
