"""Operator recovery of saved GM profiles; no writer or provider is invoked."""

import json
from datetime import UTC, datetime

from anthropic.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User
from app.services.generation.artifacts import save_artifact
from app.services.generation.commands import LEASE_SECONDS
from app.services.generation.features import ValidatedOutput, validate
from app.services.generation.gateway import Gateway
from app.services.generation.models import (
    ContentArtifact,
    GenerationOperation,
    ProviderAttempt,
    stamp,
)
from app.services.generation.store import Conflict, Held, audit, digest, lock_control
from sleeper_dynasty.llm.gm_rating_blurb_writer import parse_blurb
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts


async def recover_saved_profile(
    db: AsyncSession, job_id: str, *, expected_generation: int, actor: str, reason: str
) -> ContentArtifact:
    """Call inside a transaction; any failed publication fence rolls back recovery.

    The latest complete receipt must pass current validation. Earlier responses,
    original requests, authorizations, and accounting records remain unchanged.
    """
    control = await lock_control(db)
    owner = await db.get(User, actor)
    if (
        not owner
        or not owner.is_admin
        or owner.email.lower() not in get_settings().admin_email_list
    ):
        raise Held("An active admin must review saved profile recovery")
    if not reason.strip():
        raise Held("A recovery reason is required")
    job = await db.get(GenerationOperation, job_id)
    if (
        not job
        or job.generation != expected_generation
        or job.state != "needs_attention"
    ):
        raise Conflict("Job state changed; reload before recovering saved writing")
    if (
        job.kind != "generation"
        or job.feature != "gm_rating_blurb"
        or job.reason != "execution_failed"
    ):
        raise Held("Only failed GM profiles can use saved profile recovery")
    if control.hold or not control.epoch or job.epoch != control.epoch:
        raise Held(control.hold or "restore_quarantine")
    attempts = list(
        (
            await db.scalars(
                select(ProviderAttempt)
                .where(ProviderAttempt.operation_id == job.id)
                .order_by(ProviderAttempt.stage)
            )
        ).all()
    )
    if (
        not attempts
        or len(attempts) != job.calls
        or [a.stage for a in attempts] != list(range(1, job.calls + 1))
        or any(
            a.state != "received"
            or a.usage_state != "known"
            or a.error_code
            or a.cost_microusd is None
            or not a.receipt_json
            for a in attempts
        )
    ):
        raise Held(
            "Saved requests or costs are incomplete; reconcile them before recovery"
        )
    latest = attempts[-1]
    raw = Gateway._parse_receipt(latest.receipt_json)
    try:
        message = Message.model_validate(raw)
    except ValueError as exc:
        raise Held("Saved response is malformed; no recovery was applied") from exc
    if message.stop_reason != "end_turn":
        raise Held("Saved profile is incomplete; no recovery was applied")
    text = "".join(block.text for block in message.content if block.type == "text")
    result = parse_blurb(text)
    saved = json.loads(job.payload_json)
    errors = validate(job.feature, result, OwnerRatingFacts(**saved["facts"]), raw)
    if errors:
        raise Held("Saved profile still fails validation: " + "; ".join(errors))
    result.update(
        generated_at=datetime.fromtimestamp(
            latest.settled_at or latest.created_at, UTC
        ).isoformat(),
        generation_period={"season": saved.get("season"), "week": saved.get("week")},
        facts_hash=job.request_digest,
    )
    proof = ValidatedOutput(result, digest(result), digest(saved), len(attempts))
    before = {
        "state": job.state,
        "reason": job.reason,
        "generation": job.generation,
        "calls": job.calls,
    }
    # Own a new fenced local completion, never queue a worker or renew an allowance.
    job.state, job.reason = "running", ""
    job.generation += 1
    job.lease_until = stamp() + LEASE_SECONDS
    artifact = await save_artifact(db, job.id, job.generation, proof)
    audit(
        db,
        actor,
        "saved_profile_recovered",
        job.id,
        reason,
        before,
        {
            "artifact_id": artifact.id,
            "receipt_id": latest.id,
            "calls": job.calls,
            "new_requests": 0,
        },
    )
    return artifact
