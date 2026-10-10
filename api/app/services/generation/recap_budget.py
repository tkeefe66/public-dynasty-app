"""Editable recap ceilings. Admission remains inactive until obligation accounting exists."""
import json
import time
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from zoneinfo import ZoneInfo

from pydantic import Field

from app.repositories.app_settings import get_monthly_budget
from app.services.generation.models import LeagueSeries
from app.services.generation.policy import StrictModel
from app.services.generation.recap_models import RecapBudgetPolicy
from app.services.generation.store import Conflict, audit, dump, lock_control

SAFE_INTEGER = 9_007_199_254_740_991


class RecapCaps(StrictModel):
    video_episode_microusd: int = Field(default=3_000_000, gt=0, le=SAFE_INTEGER)
    video_month_microusd: int = Field(default=15_000_000, gt=0, le=SAFE_INTEGER)
    combined_episode_microusd: int = Field(default=5_000_000, gt=0, le=SAFE_INTEGER)
    combined_month_microusd: int = Field(default=25_000_000, gt=0, le=SAFE_INTEGER)


class UnknownSeries(ValueError):
    pass


async def get_budget_view(db, series_id: str, episode_id: str | None, now: int) -> dict:
    if not await db.get(LeagueSeries, series_id):
        raise UnknownSeries("League series not found")
    row = await db.get(RecapBudgetPolicy, series_id)
    caps = RecapCaps.model_validate(json.loads(row.caps_json)) if row else RecapCaps()
    app_budget = Decimal(str(await get_monthly_budget(db)))
    app_cap = int((app_budget * 1_000_000).to_integral_value(rounding=ROUND_CEILING)) if app_budget > 0 else None
    return {"series_id": series_id, "revision": row.revision if row else 0,
        "caps": caps.model_dump(), "episode_id": episode_id,
        "month_key": datetime.fromtimestamp(now, ZoneInfo("America/Denver")).strftime("%Y-%m"),
        "balances": {key: None for key in RecapCaps.model_fields},
        "app_limit": {"month_microusd": app_cap, "balance": None},
        "enforcement_state": {"active": False, "reason": "ledger_unavailable"}}


async def save_caps(db, series_id: str, caps: RecapCaps, expected_revision: int,
                    actor_id: str, reason: str, acknowledge_overcommitted: bool) -> dict:
    if not reason.strip():
        raise ValueError("An audit reason is required")
    if not await db.get(LeagueSeries, series_id):
        raise UnknownSeries("League series not found")
    await lock_control(db)
    row = await db.get(RecapBudgetPolicy, series_id, populate_existing=True)
    revision = row.revision if row else 0
    if revision != expected_revision:
        raise Conflict("Recap limits changed. Reload the saved values before saving.")
    before = {"revision": revision, "caps": json.loads(row.caps_json) if row else RecapCaps().model_dump()}
    now = int(time.time())
    if row is None:
        row = RecapBudgetPolicy(series_id=series_id, revision=1, caps_json=dump(caps.model_dump()), updated_at=now)
        db.add(row)
    else:
        row.revision += 1
        row.caps_json = dump(caps.model_dump())
        row.updated_at = now
    audit(db, actor_id, "recap_caps_saved", series_id, reason, before,
        {"revision": row.revision, "caps": caps.model_dump(),
         "acknowledge_overcommitted": acknowledge_overcommitted})
    await db.flush()
    return await get_budget_view(db, series_id, None, now)
