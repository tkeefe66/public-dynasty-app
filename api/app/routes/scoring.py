"""League scoring leaders; mounted behind the standard membership guard."""
import logging

import httpx
from fastapi import APIRouter, HTTPException, Response

from app.deps import get_cache_dir
from app.models.scoring import ScoringResp
from app.services.scoring_leaders import load_scoring_leaders
from sleeper_dynasty.api.sleeper import SleeperClient

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/league/{league_id}/scoring", response_model=ScoringResp)
async def scoring_leaders(league_id: str, response: Response):
    if not league_id.isascii() or not league_id.isdigit():
        raise HTTPException(422, "Scoring leaders currently support Sleeper leagues.")
    client = SleeperClient()
    try:
        data = await load_scoring_leaders(league_id, get_cache_dir(), client)
        response.headers["Cache-Control"] = "private, no-store"
        return data
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
        detail = str(exc) if isinstance(exc, ValueError) else "Sleeper returned incomplete scoring data. Try again shortly."
        raise HTTPException(503, detail) from exc
    finally:
        await client.close()
