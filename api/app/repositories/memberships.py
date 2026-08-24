from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LeagueMembership


async def list_for_user(db: AsyncSession, user_id: str) -> list[LeagueMembership]:
    res = await db.execute(
        select(LeagueMembership)
        .where(LeagueMembership.user_id == user_id)
        .order_by(LeagueMembership.added_at)
    )
    return list(res.scalars().all())


async def is_member(db: AsyncSession, user_id: str, league_id: str) -> bool:
    res = await db.execute(
        select(LeagueMembership.id).where(
            LeagueMembership.user_id == user_id,
            LeagueMembership.league_id == league_id,
        )
    )
    return res.first() is not None


async def add(
    db: AsyncSession,
    *,
    user_id: str,
    league_id: str,
    sleeper_roster_id: int | None = None,
    league_name: str | None = None,
) -> LeagueMembership:
    """Idempotent add: returns the existing row if the membership exists.
    Backfills league_name on an existing row if it was missing."""
    existing = await db.execute(
        select(LeagueMembership).where(
            LeagueMembership.user_id == user_id,
            LeagueMembership.league_id == league_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        if league_name and not row.league_name:
            row.league_name = league_name
            await db.flush()
        return row
    row = LeagueMembership(
        user_id=user_id,
        league_id=league_id,
        sleeper_roster_id=sleeper_roster_id,
        league_name=league_name,
    )
    db.add(row)
    await db.flush()
    return row


async def remove(db: AsyncSession, *, user_id: str, league_id: str) -> None:
    await db.execute(
        delete(LeagueMembership).where(
            LeagueMembership.user_id == user_id,
            LeagueMembership.league_id == league_id,
        )
    )


async def league_ids_with_members(db: AsyncSession) -> list[str]:
    """Distinct league ids that have at least one member — drives the
    membership-aware scheduler (Phase 2)."""
    res = await db.execute(select(LeagueMembership.league_id).distinct())
    return [r[0] for r in res.all()]
