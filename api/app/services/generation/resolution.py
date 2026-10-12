"""Evidence-based guidance for owners; reading guidance never authorizes work."""
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.services.generation import administration
from app.services.generation.bulk_jobs import blocked_reason
from app.services.generation.candidate_status import (
    ACTIVE_STATES,
    REVIEWABLE_HOLDS,
    _completed,
    _period,
    replacement_review_target,
)
from app.services.generation.commands import (
    FREE_REFRESH_KINDS,
    UNRESOLVED,
    require_actor,
)
from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationCandidate,
    GenerationControl,
    GenerationOperation,
    GenerationOutbox,
    ProviderAttempt,
)
from app.services.generation.store import Conflict, Held, audit, lock_control


def review_group(job):
    """Group attempts for the same event, never different weeks or corrections."""
    if not job.subject or job.kind != "generation":
        return job.id
    payload = json.loads(job.payload_json)
    return json.dumps([job.series_id, job.league_id, job.feature, job.subject,
        _period(payload), payload.get("correction_base")], sort_keys=True)


async def resolution(db, job):
    """Inspect related work, saved content and receipts before recommending recovery."""
    related = [job]
    if job.subject and job.kind == "generation":
        related = list((await db.scalars(select(GenerationOperation).where(
            GenerationOperation.subject == job.subject,
            GenerationOperation.kind == "generation",
        ).order_by(GenerationOperation.created_at.desc(), GenerationOperation.id))).all())
    attempts = list((await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id.in_([row.id for row in related])))).all())
    own_attempts = [row for row in attempts if row.operation_id == job.id]
    report = "\n".join([
        "AI writing issue — please investigate before retrying.",
        f"Job: {job.id}", f"League: {job.league_id}", f"Feature: {job.feature or job.kind}",
        f"State: {job.state}; reason: {job.reason or 'not recorded'}; version: {job.generation}",
        f"Requests used: {job.calls}/{job.max_calls}",
        "Related jobs: " + ", ".join(f"{row.id} ({row.state}, {row.reason})" for row in related),
        "Request status: " + (", ".join(
            f"{row.id} ({row.state}, {row.usage_state}, {row.error_code or 'no error code'})"
            for row in attempts) or "No requests recorded"),
    ])

    def result(action, title, explanation, cost="No new writing is approved by checking this issue.", **extra):
        return {"action": action, "title": title, "explanation": explanation, "cost": cost,
            "report": report, "related_jobs": [{"id": row.id, "state": row.state,
                "reason": row.reason, "created_at": row.created_at} for row in related], **extra}

    if job.state not in ("held", "needs_attention"):
        return result("none", "This work has changed", "Reload status to see its latest progress.")
    if job.kind in FREE_REFRESH_KINDS:
        if job.calls or job.max_calls or own_attempts:
            return result("support", "Requires an app fix", "This import unexpectedly contains paid AI activity. Copy the issue details so it can be checked before another attempt.")
        try:
            await require_actor(db, job)
        except Held:
            return result("support", "League connection needs attention", "The account that started this import no longer has a valid league connection. Ask that member to reconnect the league, then reload status. Copy the issue details if it still fails.")
        if job.state == "held":
            return result("resume", "Data import paused", "Continue this import using its original account. If it fails again, copy the issue details so the app can be fixed.", "No paid AI request.")
        if job.reason == "execution_failed":
            return result("retry_refresh", "Data import stopped", "The import did not finish. Retry it once; if it fails again, copy the issue details so the app can be fixed.", "No paid AI request.")
        return result("support", "Data import needs checking", "Copy the issue details so the import failure can be investigated before retrying.")
    if job.feature == "recap_video":
        return result("episode", "Recap needs attention", "Open the recap episode for its next action and spending limits.")
    if len(own_attempts) != job.calls or any(row.state in UNRESOLVED or row.cost_microusd is None for row in attempts):
        return result("support", "Previous AI request needs checking", "The app cannot confirm the outcome or cost of an earlier request for this content. Copy the issue details for investigation; starting again could pay for the same work twice.", "Earlier charges may still apply. No new request will be sent.")
    head = await db.get(ArtifactHead, job.subject) if job.subject else None
    artifact = await db.get(ContentArtifact, head.artifact_id) if head else None
    snapshot = SimpleNamespace(feature=job.feature, digest=job.request_digest, subject=job.subject)
    completed = _completed(snapshot, json.loads(job.payload_json), related, artifact)
    if artifact and (artifact.operation_id == job.id or completed):
        if head.hold:
            return result("support", "Saved content needs checking", "A safety hold prevents publishing this saved content. Copy the issue details so the hold can be investigated.")
        delivery = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == "artifact:" + artifact.id))
        if delivery and not delivery.delivered and delivery.error:
            return result("retry_publication", "Writing is saved; publication failed", "Publish the saved content again. This reuses the writing already paid for.", "No new AI request.", outbox_id=delivery.id, expected_error=delivery.error)
        if delivery and not delivery.delivered:
            return result("wait", "Saved writing is waiting to publish", "Publication is already queued. Reload status to check progress; no replacement writing is needed.", "No new AI request.")
        if delivery and delivery.delivered:
            return result("saved", "This content is already published", "You can close this stopped attempt by cancelling it. Published content and its history will be kept.", "No new AI request.")
        return result("support", "Saved content needs checking", "Writing exists, but its publication status could not be verified. Copy the issue details before starting another attempt.")
    other_active = [row for row in related if row.id != job.id and row.state in ACTIVE_STATES]
    if other_active:
        return result("related", "Other work exists for this content", "Another attempt is running or also needs attention. Review the related attempts below before starting more writing. You can cancel unwanted stopped attempts individually.")
    control = await db.get(GenerationControl, "global")
    resume_block = await blocked_reason(db, job, control) if control else "activation_required"
    if job.reason.startswith("recap_budget_") or job.reason == "legacy_budget_reached":
        return result("budget", "Spending limit reached", "Review this league’s spending limits before continuing the work.", "Continuing may use the remaining approved AI requests.")
    if job.reason in ("feature_paused", "app_paused", "manual_only", "resume_review_required") and resume_block:
        return result("settings", "Writing settings need review", "Review the writing rules for this league, then return here to continue the work.", "Continuing may use the remaining approved AI requests.")
    candidate = await db.get(GenerationCandidate, job.candidate_key) if job.candidate_key else None
    payload = json.loads(job.payload_json)
    candidate_payload = json.loads(candidate.payload_json) if candidate else {}
    same_content = candidate and (candidate.subject, candidate.series_id, candidate.league_id, candidate.feature) == (
        job.subject, job.series_id, job.league_id, job.feature) and _period(candidate_payload) == _period(payload) and candidate_payload.get("correction_base") == payload.get("correction_base")
    if (job.reason in ("attempt_allowance_exhausted", "restore_reapproval_required") and same_content and not completed
            and candidate.hold in (*REVIEWABLE_HOLDS, "subject_needs_attention") and candidate_payload.get("facts")):
        return result("replacement", "A new writing attempt needs approval", "The old attempt cannot continue. Cancel it and review a replacement; writing will start only after you approve the new request allowance.", "Reviewing sends no AI request. Starting replacement writing costs extra.")
    if job.reason in ("worker_shutdown", "publication_failed", "provider_outcome_unknown", "resume_review_required", "manual_only", "feature_paused", "app_paused") and not resume_block:
        remaining = max(0, job.max_calls - job.calls)
        return result("resume", "Ready to continue", "Continue using the saved progress and the original request allowance. The app checks permissions and request status again before proceeding.", f"Up to {remaining} additional AI requests within the original allowance.")
    return result("support", "Requires an app fix", "The app could not safely determine a retry that would resolve this issue. Copy the issue details and paste them into your Codex chat. You can also cancel this work if you no longer want it.")


async def prepare_replacement(db, job_id, body, actor):
    """Explicitly cancel one stopped job and prepare its exact replacement, atomically.

    No worker or provider is invoked. Existing campaign apply is the separate paid gate.
    Any failed eligibility/preview check rolls back the cancellation with the transaction.
    """
    await lock_control(db)
    job = await db.get(GenerationOperation, job_id)
    if not job or (job.generation, job.state) != (body.expected_generation, body.expected_state):
        raise Conflict("This work changed. Reload status before reviewing a replacement.")
    guidance = await resolution(db, job)
    if guidance["action"] != "replacement":
        raise Held(guidance["explanation"])
    await administration.job_action(db, job_id, SimpleNamespace(action="cancel",
        expected_generation=job.generation, expected_state=job.state, reason=body.reason), actor)
    candidate = await db.get(GenerationCandidate, job.candidate_key)
    candidate.hold = "manual_approval_required"
    candidate.revision += 1
    audit(db, actor, "replacement_review_required", replacement_review_target(candidate.subject, candidate.event),
        body.reason, after={"job_id": job_id, "candidate_key": candidate.key, "event": candidate.event})
    await db.flush()
    return await administration.preview(db, [job.candidate_key], actor, body.reason)
