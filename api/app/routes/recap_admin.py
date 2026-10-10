"""Authenticated owner controls for league recap ceilings."""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.routes.generation_admin import DB, Owner
from app.auth.deps import require_admin
from app.services.generation.policy import StrictModel
from app.services.generation.recap_budget import InvalidBudgetRequest, Overcommitted, RecapCaps, SAFE_INTEGER, UnknownSeries, get_budget_view, save_caps
from app.services.generation.store import Conflict

router = APIRouter(prefix="/api/admin/generation/recap-budgets", dependencies=[Depends(require_admin)])


class CapsChange(StrictModel):
    caps: RecapCaps
    expected_revision: int = Field(ge=0, le=SAFE_INTEGER)
    reason: str = Field(min_length=1, max_length=1000)
    acknowledge_overcommitted: bool = False


async def execute(command):
    try:
        return await command
    except UnknownSeries as exc:
        raise HTTPException(404, str(exc)) from exc
    except Overcommitted as exc:
        raise HTTPException(409, exc.detail) from exc
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except InvalidBudgetRequest as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{series_id}")
async def view(series_id: str, db: DB, episode_id: str | None = None):
    return await execute(get_budget_view(db, series_id, episode_id, int(time.time())))


@router.put("/{series_id}")
async def save(series_id: str, body: CapsChange, db: DB, owner: Owner):
    return await execute(save_caps(db, series_id, body.caps, body.expected_revision,
        owner.id, body.reason, body.acknowledge_overcommitted))
