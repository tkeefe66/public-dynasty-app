"""Canonical paid prose survives cache rebuilds; head changes use a DB fence."""
import json

from sqlalchemy import select

from app.services.generation.commands import finish, require_actor, require_owner
from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationOutbox,
    ProviderAttempt,
    stamp,
)
from app.services.generation.store import (
    Held,
    digest,
    dump,
    lock_control,
    resolve_policy,
)


def subject_key(feature, *parts):
    return feature + ":" + digest(list(parts))


async def import_artifact(db, *, series_id, league_id, feature, subject, payload, target,
                          revision=1, facts=None):
    await lock_control(db)
    matching = await db.scalar(select(ContentArtifact).where(
        ContentArtifact.subject == subject, ContentArtifact.digest == digest(payload)))
    if matching:
        return matching
    previous = await db.scalar(select(ContentArtifact).where(
        ContentArtifact.subject == subject, ContentArtifact.revision == revision))
    head = await db.get(ArtifactHead, subject)
    if previous:
        if previous.digest != digest(payload) and head:
            head.hold = "legacy_artifact_conflict"
        return previous
    row = ContentArtifact(series_id=series_id, league_id=league_id, feature=feature,
        subject=subject, revision=revision, payload_json=dump(payload), digest=digest(payload),
        facts_json=dump({"target": target, "facts": facts or {}}), provenance="legacy_unreviewed")
    db.add(row)
    await db.flush()
    if not head:
        db.add(ArtifactHead(subject=subject, artifact_id=row.id, revision=revision))
    elif revision > head.revision:
        head.artifact_id, head.revision = row.id, revision
    return row


async def overlay(db, entry, series_id):
    rows = (await db.scalars(select(ContentArtifact).join(
        ArtifactHead, ArtifactHead.artifact_id == ContentArtifact.id).where(
            ContentArtifact.series_id == series_id))).all()
    for row in rows:
        if row.feature == "analyst":
            continue
        target = json.loads(row.facts_json).get("target", {})
        if row.feature != "trade_story" and row.league_id != entry.league_id:
            continue
        slot = target.get("slot")
        if slot not in ("trade_stories", "owner_rating_blurbs", "franchise_blurbs"):
            continue
        container = getattr(entry, slot)
        if "scope" in target:
            container = container.setdefault(target["scope"], {})
        container[target["key"]] = json.loads(row.payload_json)


async def save_artifact(db, operation_id, generation, validated):
    control = await lock_control(db)
    job = await require_owner(db, operation_id, generation)
    from app.services.generation.features import ValidatedOutput
    if (not isinstance(validated, ValidatedOutput)
            or validated.digest != digest(validated.payload)
            or validated.snapshot_digest != job.request_digest):
        raise Held("validation_changed")
    attempts = (await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id == job.id).order_by(ProviderAttempt.stage))).all()
    if (not attempts or len(attempts) != validated.stages or len(attempts) != job.calls
            or any(a.state != "received" or a.usage_state != "known" or a.error_code for a in attempts)):
        raise Held("validation_checkpoints_missing")
    payload = validated.payload
    await require_actor(db, job)
    policy = await resolve_policy(db, job.series_id)
    if policy["blocked_by"]:
        raise Held(policy["blocked_by"][0])
    from app.config import get_settings
    from app.services.generation.models import LeagueSeason
    from app.services.generation.policy import paid_capabilities, supports_feature
    feature = policy["policy"]["features"][job.feature]
    if feature["paused"] or feature["mode"] == "disabled":
        raise Held("feature_paused")
    if job.actor_kind == "scheduler" and feature["mode"] != "automatic":
        raise Held("manual_only")
    if get_settings().generation_emergency_pause:
        raise Held("emergency_pause")
    season = await db.get(LeagueSeason, job.league_id)
    if not season or not season.verified_at or not supports_feature(
            paid_capabilities(json.loads(season.capabilities_json)), season.provider, job.feature):
        raise Held("capability_unknown_or_unsupported")
    if job.actor_kind == "scheduler":
        from app.services.generation.planner import automatic_eligibility
        reason = await automatic_eligibility(db, season, job.feature, json.loads(job.payload_json), stamp())
        if reason:
            raise Held(reason)
    if not control.epoch or job.epoch != control.epoch:
        raise Held("restore_quarantine")
    head = await db.get(ArtifactHead, job.subject)
    if (head.artifact_id if head else "") != job.expected_artifact:
        raise Held("artifact_revision_changed")
    if head and head.hold:
        raise Held(head.hold)
    revision = head.revision + 1 if head else 1
    if job.feature == "analyst":
        from app.services.analyst_store import AnalystEdition
        payload = {**payload, "revision": revision, "original_markdown": None}
        payload = AnalystEdition.model_validate(payload).model_dump()
    row = ContentArtifact(operation_id=job.id, series_id=job.series_id,
        league_id=job.league_id, feature=job.feature, subject=job.subject,
        revision=revision, payload_json=dump(payload), digest=digest(payload),
        facts_json=dump({**json.loads(job.payload_json), "_validation": {
            "content_digest": validated.digest, "snapshot_digest": validated.snapshot_digest,
            "stages": [a.id for a in attempts], "contract": "bounded-writers-v1"}}), provenance="managed")
    db.add(row)
    await db.flush()
    if head:
        head.artifact_id, head.revision = row.id, revision
    else:
        db.add(ArtifactHead(subject=job.subject, artifact_id=row.id, revision=revision))
    job.artifact_id = row.id
    db.add(GenerationOutbox(key="artifact:" + row.id, kind="artifact",
        payload_json=dump({"artifact_id": row.id, "expected_artifact": job.expected_artifact})))
    breakers = json.loads(control.breakers_json)
    # A successful already-running operation must not silently close an open breaker.
    breaker = breakers.setdefault(job.feature, {"failures": 0, "open": False})
    if not breaker["open"]:
        breaker["failures"] = 0
    control.breakers_json = dump(breakers)
    await finish(db, job.id, generation)
    return row
