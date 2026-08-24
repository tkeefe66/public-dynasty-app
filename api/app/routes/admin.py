"""App-owner admin surface (require_admin). Not league-scoped — this is the
owner's home for spend, leagues, users, and budget control."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin
from app.config import get_settings
from app.db.models import LeagueMembership, User
from app.db.session import get_db
from app.deps import get_cache_dir
from app.repositories import app_settings, events
from app.services import backup_service
from app.services.chain_cache import ChainCache
from app.services.refresh_service import month_to_date_spend
from sleeper_dynasty.engine.capabilities import capabilities_from_dict
from sleeper_dynasty.llm.cost_store import LlmCostStore

router = APIRouter()


def _cache_dir() -> Path:
    return get_cache_dir()


def _spend_by_league(cache_dir: Path) -> dict[str, float]:
    now = datetime.now(tz=timezone.utc)
    prefix = f"{now.year:04d}-{now.month:02d}"
    out: dict[str, float] = {}
    for r in LlmCostStore(cache_dir).read_all():
        if str(r.get("ts", ""))[:7] != prefix:
            continue
        lid = r.get("league_id") or "?"
        out[lid] = round(out.get(lid, 0.0) + float(r.get("cost_usd", 0) or 0), 6)
    return out


class BudgetStatus(BaseModel):
    monthly_budget_usd: float
    month_to_date_usd: float
    budget_remaining_usd: float | None


class BackupStatus(BaseModel):
    enabled: bool
    last_ok_at: str | None
    last_error: str | None
    last_run_id: str | None


class Overview(BaseModel):
    users: int
    memberships: int
    leagues: int
    budget: BudgetStatus


class AdminLeague(BaseModel):
    league_id: str
    name: str | None
    season: int | None
    format: str | None
    member_count: int
    warm: bool
    spend_mtd_usd: float
    active_users: int
    last_activity: str | None


class DailyPoint(BaseModel):
    date: str
    count: int


class ActiveUsers(BaseModel):
    daily: list[DailyPoint]
    d1: int
    d7: int
    d30: int


class ActivityEvent(BaseModel):
    path: str
    route: str
    league_id: str | None
    league_name: str | None
    created_at: str


class UserActivity(BaseModel):
    email: str
    name: str | None
    recent: list[ActivityEvent]
    daily: list[DailyPoint]


class AdminUserLeague(BaseModel):
    league_id: str
    name: str | None


class AdminUser(BaseModel):
    id: str
    email: str
    name: str | None
    is_admin: bool
    league_count: int
    leagues: list[AdminUserLeague]
    active_days: int
    last_active_at: str | None
    created_at: str


class BudgetReq(BaseModel):
    monthly_budget_usd: float


async def _budget_status(db: AsyncSession, cache_dir: Path) -> BudgetStatus:
    budget = await app_settings.get_monthly_budget(db)
    mtd = month_to_date_spend(cache_dir)
    remaining = round(max(0.0, budget - mtd), 6) if budget and budget > 0 else None
    return BudgetStatus(
        monthly_budget_usd=budget, month_to_date_usd=mtd,
        budget_remaining_usd=remaining,
    )


@router.get("/api/admin/overview", response_model=Overview)
async def overview(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> Overview:
    users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    memberships = (
        await db.execute(select(func.count()).select_from(LeagueMembership))
    ).scalar() or 0
    leagues = (
        await db.execute(select(func.count(func.distinct(LeagueMembership.league_id))))
    ).scalar() or 0
    return Overview(
        users=users, memberships=memberships, leagues=leagues,
        budget=await _budget_status(db, _cache_dir()),
    )


@router.get("/api/admin/leagues", response_model=list[AdminLeague])
async def leagues(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[AdminLeague]:
    rows = (
        await db.execute(
            select(
                LeagueMembership.league_id,
                func.count(),
                func.max(LeagueMembership.league_name),
            ).group_by(LeagueMembership.league_id)
        )
    ).all()
    spend = _spend_by_league(_cache_dir())
    activity = await events.league_activity(db)
    cache = ChainCache(cache_dir=_cache_dir())
    out: list[AdminLeague] = []
    for league_id, count, stored_name in rows:
        entry = cache.read(league_id)
        cache_name = (entry.league_name_by_id or {}).get(league_id) if entry else None
        out.append(
            AdminLeague(
                league_id=league_id,
                name=cache_name or stored_name,
                season=(entry.league_season_by_id or {}).get(league_id) if entry else None,
                format=capabilities_from_dict(entry.capabilities).format if entry else None,
                member_count=count,
                warm=entry is not None,
                spend_mtd_usd=spend.get(league_id, 0.0),
                active_users=(activity.get(league_id) or {}).get("active_users", 0),
                last_activity=(activity.get(league_id) or {}).get("last_activity"),
            )
        )
    out.sort(key=lambda x: x.spend_mtd_usd, reverse=True)
    return out


@router.get("/api/admin/users", response_model=list[AdminUser])
async def users_list(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[AdminUser]:
    # All memberships at once; group into per-user league lists. Resolve each
    # league's display name from the warm chain cache (preferred, kept current)
    # and fall back to the name denormalized on the membership row.
    mem_rows = (
        await db.execute(
            select(
                LeagueMembership.user_id,
                LeagueMembership.league_id,
                LeagueMembership.league_name,
            ).order_by(LeagueMembership.added_at)
        )
    ).all()
    cache = ChainCache(cache_dir=_cache_dir())
    name_by_league: dict[str, str | None] = {}

    def _resolve_name(league_id: str, stored: str | None) -> str | None:
        if league_id not in name_by_league:
            entry = cache.read(league_id)
            name_by_league[league_id] = (
                (entry.league_name_by_id or {}).get(league_id) if entry else None
            )
        return name_by_league[league_id] or stored

    leagues_by_user: dict[str, list[AdminUserLeague]] = {}
    for user_id, league_id, stored_name in mem_rows:
        leagues_by_user.setdefault(user_id, []).append(
            AdminUserLeague(league_id=league_id, name=_resolve_name(league_id, stored_name))
        )

    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [
        AdminUser(
            id=u.id,
            email=u.email,
            name=u.name,
            is_admin=u.is_admin,
            league_count=len(leagues_by_user.get(u.id, [])),
            leagues=leagues_by_user.get(u.id, []),
            active_days=u.active_days or 0,
            last_active_at=u.last_active_at.isoformat() if u.last_active_at else None,
            created_at=u.created_at.isoformat() if u.created_at else "",
        )
        for u in rows
    ]


@router.put("/api/admin/budget", response_model=BudgetStatus)
async def set_budget(
    body: BudgetReq,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BudgetStatus:
    await app_settings.set_monthly_budget(db, max(0.0, body.monthly_budget_usd))
    return await _budget_status(db, _cache_dir())


@router.get("/api/admin/backups", response_model=BackupStatus)
async def backups(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> BackupStatus:
    """Last backup outcome. Read from app_settings, which the scheduler stamps
    on every run — a stale last_ok_at is the signal that backups are broken."""

    def _blank_to_none(v: str | None) -> str | None:
        return v or None

    return BackupStatus(
        enabled=get_settings().backup_configured,
        last_ok_at=_blank_to_none(
            await app_settings.get_setting(db, backup_service.STATUS_OK_KEY)
        ),
        last_error=_blank_to_none(
            await app_settings.get_setting(db, backup_service.STATUS_ERROR_KEY)
        ),
        last_run_id=_blank_to_none(
            await app_settings.get_setting(db, backup_service.STATUS_RUN_KEY)
        ),
    )


@router.get("/api/admin/telemetry/active-users", response_model=ActiveUsers)
async def telemetry_active_users(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> ActiveUsers:
    counts = await events.active_user_counts(db)
    daily = await events.daily_active_users(db, days=30)
    return ActiveUsers(
        daily=[DailyPoint(date=d, count=n) for d, n in daily],
        d1=counts["d1"], d7=counts["d7"], d30=counts["d30"],
    )


@router.get("/api/admin/users/{user_id}/activity", response_model=UserActivity)
async def telemetry_user_activity(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserActivity:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    data = await events.user_activity(db, user_id, recent_limit=50, days=30)
    # Resolve league names (cache name preferred, else stored membership name).
    cache = ChainCache(cache_dir=_cache_dir())
    membership_names = dict(
        (
            await db.execute(
                select(LeagueMembership.league_id, func.max(LeagueMembership.league_name))
                .group_by(LeagueMembership.league_id)
            )
        ).all()
    )
    name_cache: dict[str, str | None] = {}

    def _name(lid: str | None) -> str | None:
        if not lid:
            return None
        if lid not in name_cache:
            entry = cache.read(lid)
            cache_name = (entry.league_name_by_id or {}).get(lid) if entry else None
            name_cache[lid] = cache_name or membership_names.get(lid)
        return name_cache[lid]

    return UserActivity(
        email=target.email,
        name=target.name,
        recent=[
            ActivityEvent(
                path=e["path"], route=e["route"], league_id=e["league_id"],
                league_name=_name(e["league_id"]), created_at=e["created_at"],
            )
            for e in data["recent"]
        ],
        daily=[DailyPoint(date=d, count=n) for d, n in data["daily"]],
    )
