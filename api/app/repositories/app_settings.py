from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import AppSetting

_BUDGET_KEY = "llm_monthly_budget_usd"


async def get_setting(db: AsyncSession, key: str) -> str | None:
    res = await db.execute(select(AppSetting.value).where(AppSetting.key == key))
    row = res.first()
    return row[0] if row else None


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    existing = await db.get(AppSetting, key)
    if existing is None:
        db.add(AppSetting(key=key, value=value))
    else:
        existing.value = value
    await db.flush()


async def get_monthly_budget(db: AsyncSession) -> float:
    """Effective LLM monthly budget: DB override if set, else the env default."""
    raw = await get_setting(db, _BUDGET_KEY)
    if raw is not None:
        try:
            return float(raw)
        except ValueError:
            pass
    return get_settings().llm_monthly_budget_usd


async def set_monthly_budget(db: AsyncSession, value: float) -> None:
    await set_setting(db, _BUDGET_KEY, str(value))
