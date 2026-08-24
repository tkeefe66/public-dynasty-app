from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PageEvent
from app.services.route_normalize import normalize_route


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _day(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _day_range(since: datetime, until: datetime) -> list[str]:
    """Every UTC calendar day from `since` through `until`, inclusive, as
    'YYYY-MM-DD' strings ascending. Pure Python (dialect-portable convention)."""
    start = date.fromisoformat(_day(since))
    end = date.fromisoformat(_day(until))
    out: list[str] = []
    d = start
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


async def record_event(db: AsyncSession, *, user_id: str, path: str) -> None:
    """Normalize a raw pathname and store one pageview. Query strings dropped."""
    route, league_id = normalize_route(path)
    clean_path = path.split("?", 1)[0].split("#", 1)[0]
    db.add(
        PageEvent(user_id=user_id, league_id=league_id, route=route, path=clean_path)
    )
    await db.flush()


async def _distinct_users_since(db: AsyncSession, since: datetime) -> int:
    stmt = select(func.count(func.distinct(PageEvent.user_id))).where(
        PageEvent.created_at >= since
    )
    return (await db.execute(stmt)).scalar() or 0


async def active_user_counts(db: AsyncSession) -> dict[str, int]:
    now = _now()
    return {
        "d1": await _distinct_users_since(db, now - timedelta(days=1)),
        "d7": await _distinct_users_since(db, now - timedelta(days=7)),
        "d30": await _distinct_users_since(db, now - timedelta(days=30)),
    }


async def daily_active_users(db: AsyncSession, days: int) -> list[tuple[str, int]]:
    """Distinct users per UTC day over the window, zero-filled to a contiguous
    day range so quiet days show as 0 rather than being dropped. Bucketed in
    Python so the query is dialect-portable (no SQL date functions)."""
    now = _now()
    since = now - timedelta(days=days)
    rows = (
        await db.execute(
            select(PageEvent.user_id, PageEvent.created_at).where(
                PageEvent.created_at >= since
            )
        )
    ).all()
    per_day: dict[str, set[str]] = {}
    for user_id, created_at in rows:
        per_day.setdefault(_day(created_at), set()).add(user_id)
    return [(day, len(per_day.get(day, set()))) for day in _day_range(since, now)]


async def league_activity(db: AsyncSession) -> dict[str, dict]:
    rows = (
        await db.execute(
            select(
                PageEvent.league_id,
                func.count(),
                func.count(func.distinct(PageEvent.user_id)),
                func.max(PageEvent.created_at),
            )
            .where(PageEvent.league_id.is_not(None))
            .group_by(PageEvent.league_id)
        )
    ).all()
    out: dict[str, dict] = {}
    for league_id, events_n, users_n, last in rows:
        out[league_id] = {
            "events": events_n,
            "active_users": users_n,
            "last_activity": last.isoformat() if last else None,
        }
    return out


async def user_activity(
    db: AsyncSession, user_id: str, *, recent_limit: int = 50, days: int = 30
) -> dict:
    recent_rows = (
        await db.execute(
            select(PageEvent)
            .where(PageEvent.user_id == user_id)
            .order_by(PageEvent.created_at.desc())
            .limit(recent_limit)
        )
    ).scalars().all()
    recent = [
        {
            "path": e.path,
            "route": e.route,
            "league_id": e.league_id,
            "created_at": e.created_at.isoformat(),
        }
        for e in recent_rows
    ]
    now = _now()
    since = now - timedelta(days=days)
    day_rows = (
        await db.execute(
            select(PageEvent.created_at).where(
                PageEvent.user_id == user_id, PageEvent.created_at >= since
            )
        )
    ).scalars().all()
    counts = Counter(_day(ts) for ts in day_rows)
    daily = [(day, counts.get(day, 0)) for day in _day_range(since, now)]
    return {"recent": recent, "daily": daily}
