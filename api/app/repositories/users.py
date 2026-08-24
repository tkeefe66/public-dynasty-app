from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def get_by_google_sub(db: AsyncSession, google_sub: str) -> User | None:
    res = await db.execute(select(User).where(User.google_sub == google_sub))
    return res.scalar_one_or_none()


async def upsert_from_token(
    db: AsyncSession,
    *,
    google_sub: str,
    email: str,
    name: str | None,
    avatar_url: str | None,
    is_admin: bool,
) -> User:
    """Find-or-create the user for an authenticated request.

    Steady state is a pure SELECT: on the common path the row exists and its
    fields already match the token, so we return without dirtying the session
    (no UPDATE/commit per request). We only INSERT on first sight and only
    UPDATE when a profile field actually changed.
    """
    user = await get_by_google_sub(db, google_sub)
    if user is None:
        user = User(
            google_sub=google_sub,
            email=email,
            name=name,
            avatar_url=avatar_url,
            is_admin=is_admin,
        )
        db.add(user)
        await db.flush()
        return user

    if (
        user.email != email
        or user.name != name
        or user.avatar_url != avatar_url
        or user.is_admin != is_admin
    ):
        user.email = email
        user.name = name
        user.avatar_url = avatar_url
        user.is_admin = is_admin
        await db.flush()
    return user


async def touch_activity(db: AsyncSession, user: User) -> User:
    """Record that the user was active today (engagement signal).

    Counts distinct UTC calendar days: the first authenticated request of each
    day bumps ``active_days`` and stamps ``last_active_at``; later requests the
    same day are a no-op, so this writes at most once per user per day (steady
    state stays a pure read). Day boundaries are UTC, not the user's local tz.
    """
    now = datetime.now(tz=timezone.utc)
    last = user.last_active_at
    if last is None or last.date() != now.date():
        user.active_days = (user.active_days or 0) + 1
        user.last_active_at = now
        await db.flush()
    return user


async def set_sleeper_link(
    db: AsyncSession,
    user: User,
    *,
    sleeper_user_id: str | None,
    sleeper_username: str | None,
) -> User:
    """Set or clear the soft Sleeper link (personalization only — never authz)."""
    user.sleeper_user_id = sleeper_user_id
    user.sleeper_username = sleeper_username
    await db.flush()
    return user
