"""Explicit scoped operator commands. No provider network calls or generic retry."""
import json

from sqlalchemy import select
from app.config import get_settings

from app.services.generation.models import ArtifactHead, ContentArtifact, stamp
from app.services.generation.recap_models import RecapEpisode, RecapProviderAttempt, RecapRecovery, RecapStage
from app.services.generation.store import Conflict, Held, audit, data, digest, dump, lock_control
from app.services.recap_video.qualification import require_admin_actor


async def active_stages(db, episode_id):
    rows = (await db.scalars(select(RecapStage).where(RecapStage.episode_id == episode_id,
        RecapStage.kind != 'preflight').order_by(RecapStage.revision.desc(), RecapStage.execution_revision.desc(), RecapStage.created_at, RecapStage.id))).all()
    if not rows:
        return []
    return [row for row in rows if (row.revision,row.execution_revision) == (rows[0].revision,rows[0].execution_revision)]


async def replacement_preview(db, episode_id):
    from app.services.recap_video.workflow import _current
    rows = await active_stages(db, episode_id)
    paid = sorted([row for row in rows if row.kind == 'narrate'], key=lambda r:r.chunk)
    if not paid:
        raise Held('replacement_narration_missing')
    await _current(db, paid[0], now=stamp())
    maximum = sum(json.loads(row.input_json)['paid']['max_microusd'] for row in paid)
    attempts = (await db.scalars(select(RecapProviderAttempt).where(RecapProviderAttempt.episode_id == episode_id)
        .order_by(RecapProviderAttempt.id))).all()
    snapshot = dict(episode_id=episode_id, script_id=paid[0].script_id, revision=paid[0].revision,
        execution_revision=paid[0].execution_revision, requests=len(paid), maximum_microusd=maximum,
        stages=[[row.id,row.generation,row.state,row.input_digest] for row in rows])
    snapshot['original_requests'] = [dict(id=a.id, state=a.state, identity=json.loads(a.identity_json),
        cost_microusd=a.cost_microusd) for a in attempts]
    return {**snapshot, 'digest':digest(snapshot)}


async def approve_replacement(db, episode_id, *, preview_digest, maximum_microusd, actor_id, reason, disposition_evidence):
    from app.services.generation.recap_budget import _reserve
    await lock_control(db)
    await require_admin_actor(db, actor_id)
    preview = await replacement_preview(db, episode_id)
    if preview['digest'] != preview_digest or preview['maximum_microusd'] != maximum_microusd:
        raise Conflict('Replacement changed. Review its current request count and maximum cost.')
    if not isinstance(disposition_evidence,str) or len(disposition_evidence.strip()) < 20:
        raise Held('replacement_unrecoverable_evidence_required')
    if any(a['state'] == 'dispatching' for a in preview['original_requests']):
        raise Held('replacement_request_still_active')
    episode = await db.get(RecapEpisode, episode_id)
    old = await active_stages(db, episode_id)
    order = {'narrate':0, 'speech_check':1, 'render':2, 'media_check':3}
    old.sort(key=lambda row:(order[row.kind],row.chunk))
    revision = preview['execution_revision'] + 1
    previous, fresh, allocations = '', [], []
    for row in old:
        new = RecapStage(episode_id=episode_id, revision=row.revision, execution_revision=revision,
            kind=row.kind, chunk=row.chunk, script_id=row.script_id, operation_id=row.operation_id,
            predecessor_id=previous, input_json=row.input_json, input_digest=row.input_digest,
            policy_digest=row.policy_digest, epoch=row.epoch)
        db.add(new)
        await db.flush()
        previous = new.id
        fresh.append(new)
        if new.kind == 'narrate':
            paid = json.loads(new.input_json)['paid']
            allocations.append(dict(key=new.id,category='video',operation_id=new.id,
                max_microusd=paid['max_microusd'],rate_snapshot=paid['rate_snapshot']))
    # Every old unknown obligation remains in the episode/month intersection.
    await _reserve(db, episode_id, episode.series_id, 'media:'+preview['script_id']+':'+str(revision), allocations, stamp(), allow_bounded_unknown=True)
    dispositioned = []
    for item in preview['original_requests']:
        attempt = await db.get(RecapProviderAttempt,item['id'])
        if attempt.state in ('unknown','abandoned'):
            attempt.state = 'abandoned'
            dispositioned.append(attempt.id)
    for row in fresh:
        if row.kind == 'narrate':
            db.add(RecapRecovery(episode_id=episode_id,stage_id=row.id,action='bounded_replacement_authority',
                before_json=dump(dict(input_digest=row.input_digest,script_id=row.script_id,execution_revision=revision,
                    dispositioned=dispositioned,maximum_microusd=maximum_microusd,evidence=disposition_evidence)),
                actor_id=actor_id,reason=reason))
    for row in old:
        db.add(RecapRecovery(episode_id=episode_id,stage_id=row.id,action='bounded_replacement',
            before_json=dump(data(row)),actor_id=actor_id,reason=reason))
        if row.state != 'succeeded':
            row.state, row.reason, row.lease_until = 'cancelled', 'replacement_approved', 0
            row.generation += 1
    for attempt in (await db.scalars(select(RecapProviderAttempt).where(RecapProviderAttempt.stage_id.in_([r.id for r in old]),
            RecapProviderAttempt.state == 'dispatching'))).all():
        attempt.state = 'unknown'
    audit(db, actor_id, 'recap_bounded_replacement', episode_id, reason,
        after=dict(maximum_microusd=maximum_microusd,requests=preview['requests'],execution_revision=revision))
    return dict(episode_id=episode_id, execution_revision=revision, requests=preview['requests'], maximum_microusd=maximum_microusd)


async def replacement_dispositions(db, stage):
    if stage.execution_revision == 1:
        return frozenset()
    proof = await db.scalar(select(RecapRecovery).where(RecapRecovery.stage_id == stage.id,
        RecapRecovery.action == 'bounded_replacement_authority'))
    if not proof:
        raise Held('replacement_authorization_required')
    await require_admin_actor(db,proof.actor_id)
    value=json.loads(proof.before_json)
    if (value['input_digest'] != stage.input_digest or value['script_id'] != stage.script_id
            or value['execution_revision'] != stage.execution_revision):
        raise Held('replacement_authorization_changed')
    approved=set()
    for ident in value['dispositioned']:
        attempt=await db.get(RecapProviderAttempt,ident)
        if not attempt or attempt.episode_id != stage.episode_id or attempt.state == 'dispatching':
            raise Held('replacement_disposition_changed')
        original = await db.get(RecapStage, attempt.stage_id)
        if (not original or original.script_id != stage.script_id
                or original.execution_revision >= stage.execution_revision):
            raise Held('replacement_disposition_changed')
        if attempt.state in ('abandoned','unknown') or (attempt.state == 'received' and attempt.error_code == 'response_invalid'):
            approved.add(ident)
    return frozenset(approved)


async def episode_view(db, episode_id):
    from app.services.generation.recap_budget import get_budget_view
    from app.services.recap_video.qualification import qualification_status
    from app.services.recap_video.publication import authority_for_episode
    episode = await db.get(RecapEpisode, episode_id)
    if not episode:
        raise Held('recap_episode_missing')
    stages = await active_stages(db, episode_id)
    public = await authority_for_episode(db, episode)
    attempts = (await db.scalars(select(RecapProviderAttempt).where(RecapProviderAttempt.episode_id == episode_id))).all()
    stage = next((s for s in stages if s.state in ('held','needs_attention','running')), None)
    if not stages:
        stage=await db.scalar(select(RecapStage).where(RecapStage.episode_id==episode_id,RecapStage.kind=='preflight')
            .order_by(RecapStage.revision.desc()).limit(1))
    finished = next((s for s in stages if s.kind == 'media_check' and s.state == 'succeeded'), None)
    reason = episode.hold or (stage.reason if stage else '')
    from app.services.generation.recap_models import RecapRecoveryRequest
    requests=(await db.scalars(select(RecapRecoveryRequest).where(RecapRecoveryRequest.attempt_id.in_([a.id for a in attempts])).order_by(RecapRecoveryRequest.created_at.desc()))).all()
    actions = ['disable_future_sharing', 'restore_access', 'skip_video']
    if finished and not episode.hold:
        actions.insert(0, 'review_publish')
    if stage and stage.kind in ('speech_check','render','media_check') and stage.state in ('held','needs_attention'):
        actions.insert(0, 'resume_free')
    if any(a.state in ('unknown','dispatching','abandoned') for a in attempts):
        actions.insert(0, 'reconcile_request')
    if any(a.recovery_receipt_json and a.state != 'abandoned' for a in attempts) and stage and stage.kind=='narrate':
        actions.insert(0,'resume_recovered_audio')
    if any(a.worker_id != get_settings().media_worker_id for a in attempts):
        actions.append('reassign_worker')
    if stages:
        actions.append('bounded_replacement')
    else:
        actions.append('prepare_preview')
    if episode.admitted_at and not episode.hold:
        actions.append('renew_preflight')
    if episode.hold.startswith('recap_'):
        actions.insert(0,'review_correction')
    values = dict(episode=data(episode), authority_revision=public.authority_revision if public else 0,
        stage=data(stage) if stage else None, media_id=finished.id if finished else None,
        stages=[data(s) for s in stages], attempts=[dict(id=a.id,state=a.state,cost_microusd=a.cost_microusd,
            identity=json.loads(a.identity_json),worker_id=a.worker_id,error_code=a.error_code) for a in attempts],
        qualification=await qualification_status(db, episode.series_id, episode.season), reason=reason, actions=actions,
        budget=await get_budget_view(db, episode.series_id, episode_id, stamp()))
    values['recovery_requests']=[data(r) for r in requests]
    values['configured_worker_id']=get_settings().media_worker_id
    values['speech_entities']=[]
    values['needed_microusd']=sum(json.loads(s.input_json).get('paid',{}).get('max_microusd',0)
        for s in stages if s.kind=='narrate' and s.state!='succeeded')
    if stage and stage.kind=='speech_check':
        from app.services.recap_video.speech_reviews import context
        _,entities,_=await context(db,await db.get(ContentArtifact,stage.script_id))
        values['speech_entities']=[dict(kind=kind,id=ident,name=name) for (kind,ident),name in entities.items()]
    values['revision'] = digest([data(episode), [[s.id,s.generation,s.state,s.input_digest] for s in stages],
        values['authority_revision'], [(a.id,a.state,a.identity_json) for a in attempts]])
    return values


async def require_episode_revision(db, episode_id, expected):
    await lock_control(db)
    view = await episode_view(db, episode_id)
    if view['revision'] != expected:
        raise Conflict('Episode changed. Reload current evidence before acting.')
    return view


async def apply_action(db, episode_id, *, actor_id, expected_revision, action, reason, stage_id='',
        expected_generation=0, attempt_id='', worker_id='', spellings=None):
    await require_admin_actor(db, actor_id)
    verified = None
    if action == 'resume_recovered_audio':
        from app.services.recap_video.recovery import recovered_audio_plan
        # Remote object verification must finish before the generation control lock.
        verified = await recovered_audio_plan(db,episode_id,verify_bytes=True)
        db.expire_all()
    view = await require_episode_revision(db, episode_id, expected_revision)
    episode = await db.get(RecapEpisode, episode_id)
    if action == 'resume_recovered_audio':
        from app.services.recap_video.recovery import adopt_recovered_audio
        return await adopt_recovered_audio(db,episode_id,verified,actor_id=actor_id,reason=reason)
    if action == 'resume_free':
        from app.services.recap_video.corrections import resume_free
        from app.services.recap_video.speech_reviews import approve_spellings
        if spellings:
            stage = await db.get(RecapStage, stage_id)
            if not stage or stage.episode_id != episode_id or stage.kind != 'speech_check':
                raise Held('speech_review_checkpoint_required')
            for spelling in spellings:
                await approve_spellings(db, script_id=stage.script_id, actor_id=actor_id, reason=reason, **spelling)
        return await resume_free(db, episode_id, stage_id=stage_id,expected_generation=expected_generation,actor_id=actor_id,reason=reason)
    if action in ('reconcile_request','reassign_worker'):
        from app.services.recap_video.workflow import recovery_evidence, settle_receipt
        attempt = await db.get(RecapProviderAttempt, attempt_id)
        if not attempt or attempt.episode_id != episode_id:
            raise Held('recap_attempt_missing')
        if action == 'reassign_worker':
            from app.config import get_settings
            if not worker_id or worker_id != get_settings().media_worker_id:
                raise Held('recovery_configured_worker_required')
            from app.services.generation.recap_models import RecapRecoveryRequest
            for request in (await db.scalars(select(RecapRecoveryRequest).where(RecapRecoveryRequest.attempt_id==attempt.id,RecapRecoveryRequest.state.in_(('pending','running'))))).all():
                request.state,request.error,request.lease_until='held','worker_reassigned',0
                request.generation += 1
            db.add(RecapRecovery(episode_id=episode_id,stage_id=attempt.stage_id,action=action,
                before_json=dump({'worker_id':attempt.worker_id,'attempt_id':attempt.id}),actor_id=actor_id,reason=reason))
            attempt.worker_id = worker_id
        if attempt.receipt_json or attempt.recovery_receipt_json:
            await settle_receipt(db, attempt.id, worker_id=attempt.worker_id)
        evidence = await recovery_evidence(db, attempt.id, worker_id=attempt.worker_id)
        audit(db, actor_id, 'recap_'+action, attempt.id, reason)
        from app.services.recap_video.recovery import enqueue_recovery
        request=await enqueue_recovery(db,attempt.id,actor_id=actor_id,reason=reason)
        return dict(attempt_id=attempt.id,worker_id=attempt.worker_id,state=request.state,
            identity=evidence['identity'],recovery_id=request.id,action='Exact saved history retrieval queued for original worker; narration will not be resent')
    if action == 'disable_future_sharing':
        from app.services.recap_video.publication import set_future_sharing
        await set_future_sharing(db, episode.series_id, allowed=False, actor_id=actor_id)
    elif action == 'restore_access':
        from app.services.recap_video.publication import authority_for_episode, change_share
        row = await authority_for_episode(db, episode)
        await change_share(db,row,enabled=True,actor_id=actor_id,
            league_id=episode.league_id,season=episode.season,week=episode.week)
    elif action == 'skip_video':
        from app.services.recap_video.workflow import cancel_media
        await cancel_media(db,episode_id,actor_id,reason)
        episode.lifecycle = 'video_skipped'
    elif action == 'renew_preflight':
        from app.services.recap_video.workflow import prepare_preflight
        if not episode.admitted_at or episode.hold:
            raise Held(episode.hold or 'recap_not_admitted')
        await prepare_preflight(db,episode_id,actor_id=actor_id,reason=reason)
    elif action == 'prepare_preview':
        from app.services.recap_video.workflow import prepare_preflight
        from app.services.recap_video.readiness import source_ready, _admission_reason, EpisodeKey
        from app.services.generation.recap_models import RecapObservation
        observation=await db.get(RecapObservation,episode.latest_observation_id)
        source=json.loads(observation.snapshot_json) if observation else {}
        if not source_ready(episode,source):
            raise Held('recap_stable_facts_required')
        denial=await _admission_reason(db,EpisodeKey(episode.series_id,episode.season,episode.period_id),source,explicit_manual=True)
        if denial:
            raise Held(denial)
        if not episode.admitted_at:
            episode.admitted_at=stamp()
            episode.lifecycle,episode.hold='ready',''
        await prepare_preflight(db,episode_id,actor_id=actor_id,reason=reason)
    elif action == 'review_correction':
        from app.services.recap_video.readiness import source_ready
        from app.services.generation.recap_models import RecapObservation
        observation = await db.get(RecapObservation,episode.latest_observation_id)
        if not observation or not source_ready(episode,json.loads(observation.snapshot_json)):
            raise Held('correction_stable_facts_required')
        episode.lifecycle,episode.hold = 'ready',''
        # Proposal is free; existing admin correction/campaign approves paid prose.
        from app.services.recap_video.collector import edition_from_snapshot
        from app.services.generation.planner import observe
        from app.services.generation.artifacts import subject_key
        source=json.loads(observation.snapshot_json)
        edition=edition_from_snapshot(source,generated_at=stamp())
        candidate=await observe(db,series_id=episode.series_id,league_id=episode.league_id,feature='analyst',
            subject=subject_key('analyst',episode.series_id,episode.season,episode.week),event=f'{episode.season}:week:{episode.week:02d}',
            payload=dict(edition=edition,facts=edition['facts'],season=episode.season,week=episode.week,
                period_id=episode.period_id,recap_facts_digest=episode.facts_digest,event_at=stamp()))
        head=await db.get(ArtifactHead,candidate.subject)
        if head:
            from app.services.generation.models import GenerationCandidate,uid
            artifact=await db.get(ContentArtifact,head.artifact_id)
            payload={**json.loads(candidate.payload_json),'correction_base':head.artifact_id,
                'correction_reason':reason,'previous_content':json.loads(artifact.payload_json)}
            db.add(GenerationCandidate(key='correction:'+uid(),series_id=candidate.series_id,league_id=candidate.league_id,
                feature='analyst',subject=candidate.subject,event='correction:'+head.artifact_id,
                payload_json=dump(payload),digest=digest(payload),hold='historical_approval_required'))
    else:
        raise Held('recap_action_invalid')
    audit(db,actor_id,'recap_'+action,episode_id,reason)
    return {'episode_id':episode_id,'action':action}
