"""Bounded operation commands; browsers never own worker lifetimes."""
from __future__ import annotations

import json

from sqlalchemy import select

from app.db.models import LeagueMembership, User, YahooConnection, YahooLeagueGrant
from app.services.generation.models import (
    GenerationCandidate,
    GenerationOperation,
    GenerationSubmission,
    LeagueSeason,
    ProviderAttempt,
    stamp,
)
from app.services.generation.store import (
    Conflict,
    Held,
    OwnershipLost,
    audit,
    digest,
    dump,
    lock_control,
    resolve_policy,
)

LEASE_SECONDS = 600
UNRESOLVED = ("dispatching", "unknown")
# Abandoned work is not active concurrency, but its unknown content outcome
# still prohibits replacement. Invoice reconciliation cannot grant authority.
UNRESOLVED_OUTCOMES = (*UNRESOLVED, "abandoned")
FREE_REFRESH_KINDS = ("refresh", "analyst_refresh")


def failed_data_refresh(job: GenerationOperation) -> bool:
    """A stopped free data collection can be retried after an explicit review."""
    return (job.kind in FREE_REFRESH_KINDS
            and job.state == "needs_attention" and job.reason == "execution_failed")


async def require_actor(db, job: GenerationOperation):
    """Recheck stored identity, membership and connection generation per stage."""
    member_ids = list((await db.scalars(select(LeagueMembership.user_id).where(
        LeagueMembership.league_id == job.league_id))).all())
    if not member_ids:
        raise Held("membership_removed")
    if not job.actor_id:
        raise Held("actor_removed")
    if job.actor_id:
        user = await db.get(User, job.actor_id)
        if not user:
            raise Held("actor_removed")
        if job.kind == "generation":
            from app.config import get_settings
            if not user.is_admin or user.email.lower() not in get_settings().admin_email_list:
                raise Held("admin_permission_removed")
        if job.actor_id not in member_ids and not (user.is_admin and ".l." not in job.league_id):
            raise Held("membership_removed")
    if ".l." in job.league_id:
        # The worker explicitly selects a scheduler connection before running;
        # a manual operation can never change its saved actor.
        connection = await db.get(YahooConnection, job.actor_id)
        grant = await db.get(YahooLeagueGrant, (job.actor_id, job.league_id))
        if (not connection or connection.status != "connected" or not grant
                or grant.generation != connection.generation
                or connection.generation != job.connection_generation
                or (job.kind == "generation" and grant.expires_at <= stamp())):
            raise Held("provider_grant_changed")


async def submit_refresh(db, league_id: str, actor_id: str, *,
                         actor_kind="member", idempotency_key: str | None = None, kind="refresh", cache_missing=False):
    if kind not in FREE_REFRESH_KINDS:
        raise ValueError("Unregistered free refresh kind")
    await lock_control(db)
    request_hash = digest({"league_id": league_id, "actor_kind": actor_kind, "kind": kind})
    key = f"{actor_id}:{idempotency_key}" if idempotency_key else None
    if key:
        prior = await db.get(GenerationSubmission, key)
        if prior:
            if prior.request_digest != request_hash:
                raise Conflict("Idempotency key was already used for a different request")
            return await db.get(GenerationOperation, prior.operation_id)

    async def remember(row):
        if key:
            db.add(GenerationSubmission(key=key, request_digest=request_hash, operation_id=row.id))
            await db.flush()
        return row
    active_key = "refresh:" + league_id
    active = await db.scalar(select(GenerationOperation).where(
        GenerationOperation.active_key == active_key))
    if active:
        return await remember(active)
    last = await db.scalar(select(GenerationOperation).where(
        GenerationOperation.league_id == league_id,
        GenerationOperation.kind == kind).order_by(
            GenerationOperation.created_at.desc()).limit(1))
    # Rate-limited requests join a recent result instead of buying new I/O.
    interval = 900
    if actor_kind == "scheduler" and kind == "refresh":
        season = await db.get(LeagueSeason, league_id)
        config = await resolve_policy(db, season.series_id if season else "")
        interval = config["policy"]["refresh_interval_seconds"]
    # A new explicit request may replace cancelled free work immediately. The
    # original idempotency key still resolves to the cancelled job above, and
    # scheduler requests retain their cooldown instead of undoing cancellation.
    replace_cancelled = (last and last.state in ("cancelled", "superseded")
                         and actor_kind in ("member", "admin"))
    if (last and last.created_at > stamp() - interval
            and not (cache_missing and last.state == "succeeded") and not replace_cancelled):
        return await remember(last)
    connection = await db.get(YahooConnection, actor_id) if ".l." in league_id else None
    row = GenerationOperation(kind=kind, league_id=league_id,
        actor_id=actor_id, actor_kind=actor_kind, active_key=active_key,
        idempotency_key=key, request_digest=request_hash,
        connection_generation=connection.generation if connection else "")
    db.add(row)
    await db.flush()
    audit(db, actor_id or "scheduler", "refresh_submitted", row.id, "Data refresh requested")
    return await remember(row)


async def claim_operation(db, worker_id: str, *, now: int | None = None):
    now = stamp() if now is None else now
    control = await lock_control(db)
    expired = list((await db.scalars(select(GenerationOperation).where(
        GenerationOperation.state == "running", GenerationOperation.lease_until <= now
    ).with_for_update(skip_locked=True).limit(50))).all())
    for job in expired:
        pending = list((await db.scalars(select(ProviderAttempt).where(
            ProviderAttempt.operation_id == job.id, ProviderAttempt.state.in_(UNRESOLVED)))).all())
        job.generation += 1
        if pending:
            for attempt in pending:
                attempt.state = "unknown"
            job.state = "needs_attention"
            job.reason = "provider_outcome_unknown"
        else:
            job.state = "queued"
        job.updated_at = now
    await db.flush()
    query = select(GenerationOperation).where(GenerationOperation.state == "queued")
    free_running = await db.scalar(select(GenerationOperation.id).where(
        GenerationOperation.state == "running",
        GenerationOperation.kind.in_(("refresh", "analyst_refresh"))).limit(1))
    if free_running:
        query = query.where(GenerationOperation.kind == "generation")
    if control.hold or control.provider_hold or control.cooldown_until > now:
        query = query.where(GenerationOperation.kind.in_(("refresh", "analyst_refresh")))
    job = await db.scalar(query.order_by(GenerationOperation.created_at).with_for_update(skip_locked=True).limit(1))
    if job:
        job.state = "running"
        job.worker_id = worker_id
        job.generation += 1
        job.lease_until = now + LEASE_SECONDS
        job.updated_at = now
        job.epoch = control.epoch
        await db.flush()
    return job


async def require_owner(db, operation_id: str, generation: int, *, now=None):
    now = stamp() if now is None else now
    job = await db.get(GenerationOperation, operation_id, populate_existing=True)
    if not job or job.state != "running" or job.generation != generation or job.lease_until <= now:
        raise OwnershipLost("Job ownership changed; late worker cannot advance or publish")
    return job


async def finish(db, operation_id, generation, *, now=None, progress=None):
    await lock_control(db)
    job = await require_owner(db, operation_id, generation, now=now)
    job.state = "succeeded"
    job.active_key = None
    job.updated_at = stamp() if now is None else now
    job.progress_json = dump(progress or {"stage": "done"})
    from app.services.generation.recap_budget import release_unsubmitted
    await release_unsubmitted(db, job.id, "operation_completed")
    return job


async def cancel(db, operation_id, actor, reason):
    await lock_control(db)
    job = await db.get(GenerationOperation, operation_id)
    if not job:
        raise ValueError("Job does not exist")
    if job.state == "succeeded":
        raise Conflict("Completed work cannot be cancelled")
    before = {"state": job.state, "generation": job.generation}
    job.state = "cancelled"
    job.generation += 1
    job.active_key = None
    job.reason = "owner_cancelled"
    job.updated_at = stamp()
    audit(db, actor, "job_cancelled", operation_id, reason, before, {"state": job.state})
    from app.services.generation.recap_budget import release_unsubmitted
    await release_unsubmitted(db, job.id, "operation_cancelled")
    return job


async def authorize_candidate(db, candidate_key, *, actor_id, actor_kind,
                              reason, authorization_key):
    control = await lock_control(db)
    previous = await db.scalar(select(GenerationOperation).where(
        GenerationOperation.authorization_key == authorization_key))
    if previous:
        return previous
    candidate = await db.get(GenerationCandidate, candidate_key)
    if not candidate:
        raise ValueError("Generation candidate no longer exists")
    settings = await resolve_policy(db, candidate.series_id)
    if settings["blocked_by"]:
        raise Held(settings["blocked_by"][0])
    feature = settings["policy"]["features"][candidate.feature]
    if feature["paused"] or feature["mode"] == "disabled":
        raise Held("feature_paused")
    if actor_kind == "scheduler" and feature["mode"] != "automatic":
        raise Held("manual_only")
    recap_episode = None
    if candidate.feature == "analyst":
        from app.services.recap_video.readiness import require_readiness
        recap_episode = await require_readiness(db, candidate.series_id, json.loads(candidate.payload_json),
            league_id=candidate.league_id, allow_current_admission=actor_kind == "admin",
            automatic=actor_kind == "scheduler")
    pending = await db.scalar(select(GenerationOperation).where(
        GenerationOperation.subject == candidate.subject,
        GenerationOperation.state.in_(("queued", "running", "held", "needs_attention"))))
    if pending:
        if pending.request_digest != candidate.digest:
            raise Held("An existing job has different facts; resolve it before approving replacement work")
        return pending
    unresolved = await db.scalar(select(ProviderAttempt.id).join(
        GenerationOperation, GenerationOperation.id == ProviderAttempt.operation_id).where(
            GenerationOperation.subject == candidate.subject,
            ProviderAttempt.state.in_(UNRESOLVED_OUTCOMES)).limit(1))
    if unresolved:
        raise Held("provider_outcome_unknown")
    from app.services.generation.models import ArtifactHead
    head = await db.get(ArtifactHead, candidate.subject)
    if head and head.hold:
        raise Held(head.hold)
    connection = await db.get(YahooConnection, actor_id) if ".l." in candidate.league_id else None
    row = GenerationOperation(kind="generation", league_id=candidate.league_id,
        series_id=candidate.series_id, feature=candidate.feature, subject=candidate.subject,
        authorization_key=authorization_key, active_key="generate:" + candidate.subject,
        candidate_key=candidate.key, request_digest=candidate.digest,
        payload_json=candidate.payload_json, policy_json=dump(settings),
        actor_id=actor_id, actor_kind=actor_kind, max_calls=feature["max_calls"],
        connection_generation=connection.generation if connection else "",
        expected_artifact=head.artifact_id if head else "", epoch=control.epoch, reason=reason)
    await require_actor(db, row)
    if recap_episode is not None and not recap_episode.admitted_at:
        audit(db, actor_id, "recap_period_admitted", recap_episode.episode_id, reason,
              after={"candidate": candidate.key, "facts_digest": recap_episode.facts_digest})
        recap_episode.admitted_at = stamp()
        recap_episode.lifecycle, recap_episode.hold = "ready", ""
    db.add(row)
    await db.flush()
    audit(db, actor_id or "scheduler", "generation_authorized", row.id, reason,
          after={"candidate": candidate.key, "max_calls": row.max_calls,
                 "policy_revisions": settings["revisions"]})
    return row


async def attention(db, operation_id, generation, code):
    control = await lock_control(db)
    job = await require_owner(db, operation_id, generation)
    job.state = "needs_attention"
    job.reason = code
    job.updated_at = stamp()
    if job.kind == "generation":
        breakers = json.loads(control.breakers_json)
        item = breakers.setdefault(job.feature, {"failures": 0, "open": False})
        item["failures"] += 1
        settings = await resolve_policy(db, job.series_id)
        item["open"] = item["open"] or item["failures"] >= settings["policy"]["breaker_failures"]
        control.breakers_json = dump(breakers)
    return job
