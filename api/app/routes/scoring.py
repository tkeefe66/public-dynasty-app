"""League scoring leaders; mounted behind the standard membership guard."""
import logging
import re
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth.deps import require_league_member
from app.db.session import get_db
from app.deps import get_cache_dir
from app.models.scoring import ScoringResp
from app.services.name_override_store import NameOverrideStore
from app.services.platform_client import YahooCredentialsMissing, connected_client
from app.services.scoring_leaders import load_scoring_leaders
from sleeper_dynasty.api.yahoo import (
    YahooAuthenticationError,
    YahooDataError,
    YahooRateLimitError,
    YahooUnsupportedScoringError,
)

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/league/{league_id}/scoring", response_model=ScoringResp)
async def scoring_leaders(league_id: str, response: Response,
                          user: Annotated[object, Depends(require_league_member)],
                          db: Annotated[object, Depends(get_db)]):
    if not re.fullmatch(r"[0-9]+(?:\.l\.[0-9]+)?", league_id):
        raise HTTPException(422, "Scoring leaders support Sleeper and Yahoo league IDs. Check the league URL.")
    client = None
    try:
        client = await connected_client(league_id, db=db, user_id=user.id)
        data = await load_scoring_leaders(league_id, get_cache_dir(), client)
        overrides = NameOverrideStore(get_cache_dir()).read(league_id)
        data = {**data, "franchises": [
            {**franchise, "owner_name": overrides.get(franchise["owner_id"]) or franchise["owner_name"]}
            for franchise in data["franchises"]
        ]}
        response.headers["Cache-Control"] = "private, no-store"
        return data
    except (YahooAuthenticationError, YahooCredentialsMissing) as exc:
        log.warning("Yahoo scoring authorization failed league=%s", league_id)
        raise HTTPException(409, str(exc)) from exc
    except YahooRateLimitError as exc:
        log.warning("Yahoo scoring rate limited league=%s", league_id)
        raise HTTPException(503, str(exc), headers={"Retry-After": str(max(60, exc.retry_after))}) from exc
    except YahooUnsupportedScoringError as exc:
        log.warning("Yahoo scoring settings unsupported league=%s: %s", league_id, exc)
        raise HTTPException(422, str(exc)) from exc
    except YahooDataError as exc:
        log.warning("Yahoo scoring unavailable league=%s: %s", league_id, exc)
        raise HTTPException(503, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        log.warning("Sleeper scoring request failed league=%s status=%s", league_id, status)
        if status == 429:
            detail = "Sleeper's rate limit was reached. Try again in a minute."
        elif status in {401, 403}:
            detail = "Sleeper refused access to scoring data. Try again later."
        elif status == 404:
            detail = "Sleeper could not find this league or its scoring data. Check the league and try again."
        else:
            detail = "Sleeper could not provide scoring data. Try again shortly."
        raise HTTPException(503, detail, headers={"Retry-After": "60"}) from exc
    except httpx.TimeoutException as exc:
        log.warning("Sleeper scoring request timed out league=%s", league_id)
        raise HTTPException(503, "Sleeper took too long to return scoring data. Try again shortly.") from exc
    except httpx.RequestError as exc:
        log.warning("Sleeper scoring connection failed league=%s", league_id)
        raise HTTPException(503, "Could not reach Sleeper for scoring data. Try again shortly.") from exc
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        log.warning("Scoring leaders unavailable league=%s: %s", league_id, exc)
        detail = str(exc) if isinstance(exc, ValueError) else "The scoring source returned incomplete data. Try again shortly."
        raise HTTPException(503, detail) from exc
    finally:
        if client is not None:
            await client.close()
