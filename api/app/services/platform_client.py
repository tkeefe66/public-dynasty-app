"""Create an ingestion client with caller-scoped credentials.

Developer tokens are deliberately not read from process environment here.
Account-backed clients resolve credentials through the identity database.
"""

import re

from sleeper_dynasty.api.platform import PLATFORM_SLEEPER, platform_for_league_id
from sleeper_dynasty.api.sleeper import SleeperClient


class YahooCredentialsMissing(RuntimeError):
    """The caller has no authorized Yahoo connection for this league."""


def client_for_league(league_id: str, *, access_token: str | None = None):
    platform = platform_for_league_id(league_id)
    if platform == PLATFORM_SLEEPER:
        return SleeperClient()
    if not re.fullmatch(r"\d+\.l\.\d+", league_id):
        raise ValueError("Invalid Yahoo league key.")
    if not access_token:
        raise YahooCredentialsMissing(
            "Yahoo account connection is required before this league can refresh."
        )
    from sleeper_dynasty.api.yahoo import YahooAdapter

    return YahooAdapter(access_token)


async def connected_client(league_id: str, *, db=None, user_id=None):
    """Manual calls require their own account; scheduler may use a verified member."""
    if platform_for_league_id(league_id) == PLATFORM_SLEEPER:
        return client_for_league(league_id)
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.db.engine import session_scope
    from app.db.models import LeagueMembership
    from app.services.yahoo_connection import YahooConnectionService

    if db is not None and user_id is not None:
        service = YahooConnectionService(db)
        await service.ensure_grant(user_id, league_id)
        token = await service.access_token(user_id)
        # Disconnect/reconnect may have won a race during refresh-token commit.
        if not await service.has_grant(user_id, league_id):
            raise HTTPException(
                409, "Yahoo connection changed. Reconnect from Add a league."
            )
        await db.commit()  # never hold a connection/row lock during an SSE import
        return client_for_league(league_id, access_token=token)
    async with session_scope() as session:
        ids = list(
            (
                await session.scalars(
                    select(LeagueMembership.user_id).where(
                        LeagueMembership.league_id == league_id
                    )
                )
            ).all()
        )
    for uid in ids:
        async with session_scope() as session:
            try:
                return await connected_client(league_id, db=session, user_id=uid)
            except HTTPException as exc:
                if exc.status_code not in (403, 409):
                    raise
    raise YahooCredentialsMissing(
        "No connected Yahoo league member is available for refresh."
    )
