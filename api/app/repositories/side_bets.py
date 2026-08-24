"""Persistence for the side_bets ledger. Plain async functions taking the
session first — same convention as app/repositories/events.py. All rollup
math lives in app/services/side_bets.py (pure Python, dialect-portable)."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SideBet


async def create(db: AsyncSession, bet: SideBet) -> SideBet:
    db.add(bet)
    await db.flush()
    return bet


async def get(db: AsyncSession, league_id: str, bet_id: str) -> SideBet | None:
    stmt = select(SideBet).where(SideBet.id == bet_id, SideBet.league_id == league_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_for_league(
    db: AsyncSession,
    league_id: str,
    *,
    owner_id: str | None = None,
    season: int | None = None,
) -> list[SideBet]:
    stmt = select(SideBet).where(SideBet.league_id == league_id)
    if owner_id is not None:
        stmt = stmt.where(
            or_(
                SideBet.side_a_owner_id == owner_id,
                SideBet.side_b_owner_id == owner_id,
            )
        )
    if season is not None:
        stmt = stmt.where(SideBet.season == season)
    stmt = stmt.order_by(SideBet.made_at.desc(), SideBet.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())
