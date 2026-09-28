"""Yahoo account discovery and verified access, separate from fantasy grading."""

import re

from fastapi import HTTPException
from sqlalchemy import delete

from app.db.models import YahooConnection, YahooLeagueGrant
from app.services.yahoo_connection import YahooConnectionService
from sleeper_dynasty.api.yahoo import (
    YahooAdapter,
    YahooAuthenticationError,
    YahooDataError,
    YahooRateLimitError,
    child,
)
from sleeper_dynasty.api.yahoo_json import collection, merge_fragments


def league_resources(payload):
    root = payload.get("fantasy_content", {})
    users = child(root, "users")
    if users is None:
        raise HTTPException(
            502, "Yahoo returned incomplete league discovery. Retry later."
        )
    leagues = []
    for user in collection(users):
        for game in collection(child(child(user, "user"), "games")):
            for item in collection(child(child(game, "game"), "leagues")):
                league = merge_fragments(child(item, "league"))
                key = str(league.get("league_key", ""))
                if not re.fullmatch(r"\d+\.l\.\d+", key):
                    raise HTTPException(
                        502, "Yahoo returned an invalid league. Retry later."
                    )
                leagues.append(league)
    return leagues


async def discover(db, user_id) -> list[dict]:
    service = YahooConnectionService(db)
    token = await service.access_token(user_id)
    # access_token retains the user row lock; account cannot change mid-discovery.
    connection = await db.get(YahooConnection, user_id, populate_existing=True)
    adapter = YahooAdapter(token)
    try:
        payload = await adapter._get("/users;use_login=1/games;game_keys=nfl/leagues")
        resources = league_resources(payload)
        result = []
        for league in resources:
            key = league["league_key"]
            settings_payload = await adapter._get(f"/league/{key}/settings")
            settings = merge_fragments(
                child(child(settings_payload["fantasy_content"], "league"), "settings")
            )
            keeper = any(
                str(settings.get(k)).lower() in {"1", "true"}
                for k in ("uses_roster_import", "is_keeper_league")
            )
            result.append(
                {
                    "league_id": key,
                    "name": str(league.get("name") or "Yahoo league"),
                    "season": int(league["season"]),
                    "total_rosters": int(league["num_teams"]),
                    "format": "keeper" if keeper else "redraft",
                }
            )
    except YahooAuthenticationError:
        connection.status = "reconnect"
        await db.commit()
        raise HTTPException(
            409, "Yahoo refused access. Reconnect Yahoo and approve read access."
        ) from None
    except YahooRateLimitError:
        raise HTTPException(
            503,
            "Yahoo is limiting API access right now. Wait before retrying; "
            "your Yahoo connection is still saved.",
        ) from None
    except (YahooDataError, KeyError, TypeError, ValueError):
        raise HTTPException(
            502, "Yahoo leagues could not be loaded. Try again in a minute."
        ) from None
    finally:
        await adapter.close()
    await db.execute(
        delete(YahooLeagueGrant).where(YahooLeagueGrant.user_id == user_id)
    )
    for league in result:
        db.add(
            YahooLeagueGrant(
                user_id=user_id,
                league_id=league["league_id"],
                generation=connection.generation,
            )
        )
    await db.flush()
    return result


async def verify_league(db, user_id, league_id) -> dict:
    if not re.fullmatch(r"\d+\.l\.\d+", league_id):
        raise HTTPException(400, "Invalid Yahoo league key.")
    leagues = await discover(db, user_id)
    for league in leagues:
        if league["league_id"] == league_id:
            return league
    # Keep authoritative removal even though the caller returns an error. An
    # ordinary request rollback must not resurrect the stale grant and repeat
    # expensive provider discovery on every subsequent denied read.
    await db.commit()
    raise HTTPException(
        403, "This league is not available to your connected Yahoo account."
    )
