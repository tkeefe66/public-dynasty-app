"""Free preparation of explicitly approved replacement script campaigns."""
import json

from sqlalchemy import select

from app.services.generation.models import (ArtifactHead, ContentArtifact, GenerationAudit,
    GenerationOperation, ProviderAttempt)
from app.services.generation.recap_models import (RecapEpisode, RecapProviderAttempt, RecapStage,
    RecapPublication, RecapPublicationSelection)
from app.services.generation.store import Held, digest, dump, resolve_policy


async def require_failed_script(db, job, *, prepared=False):
    """Receipts, unpublished output and related work must all be resolved first."""
    if (job.kind != 'generation' or job.feature != 'recap_video'
            or job.state not in (('cancelled',) if prepared else ('held','needs_attention'))
            or (not prepared and job.reason not in ('execution_failed','attempt_allowance_exhausted'))
            or job.max_calls <= 0 or job.calls != job.max_calls or job.artifact_id):
        raise Held('recap_script_exhausted_attempt_required')
    payload = json.loads(job.payload_json)
    episode = await db.get(RecapEpisode,payload.get('episode_id',''))
    if (not episode or episode.league_id != job.league_id or episode.series_id != job.series_id
            or job.subject != 'recap_video:'+episode.episode_id
            or payload.get('season') != episode.season or payload.get('week') != episode.week):
        raise Held('recap_script_episode_identity_changed')
    if prepared:
        from app.services.generation.candidate_status import replacement_review_target
        reviews=(await db.scalars(select(GenerationAudit).where(GenerationAudit.action=='replacement_review_required',
            GenerationAudit.target==replacement_review_target(job.subject,episode.period_id)))).all()
        if not any(json.loads(review.after_json).get('job_id')==job.id for review in reviews):
            raise Held('recap_script_replacement_review_required')
    if await db.get(ArtifactHead,job.subject):
        raise Held('recap_script_saved_output_requires_review')
    from app.services.recap_video.editorial_amendment import require_retired_editorial
    for historical in (await db.scalars(select(ContentArtifact).where(ContentArtifact.subject==job.subject))).all():
        await require_retired_editorial(db, historical)
    if (await db.scalar(select(RecapStage.id).where(RecapStage.episode_id==episode.episode_id,
            RecapStage.kind!='preflight').limit(1))
            or await db.scalar(select(RecapProviderAttempt.id).where(RecapProviderAttempt.episode_id==episode.episode_id).limit(1))):
        raise Held('recap_script_media_already_started')
    if (await db.scalar(select(RecapPublicationSelection.id).where(RecapPublicationSelection.episode_id==episode.episode_id).limit(1))
            or await db.scalar(select(RecapPublication.episode_id).where(RecapPublication.episode_id==episode.episode_id,
                RecapPublication.script_id!='').limit(1))):
        raise Held('recap_script_selected_output_requires_review')
    related = list((await db.scalars(select(GenerationOperation).where(GenerationOperation.subject==job.subject))).all())
    if any(other.id!=job.id and other.state in ('queued','running','held','needs_attention') for other in related):
        raise Held('recap_script_related_work_requires_review')
    attempts = list((await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id.in_([other.id for other in related])))).all())
    own = [attempt for attempt in attempts if attempt.operation_id==job.id]
    if (len(own)!=job.calls or any(a.state!='received' or a.usage_state!='known'
            or a.cost_microusd is None or not a.receipt_json for a in attempts)):
        raise Held('recap_script_previous_receipts_unsettled')
    return episode, sum(a.cost_microusd for a in own)


async def prepare_candidate(db, job):
    """Rebuild through the normal immutable observation/article compilation path."""
    from app.config import get_settings
    from app.services.recap_video import workflow
    episode=await db.get(RecapEpisode,json.loads(job.payload_json)['episode_id'])
    selections=await workflow.PUBLISHED_SCRIPT_SELECTIONS(db,episode.series_id) if workflow.PUBLISHED_SCRIPT_SELECTIONS else ()
    candidate=await workflow.prepare_episode_script(db,episode.episode_id,cache_dir=get_settings().cache_dir,
        published_script_ids=selections)
    if episode.lifecycle=='scripting' and not episode.hold:
        episode.lifecycle='ready'
    return candidate


async def add_replacement_cost(db, preview, job, prior_cost):
    """Bind conservative extra script-only spend to the existing campaign digest."""
    from app.services.generation.accounting import bounded_plan
    policy = await resolve_policy(db,job.series_id)
    feature = policy['policy']['features']['recap_video']
    plan = bounded_plan('preview','recap_video',feature,feature,feature['max_calls'])
    manifest = {key:value for key,value in preview.items() if key not in ('id','digest')}
    manifest.update(replacement_job_id=job.id, prior_cost_microusd=prior_cost,
        replacement_job_generation=job.generation,
        maximum_additional_microusd=sum(item['max_microusd'] for item in plan),
        replacement_pricing_plan=plan, cost_scope='script_only_narration_not_included')
    await db.flush()
    record = await db.get(GenerationAudit,preview['id'])
    record.after_json = dump(manifest)
    return {'id':preview['id'],'digest':digest(manifest),**manifest}


async def verify_replacement_cost(db, manifest, candidates):
    required_job=await replacement_for_candidates(db,list(candidates.values()))
    if required_job and 'replacement_pricing_plan' not in manifest:
        raise Held('recap_script_replacement_price_review_required')
    if 'replacement_pricing_plan' not in manifest:
        return
    from app.services.generation.accounting import bounded_plan
    if len(candidates)!=1:
        raise Held('recap_script_replacement_scope_changed')
    candidate = next(iter(candidates.values()))
    if candidate.feature!='recap_video':
        raise Held('recap_script_replacement_scope_changed')
    job=await db.get(GenerationOperation,manifest.get('replacement_job_id',''))
    if (not job or not required_job or job.id!=required_job.id
            or job.generation!=manifest.get('replacement_job_generation') or job.subject!=candidate.subject):
        raise Held('recap_script_replacement_original_changed')
    _,prior_cost=await require_failed_script(db,job,prepared=True)
    if prior_cost!=manifest['prior_cost_microusd']:
        raise Held('recap_script_replacement_original_cost_changed')
    policy = await resolve_policy(db,candidate.series_id)
    feature = policy['policy']['features']['recap_video']
    plan = bounded_plan('preview','recap_video',feature,feature,feature['max_calls'])
    if (plan!=manifest['replacement_pricing_plan']
            or sum(item['max_microusd'] for item in plan)!=manifest['maximum_additional_microusd']):
        raise Held('recap_script_replacement_price_changed')


async def replacement_for_candidates(db, candidates):
    """Any campaign route must retain the durable replacement cost fence."""
    from app.services.generation.candidate_status import replacement_review_target
    replacement_jobs=[]
    for candidate in candidates:
        if candidate.feature!='recap_video':
            continue
        reviews=(await db.scalars(select(GenerationAudit).where(GenerationAudit.action=='replacement_review_required',
            GenerationAudit.target==replacement_review_target(candidate.subject,candidate.event)))).all()
        ids={json.loads(review.after_json).get('job_id') for review in reviews}
        if not ids:
            continue
        jobs=list((await db.scalars(select(GenerationOperation).where(GenerationOperation.id.in_(ids))
            .order_by(GenerationOperation.created_at.desc(),GenerationOperation.id.desc()))).all())
        if not jobs or (len(jobs)>1 and jobs[0].created_at==jobs[1].created_at):
            raise Held('recap_script_replacement_original_ambiguous')
        job=jobs[0]
        if job.subject!=candidate.subject or job.league_id!=candidate.league_id or job.series_id!=candidate.series_id:
            raise Held('recap_script_replacement_scope_changed')
        await require_failed_script(db,job,prepared=True)
        replacement_jobs.append(job)
    if replacement_jobs and (len(candidates)!=1 or len(replacement_jobs)!=1):
        raise Held('recap_script_replacement_separate_review_required')
    return replacement_jobs[0] if replacement_jobs else None


async def bind_campaign_replacement(db, preview, candidates):
    job=await replacement_for_candidates(db,candidates)
    if not job:
        return preview
    _,prior_cost=await require_failed_script(db,job,prepared=True)
    return await add_replacement_cost(db,preview,job,prior_cost)
