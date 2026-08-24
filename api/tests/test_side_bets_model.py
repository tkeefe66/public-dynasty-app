"""SideBet model smoke test: table creates, defaults apply, row round-trips."""
from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from app.db.models import SideBet


def test_side_bet_round_trip_with_defaults(maker):
    async def _run():
        async with maker() as session:
            session.add(
                SideBet(
                    league_id="L1",
                    season=2026,
                    description="Tom finishes above Mike in the regular season",
                    amount_cents=50000,
                    side_a_owner_id="u_tom",
                    side_b_owner_id="u_mike",
                    made_at=date(2026, 7, 15),
                    created_by_user_id=None,
                )
            )
            await session.commit()
            row = (await session.execute(select(SideBet))).scalar_one()
            assert row.status == "open"
            assert row.winner_owner_id is None
            assert row.settled_at is None
            assert row.amount_cents == 50000
            assert row.id  # uuid default applied

    asyncio.run(_run())
