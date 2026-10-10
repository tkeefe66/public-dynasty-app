"""Durable calibration and three distinct, unchanged, reviewed episodes.

Calibration is an explicit administrator attestation to retained external
evidence. Metadata accessibility and synthetic QA cannot create this authority.
"""
import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import User
from app.services.generation.models import ContentArtifact, LeagueSeason, ProviderAttempt, stamp
from app.services.generation.recap_models import (RecapAsset, RecapBudgetAllocation, RecapBudgetPlan,
    RecapCalibration, RecapEpisode, RecapProviderAttempt, RecapPublicationApproval,
    RecapQualificationReview, RecapRecovery, RecapShareDecision, RecapStage, RecapStandingAuthorization)
from app.services.generation.store import Held, audit, digest, dump, lock_control, resolve_policy


async def require_admin_actor(db, actor_id):
    actor = await db.get(User, actor_id, populate_existing=True)
    if not actor or not actor.is_admin or actor.email.lower() not in get_settings().admin_email_list:
        raise Held('admin_permission_removed')
    return actor


def current_versions():
    from sleeper_dynasty.engine import recap_video_claims
    from sleeper_dynasty.llm import recap_video_writer
    from media import timeline, geometry, qa, audio_seams
    from app.services.recap_video import audio, rendering, elevenlabs, periods, readiness
    modules = (recap_video_claims, recap_video_writer, timeline, geometry, qa, audio_seams, audio, rendering, elevenlabs, periods, readiness)
    result={module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in modules}
    root=Path(timeline.__file__).parent
    for name in ('render/render.cjs','render/scene.js','render/style.css','render/index.html','Dockerfile','requirements.lock','package-lock.json'):
        result[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    return result


def evidence_hashes(evidence, required):
    if (not isinstance(evidence, dict) or set(evidence) != set(required)
            or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in evidence.values())):
        raise Held('qualification_evidence_required')


async def record_calibration(db, series_id, season, *, actor_id, config, metadata, rate_snapshot, evidence, reason):
    from app.services.recap_video.elevenlabs import preflight_config, validate_request, MODEL
    await lock_control(db)
    await require_admin_actor(db, actor_id)
    evidence_hashes(evidence, ('account_entitlement', 'settings_continuity', 'billing_terms', 'full_performance', 'linux_runtime'))
    if config != preflight_config() or not isinstance(metadata, dict) or not metadata or not reason.strip():
        raise Held('media_calibration_invalid')
    validate_request({'model_id': MODEL, 'inputs':[{'voice_id':config['voice_id'], 'text':'Calibration'}],
        'settings':config['settings']}, rate_snapshot, 9_007_199_254_740_991)
    latest = await db.scalar(select(func.max(LeagueSeason.season)).where(LeagueSeason.series_id == series_id))
    if latest != season:
        raise Held('qualification_current_season_required')
    row = RecapCalibration(series_id=series_id, season=season, config_json=dump(config), metadata_json=dump(metadata),
        rate_json=dump(rate_snapshot), versions_json=dump(current_versions()), evidence_json=dump(evidence), actor_id=actor_id)
    db.add(row)
    await db.flush()
    audit(db, actor_id, 'recap_calibration_approved', row.id, reason)
    return row


async def calibration(db, series_id, season):
    from app.services.recap_video.elevenlabs import preflight_config
    row = await db.scalar(select(RecapCalibration).where(RecapCalibration.series_id == series_id,
        RecapCalibration.season == season).order_by(RecapCalibration.created_at.desc(), RecapCalibration.id.desc()).limit(1))
    if not row:
        raise Held('media_calibration_required')
    if json.loads(row.config_json) != preflight_config() or json.loads(row.versions_json) != current_versions():
        raise Held('media_calibration_changed')
    await require_admin_actor(db, row.actor_id)
    return row


async def qualification_reader(db, episode_id):
    episode = await db.get(RecapEpisode, episode_id)
    if not episode:
        raise Held('recap_episode_missing')
    row = await calibration(db, episode.series_id, episode.season)
    return dict(revision=row.id, config=json.loads(row.config_json), metadata=json.loads(row.metadata_json),
        rate_snapshot=json.loads(row.rate_json))


async def review_binding(db, episode_id, media_id):
    """Bind content and all selected paid/free evidence; timestamps are not content."""
    episode = await db.get(RecapEpisode, episode_id, populate_existing=True)
    stage = await db.get(RecapStage, media_id, populate_existing=True)
    if not episode or episode.hold or not stage or stage.episode_id != episode_id or stage.kind != 'media_check' or stage.state != 'succeeded':
        raise Held('qualification_finished_preview_required')
    script = await db.get(ContentArtifact, stage.script_id, populate_existing=True)
    if not script or script.digest != digest(json.loads(script.payload_json)):
        raise Held('qualification_script_changed')
    stages = (await db.scalars(select(RecapStage).where(RecapStage.script_id == script.id,
        RecapStage.execution_revision == stage.execution_revision).order_by(RecapStage.id).execution_options(populate_existing=True))).all()
    if not stages or any(item.state != 'succeeded' for item in stages):
        raise Held('qualification_checkpoints_incomplete')
    narration = (await db.scalars(select(RecapProviderAttempt).where(RecapProviderAttempt.episode_id == episode_id).execution_options(populate_existing=True))).all()
    if not narration or any(item.cost_microusd is None or item.state in ('dispatching', 'unknown', 'abandoned') for item in narration):
        raise Held('qualification_receipts_unreconciled')
    allocations = (await db.scalars(select(RecapBudgetAllocation).join(RecapBudgetPlan,
        RecapBudgetAllocation.plan_id == RecapBudgetPlan.id).where(RecapBudgetPlan.episode_id == episode_id).execution_options(populate_existing=True))).all()
    if any(item.outstanding_microusd for item in allocations):
        raise Held('qualification_receipts_unreconciled')
    prose = (await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == script.operation_id).execution_options(populate_existing=True))).all()
    if not prose or any(item.cost_microusd is None for item in prose):
        raise Held('qualification_receipts_unreconciled')
    assets = (await db.scalars(select(RecapAsset).where(RecapAsset.stage_id.in_([item.id for item in stages])).order_by(RecapAsset.id))).all()
    from app.services.generation.models import ArtifactHead
    script_head=await db.get(ArtifactHead,script.subject)
    article=await db.scalar(select(ContentArtifact).where(ContentArtifact.series_id==episode.series_id,
        ContentArtifact.feature=='analyst',ContentArtifact.digest==episode.article_digest))
    article_head=await db.get(ArtifactHead,article.subject) if article else None
    heads=[[head.artifact_id,head.revision,head.hold] if head else None for head in (script_head,article_head)]
    recoveries = (await db.scalars(select(RecapRecovery).where(RecapRecovery.stage_id.in_([item.id for item in stages]),
        RecapRecovery.action == 'adopt_recovered_audio').order_by(RecapRecovery.id))).all()
    return dict(facts_digest=episode.facts_digest, article_digest=episode.article_digest,
        heads=heads,
        script_id=script.id, script_digest=script.digest, media_id=media_id, versions=current_versions(),
        stages=[[s.id,s.generation,s.input_digest,s.result_json,s.evidence_json] for s in stages],
        assets=[[a.id,a.digest] for a in assets],
        recoveries=[[r.id,r.stage_id,r.before_json] for r in recoveries],
        receipts=sorted([[a.id,a.cost_microusd,a.state,a.recovery_receipt_json] for a in narration]))


async def qualification_status(db, series_id: str, season: int) -> dict:
    status = dict(passed=0, required=3, automatic=False, reason='media_calibration_required', review_ids=[], standing_id=None)
    try:
        calibrated = await calibration(db, series_id, season)
    except Held as exc:
        status['reason'] = exc.code
        return status
    rows = (await db.scalars(select(RecapQualificationReview).where(RecapQualificationReview.series_id == series_id,
        RecapQualificationReview.season == season).order_by(RecapQualificationReview.created_at, RecapQualificationReview.id))).all()
    latest = {row.episode_id:row for row in rows}
    valid = []
    for row in latest.values():
        if not row.passed or row.calibration_id != calibrated.id:
            continue
        try:
            await require_admin_actor(db, row.actor_id)
            saved = json.loads(row.binding_json)
            if saved != await review_binding(db, row.episode_id, saved['media_id']):
                continue
            valid.append(row.id)
        except Held:
            continue
    status.update(passed=len(valid), review_ids=valid, reason='reviewed_episodes_required')
    standing = await db.scalar(select(RecapStandingAuthorization).where(RecapStandingAuthorization.series_id == series_id,
        RecapStandingAuthorization.season == season, RecapStandingAuthorization.calibration_id == calibrated.id)
        .order_by(RecapStandingAuthorization.created_at.desc()).limit(1))
    if not standing or len(set(json.loads(standing.review_ids_json)) & set(valid)) < 3:
        return status
    status['standing_id'] = standing.id
    config = await resolve_policy(db, series_id)
    from app.services.recap_video import workflow
    settings=get_settings()
    if (settings.generation_emergency_pause or not config['epoch'] or settings.generation_execution_epoch != config['epoch']
            or workflow.MEDIA_PLAN_BUILDER is None or set(workflow.MEDIA_KINDS)-set(workflow.RESULT_VALIDATORS)):
        status['reason']='media_runtime_not_authorized'
        return status
    latest_season = await db.scalar(select(func.max(LeagueSeason.season)).where(LeagueSeason.series_id == series_id))
    from app.services.recap_video.publication import serving_gate
    try:
        await serving_gate(db)
    except Held as exc:
        status['reason'] = exc.code
        return status
    if latest_season != season or config['blocked_by'] or any(config['policy']['features'][f]['mode'] != 'automatic'
            or config['policy']['features'][f]['paused'] for f in ('analyst', 'recap_video')):
        status['reason'] = 'automatic_policy_not_current'
        return status
    future = await db.get(RecapShareDecision, 'series:'+series_id)
    if not future or not future.allowed or future.opted_out:
        status['reason'] = 'future_sharing_disabled'
        return status
    status.update(automatic=True, reason='qualified')
    return status


async def record_preview_approval(db, episode_id: str, expected_revision: int, actor_id: str, evidence: dict) -> dict:
    from app.services.recap_video import publication
    # Do not take a control lock until publication verifies storage.
    actor = await require_admin_actor(db, actor_id)
    required = ('factual_coverage', 'performance', 'physical_phone', 'message_preview')
    checks=evidence.get('checks')
    if not isinstance(checks,dict) or set(checks) != set(required) or any(not isinstance(v,str) or not 20 <= len(v.strip()) <= 2000 for v in checks.values()):
        raise Held('qualification_review_evidence_required')
    proof = await publication.record_approval(db, episode_id, expected_revision, evidence.get('media_id'),
        reviewer=actor, reason=evidence.get('reason', ''), preview_digest=evidence.get('preview_digest', ''))
    episode = await db.get(RecapEpisode, episode_id)
    calibrated = await calibration(db, episode.series_id, episode.season)
    binding = await review_binding(db, episode_id, evidence['media_id'])
    review = RecapQualificationReview(episode_id=episode_id, series_id=episode.series_id, season=episode.season,
        calibration_id=calibrated.id, approval_id=proof['approval_id'], binding_json=dump(binding),
        evidence_json=dump(evidence['checks']), actor_id=actor_id, passed=True)
    db.add(review)
    await db.flush()
    status = await qualification_status(db, episode.series_id, episode.season)
    if status['passed'] >= 3 and not status['standing_id']:
        db.add(RecapStandingAuthorization(series_id=episode.series_id, season=episode.season,
            calibration_id=calibrated.id, review_ids_json=dump(sorted(status['review_ids'])), actor_id=actor_id))
        audit(db, actor_id, 'recap_standing_policy_qualified', episode.series_id,
            'Accepted standing policy; three distinct current season reviewed episodes')
    return proof


async def require_standing_format(db, episode):
    """Recognize the saved authoritative format, including qualified postseason."""
    from app.services.generation.recap_models import RecapObservation
    from app.services.recap_video.periods import scoring_period
    from app.services.recap_video.readiness import source_ready, competitive_digest
    observation = await db.get(RecapObservation,episode.latest_observation_id)
    source = json.loads(observation.snapshot_json) if observation else {}
    if source.get('phase') == 'regular' and episode.round is None and source.get('round') is None:
        return
    try:
        recognized = scoring_period(episode.week,source.get('rules',{}),source.get('bracket',{}))
    except (ValueError,TypeError,KeyError):
        raise Held('recap_format_review_required') from None
    if (recognized['phase'] != 'post' or source.get('phase') != 'post'
            or any(source.get(key) != recognized.get(key) for key in ('period_id','week','round','round_type','nfl_weeks'))
            or (episode.period_id,episode.week,episode.round,json.loads(episode.nfl_weeks_json))
                != (recognized['period_id'],recognized['week'],recognized['round'],recognized['nfl_weeks'])
            or episode.facts_digest != competitive_digest(source) or not source_ready(episode,source)):
        raise Held('recap_format_review_required')


async def record_standing_approval(db, episode_id, expected_revision, media_id):
    from app.services.recap_video import publication
    media, script_id = await publication.verified_media(db, episode_id, media_id)
    await db.flush()
    db.expire_all()  # Storage I/O may have overlapped a recovery or policy commit.
    await lock_control(db)
    episode = await db.get(RecapEpisode, episode_id)
    status = await qualification_status(db, episode.series_id, episode.season)
    if not status['automatic']:
        raise Held('recap_standing_review_required')
    await require_standing_format(db,episode)
    scope = await publication.current_scope(db, episode_id, expected_revision, media_id)
    # Initial same-revision article-only sharing is not a media approval. The
    # independent standing grant can attach its first video; revisions/retakes
    # still require an explicit finished-preview review.
    existing = await publication.authority_for_episode(db, episode)
    article = scope['article']
    if (article['revision'] != 1 or existing and (existing.withdrawn or existing.hold or existing.media_id
            or existing.article_revision != 1 or existing.article_id != article['artifact_id']
            or existing.article_digest != article['digest'])):
        raise Held('recap_revision_review_required')
    scope.update(media_digest=digest(media), script_id=script_id)
    scope['target_review_binding'] = await target_publication_binding(db,episode_id,scope)
    row = RecapPublicationApproval(episode_id=episode_id, scope_json=dump(scope), reviewer_id='',
        reason='Current standing policy authorization', authorization_kind='standing', authorization_id=status['standing_id'])
    db.add(row)
    await db.flush()
    audit(db, 'standing-policy:'+status['standing_id'], 'recap_standing_selection_authorized', episode_id, row.reason)
    return {'approval_id':row.id}


async def target_publication_binding(db, episode_id, scope, *, manual_proof_id=None):
    """Reconcile every obligation; recovered bytes additionally need human review.

    This is database-only and runs under the publication control lock. Storage
    verification remains in the caller's pre-lock phase.
    """
    binding = await review_binding(db,episode_id,scope['media_id'])
    if binding['recoveries']:
        episode = await db.get(RecapEpisode,episode_id)
        calibrated = await calibration(db,episode.series_id,episode.season)
        reviews = (await db.scalars(select(RecapQualificationReview).where(
            RecapQualificationReview.episode_id == episode_id,
            RecapQualificationReview.calibration_id == calibrated.id,
            RecapQualificationReview.passed.is_(True)))).all()
        for review in reviews:
            if json.loads(review.binding_json) != binding:
                continue
            approval = await db.get(RecapPublicationApproval,review.approval_id)
            if (not approval or approval.authorization_kind != 'manual'
                    or approval.reviewer_id != review.actor_id or approval.episode_id != episode_id
                    or manual_proof_id and approval.id != manual_proof_id
                    or json.loads(approval.scope_json) != scope):
                continue
            await require_admin_actor(db,review.actor_id)
            return binding
        raise Held('recovered_audio_finished_review_required')
    return binding


async def require_standing_proof(db, proof):
    scope = json.loads(proof.scope_json)
    if proof.authorization_kind != 'standing':
        # Manual recovered publication also rechecks its exact review after the
        # separate approval transaction and again before outbox projection.
        if scope.get('media_id'):
            stage = await db.get(RecapStage,scope['media_id'])
            recovered = await db.scalar(select(RecapRecovery.id).join(RecapStage,
                RecapRecovery.stage_id == RecapStage.id).where(
                RecapStage.script_id == stage.script_id,
                RecapStage.execution_revision == stage.execution_revision,
                RecapRecovery.action == 'adopt_recovered_audio').limit(1)) if stage else None
            if recovered:
                await target_publication_binding(db,proof.episode_id,scope,manual_proof_id=proof.id)
        return {}
    episode = await db.get(RecapEpisode, proof.episode_id)
    status = await qualification_status(db, episode.series_id, episode.season)
    if not status['automatic'] or status['standing_id'] != proof.authorization_id:
        raise Held('recap_standing_authorization_changed')
    await require_standing_format(db,episode)
    saved = scope.pop('target_review_binding',None)
    binding = await target_publication_binding(db,proof.episode_id,scope)
    if saved != binding:
        raise Held('recap_target_review_changed')
    return {'target_review_binding':binding}


def install_api():
    from app.services.recap_video import elevenlabs
    elevenlabs.QUALIFICATION_READER = qualification_reader


async def advance_qualified_publication(maker):
    """Existing API projector only; storage verification never under an inherited lock."""
    from app.services.recap_video.admin_actions import active_stages
    from app.services.recap_video.publication import select_publication
    from app.services.recap_video.corrections import attention
    from app.services.generation.store import Conflict
    async with maker() as db:
        rows=(await db.scalars(select(RecapEpisode).where(RecapEpisode.lifecycle=='review',RecapEpisode.hold=='').limit(50))).all()
        targets=[row.episode_id for row in rows]
    for ident in targets:
        try:
            async with maker.begin() as db:
                stages=await active_stages(db,ident)
                finished=next((row for row in stages if row.kind=='media_check' and row.state=='succeeded'),None)
                if not finished:
                    continue
                media_id=finished.id
                from app.services.recap_video.publication import authority_for_episode
                authority=await authority_for_episode(db,await db.get(RecapEpisode,ident))
                expected_revision=authority.authority_revision if authority else 0
                proof=await record_standing_approval(db,ident,expected_revision,media_id)
            async with maker.begin() as db:
                await select_publication(db,ident,expected_revision,media_id,proof)
                (await db.get(RecapEpisode,ident)).lifecycle='published'
        except (Held,Conflict) as exc:
            async with maker.begin() as db:
                await lock_control(db)
                await attention(db,ident,'review',str(exc))
