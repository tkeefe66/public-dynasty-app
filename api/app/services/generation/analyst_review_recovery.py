"""Explicit replacement of one lost review, retaining its full unknown charge.

Only a saved first draft with an interrupted second-stage review qualifies.
One existing reserved call is consumed. No automatic retry or rewrite is allowed.
"""
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.services.generation.analyst_saved_draft import review_evidence, settled, verdict
from app.services.generation.models import GenerationAudit, GenerationOperation, ProviderAttempt, stamp
from app.services.generation.recap_models import RecapBudgetAllocation
from app.services.generation.store import Held, audit, digest, dump, lock_control

ACTION = "analyst_lost_review_replacement"


async def binding(db, job):
    row = await db.scalar(select(GenerationAudit).where(
        GenerationAudit.action == ACTION, GenerationAudit.target == job.id))
    return json.loads(row.after_json) if row else None


async def source(db, job):
    attempts = list((await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id == job.id).order_by(ProviderAttempt.stage))).all())
    if job.feature != "analyst" or job.kind != "generation" or len(attempts) < 2:
        raise Held("lost_review_source_invalid")
    first, lost = attempts[:2]
    saved = json.loads(job.payload_json)
    if (first.stage != 1 or lost.stage != 2 or job.request_digest != digest(saved)
            or lost.state not in ("unknown", "abandoned") or lost.receipt_json
            or lost.usage_state == "known"
            or digest(json.loads(lost.request_json)) != lost.request_digest):
        raise Held("lost_review_source_changed")
    evidence, _ = review_evidence(json.loads(lost.request_json), saved["edition"])
    from sleeper_dynasty.llm.trade_story_writer import sanitize_prose
    body = json.loads(json.loads(first.receipt_json)["body"])
    draft = sanitize_prose("\n".join(b["text"] for b in body["content"] if b["type"] == "text"))
    if body.get("stop_reason") != "end_turn" or draft != evidence["draft"]:
        raise Held("lost_review_draft_changed")
    allocation = await db.scalar(select(RecapBudgetAllocation).where(
        RecapBudgetAllocation.attempt_id == lost.id))
    if (not allocation or allocation.max_microusd <= 0
            or (lost.cost_microusd is None and (allocation.actual_microusd is not None
                or allocation.outstanding_microusd != allocation.max_microusd))
            or (lost.cost_microusd is not None and (
                lost.usage_state != "financially_reconciled"
                or allocation.actual_microusd != lost.cost_microusd
                or not 0 <= lost.cost_microusd <= allocation.max_microusd))):
        raise Held("lost_review_charge_unbounded")
    return dict(first_digest=digest(settled(first)), lost_id=lost.id,
        request_digest=lost.request_digest, payload_digest=job.request_digest,
        policy_digest=digest(job.policy_json), epoch=job.epoch, actor_id=job.actor_id,
        unknown_ceiling_microusd=allocation.max_microusd,
        prior_cost_microusd=first.cost_microusd), evidence, attempts


async def authorize(db, job_id, *, actor, expected_generation, workers_stopped,
                    evidence, reason, maximum_total_microusd):
    """Owner command: no network; worker must later revalidate exact audit evidence."""
    await lock_control(db)
    job = await db.get(GenerationOperation, job_id)
    from app.services.generation.commands import require_actor
    if (not job or job.actor_id != actor or not workers_stopped or not evidence.strip()
            or not reason.strip() or job.generation != expected_generation
            or job.state != "needs_attention" or job.reason != "provider_outcome_unknown"
            or job.calls != 2 or job.max_calls < 3 or job.artifact_id
            or await binding(db, job)):
        raise Held("lost_review_explicit_authorization_required")
    await require_actor(db, job)
    snapshot, _, attempts = await source(db, job)
    if len(attempts) != 2 or attempts[1].cost_microusd is not None:
        raise Held("lost_review_source_changed")
    replacement = await db.scalar(select(RecapBudgetAllocation).where(
        RecapBudgetAllocation.operation_id == job.id, RecapBudgetAllocation.key == "3"))
    if (not replacement or replacement.attempt_id or replacement.state != "reserved"
            or replacement.actual_microusd is not None
            or replacement.outstanding_microusd != replacement.max_microusd):
        raise Held("lost_review_reserved_call_required")
    ceiling = snapshot["prior_cost_microusd"] + snapshot["unknown_ceiling_microusd"] + replacement.max_microusd
    if type(maximum_total_microusd) is not int or ceiling > maximum_total_microusd:
        raise Held("lost_review_cost_ceiling_exceeded")
    lost = attempts[1]
    lost.state = "abandoned"
    # Never invent a receipt, zero the unknown charge, or change call counts.
    from app.services.generation.recap_budget import settle_attempt
    await settle_attempt(db, lost, {"action": ACTION, "evidence": evidence, "actor_id": actor})
    job.generation += 1
    job.state, job.reason, job.updated_at = "queued", "Explicitly approved saved-draft review replacement", stamp()
    value = dict(source=snapshot, generation=job.generation, stage=3,
        allocation_id=replacement.id, rate_digest=digest(replacement.rate_json),
        maximum_additional_microusd=replacement.max_microusd,
        maximum_total_microusd=ceiling, evidence=evidence, workers_stopped=True)
    audit(db, actor, ACTION, job.id, reason, after=value)
    return value


async def require_recovery(db, job):
    value = await binding(db, job)
    if value is None:
        return None
    snapshot, evidence, attempts = await source(db, job)
    allocation = await db.get(RecapBudgetAllocation, value["allocation_id"])
    if (value["source"] != snapshot or value["generation"] > job.generation
            or value["stage"] != 3 or attempts[1].state != "abandoned"
            or job.calls not in (2, 3) or len(attempts) != job.calls
            or not allocation or allocation.operation_id != job.id or allocation.key != "3"
            or allocation.max_microusd != value["maximum_additional_microusd"]
            or digest(allocation.rate_json) != value["rate_digest"]):
        raise Held("lost_review_authorization_changed")
    return value, evidence, attempts


async def dispositioned(db, job):
    recovery = await require_recovery(db, job)
    return {recovery[0]["source"]["lost_id"]} if recovery else set()


async def generate_recovery(job, gateway):
    async with gateway.maker() as db:
        recovery = await require_recovery(db, job)
    if recovery is None:
        return None
    _, evidence, attempts = recovery
    await gateway.invoke(job.id, job.generation, 3, json.loads(attempts[1].request_json))
    async with gateway.maker() as db:
        current = await db.get(GenerationOperation, job.id)
        _, _, attempts = await require_recovery(db, current)
        settled(attempts[-1])
        verdict(attempts[-1].receipt_json, approved=True)
    saved = json.loads(job.payload_json)
    edition = saved["edition"]
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket
    from sleeper_dynasty.llm.recap_writer import require_matchup_coverage, require_scoring_claims
    facts = ArchivedPacket(edition["facts"])
    outlook = ArchivedPacket(edition["outlook"]) if edition.get("outlook") else None
    require_matchup_coverage(evidence["draft"], facts, outlook)
    require_scoring_claims(evidence["draft"], facts)
    context = edition["facts"].get("player_context", {})
    policy = json.loads(job.policy_json)["policy"]["features"]["analyst"]
    payload = {**edition, "markdown": evidence["draft"], "edition_type": "roast",
        "model": policy["model"], "generated_at": datetime.now(UTC).isoformat(),
        "correction_note": saved.get("correction_reason", ""),
        "sources": context.get("sources", []), "context_note": context.get("note")}
    from app.services.generation.features import ValidatedOutput
    return ValidatedOutput(payload, digest(payload), job.request_digest, 3)


async def publication_attempts(db, job, payload, attempts):
    recovery = await require_recovery(db, job)
    if recovery is None:
        return attempts
    _, evidence, saved_attempts = recovery
    if (len(saved_attempts) != 3 or saved_attempts[-1].stage != 3
            or saved_attempts[-1].request_digest != saved_attempts[1].request_digest
            or payload.get("markdown") != evidence["draft"]
            or any(payload.get(k) != json.loads(job.payload_json)["edition"].get(k)
                   for k in ("facts", "outlook", "lore", "season", "week", "league_name"))):
        raise Held("lost_review_publication_changed")
    settled(saved_attempts[-1])
    verdict(saved_attempts[-1].receipt_json, approved=True)
    return [saved_attempts[0], saved_attempts[2]]
