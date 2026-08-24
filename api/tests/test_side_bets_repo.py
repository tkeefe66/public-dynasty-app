"""Repository tests for the side_bets table (SQLite, like test_events_repo)."""
from __future__ import annotations

import asyncio
from datetime import date

from app.db.models import SideBet
from app.repositories import side_bets as repo


def _bet(league_id="L1", a="u_a", b="u_b", season=2026, made=date(2026, 7, 1)):
    return SideBet(
        league_id=league_id,
        season=season,
        description="test bet",
        amount_cents=10000,
        side_a_owner_id=a,
        side_b_owner_id=b,
        made_at=made,
    )


def test_create_get_and_league_scoping(maker):
    async def _run():
        async with maker() as db:
            bet = await repo.create(db, _bet())
            await db.commit()
            assert await repo.get(db, "L1", bet.id) is not None
            # A bet id is only reachable through its own league.
            assert await repo.get(db, "OTHER", bet.id) is None
            assert await repo.get(db, "L1", "missing") is None

    asyncio.run(_run())


def test_list_orders_newest_first_and_filters(maker):
    async def _run():
        async with maker() as db:
            old = await repo.create(db, _bet(made=date(2025, 9, 1), season=2025))
            new = await repo.create(db, _bet(made=date(2026, 7, 1)))
            other_pair = await repo.create(db, _bet(a="u_c", b="u_d"))
            await repo.create(db, _bet(league_id="L2"))
            await db.commit()

            all_l1 = await repo.list_for_league(db, "L1")
            assert [x.id for x in all_l1[:1]] and all_l1[0].made_at >= all_l1[-1].made_at
            assert {x.id for x in all_l1} == {old.id, new.id, other_pair.id}

            mine = await repo.list_for_league(db, "L1", owner_id="u_a")
            assert {x.id for x in mine} == {old.id, new.id}
            theirs = await repo.list_for_league(db, "L1", owner_id="u_d")
            assert {x.id for x in theirs} == {other_pair.id}

            s2025 = await repo.list_for_league(db, "L1", season=2025)
            assert [x.id for x in s2025] == [old.id]

    asyncio.run(_run())
