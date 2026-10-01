"""Schedulers submit shared jobs, never execute refreshes themselves."""
from sqlalchemy import select

from app.db.models import LeagueMembership, YahooConnection, YahooLeagueGrant
from app.services.generation.commands import submit_refresh


async def enqueue_members(*, kind="refresh", maker=None):
    if maker is None:
        from app.db.engine import get_sessionmaker
        maker = get_sessionmaker()
    async with maker() as db:
        members = list((await db.scalars(select(LeagueMembership).order_by(
            LeagueMembership.league_id, LeagueMembership.added_at))).all())
    selected = set()
    for member in members:
        if member.league_id in selected or (kind == "analyst_refresh" and ".l." in member.league_id):
            continue
        async with maker.begin() as db:
            if ".l." in member.league_id:
                connection = await db.get(YahooConnection, member.user_id)
                grant = await db.get(YahooLeagueGrant, (member.user_id, member.league_id))
                if (not connection or connection.status != "connected" or not grant
                        or grant.generation != connection.generation):
                    continue
                # Credential refresh is resolved only for this selected member
                # by the worker; never substitute another account inside a job.
            await submit_refresh(db, member.league_id, member.user_id, actor_kind="scheduler", kind=kind)
            selected.add(member.league_id)
