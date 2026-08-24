"""Current NFL week for the TopBar week note (followup C2).

User-scoped (``get_current_user``, which also stamps active-days), NOT
league-gated — the note is app chrome and shows before any league is picked, so
this must never 409 on a cold cache the way the dashboard endpoints do. Mirrors
``/api/events``' auth shape.

Upstream failure is a 200 with null fields, not an error: the note's contract is
to render nothing when the week is unknown, and a 502 here would put a red
error in the chrome of an otherwise working page.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.db.models import User
# Imported as a module (not `from … import fetch_state`) so the memo and the
# fetch can be substituted in tests without the route holding a stale binding.
from app.services import nfl_state as state_service

router = APIRouter()


class NflStateResp(BaseModel):
    """Sleeper's ``/state/nfl``, narrowed to what the chrome needs. Every field
    is nullable — unknown state renders nothing."""

    season: str | None = None
    season_type: str | None = None
    week: int | None = None


@router.get("/api/nfl-state", response_model=NflStateResp)
async def nfl_state(user: User = Depends(get_current_user)) -> NflStateResp:
    state = await state_service.fetch_state()
    if not state:
        return NflStateResp()
    try:
        week = int(state.get("week")) if state.get("week") is not None else None
    except (TypeError, ValueError):
        week = None
    season = state.get("season")
    season_type = state.get("season_type")
    return NflStateResp(
        season=str(season) if season is not None else None,
        season_type=str(season_type) if season_type is not None else None,
        week=week,
    )
