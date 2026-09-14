from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.deps import get_cache_dir
from app.services.analyst_store import AnalystEdition, AnalystStore

router = APIRouter()


class AnalystArchive(BaseModel):
    editions: list[AnalystEdition]


@router.get("/api/league/{league_id}/analyst", response_model=AnalystArchive)
def analyst_archive(league_id: str):
    try:
        return {"editions": AnalystStore(get_cache_dir()).editions(league_id)}
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "The Analyst archive could not be read. Please retry; saved editions have not been changed.") from exc
