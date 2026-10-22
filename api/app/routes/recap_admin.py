"""Authenticated owner controls for league recap ceilings."""
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field
from sleeper_dynasty.llm.recap_video_writer import Script, Checks

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
    action: Literal['resume_free','resume_recovered_audio','reconcile_request','reassign_worker','skip_video','restore_access','disable_future_sharing','prepare_preview','renew_preflight','review_correction']
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


class EditorialPreview(StrictModel):
    operation_id: str = Field(min_length=1,max_length=128)
    script: Script
    checks: Checks
    reason: str = Field(min_length=1,max_length=1000)


class EditorialApproval(StrictModel):
    preview_id: str = Field(min_length=1,max_length=128)
    preview_digest: str = Field(min_length=64,max_length=64)
    reason: str = Field(min_length=1,max_length=1000)


async def editorial_episode(db, episode_id, operation_id):
    import json
    from app.services.generation.models import GenerationOperation
    job = await db.get(GenerationOperation, operation_id)
    if not job or json.loads(job.payload_json).get('episode_id') != episode_id:
        raise HTTPException(404, 'Saved script does not belong to this episode.')


@episodes.get('/{episode_id}/editorial-source')
async def editorial_source(episode_id: str, operation_id: str, db: DB, owner: Owner):
    from app.services.recap_video.editorial import get_editorial_source
    await editorial_episode(db, episode_id, operation_id)
    return await execute(get_editorial_source(db, operation_id=operation_id, actor_id=owner.id))


@episodes.post('/{episode_id}/editorial-preview')
async def editorial_preview(episode_id: str, body: EditorialPreview, db: DB, owner: Owner):
    from app.services.recap_video.editorial import preview_editorial
    from app.services.generation.store import digest, dump
    await editorial_episode(db, episode_id, body.operation_id)
    script = body.script.model_dump()
    if len(dump(script)) > 96000:
        raise HTTPException(422, 'Corrected script exceeds the review size limit.')
    # Browser callers attest their own review; they cannot submit another
    # reviewer identity, a provider receipt, or a purported delegated verdict.
    review = dict(reviewer_identity='Authenticated administrator '+owner.id,
        reviewer_kind='human_editorial_reviewer', approved=all(body.checks.model_dump().values()),
        script_sha256=digest(script), article_digest=script['article_digest'],
        checks=body.checks.model_dump(), issues=[],
        checked_segment_ids=['opening', *[s['id'] for s in script['segments']], 'closing'])
    return await execute(preview_editorial(db, operation_id=body.operation_id, script=script,
        semantic_review=review, actor_id=owner.id, reason=body.reason))


@episodes.post('/{episode_id}/editorial-approve')
async def editorial_approve(episode_id: str, body: EditorialApproval, db: DB, owner: Owner):
    import json
    from app.services.generation.models import GenerationAudit
    from app.services.recap_video.editorial import apply_editorial
    preview = await db.get(GenerationAudit, body.preview_id)
    if not preview or preview.action != 'recap_editorial_preview':
        raise HTTPException(404, 'Editorial preview is unavailable. Prepare a new preview.')
    manifest = json.loads(preview.after_json)
    await editorial_episode(db, episode_id, manifest.get('operation_id', ''))
    return await execute(apply_editorial(db, preview_id=body.preview_id, preview_digest=body.preview_digest,
        actor_id=owner.id, reason=body.reason))


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


@episodes.post('/{episode_id}/member-preview')
async def member_preview(episode_id: str, body: PreviewRequest, db: DB):
    from app.services.recap_video.publication import preview_publication
    return await execute(preview_publication(db, episode_id, body.expected_revision, body.media_id, audience='members'))


@episodes.post('/{episode_id}/member-approve')
async def member_approve(episode_id: str, body: PreviewApproval, db: DB, owner: Owner):
    from app.services.recap_video.qualification import require_admin_actor
    from app.services.recap_video.publication import record_approval, select_publication
    from app.services.generation.store import dump
    reviewer = await execute(require_admin_actor(db, owner.id))
    if (set(body.checks) != {'factual_coverage', 'performance'}
            or any(not 20 <= len(value.strip()) <= 4000 for value in body.checks.values())):
        raise HTTPException(422, 'Record factual coverage and playback evidence, each between 20 and 4000 characters.')
    proof = await execute(record_approval(db, episode_id, body.expected_revision, body.media_id,
        reviewer=reviewer, reason=body.reason+'\n'+dump(body.checks),
        preview_digest=body.preview_digest, audience='members'))
    # Member publication neither attests a physical-phone review nor grants
    # recurring publication qualification. Persist this exact review first.
    await db.commit()
    return await execute(select_publication(db, episode_id, body.expected_revision, body.media_id, proof))


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
