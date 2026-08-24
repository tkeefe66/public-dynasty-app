from datetime import date, datetime, timezone

import pytest
from sqlalchemy import Boolean, Date, DateTime, Integer, String, select

from app.db.base import Base
from app.db.models import AppSetting, LeagueMembership, PageEvent, SideBet, User
from app.services.backup_service import (
    SUPPORTED_COLUMN_TYPES,
    dump_database,
    load_database,
)


def _seed():
    """One row per table, exercising every column type in the schema."""
    u = User(
        id="u-1", google_sub="g-1", email="a@b.c", name="Ann",
        avatar_url=None, sleeper_user_id="s-1", sleeper_username="ann",
        is_admin=True, active_days=3,
        last_active_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )
    m = LeagueMembership(
        id="m-1", user_id="u-1", league_id="L1", league_name="The League",
        sleeper_roster_id=4,
        added_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    )
    s = AppSetting(
        key="llm_monthly_budget_usd", value="25.0",
        updated_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    )
    e = PageEvent(
        id="e-1", user_id="u-1", league_id="L1",
        route="/league/[id]", path="/league/L1",
        created_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    )
    b = SideBet(
        id="b-1", league_id="L1", season=2025, description="last place buys",
        amount_cents=5000, side_a_owner_id="o-1", side_b_owner_id="o-2",
        status="settled", winner_owner_id="o-1",
        made_at=date(2025, 9, 1), settled_at=date(2026, 1, 5),
        created_by_user_id="u-1", settled_by_user_id=None,
        created_at=datetime(2025, 9, 1, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
    )
    return [u, m, s, e, b]


async def _rows(maker, table):
    async with maker() as db:
        res = await db.execute(select(table))
        return [dict(r) for r in res.mappings()]


@pytest.mark.asyncio
async def test_dump_then_load_round_trips_every_table(maker, tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async with maker() as db:
        for obj in _seed():
            db.add(obj)
        await db.commit()

    async with maker() as db:
        blob, counts = await dump_database(db)

    assert counts == {
        "users": 1, "league_memberships": 1, "app_settings": 1,
        "page_events": 1, "side_bets": 1,
    }

    # A fresh, migrated-but-empty target.
    engine2 = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'restored.db'}")
    async with engine2.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker2 = async_sessionmaker(engine2, expire_on_commit=False)

    async with maker2() as db:
        restored_counts = await load_database(db, blob)
        await db.commit()
    assert restored_counts == counts

    for table in Base.metadata.sorted_tables:
        assert await _rows(maker, table) == await _rows(maker2, table), table.name

    await engine2.dispose()


@pytest.mark.asyncio
async def test_dump_of_an_empty_database_is_valid_and_all_zero(maker):
    async with maker() as db:
        blob, counts = await dump_database(db)
    assert set(counts.values()) == {0}
    assert blob  # a valid (empty) gzip member, not b""


def test_every_column_type_is_dumpable():
    """Guard: _encode/_decode handle scalars only. When someone adds a JSONB or
    bytea column, this fails loudly instead of the backups going quietly lossy."""
    offenders = [
        f"{t.name}.{c.name} ({type(c.type).__name__})"
        for t in Base.metadata.sorted_tables
        for c in t.columns
        if not isinstance(c.type, SUPPORTED_COLUMN_TYPES)
    ]
    assert not offenders, (
        "backup_service._encode/_decode only round-trip String/Integer/Boolean/"
        f"Date/DateTime. These columns would be lossy: {offenders}. Extend both "
        "encoders (and this tuple) before merging the migration."
    )
