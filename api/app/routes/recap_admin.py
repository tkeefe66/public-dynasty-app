"""Authenticated owner controls for league recap ceilings."""
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field

from app.routes.generation_admin import DB, Owner
from app.auth.deps import require_admin
from app.services.generation.policy import StrictModel
from app.services.generation.recap_budget import InvalidBudgetRequest, Overcommitted, RecapCaps, SAFE_INTEGER, UnknownSeries, get_budget_view, save_caps
from app.services.generation.store import Conflict
from app.services.generation.store import Held

router = APIRouter(prefix="/api/admin/generation/recap-budgets", dependencies=[Depends(require_admin)])


class CapsChange(StrictModel):
    caps: RecapCaps
    expected_revision: int = Field(ge=0, le=SAFE_INTEGER)
    reason: str = Field(min_length=1, max_length=1000)
    acknowledge_overcommitted: bool = False


async def execute(command):
    try:
        return await command
    except UnknownSeries as exc:
        raise HTTPException(404, str(exc)) from exc
    except Overcommitted as exc:
        raise HTTPException(409, exc.detail) from exc
    except (Conflict, Held) as exc:
        raise HTTPException(409, str(exc)) from exc
    except InvalidBudgetRequest as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{series_id}")
async def view(series_id: str, db: DB, episode_id: str | None = None):
    return await execute(get_budget_view(db, series_id, episode_id, int(time.time())))


@router.put("/{series_id}")
async def save(series_id: str, body: CapsChange, db: DB, owner: Owner):
    return await execute(save_caps(db, series_id, body.caps, body.expected_revision,
        owner.id, body.reason, body.acknowledge_overcommitted))


episodes = APIRouter(prefix='/api/admin/generation/recap-episodes', dependencies=[Depends(require_admin)])


class SpellingReview(StrictModel):
    entity_kind: Literal['owner','player']
    entity_id: str = Field(min_length=1,max_length=128)
    canonical_token: str = Field(min_length=1,max_length=128)
    aliases: list[str] = Field(min_length=1,max_length=20)
    reusable: bool = False


class EpisodeAction(StrictModel):
    action: Literal['resume_free','resume_recovered_audio','reconcile_request','reassign_worker','skip_video','restore_access','disable_future_sharing','prepare_preview','review_correction']
    expected_revision: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=1,max_length=1000)
    stage_id: str = ''
    expected_generation: int = Field(default=0,ge=0)
    attempt_id: str = ''
    worker_id: str = Field(default='',max_length=128)
    spellings: list[SpellingReview] = Field(default_factory=list,max_length=20)


class PreviewRequest(StrictModel):
    expected_revision: int = Field(ge=0)
    media_id: str


class PreviewApproval(PreviewRequest):
    preview_digest: str = Field(min_length=64,max_length=64)
    checks: dict[str,str]
    reason: str = Field(min_length=1,max_length=1000)


class ReplacementApproval(StrictModel):
    preview_digest: str = Field(min_length=64,max_length=64)
    maximum_microusd: int = Field(gt=0,le=SAFE_INTEGER)
    reason: str = Field(min_length=1,max_length=1000)
    disposition_evidence: str = Field(min_length=20,max_length=4000)


@episodes.get('')
async def episode_list(series_id: str, db: DB):
    from sqlalchemy import select
    from app.services.generation.recap_models import RecapEpisode
    from app.services.generation.store import data
    rows = (await db.scalars(select(RecapEpisode).where(RecapEpisode.series_id == series_id)
        .order_by(RecapEpisode.season.desc(),RecapEpisode.week.desc()).limit(100))).all()
    return {'records':[data(row) for row in rows]}


@episodes.get('/{episode_id}')
async def episode_detail(episode_id: str, db: DB):
    from app.services.recap_video.admin_actions import episode_view
    return await execute(episode_view(db,episode_id))


@episodes.post('/{episode_id}/actions')
async def episode_action(episode_id: str, body: EpisodeAction, db: DB, owner: Owner):
    from app.services.recap_video.admin_actions import apply_action
    return await execute(apply_action(db,episode_id,actor_id=owner.id,**body.model_dump()))


@episodes.post('/{episode_id}/preview')
async def episode_preview(episode_id: str, body: PreviewRequest, db: DB):
    from app.services.recap_video.publication import preview_publication
    return await execute(preview_publication(db,episode_id,body.expected_revision,body.media_id))


@episodes.post('/{episode_id}/approve')
async def episode_approve(episode_id: str, body: PreviewApproval, db: DB, owner: Owner):
    from app.services.recap_video.qualification import record_preview_approval
    from app.services.recap_video.publication import select_publication
    proof = await execute(record_preview_approval(db,episode_id,body.expected_revision,owner.id,body.model_dump()))
    # Review commit is separate from selection/storage I/O and survives its failure.
    await db.commit()
    return await execute(select_publication(db,episode_id,body.expected_revision,body.media_id,proof))


@episodes.get('/{episode_id}/replacement')
async def episode_replacement_preview(episode_id: str, db: DB):
    from app.services.recap_video.admin_actions import replacement_preview
    return await execute(replacement_preview(db,episode_id))


@episodes.post('/{episode_id}/replacement')
async def episode_replacement(episode_id: str, body: ReplacementApproval, db: DB, owner: Owner):
    from app.services.recap_video.admin_actions import approve_replacement
    return await execute(approve_replacement(db,episode_id,actor_id=owner.id,**body.model_dump()))


@episodes.api_route('/{episode_id}/preview/{media_id}/{name}',methods=['GET','HEAD'])
async def preview_asset(episode_id: str, media_id: str, name: str, request: Request, db: DB):
    from app.services.recap_video.publication import verified_media, ASSETS
    from app.services.generation.recap_models import RecapEpisode
    from app.routes.analyst_sharing import private_object_response
    if name not in ASSETS:
        raise HTTPException(404,'Preview asset unavailable')
    media,_ = await execute(verified_media(db,episode_id,media_id))
    episode=await db.get(RecapEpisode,episode_id)
    return await private_object_response(request,{'media':media,'article':{'season':episode.season,'week':episode.week}},name,False,
        {'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})
