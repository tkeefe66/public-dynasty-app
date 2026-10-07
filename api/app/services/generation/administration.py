"""Audited owner commands with optimistic revisions and exact campaign approval."""
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.services.generation.commands import UNRESOLVED, authorize_candidate, cancel
from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationAudit,
    GenerationCandidate,
    GenerationOperation,
    GenerationOutbox,
    GenerationPolicy,
    LeagueSeason,
    LeagueSeries,
    ProviderAttempt,
    stamp,
    uid,
)
from app.services.generation.policy import paid_capabilities, supports_feature
from app.services.generation.store import (
    Conflict,
    Held,
    audit,
    data,
    digest,
    dump,
    lock_control,
    resolve_policy,
    save_policy,
)


async def policy_view(db, scope):
    if (scope not in ("app", "profile:dynasty", "profile:keeper", "profile:redraft")
            and (not scope.startswith("series:") or not await db.get(LeagueSeries, scope[7:]))):
        raise ValueError("Unknown policy scope")
    row = await db.get(GenerationPolicy, scope)
    effective = await resolve_policy(db, scope[7:] if scope.startswith("series:") else "",
        profile=scope[8:] if scope.startswith("profile:") else "")
    return {"scope": scope, "revision": row.revision if row else 0,
            "value": json.loads(row.value_json) if row else {}, "effective": effective}


async def hold_backlog(db, series_ids=None):
    """Resume/activation does not authorize work accumulated during the pause."""
    query = select(LeagueSeries)
    if series_ids is not None:
        query = query.where(LeagueSeries.id.in_(series_ids))
    for series in (await db.scalars(query)).all():
        latest = await db.scalar(select(LeagueSeason).where(LeagueSeason.series_id == series.id)
            .order_by(LeagueSeason.season.desc()).limit(1))
        series.activated_at, series.activation_week = stamp(), latest.latest_week if latest else 0
        candidates = (await db.scalars(select(GenerationCandidate).where(
            GenerationCandidate.series_id == series.id, GenerationCandidate.hold == ""))).all()
        for candidate in candidates:
            candidate.hold, candidate.eligible_at = "historical_approval_required", 0
        jobs = (await db.scalars(select(GenerationOperation).where(
            GenerationOperation.series_id == series.id, GenerationOperation.actor_kind == "scheduler",
            GenerationOperation.kind == "generation", GenerationOperation.state == "queued"))).all()
        for job in jobs:
            job.state, job.reason = "held", "resume_review_required"


async def update_policy(db, scope, value, expected_revision, actor, reason):
    before = await policy_view(db, scope)
    await save_policy(db, scope, value, expected_revision, actor, reason)
    after = await policy_view(db, scope)
    old, new = before["effective"]["policy"], after["effective"]["policy"]
    resumes = old["paused"] and not new["paused"]
    resumes = resumes or any(
        (old["features"][f]["paused"] and not new["features"][f]["paused"])
        or (old["features"][f]["mode"] != "automatic" and new["features"][f]["mode"] == "automatic")
        for f in new["features"])
    if resumes:
        series_ids = ([scope[7:]] if scope.startswith("series:") else
            list((await db.scalars(select(LeagueSeries.id).where(
                LeagueSeries.profile == scope[8:]))).all()) if scope.startswith("profile:") else None)
        await hold_backlog(db, series_ids)
    return after


async def control_action(db, body, actor):
    control = await lock_control(db)
    from app.services.generation.recovery import bootstrap_control
    initial = body.expected_revision == 0 and bootstrap_control(control)
    if control.revision != body.expected_revision and not initial:
        raise Conflict("Control state changed. Reload before applying this action.")
    before = data(control)
    if body.action == "pause":
        if control.hold != "restore_quarantine":
            control.hold = "owner_paused"
    elif body.action in ("activate", "resume"):
        epoch = get_settings().generation_execution_epoch
        if not epoch or not body.workers_stopped:
            raise Held("Confirm legacy workers stopped and configure the deployment execution epoch first")
        if control.hold == "restore_quarantine" and control.epoch == epoch:
            raise Held("fresh_execution_epoch_required")
        if body.action == "resume" and control.epoch != epoch:
            raise Held("restore_quarantine")
        control.epoch, control.hold = epoch, ""
        await hold_backlog(db)
    elif body.action == "clear_provider":
        if await db.scalar(select(ProviderAttempt.id).where(ProviderAttempt.state.in_(UNRESOLVED)).limit(1)):
            raise Held("Resolve outstanding provider uncertainty before clearing this hold")
        control.provider_hold, control.cooldown_until = "", 0
    elif body.action == "reset_breaker":
        breakers = json.loads(control.breakers_json)
        if body.feature not in ("trade_story", "gm_rating_blurb", "franchise_blurb", "analyst"):
            raise ValueError("Choose a registered feature")
        breakers[body.feature] = {"failures": 0, "open": False}
        control.breakers_json = dump(breakers)
    control.revision += 1
    audit(db, actor, "control_" + body.action, "global", body.reason, before, data(control))
    return data(control)


async def preview(db, candidates, actor, reason):
    control = await lock_control(db)
    items = []
    for key in sorted(set(candidates)):
        row = await db.get(GenerationCandidate, key)
        if not row:
            raise Conflict("A candidate disappeared; reload the list")
        policy = await resolve_policy(db, row.series_id)
        feature = policy["policy"]["features"][row.feature]
        head = await db.get(ArtifactHead, row.subject)
        items.append({"key": key, "subject": row.subject, "league_id": row.league_id,
            "feature": row.feature, "event": row.event, "revision": row.revision,
            "label": candidate_label(row),
            "digest": row.digest, "hold": row.hold, "head": head.artifact_id if head else "",
            "policy_revisions": policy["revisions"], "model": feature["model"],
            "max_calls": feature["max_calls"], "max_tokens_per_call": feature["max_tokens"],
            "blocked_by": policy["blocked_by"]})
    manifest = {"items": items, "control_revision": control.revision, "epoch": control.epoch,
        "expires_at": stamp() + 900, "max_calls": sum(i["max_calls"] for i in items)}
    ident = uid()
    if not reason.strip():
        raise ValueError("Explain why this campaign is being proposed")
    db.add(GenerationAudit(id=ident, actor_id=actor, action="campaign_preview",
        target=ident, reason=reason, after_json=dump(manifest)))
    return {"id": ident, "digest": digest(manifest), **manifest}


def candidate_label(row):
    payload = json.loads(row.payload_json)
    facts = payload.get("facts", {})
    if facts.get("trade_id"):
        owners = [side["owner_name"] for side in facts.get("sides", []) if side.get("owner_name")]
        if owners:
            label = " ↔ ".join(dict.fromkeys(owners))
            if payload.get("event_at"):
                label += " · " + datetime.fromtimestamp(payload["event_at"], UTC).strftime("%b %-d, %Y")
            return label
    return str(facts.get("owner_name") or facts.get("trade_id") or
        (f'Week {payload.get("week")}, {payload.get("season")}' if payload.get("week") else row.subject))


async def apply_campaign(db, preview_id, expected_digest, actor, reason):
    control = await lock_control(db)
    record = await db.get(GenerationAudit, preview_id)
    if not record or record.action != "campaign_preview":
        raise ValueError("Campaign preview does not exist")
    manifest = json.loads(record.after_json)
    if digest(manifest) != expected_digest:
        raise Conflict("Campaign preview changed")
    applied = await db.scalar(select(GenerationAudit).where(
        GenerationAudit.action == "campaign_applied", GenerationAudit.target == preview_id))
    if applied:
        return json.loads(applied.after_json)
    if (manifest["expires_at"] < stamp() or manifest["control_revision"] != control.revision
            or manifest["epoch"] != control.epoch):
        raise Conflict("Campaign preview expired or control state changed; preview again")
    jobs = []
    for item in manifest["items"]:
        candidate = await db.get(GenerationCandidate, item["key"])
        if not candidate or candidate.revision != item["revision"] or candidate.digest != item["digest"]:
            raise Conflict("Candidate facts changed; preview again")
        policy = await resolve_policy(db, candidate.series_id)
        head = await db.get(ArtifactHead, candidate.subject)
        correction_base = json.loads(candidate.payload_json).get("correction_base")
        if correction_base and (not head or correction_base != head.artifact_id):
            raise Conflict("Saved content changed since the correction was proposed")
        if policy["revisions"] != item["policy_revisions"] or (head.artifact_id if head else "") != item["head"]:
            raise Conflict("Policy or saved content changed; preview again")
        if candidate.hold not in ("", "historical_approval_required", "missed_event_approval_required"):
            raise Held(candidate.hold)
        season = await db.get(LeagueSeason, candidate.league_id)
        if not season or not season.verified_at or not supports_feature(
                paid_capabilities(json.loads(season.capabilities_json)), season.provider, candidate.feature):
            raise Held("capability_unknown_or_unsupported")
        job = await authorize_candidate(db, candidate.key, actor_id=actor, actor_kind="admin",
            reason=reason, authorization_key=f"campaign:{preview_id}:{candidate.subject}")
        jobs.append(job.id)
    response = {"jobs": jobs, "preview_id": preview_id}
    audit(db, actor, "campaign_applied", preview_id, reason, after=response)
    return response


async def job_action(db, job_id, body, actor):
    await lock_control(db)
    job = await db.get(GenerationOperation, job_id)
    if not job or job.generation != body.expected_generation or job.state != body.expected_state:
        raise Conflict("Job state changed; reload before acting")
    if body.action == "cancel":
        return data(await cancel(db, job_id, actor, body.reason))
    settled_recovery = job.state == "needs_attention" and job.reason == "provider_outcome_unknown"
    if job.state != "held" and not settled_recovery:
        raise Held("Only held jobs can resume; failed jobs require a separate reviewed authorization")
    if job.reason == "restore_reapproval_required" and job.kind == "generation":
        raise Held("Cancel restored work, reconcile provider activity, then preview a separate authorization")
    if await db.scalar(select(ProviderAttempt.id).where(
            ProviderAttempt.operation_id == job_id, ProviderAttempt.state.in_(UNRESOLVED)).limit(1)):
        raise Held("provider_outcome_unknown")
    if job.kind == "generation" and (settled_recovery or job.calls >= job.max_calls):
        saved = (await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == job_id))).all()
        if len(saved) != job.calls or any(a.state != "received" or a.usage_state != "known" or a.error_code for a in saved):
            raise Held("provider_outcome_unknown" if settled_recovery else "attempt_allowance_exhausted")
    before = {"state": job.state, "reason": job.reason, "calls": job.calls}
    job.state, job.reason = "queued", ""
    audit(db, actor, "job_resumed", job_id, body.reason, before, {"state": job.state, "calls": job.calls})
    return data(job)


async def resolve_attempt(db, attempt_id, body, actor):
    await lock_control(db)
    row = await db.get(ProviderAttempt, attempt_id)
    if not row or row.state != body.expected_state:
        raise Conflict("Attempt state changed; reload its receipt before acting")
    if not body.workers_stopped or not body.evidence.strip():
        raise ValueError("Confirm the sending worker stopped and record supporting evidence")
    if row.usage_state == "known":
        raise Conflict("Known paid usage cannot be abandoned or marked unbilled")
    before = {"state": row.state, "usage_state": row.usage_state, "cost_microusd": row.cost_microusd}
    row.state = "abandoned" if body.action == "abandon_unknown" else "not_sent"
    if body.action == "not_sent":
        row.usage_state, row.cost_microusd = "not_billed", 0
    job = await db.get(GenerationOperation, row.operation_id)
    job.state, job.reason, job.active_key = "cancelled", "owner_resolved_attempt", None
    job.generation += 1
    audit(db, actor, "attempt_" + body.action, attempt_id, body.reason, before,
        {"state": row.state, "usage_state": row.usage_state, "evidence": body.evidence,
         "sending_process_stopped": True, "replacement_authorized": False})
    return data(row)


async def retry_projection(db, ident, body, actor):
    await lock_control(db)
    row = await db.get(GenerationOutbox, ident)
    if not row or row.delivered or not row.error or row.error != body.expected_error:
        raise Conflict("Publication state changed; reload before retrying")
    before = {"error": row.error, "payload": row.payload_json}
    row.error = ""
    audit(db, actor, "projection_retry", ident, body.reason, before,
        {"error": "", "new_generation_authorized": False})
    return data(row)


async def propose_correction(db, ident, body, actor):
    await lock_control(db)
    artifact = await db.get(ContentArtifact, ident)
    head = await db.get(ArtifactHead, artifact.subject) if artifact else None
    if not head or head.artifact_id != ident or body.expected_artifact != ident:
        raise Conflict("Saved content changed; propose a correction from its current revision")
    saved = json.loads(artifact.facts_json)
    previous = json.loads(artifact.payload_json)
    if artifact.feature == "analyst":
        saved = {"edition": previous, "facts": previous.get("facts", {}),
                 "season": previous["season"], "week": previous["week"]}
    if not saved.get("facts"):
        raise Held("Legacy facts are unavailable; refresh data and preview the current candidate instead")
    saved = {**saved, "correction_base": ident, "correction_reason": body.reason,
             "previous_content": previous}
    saved.pop("_validation", None)
    row = GenerationCandidate(key="correction:" + uid(), series_id=artifact.series_id,
        league_id=artifact.league_id, feature=artifact.feature, subject=artifact.subject,
        event="correction:" + ident, payload_json=dump(saved), digest=digest(saved),
        hold="historical_approval_required")
    db.add(row)
    await db.flush()
    audit(db, actor, "correction_proposed", ident, body.reason, after={"candidate": row.key})
    return data(row)
