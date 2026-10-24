"""Explicit two-call repair of a rejected, fully receipted Analyst draft.

Inspection is read-only. Preparation and authorization use the normal locked
replacement/campaign commands; this module cannot clear a breaker or send work.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationAudit,
    GenerationCandidate,
    GenerationControl,
    GenerationOperation,
    ProviderAttempt,
    uid,
)
from app.services.generation.store import Held, audit, digest, dump, resolve_policy
from sleeper_dynasty.llm.recap_packet import ArchivedPacket, editorial_facts
from sleeper_dynasty.llm.recap_writer import REVIEW_GROUNDING_VERSIONS, _claim_evidence

CONTRACT = "analyst_saved_draft_repair_v1"
KEY = "saved_draft_repair"
PREFIX = "analyst-repair:"


def is_repair(row):
    return KEY in json.loads(row.payload_json) or getattr(
        row, "candidate_key", getattr(row, "key", "")
    ).startswith(PREFIX)


def scope(row):
    return [row.series_id, row.league_id, row.feature, row.subject]


def object_json(value):
    try:
        result = json.loads(value)
        if isinstance(result, dict):
            return result
    except (TypeError, ValueError):
        pass
    raise Held("saved_repair_evidence_invalid")


def review_evidence(request, edition):
    """The review must have audited exactly the original immutable packets."""
    if request.get("tool_choice") != {"type": "tool", "name": "submit_recap_review"}:
        raise Held("saved_repair_review_required")
    messages = request.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 1
        or not isinstance(messages[0], dict)
        or messages[0].get("role") != "user"
    ):
        raise Held("saved_repair_review_required")
    evidence = object_json(messages[0].get("content"))
    packet = editorial_facts(ArchivedPacket(edition["facts"]))
    if (
        evidence.get("facts") != packet
        or evidence.get("outlook") != edition.get("outlook")
        or evidence.get("lore") != edition.get("lore")
        or not isinstance(evidence.get("draft"), str)
        or not evidence["draft"].strip()
    ):
        raise Held("saved_repair_review_facts_changed")
    system = request.get("system", [])
    versions = [
        version
        for version in REVIEW_GROUNDING_VERSIONS
        if isinstance(system, list)
        and any(
            isinstance(block, dict)
            and isinstance(block.get("text"), str)
            and block["text"].startswith(version + "\n")
            for block in system
        )
    ]
    if len(versions) > 1:
        raise Held("saved_repair_grounding_ambiguous")
    version = versions[0] if versions else None
    if (
        version
        and evidence.get("claim_evidence") != _claim_evidence(packet, version)
        or not version
        and "claim_evidence" in evidence
    ):
        raise Held("saved_repair_review_facts_changed")
    return evidence, version


def verdict(receipt, *, approved):
    body = object_json(object_json(receipt).get("body"))
    content = body.get("content")
    tools = (
        [
            block
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        if isinstance(content, list)
        else []
    )
    if (
        body.get("stop_reason") != "tool_use"
        or len(tools) != 1
        or tools[0].get("name") != "submit_recap_review"
    ):
        raise Held("saved_repair_structured_review_required")
    value = tools[0].get("input")
    checks = value.get("checks") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != {"approved", "checks"}
        or value["approved"] is not approved
        or not isinstance(checks, list)
        or len(checks) > 12
        or any(
            not isinstance(check, dict)
            or set(check) != {"status", "quote", "evidence"}
            or check["status"] not in ("supported", "needs_correction")
            or any(
                not isinstance(check[k], str) or not check[k].strip()
                for k in ("quote", "evidence")
            )
            for check in checks
        )
    ):
        raise Held("saved_repair_valid_verdict_required")
    findings = [
        {k: check[k] for k in ("quote", "evidence")}
        for check in checks
        if check["status"] == "needs_correction"
    ]
    if bool(findings) == approved:
        raise Held("saved_repair_valid_verdict_required")
    return findings


def settled(attempt):
    receipt = object_json(attempt.receipt_json)
    if (
        attempt.state != "received"
        or attempt.usage_state != "known"
        or attempt.error_code
        or type(attempt.cost_microusd) is not int
        or attempt.cost_microusd < 0
        or not attempt.settled_at
        or not attempt.status_code
        or not 200 <= attempt.status_code < 300
        or type(receipt.get("status")) is not int
        or not 200 <= receipt["status"] < 300
        or attempt.request_digest != digest(object_json(attempt.request_json))
    ):
        raise Held("saved_repair_previous_receipts_unsettled")
    return {
        column.name: getattr(attempt, column.name)
        for column in ProviderAttempt.__table__.columns
    }


async def describe(db, job, *, prepared=False, repair_job_id=""):
    """Return exact inspectable evidence without mutation, pricing calls, or network."""
    from app.services.generation.commands import require_actor

    payload = object_json(job.payload_json)
    if (
        job.kind != "generation"
        or job.feature != "analyst"
        or is_repair(job)
        or (
            job.state != "cancelled" or job.reason != "owner_cancelled"
            if prepared
            else job.state not in ("held", "needs_attention")
            or job.reason not in ("execution_failed", "attempt_allowance_exhausted")
        )
        or job.calls < 2
        or job.calls > job.max_calls
        or job.artifact_id
        or job.request_digest != digest(payload)
    ):
        raise Held("saved_repair_failed_source_required")
    edition = payload.get("edition")
    if (
        not isinstance(edition, dict)
        or not isinstance(edition.get("facts"), dict)
        or not edition["facts"]
        or type(payload.get("season")) is not int
        or type(payload.get("week")) is not int
        or payload["season"] != edition.get("season")
        or payload["week"] != edition.get("week")
        or edition["facts"].get("week") != payload["week"]
    ):
        raise Held("saved_repair_source_period_changed")
    candidate = await db.get(GenerationCandidate, job.candidate_key)
    if (
        not candidate
        or scope(candidate) != scope(job)
        or candidate.digest != job.request_digest
        or candidate.hold
        not in (
            "",
            "manual_approval_required",
            "historical_approval_required",
            "missed_event_approval_required",
            "subject_needs_attention",
        )
        or object_json(candidate.payload_json) != payload
        or candidate.digest != digest(payload)
    ):
        raise Held("saved_repair_source_candidate_changed")
    head = await db.get(ArtifactHead, job.subject)
    artifacts = list(
        (
            await db.scalars(
                select(ContentArtifact)
                .where(ContentArtifact.subject == job.subject)
                .order_by(ContentArtifact.id)
            )
        ).all()
    )
    if (
        (head.artifact_id if head else "") != job.expected_artifact
        or head
        and head.hold
        or head
        and not any(artifact.id == head.artifact_id for artifact in artifacts)
        or any(
            scope(artifact) != scope(job)
            or object_json(artifact.payload_json).get("edition_type") != "results"
            or object_json(artifact.payload_json).get("season") != payload["season"]
            or object_json(artifact.payload_json).get("week") != payload["week"]
            or artifact.digest != digest(object_json(artifact.payload_json))
            for artifact in artifacts
        )
    ):
        raise Held("saved_repair_saved_content_requires_review")
    head_binding = {
        "head": {
            "artifact_id": head.artifact_id,
            "revision": head.revision,
            "hold": head.hold,
        }
        if head
        else None,
        "artifacts": [
            {
                column.name: getattr(artifact, column.name)
                for column in ContentArtifact.__table__.columns
            }
            for artifact in artifacts
        ],
    }
    related = list(
        (
            await db.scalars(
                select(GenerationOperation).where(
                    GenerationOperation.subject == job.subject,
                    GenerationOperation.kind == "generation",
                )
            )
        ).all()
    )
    if any(
        other.id not in (job.id, repair_job_id)
        and (
            other.state != "cancelled"
            or other.artifact_id
            or other.created_at > job.created_at
        )
        for other in related
    ):
        raise Held("saved_repair_related_work_requires_review")
    attempts = list(
        (
            await db.scalars(
                select(ProviderAttempt)
                .where(
                    ProviderAttempt.operation_id.in_(
                        [other.id for other in related if other.id != repair_job_id]
                    )
                )
                .order_by(ProviderAttempt.operation_id, ProviderAttempt.stage)
            )
        ).all()
    )
    snapshots = [settled(attempt) for attempt in attempts]
    own = [attempt for attempt in attempts if attempt.operation_id == job.id]
    if (
        len(own) != job.calls
        or [attempt.stage for attempt in own] != list(range(1, job.calls + 1))
        or any(attempt.generation != job.generation - int(prepared) for attempt in own)
    ):
        raise Held("saved_repair_source_generation_changed")
    last = own[-1]
    evidence, version = review_evidence(object_json(last.request_json), edition)
    findings = verdict(last.receipt_json, approved=False)
    await require_actor(db, job)
    return {
        "contract": CONTRACT,
        "max_calls": 2,
        "draft": evidence["draft"],
        "findings": findings,
        "grounding_version": version,
        "source": {
            "job_id": job.id,
            "generation": job.generation,
            "scope": scope(job),
            "candidate_key": candidate.key,
            "event": candidate.event,
            "payload_digest": job.request_digest,
            "actor_id": job.actor_id,
            "connection_generation": job.connection_generation,
            "epoch": job.epoch,
            "calls": job.calls,
            "max_calls": job.max_calls,
            "expected_artifact": job.expected_artifact,
            "head_digest": digest(head_binding),
            "attempt_id": last.id,
            "request_digest": last.request_digest,
            "receipt_digest": digest(last.receipt_json),
            "receipts_digest": digest(snapshots),
            "draft_digest": digest(evidence["draft"]),
            "findings_digest": digest(findings),
            "prior_cost_microusd": sum(attempt.cost_microusd for attempt in own),
        },
    }


async def prepare_candidate(db, job, actor, reason):
    """Called after cancellation; bind its incremented generation, never alter receipts."""
    from app.services.generation.candidate_status import replacement_review_target

    proposal = await describe(db, job, prepared=True)
    if actor != job.actor_id:
        raise Held("saved_repair_original_actor_required")
    original = await db.get(GenerationCandidate, job.candidate_key)
    original.hold = "manual_approval_required"
    original.revision += 1
    payload = {**object_json(job.payload_json), KEY: proposal}
    row = GenerationCandidate(
        key=PREFIX + uid(),
        series_id=job.series_id,
        league_id=job.league_id,
        feature=job.feature,
        subject=job.subject,
        event=original.event,
        payload_json=dump(payload),
        digest=digest(payload),
        hold="manual_approval_required",
    )
    db.add(row)
    audit(
        db,
        actor,
        "saved_draft_repair_prepared",
        row.key,
        reason,
        after={
            "source": proposal["source"],
            "candidate_digest": row.digest,
            "max_calls": 2,
        },
    )
    # Protect the original event as well as the separate repair candidate. Normal
    # recollection must never turn this failed week into a fresh automatic draft.
    audit(
        db,
        actor,
        "replacement_review_required",
        replacement_review_target(original.subject, original.event),
        reason,
        after={
            "job_id": job.id,
            "candidate_key": original.key,
            "event": original.event,
        },
    )
    await db.flush()
    return row


async def require_source(db, row, actor, *, repair_job_id=""):
    payload = object_json(row.payload_json)
    proposal = payload.get(KEY)
    if not isinstance(proposal, dict) or proposal.get("contract") != CONTRACT:
        raise Held("saved_repair_contract_changed")
    source = await db.get(
        GenerationOperation, proposal.get("source", {}).get("job_id", "")
    )
    if not source or actor != source.actor_id or scope(row) != scope(source):
        raise Held("saved_repair_original_actor_required")
    current = await describe(db, source, prepared=True, repair_job_id=repair_job_id)
    if proposal != current or payload != {
        **object_json(source.payload_json),
        KEY: current,
    }:
        raise Held("saved_repair_source_changed")
    key = row.candidate_key if isinstance(row, GenerationOperation) else row.key
    candidate = await db.get(GenerationCandidate, key)
    prepared = await db.scalar(
        select(GenerationAudit).where(
            GenerationAudit.action == "saved_draft_repair_prepared",
            GenerationAudit.target == key,
        )
    )
    if (
        not candidate
        or candidate.digest != digest(payload)
        or candidate.payload_json != row.payload_json
        or not prepared
        or prepared.actor_id != actor
        or object_json(prepared.after_json)
        != {
            "source": current["source"],
            "candidate_digest": candidate.digest,
            "max_calls": 2,
        }
    ):
        raise Held("saved_repair_preparation_changed")
    return current


async def campaign_details(db, row, actor):
    proposal = await require_source(db, row, actor)
    from app.services.generation.accounting import bounded_plan

    settings = await resolve_policy(db, row.series_id)
    feature = settings["policy"]["features"]["analyst"]
    if feature["max_calls"] < 2:
        raise Held("saved_repair_two_calls_required")
    plan = bounded_plan("preview", "analyst", feature, feature, 2)
    return {
        "contract": CONTRACT,
        "candidate_key": row.key,
        "source": proposal["source"],
        "max_calls": 2,
        "pricing_plan": plan,
        "maximum_additional_microusd": sum(item["max_microusd"] for item in plan),
    }


async def bind_preview(db, preview, rows, actor):
    repairs = [row for row in rows if is_repair(row)]
    if not repairs:
        return preview
    if len(rows) != 1:
        raise Held("saved_repair_separate_approval_required")
    manifest = {k: v for k, v in preview.items() if k not in ("id", "digest")}
    manifest[KEY] = await campaign_details(db, repairs[0], actor)
    await db.flush()
    (await db.get(GenerationAudit, preview["id"])).after_json = dump(manifest)
    return {"id": preview["id"], "digest": digest(manifest), **manifest}


async def verify_campaign(db, manifest, candidates, actor):
    repairs = [row for row in candidates.values() if is_repair(row)]
    if not repairs and KEY not in manifest:
        return
    if (
        len(candidates) != 1
        or len(repairs) != 1
        or manifest.get("max_calls") != 2
        or len(manifest.get("items", [])) != 1
        or manifest["items"][0].get("max_calls") != 2
        or manifest["items"][0].get("key") != repairs[0].key
        or manifest["items"][0].get("digest") != repairs[0].digest
        or manifest["items"][0].get("revision") != repairs[0].revision
        or manifest.get(KEY) != await campaign_details(db, repairs[0], actor)
    ):
        raise Held("saved_repair_approval_changed")


async def bind_authorization(
    db, candidate, actor, actor_kind, authorization_key, settings
):
    if actor_kind != "admin" or not authorization_key.startswith("campaign:"):
        raise Held("saved_repair_manual_approval_required")
    ident = authorization_key.split(":", 2)[1]
    record = await db.get(GenerationAudit, ident)
    if not record or record.action != "campaign_preview" or record.actor_id != actor:
        raise Held("saved_repair_approval_changed")
    manifest = object_json(record.after_json)
    await verify_campaign(db, manifest, {candidate.key: candidate}, actor)
    settings["policy"]["features"]["analyst"]["max_calls"] = 2
    settings[KEY] = {"preview_id": ident, "digest": digest(manifest), "actor_id": actor}


async def require_execution(db, job):
    """Recheck source and explicit approval under the dispatch/publication lock."""
    await require_source(db, job, job.actor_id, repair_job_id=job.id)
    saved = object_json(job.policy_json)
    binding = saved.get(KEY, {})
    record = await db.get(GenerationAudit, binding.get("preview_id", ""))
    applied = await db.scalar(
        select(GenerationAudit).where(
            GenerationAudit.action == "campaign_applied",
            GenerationAudit.target == binding.get("preview_id", ""),
        )
    )
    if (
        job.actor_kind != "admin"
        or job.max_calls != 2
        or saved["policy"]["features"]["analyst"]["max_calls"] != 2
        or job.request_digest != digest(object_json(job.payload_json))
        or not record
        or record.action != "campaign_preview"
        or record.actor_id != job.actor_id
        or binding
        != {
            "preview_id": record.id,
            "digest": digest(object_json(record.after_json)),
            "actor_id": job.actor_id,
        }
        or job.authorization_key != f"campaign:{record.id}:{job.subject}"
        or not applied
        or applied.actor_id != job.actor_id
        or job.id not in object_json(applied.after_json).get("jobs", [])
    ):
        raise Held("saved_repair_approval_changed")
    current = await resolve_policy(db, job.series_id)
    manifest = object_json(record.after_json)
    control = await db.get(GenerationControl, "global")
    if (
        current["revisions"] != saved.get("revisions")
        or len(manifest.get("items", [])) != 1
        or manifest["items"][0].get("policy_revisions") != current["revisions"]
        or not control
        or control.revision != manifest.get("control_revision")
        or job.epoch != manifest.get("epoch")
        or job.epoch != object_json(job.payload_json)[KEY]["source"]["epoch"]
    ):
        raise Held("saved_repair_approval_changed")
    feature = current["policy"]["features"]["analyst"]
    if feature["max_calls"] < 2:
        raise Held("saved_repair_two_calls_required")


def require_publication(job, payload, attempts):
    """The new full review must approve the exact final article and original facts."""
    if len(attempts) != 2 or [a.stage for a in attempts] != [1, 2]:
        raise Held("saved_repair_two_checkpoints_required")
    for attempt in attempts:
        settled(attempt)
    saved = object_json(job.payload_json)
    from anthropic.types import Message

    from sleeper_dynasty.llm.recap_writer import apply_recap_edits

    response = object_json(object_json(attempts[0].receipt_json).get("body"))
    try:
        repaired = apply_recap_edits(
            saved[KEY]["draft"], Message.model_validate(response)
        )
    except (TypeError, ValueError) as exc:
        raise Held("saved_repair_edits_invalid") from exc
    if (
        object_json(attempts[0].request_json).get("tool_choice")
        != {"type": "tool", "name": "submit_recap_passage_edits"}
        or repaired != payload.get("markdown")
        or payload.get("edition_type") != "roast"
        or any(
            payload.get(key) != saved["edition"].get(key)
            for key in ("facts", "outlook", "lore", "season", "week", "league_name")
        )
    ):
        raise Held("saved_repair_output_changed")
    evidence, version = review_evidence(
        object_json(attempts[-1].request_json), saved["edition"]
    )
    if (
        evidence["draft"] != payload.get("markdown")
        or version != saved[KEY]["grounding_version"]
    ):
        raise Held("saved_repair_review_draft_changed")
    verdict(attempts[-1].receipt_json, approved=True)
