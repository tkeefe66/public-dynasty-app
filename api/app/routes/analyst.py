import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import get_cache_dir
from app.db.session import get_db
from sqlalchemy.exc import SQLAlchemyError
from app.services.generation.store import Held, digest
from app.services.recap_video import publication
from app.services.analyst_store import AnalystEdition, AnalystStore

router = APIRouter()


class AnalystArchive(BaseModel):
    editions: list[AnalystEdition]


@router.get("/api/league/{league_id}/analyst", response_model=AnalystArchive)
async def analyst_archive(league_id: str, db=Depends(get_db)):
    try:
        editions = AnalystStore(get_cache_dir()).published_editions(league_id)
        if publication.mode() == 'database':
            await publication.serving_gate(db)
            visible = []
            for edition in editions:
                row = await publication.edition_row(db, league_id, edition['season'], edition['week'])
                if row and (row.withdrawn or row.hold or not row.enabled or not await publication.article_current(db, row)):
                    continue
                if row and digest(publication.public_article(edition)) != digest(json.loads(row.article_json)):
                    continue
                visible.append(edition)
            editions = visible
        return {"editions": editions}
    except (OSError, ValueError, Held, SQLAlchemyError) as exc:
        raise HTTPException(503, "The Analyst archive could not be read. Please retry; saved editions have not been changed.") from exc
