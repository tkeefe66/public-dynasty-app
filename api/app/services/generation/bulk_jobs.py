"""Exact, auditable batch recovery using the existing job command contract."""
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.config import get_settings
from app.services.generation.administration import candidate_label, job_action
from app.services.generation.commands import UNRESOLVED
from app.services.generation.models import (
    GenerationAudit,
    GenerationOperation,
    ProviderAttempt,
    stamp,
    uid,
)
from app.services.generation.store import (
    Conflict,
    audit,
    digest,
    dump,
    lock_control,
    resolve_policy,
)


async def blocked_reason(db, job, control):
    if job.state not in ("held", "needs_attention"):
        return "job_no_longer_stopped"
    if job.state == "needs_attention" and job.reason != "provider_outcome_unknown":
        return "failed_job_requires_replacement_review"
    if job.reason == "restore_reapproval_required":
        return "restore_reapproval_required"
    if control.hold or control.provider_hold or get_settings().generation_emergency_pause:
        return "writing_paused"
    if json.loads(control.breakers_json).get(job.feature, {}).get("open"):
        return "feature_breaker_open"
    policy = await resolve_policy(db, job.series_id)
    feature = policy["policy"]["features"].get(job.feature, {})
    if policy["blocked_by"] or feature.get("paused") or feature.get("mode") == "disabled":
        return "feature_paused"
    attempts = (await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == job.id))).all()
    if any(a.state in UNRESOLVED for a in attempts):
        return "provider_outcome_unknown"
    if (job.state == "needs_attention" or job.calls >= job.max_calls) and (
        len(attempts) != job.calls or any(a.state != "received" or a.usage_state != "known" or a.error_code for a in attempts)
    ):
        return "attempt_allowance_exhausted"
    return ""


async def preview_jobs(db, job_ids, action, actor, reason):
    control = await lock_control(db)
    items, skipped = [], []
    for ident in sorted(set(job_ids)):
        job = await db.get(GenerationOperation, ident)
        if not job:
            raise Conflict("A selected job disappeared; reload the list")
        why = (await blocked_reason(db, job, control) if action == "resume" else
               "job_no_longer_stopped" if job.state not in ("held", "needs_attention") else "")
        item = {"id": job.id, "label": candidate_label(job), "league_id": job.league_id,
            "feature": job.feature, "expected_state": job.state, "expected_generation": job.generation,
            "remaining_calls": max(0, job.max_calls - job.calls)}
        if why:
            skipped.append({**item, "reason": why})
        else:
            items.append(item)
    manifest = {"action": action, "items": items, "skipped": skipped,
        "remaining_calls": sum(i["remaining_calls"] for i in items) if action == "resume" else 0,
        "control_revision": control.revision, "epoch": control.epoch, "expires_at": stamp() + 900}
    ident = uid()
    db.add(GenerationAudit(id=ident, actor_id=actor, action="job_batch_preview", target=ident,
        reason=reason, after_json=dump(manifest)))
    return {"id": ident, "digest": digest(manifest), **manifest}


async def apply_jobs(db, preview_id, expected_digest, actor, reason):
    control = await lock_control(db)
    record = await db.get(GenerationAudit, preview_id)
    if not record or record.action != "job_batch_preview" or record.actor_id != actor:
        raise ValueError("Batch preview does not exist for this administrator")
    manifest = json.loads(record.after_json)
    if digest(manifest) != expected_digest:
        raise Conflict("Batch preview changed; preview again")
    previous = await db.scalar(select(GenerationAudit).where(
        GenerationAudit.action == "job_batch_applied", GenerationAudit.target == preview_id))
    if previous:
        return json.loads(previous.after_json)
    if (manifest["expires_at"] < stamp() or manifest["control_revision"] != control.revision
            or manifest["epoch"] != control.epoch):
        raise Conflict("Batch preview expired or controls changed; preview again")
    if not manifest["items"]:
        raise ValueError("No selected jobs can use this action; review the grouped reasons")
    # Validate every snapshot before changing the first job.
    for item in manifest["items"]:
        job = await db.get(GenerationOperation, item["id"])
        if not job or job.generation != item["expected_generation"] or job.state != item["expected_state"]:
            raise Conflict("A selected job changed; reload and preview again")
        if manifest["action"] == "resume" and await blocked_reason(db, job, control):
            raise Conflict("Resume eligibility changed; preview again")
    jobs = []
    for item in manifest["items"]:
        await job_action(db, item["id"], SimpleNamespace(action=manifest["action"],
            expected_generation=item["expected_generation"], expected_state=item["expected_state"], reason=reason), actor)
        jobs.append(item["id"])
    result = {"jobs": jobs, "action": manifest["action"], "skipped": manifest["skipped"]}
    audit(db, actor, "job_batch_applied", preview_id, reason, after=result)
    return result
