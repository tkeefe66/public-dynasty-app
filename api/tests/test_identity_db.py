from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.repositories import memberships, users


def _temp_engine(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'identity.db'}"
    return create_async_engine(url)


def test_user_and_membership_round_trip(tmp_path):
    async def run():
        engine = _temp_engine(tmp_path)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)

        async with maker() as db:
            user = await users.upsert_from_token(
                db,
                google_sub="g-123",
                email="a@b.com",
                name="Ada",
                avatar_url=None,
                is_admin=True,
            )
            uid = user.id
            await db.commit()
            assert user.is_admin is True

        # Idempotent upsert: same google_sub returns the same row, refreshed.
        async with maker() as db:
            again = await users.upsert_from_token(
                db,
                google_sub="g-123",
                email="ada@new.com",
                name="Ada L",
                avatar_url="http://x/y.png",
                is_admin=False,
            )
            await db.commit()
            assert again.id == uid
            assert again.email == "ada@new.com"
            assert again.is_admin is False

        async with maker() as db:
            assert await memberships.is_member(db, uid, "LEAGUE_1") is False
            await memberships.add(db, user_id=uid, league_id="LEAGUE_1")
            # Idempotent add — no duplicate, no error.
            await memberships.add(db, user_id=uid, league_id="LEAGUE_1")
            await db.commit()

        async with maker() as db:
            assert await memberships.is_member(db, uid, "LEAGUE_1") is True
            rows = await memberships.list_for_user(db, uid)
            assert [m.league_id for m in rows] == ["LEAGUE_1"]
            assert await memberships.league_ids_with_members(db) == ["LEAGUE_1"]

        async with maker() as db:
            await memberships.remove(db, user_id=uid, league_id="LEAGUE_1")
            await db.commit()
        async with maker() as db:
            assert await memberships.is_member(db, uid, "LEAGUE_1") is False

        await engine.dispose()

    asyncio.run(run())
