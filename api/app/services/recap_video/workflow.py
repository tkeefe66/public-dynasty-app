"""API-owned media checkpoints. Workers have no source/prose/publication authority.

Task7/8 install exact provider/QA adapters; Task10 installs durable qualification.
Absent adapters fail closed. Hooks execute only inside API, never from payloads.
"""
import hashlib
import json
import secrets

from sqlalchemy import or_, select
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.services.generation.commands import LEASE_SECONDS, require_actor
from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationOperation, stamp
from app.services.generation.recap_models import RecapAsset, RecapBudgetAllocation, RecapEpisode, RecapProviderAttempt, RecapStage
from app.services.generation.store import Conflict, Held, OwnershipLost, audit, digest, dump, lock_control, resolve_policy

MEDIA_KINDS = frozenset({"preflight", "narrate", "speech_check", "render", "media_check"})
LIFECYCLE = {"narrate": "narration", "speech_check": "speech_check", "render": "rendering", "media_check": "media_check"}
BACKOFF = (60, 300, 900)
PREFLIGHT_MAX_AGE = 3600
# API integration seams, deliberately unconfigured. Each is a concrete adapter,
# not a remotely configurable callable, import path, or client success flag.
PREFLIGHT_CONFIG = None  # () -> exact nonsecret provider/voice/config snapshot
MEDIA_PLAN_BUILDER = None  # async (db, script_artifact, evidence) -> bounded stage specs
RESULT_VALIDATORS = {}  # kind -> async (db, stage, result) -> None; rejects by raising Held
RECEIPT_SETTLERS = {}  # provider -> (saved_request, immutable_rate, receipt) -> (state, cost, error)
from app.services.recap_video.publication import published_script_selections
PUBLISHED_SCRIPT_SELECTIONS = published_script_selections


def worker_can_claim(capabilities: set[str], kind: str) -> bool:
    return kind in capabilities and kind in MEDIA_KINDS


def _preflight_config():
    if PREFLIGHT_CONFIG is None:
        raise Held("media_qualification_required")
    config = PREFLIGHT_CONFIG()
    if not isinstance(config, dict) or not config or len(dump(config)) > 8000:
        raise Held("media_qualification_config_invalid")
    return config


def _evidence(evidence, episode_id):
    # qualification_revision is durable rollout approval, NEVER a challenge ID or
    # observation time. A fresh proof of identical configuration stays compatible
    # with previously completed paid checkpoints and retains both audit records.
    keys = {"episode_id", "account_alias", "voice_digest", "rate_digest", "qualification_revision"}
    if (not isinstance(evidence, dict) or set(evidence) != keys or evidence["episode_id"] != episode_id
            or any(not isinstance(v, str) or not v or len(v) > 128 for v in evidence.values())):
        raise Held("media_qualification_evidence_invalid")
    from app.services.generation.provider_control import account_alias
    if evidence["account_alias"] != account_alias("elevenlabs"):
        raise Held("media_account_changed")
    return evidence


async def _preflight_current(db, stage):
    from app.db.models import User
    from app.services.recap_video.readiness import _authority_reason
    from app.services.recap_video.contracts import EpisodeKey
    episode = await db.get(RecapEpisode, stage.episode_id)
    job = await db.get(GenerationOperation, stage.operation_id)
    if not episode or not job or job.kind != "media_preflight" or job.state != "succeeded":
        raise Held("media_preflight_invalid")
    await require_actor(db, job)
    actor = await db.get(User, job.actor_id)
    if not actor.is_admin or actor.email.lower() not in get_settings().admin_email_list:
        raise Held("admin_permission_removed")
    reason = await _authority_reason(db, EpisodeKey(episode.series_id, episode.season, episode.period_id), episode.league_id)
    if reason:
        raise Held(reason)
    config = await resolve_policy(db, episode.series_id)
    inputs = {"episode_id": episode.episode_id, "facts_digest": episode.facts_digest, "config": _preflight_config()}
    if not episode.admitted_at or stage.input_digest != digest(inputs) or stage.input_json != dump(inputs):
        raise Held("media_preflight_inputs_changed")
    if stage.policy_digest != digest([config["policy"]["features"]["recap_video"], config["revisions"]]):
        raise Held("media_policy_changed")
    return episode, config


async def prepare_preflight(db, episode_id, *, actor_id, reason):
    """Explicit API-owned free metadata checkpoint; no script or paid authority."""
    control = await lock_control(db)
    episode = await db.get(RecapEpisode, episode_id)
    if not episode:
        raise Held("recap_episode_missing")
    if "preflight" not in RESULT_VALIDATORS:
        raise Held("media_handlers_unqualified")
    config = await resolve_policy(db, episode.series_id)
    inputs = {"episode_id": episode_id, "facts_digest": episode.facts_digest, "config": _preflight_config()}
    policy_digest = digest([config["policy"]["features"]["recap_video"], config["revisions"]])
    rows = list((await db.scalars(select(RecapStage).where(RecapStage.episode_id == episode_id,
        RecapStage.kind == "preflight").order_by(RecapStage.revision.desc()))).all())
    for row in rows:
        if (row.input_digest == digest(inputs) and row.policy_digest == policy_digest
                and row.epoch == control.epoch and row.state in ("queued", "running", "succeeded")
                and row.created_at + PREFLIGHT_MAX_AGE > stamp()):
            await _current(db, row, now=stamp())
            return row
        if row.state in ("queued", "running"):
            row.state, row.reason, row.lease_until = "held", "media_preflight_inputs_changed", 0
            row.generation += 1
    job = GenerationOperation(kind="media_preflight", feature="recap_video", league_id=episode.league_id,
        series_id=episode.series_id, actor_id=actor_id, actor_kind="admin", state="succeeded", epoch=control.epoch,
        payload_json=dump(inputs), request_digest=digest(inputs), reason=reason)
    db.add(job)
    await db.flush()
    row = RecapStage(episode_id=episode_id, revision=(rows[0].revision + 1 if rows else 1), kind="preflight",
        script_id="", operation_id=job.id, input_json=dump(inputs), input_digest=digest(inputs),
        policy_digest=policy_digest, epoch=control.epoch)
    db.add(row)
    await db.flush()
    await _current(db, row, now=stamp())
    audit(db, actor_id, "media_preflight_prepared", row.id, reason)
    return row


async def require_media_preflight(db, episode_id):
    _preflight_config()
    row = await db.scalar(select(RecapStage).where(RecapStage.episode_id == episode_id,
        RecapStage.kind == "preflight", RecapStage.state == "succeeded").order_by(RecapStage.revision.desc()).limit(1))
    if not row:
        raise Held("media_qualification_required")
    if row.created_at + PREFLIGHT_MAX_AGE <= stamp():
        raise Held("media_qualification_expired")
    await _current(db, row, now=stamp())
    return _evidence(json.loads(row.result_json)["report"], episode_id)


async def require_script_preflight(db, payload):
    evidence = await require_media_preflight(db, payload.get("episode_id", ""))
    if payload.get("media_qualification_digest") != digest(evidence):
        raise Held("media_qualification_changed")


async def prepare_episode_script(db, episode_id, *, cache_dir, published_script_ids=()):
    """API projector prepares the normal candidate; history comes from Task9 only."""
    from app.services.recap_video.contracts import prepare_script
    from app.services.generation.planner import observe
    await lock_control(db)
    episode = await db.get(RecapEpisode, episode_id)
    if not episode:
        raise Held("recap_episode_missing")
    payload = await prepare_script(db, episode_id, cache_dir=cache_dir, published_script_ids=published_script_ids)
    payload["media_qualification_digest"] = digest(await require_media_preflight(db, episode_id))
    candidate = await observe(db, series_id=episode.series_id, league_id=episode.league_id,
        feature="recap_video", subject="recap_video:" + episode_id, event=episode.period_id, payload=payload)
    return candidate


async def _current(db, stage, *, now):
    control = await lock_control(db)
    settings = get_settings()
    if settings.generation_emergency_pause:
        raise Held("emergency_pause")
    if control.hold:
        raise Held(control.hold)
    if not control.epoch or stage.epoch != control.epoch or settings.generation_execution_epoch != control.epoch:
        raise Held("restore_quarantine")
    if stage.kind == "preflight":
        return await _preflight_current(db, stage)
    job = await db.get(GenerationOperation, stage.operation_id)
    artifact = await db.get(ContentArtifact, stage.script_id)
    if (not job or job.state != "succeeded" or not artifact or artifact.operation_id != job.id
            or artifact.feature != "recap_video" or artifact.revision != stage.revision
            or artifact.provenance != "managed" or artifact.digest != digest(json.loads(artifact.payload_json))):
        raise Held("media_script_invalid")
    head = await db.get(ArtifactHead, artifact.subject)
    if not head or head.artifact_id != artifact.id or head.hold:
        raise Held("media_script_changed")
    await require_actor(db, job)
    from app.services.recap_video.contracts import require_script_inputs
    episode = await require_script_inputs(db, job.series_id, job.league_id, json.loads(job.payload_json), media_checkpoint=True)
    await require_script_preflight(db, json.loads(job.payload_json))
    if episode.episode_id != stage.episode_id:
        raise Held("media_episode_changed")
    config = await resolve_policy(db, job.series_id)
    feature = config["policy"]["features"]["recap_video"]
    if config["blocked_by"]:
        raise Held(config["blocked_by"][0])
    if feature["paused"] or feature["mode"] == "disabled":
        raise Held("feature_paused")
    if job.actor_kind == "scheduler" and feature["mode"] != "automatic":
        raise Held("manual_only")
    evidence = await require_media_preflight(db, stage.episode_id)
    if stage.policy_digest != digest([feature, config["revisions"], evidence]):
        raise Held("media_policy_changed")
    if stage.input_digest != digest(json.loads(stage.input_json)):
        raise Held("media_inputs_changed")
    return episode, config


async def start_media(db, script_id):
    """Idempotent API continuation of an approved private script. No worker endpoint."""
    control = await lock_control(db)
    artifact = await db.get(ContentArtifact, script_id)
    if not artifact or artifact.feature != "recap_video" or not artifact.operation_id:
        raise Held("media_script_invalid")
    existing = list((await db.scalars(select(RecapStage).where(RecapStage.script_id == script_id))).all())
    if existing:
        return existing
    payload = json.loads(artifact.payload_json)
    evidence = await require_media_preflight(db, payload.get("episode_id", ""))
    if MEDIA_PLAN_BUILDER is None:
        raise Held("media_handlers_unqualified")
    specs = await MEDIA_PLAN_BUILDER(db, artifact, evidence)
    if not isinstance(specs, list) or not 1 <= len(specs) <= 128:
        raise Held("media_plan_unbounded")
    config = await resolve_policy(db, artifact.series_id)
    policy_digest = digest([config["policy"]["features"]["recap_video"], config["revisions"], evidence])
    rows, keys = [], set()
    previous = ""
    order = {kind: n for n, kind in enumerate(("narrate", "speech_check", "render", "media_check"))}
    last = -1
    for spec in specs:
        if (set(spec) != {"kind", "chunk", "input"} or spec["kind"] not in LIFECYCLE
                or type(spec["chunk"]) is not int or not 0 <= spec["chunk"] < 64
                or not isinstance(spec["input"], dict) or len(dump(spec["input"])) > 96_000
                or (spec["kind"], spec["chunk"]) in keys or order[spec["kind"]] < last):
            raise Held("media_plan_invalid")
        if spec["kind"] not in RESULT_VALIDATORS:
            raise Held("media_handlers_unqualified")
        keys.add((spec["kind"], spec["chunk"]))
        last = order[spec["kind"]]
        row = RecapStage(episode_id=payload["episode_id"], revision=artifact.revision,
            kind=spec["kind"], chunk=spec["chunk"], script_id=artifact.id, operation_id=artifact.operation_id,
            predecessor_id=previous, input_json=dump(spec["input"]), input_digest=digest(spec["input"]),
            policy_digest=policy_digest, epoch=control.epoch)
        db.add(row)
        await db.flush()
        await _current(db, row, now=stamp())
        rows.append(row)
        previous = row.id
    if {row.kind for row in rows} != set(LIFECYCLE):
        raise Held("media_plan_incomplete")
    audit(db, "api-projector", "media_prepared", rows[0].episode_id, "Approved script bound to subordinate checkpoints")
    return rows


async def _expire(db, now):
    expired = (await db.scalars(select(RecapStage).where(RecapStage.state == "running",
        RecapStage.lease_until <= now).with_for_update(skip_locked=True))).all()
    for row in expired:
        attempt = await db.scalar(select(RecapProviderAttempt).where(RecapProviderAttempt.stage_id == row.id))
        row.generation += 1
        if attempt and attempt.state in ("dispatching", "unknown", "abandoned"):
            if attempt.state == "dispatching":
                attempt.state = "unknown"
            row.state, row.reason = "needs_attention", "provider_outcome_unknown"
        elif row.kind == "narrate":
            row.state, row.reason = "held", "paid_checkpoint_reconciliation_required"
        else:
            _retry_free(row, now)


def _retry_free(row, now):
    if row.kind == "narrate":
        row.state, row.reason = "needs_attention", "paid_stage_review_required"
    elif row.failures < len(BACKOFF):
        row.next_attempt_at = now + BACKOFF[row.failures]
        row.failures += 1
        row.state, row.reason = "queued", "transient_failure"
    else:
        row.state, row.reason = "needs_attention", "free_retry_exhausted"


def lease_data(row, allowed_assets):
    return dict(stage_id=row.id, generation=row.generation, epoch=row.epoch,
        input_digest=row.input_digest, expires_at=row.lease_until, capability=row.kind,
        heartbeat_seconds=30, input=json.loads(row.input_json), allowed_assets=allowed_assets)


async def allowed_asset_ids(db, row):
    """Only selected outputs of this exact script's completed prerequisite chain."""
    assets, seen = [], set()
    predecessor = row.predecessor_id
    while predecessor:
        if predecessor in seen or len(seen) >= 128:
            raise Held("media_dependency_invalid")
        seen.add(predecessor)
        stage = await db.get(RecapStage, predecessor)
        if not stage or stage.script_id != row.script_id or stage.state != "succeeded":
            raise Held("media_dependency_invalid")
        assets.extend(json.loads(stage.result_json).get("asset_ids", []))
        predecessor = stage.predecessor_id
    return assets


async def claim_stage(db, worker_id: str, capabilities: set[str], now: int) -> dict | None:
    await lock_control(db)
    await _expire(db, now)
    eligible_kinds = set(capabilities) & MEDIA_KINDS
    if await db.scalar(select(RecapStage.id).where(RecapStage.kind == "render",
            RecapStage.state == "running", RecapStage.lease_until > now).limit(1)):
        eligible_kinds.discard("render")
    # Blocked dependents must not consume the bounded window and hide their root.
    predecessor = aliased(RecapStage)
    dependency_ready = select(predecessor.id).where(predecessor.id == RecapStage.predecessor_id,
        predecessor.script_id == RecapStage.script_id, predecessor.state == "succeeded").exists()
    rows = (await db.scalars(select(RecapStage).where(RecapStage.state == "queued",
        RecapStage.next_attempt_at <= now, RecapStage.kind.in_(eligible_kinds),
        or_(RecapStage.predecessor_id == "", dependency_ready))
        .order_by(RecapStage.created_at, RecapStage.id).with_for_update(skip_locked=True).limit(100))).all()
    for row in rows:
        try:
            episode, _ = await _current(db, row, now=now)
            if row.kind not in RESULT_VALIDATORS:
                raise Held("media_handlers_unqualified")
        except Held as exc:
            row.state, row.reason = "held", exc.code
            continue
        row.state, row.worker_id, row.lease_until = "running", worker_id, now + LEASE_SECONDS
        row.generation += 1
        if row.kind != "preflight":
            episode.lifecycle, episode.hold = LIFECYCLE[row.kind], ""
        assets = await allowed_asset_ids(db, row)
        audit(db, worker_id, "media_claimed", row.id, "Subordinate checkpoint leased")
        return lease_data(row, assets)
    return None


async def require_lease(db, stage_id, generation, epoch, input_digest, *, worker_id=None, now=None):
    await lock_control(db)
    now = stamp() if now is None else now
    row = await db.get(RecapStage, stage_id, populate_existing=True)
    if (not row or row.state != "running" or row.generation != generation or row.epoch != epoch
            or row.input_digest != input_digest or row.lease_until <= now
            or (worker_id is not None and row.worker_id != worker_id)):
        raise OwnershipLost("Media lease expired or changed; reconcile checkpoint before continuing")
    await _current(db, row, now=now)
    return row


async def heartbeat_stage(db, stage_id, generation, epoch, input_digest, *, worker_id, now=None):
    now = stamp() if now is None else now
    row = await require_lease(db, stage_id, generation, epoch, input_digest, worker_id=worker_id, now=now)
    row.lease_until = now + LEASE_SECONDS
    return {"expires_at": row.lease_until}


async def complete_stage(db, stage_id: str, generation: int, epoch: str, input_digest: str, result: dict,
                         *, worker_id=None, now=None) -> dict:
    now = stamp() if now is None else now
    row = await require_lease(db, stage_id, generation, epoch, input_digest, worker_id=worker_id, now=now)
    if (set(result) != {"status", "asset_ids", "report"} or result["status"] not in ("ok", "transient", "input_failure")
            or not isinstance(result["asset_ids"], list) or len(result["asset_ids"]) > 64
            or not isinstance(result["report"], dict) or len(dump(result)) > 32_000):
        raise Held("media_result_invalid")
    for asset_id in result["asset_ids"]:
        asset = await db.get(RecapAsset, asset_id) if isinstance(asset_id, str) else None
        if not asset or asset.stage_id != row.id or asset.generation != generation:
            raise Held("media_asset_not_owned")
    if result["status"] != "ok":
        # Failure diagnostics remain durable after the generation is fenced.
        row.result_json = dump(result)
        if result["status"] == "transient":
            _retry_free(row, now)
        else:
            row.state, row.reason = "held", "input_revision_required"
        row.generation += 1
    else:
        validator = RESULT_VALIDATORS.get(row.kind)
        if validator is None:
            raise Held("media_handlers_unqualified")
        if row.kind == "narrate":
            attempt = await db.scalar(select(RecapProviderAttempt).where(RecapProviderAttempt.stage_id == row.id))
            if not attempt or attempt.state != "received" or attempt.cost_microusd is None or attempt.error_code:
                raise Held("provider_outcome_unknown")
        try:
            verified = await validator(db, row, result)
        except Held as exc:
            if row.kind not in ('speech_check','render','media_check'):
                raise
            row.result_json,row.state,row.reason,row.lease_until=dump(result),'held',exc.code,0
            row.generation += 1
            from app.services.recap_video.corrections import attention
            await attention(db,row.episode_id,row.kind,exc.code)
            audit(db,row.worker_id,'media_validation_held',row.id,exc.code)
            return {'stage_id':row.id,'state':row.state}
        if row.kind == "preflight":
            result = {**result, "report": _evidence(verified, row.episode_id)}
        row.result_json, row.state = dump(result), "succeeded"
        if row.kind == "preflight":
            await db.flush()
            held = (await db.scalars(select(RecapStage).where(RecapStage.episode_id == row.episode_id,
                RecapStage.state == "held", RecapStage.reason == "media_qualification_expired"))).all()
            for checkpoint in held:
                try:
                    await _current(db, checkpoint, now=now)
                except Held:
                    continue
                checkpoint.state, checkpoint.reason = "queued", ""
        if row.kind == "media_check":
            episode = await db.get(RecapEpisode, row.episode_id)
            episode.lifecycle = "review"
    row.lease_until = 0
    audit(db, row.worker_id, "media_" + row.state, row.id, "Media checkpoint result recorded")
    return {"stage_id": row.id, "state": row.state}


async def cancel_media(db, episode_id, actor, reason):
    await lock_control(db)
    for row in (await db.scalars(select(RecapStage).where(RecapStage.episode_id == episode_id,
            RecapStage.state != "succeeded"))).all():
        row.state, row.reason, row.lease_until = "cancelled", "owner_cancelled", 0
        row.generation += 1
        from app.services.generation.recap_budget import release_unsubmitted
        await release_unsubmitted(db, row.id, "media_cancelled")
    audit(db, actor, "media_cancelled", episode_id, reason)


async def authorize_dispatch(db, stage_id, generation, epoch, input_digest, *, worker_id, now=None):
    """Return authority exactly once AFTER transaction commit by the API route.

    Retry/restart never returns that authority again. Receipt reconciliation is
    separate and cannot authorize replacements. Provider exactly-once is not claimed.
    """
    now = stamp() if now is None else now
    row = await require_lease(db, stage_id, generation, epoch, input_digest, worker_id=worker_id, now=now)
    if row.kind != "narrate":
        raise Held("paid_capability_required")
    if await db.scalar(select(RecapProviderAttempt.id).where(RecapProviderAttempt.stage_id == row.id)):
        raise Held("dispatch_authority_already_issued")
    from app.services.generation.provider_control import account_alias, active_attempts, require_provider_ready
    from app.services.generation.recap_budget import reserve_plan, require_episode_budget
    provider, alias = "elevenlabs", account_alias("elevenlabs")
    if provider not in RECEIPT_SETTLERS:
        raise Held("provider_receipts_unqualified")
    from app.services.recap_video.admin_actions import replacement_dispositions
    dispositioned = await replacement_dispositions(db, row)
    await require_provider_ready(db, provider, alias, now, dispositioned=dispositioned)
    episode, config = await _current(db, row, now=now)
    if await active_attempts(db, provider=provider, account_key=alias,dispositioned=dispositioned) >= config["policy"]["max_concurrency"]:
        raise Held("concurrency_busy")
    if await active_attempts(db, series_id=episode.series_id,dispositioned=dispositioned):
        raise Held("series_concurrency_busy")
    # Entire immutable narration plan reserved before its first physical request.
    narration = list((await db.scalars(select(RecapStage).where(RecapStage.script_id == row.script_id,
        RecapStage.execution_revision == row.execution_revision, RecapStage.kind == "narrate").order_by(RecapStage.chunk))).all())
    allocations = []
    for stage in narration:
        paid = json.loads(stage.input_json).get("paid")
        if (not isinstance(paid, dict) or set(paid) != {"request", "rate_snapshot", "max_microusd"}
                or not isinstance(paid["request"], dict) or not isinstance(paid["rate_snapshot"], dict)):
            raise Held("narration_plan_unqualified")
        allocations.append(dict(key=stage.id, category="video", operation_id=stage.id,
            max_microusd=paid["max_microusd"], rate_snapshot=paid["rate_snapshot"]))
    plan_key = "media:" + row.script_id + (":" + str(row.execution_revision) if row.execution_revision > 1 else "")
    plan = await reserve_plan(db, row.episode_id, episode.series_id, plan_key, allocations, now)
    await require_episode_budget(db, row.episode_id, episode.series_id, now, dispositioned=dispositioned)
    allocation = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.plan_id == plan,
        RecapBudgetAllocation.key == row.id))
    if allocation.attempt_id or allocation.state != "reserved":
        raise Held("narration_allocation_unavailable")
    paid = json.loads(row.input_json)["paid"]
    authority = secrets.token_urlsafe(32)
    attempt = RecapProviderAttempt(stage_id=row.id, episode_id=row.episode_id, series_id=episode.series_id,
        operation_id=row.operation_id, provider=provider, account_key=alias, worker_id=worker_id,
        generation=generation, epoch=epoch, request_digest=digest(paid["request"]), request_json=dump(paid["request"]),
        pricing_json=allocation.rate_json, authority_digest=hashlib.sha256(authority.encode()).hexdigest())
    db.add(attempt)
    await db.flush()
    allocation.attempt_id = attempt.id
    audit(db, worker_id, "media_dispatch_admitted", row.id, "One physical provider request authorized")
    return {"attempt_id": attempt.id, "dispatch_authority": authority, "request": paid["request"]}


def _safe_receipt(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if any(part in key.lower() for part in ("base64", "secret", "api_key", "authorization", "token")):
                raise Held("media_receipt_sensitive_field")
            _safe_receipt(child)
    elif isinstance(value, list):
        for child in value:
            _safe_receipt(child)


async def _owned_attempt(db, attempt_id, worker_id):
    await lock_control(db)
    attempt = await db.get(RecapProviderAttempt, attempt_id)
    if not attempt or attempt.worker_id != worker_id:
        raise OwnershipLost("Provider evidence does not belong to this worker")
    return attempt


def _identity(attempt):
    identity = {}
    for observation in json.loads(attempt.identity_json or "[]"):
        identity.update(observation)
    return identity


async def persist_identity(db, attempt_id, identity, *, worker_id):
    from app.services.recap_video.elevenlabs import identifier
    attempt = await _owned_attempt(db, attempt_id, worker_id)
    if not isinstance(identity, dict) or not identity or set(identity) - {"request_id", "history_item_id"}:
        raise Held("provider_identity_invalid")
    try:
        for value in identity.values():
            identifier(value)
    except ValueError:
        raise Held("provider_identity_invalid") from None
    previous = _identity(attempt)
    if any(key in previous and previous[key] != value for key, value in identity.items()):
        raise Conflict("Provider identity conflicts with retained evidence")
    if any(key not in previous for key in identity):
        observations = json.loads(attempt.identity_json or "[]")
        observations.append(identity)
        attempt.identity_json = dump(observations)
    return {"attempt_id": attempt.id, "identity": _identity(attempt)}


async def recovery_evidence(db, attempt_id, *, worker_id):
    attempt = await _owned_attempt(db, attempt_id, worker_id)
    return {"attempt_id": attempt.id, "identity": _identity(attempt), "request": json.loads(attempt.request_json),
        "receipt": json.loads(attempt.receipt_json) if attempt.receipt_json else None,
        "recovery_receipt": json.loads(attempt.recovery_receipt_json) if attempt.recovery_receipt_json else None}


async def persist_recovery_receipt(db, attempt_id, receipt, *, worker_id):
    attempt = await _owned_attempt(db, attempt_id, worker_id)
    _safe_receipt(receipt)
    raw = dump(receipt)
    if len(raw) > 32_000:
        raise Held("media_receipt_too_large")
    identity = _identity(attempt)
    if not identity.get("history_item_id") or receipt.get("identity") != identity:
        raise Held("provider_recovery_identity_unresolved")
    if attempt.recovery_receipt_json and attempt.recovery_receipt_json != raw:
        raise Conflict("Recovery receipt conflicts with retained evidence")
    original = json.loads(attempt.receipt_json or "{}")
    if original.get("audio_sha256") and original["audio_sha256"] != receipt.get("audio_sha256"):
        raise Conflict("Recovered audio differs from original response")
    attempt.recovery_receipt_json = raw
    return {"attempt_id": attempt.id, "state": attempt.state}


async def persist_receipt(db, attempt_id, receipt, *, worker_id):
    """Persist bounded immutable raw evidence before invoking receipt decoder."""
    await lock_control(db)
    attempt = await db.get(RecapProviderAttempt, attempt_id)
    if not attempt or attempt.worker_id != worker_id:
        raise OwnershipLost("Provider receipt does not belong to this worker")
    if receipt.get("identity"):
        await persist_identity(db, attempt_id, receipt["identity"], worker_id=worker_id)
    _safe_receipt(receipt)
    raw = dump(receipt)
    if len(raw) > 32_000:
        raise Held("media_receipt_too_large")
    if attempt.receipt_json and attempt.receipt_json != raw:
        raise Conflict("Provider receipt conflicts with immutable saved evidence")
    attempt.receipt_json = raw
    return {"attempt_id": attempt.id, "state": attempt.state}


async def settle_receipt(db, attempt_id, *, worker_id):
    """A late response settles money only; never selects a stale checkpoint."""
    await lock_control(db)
    attempt = await db.get(RecapProviderAttempt, attempt_id)
    if not attempt or attempt.worker_id != worker_id:
        raise OwnershipLost("Provider receipt does not belong to this worker")
    original_pending = bool(attempt.receipt_json) and not attempt.settled_at
    recovery_pending = bool(attempt.recovery_receipt_json) and not attempt.recovery_settled_at
    if not original_pending and not recovery_pending:
        if not attempt.receipt_json and not attempt.recovery_receipt_json:
            raise Held("media_receipt_missing")
        return {"attempt_id": attempt.id, "state": attempt.state}
    receipts = {name: json.loads(raw) for name, raw in (
        ("original", attempt.receipt_json), ("recovery", attempt.recovery_receipt_json)) if raw}
    settle = RECEIPT_SETTLERS.get(attempt.provider)
    if settle is None:
        raise Held("provider_receipts_unqualified")
    decoded = []
    for receipt in receipts.values():
        try:
            item = settle(json.loads(attempt.request_json), json.loads(attempt.pricing_json), receipt)
            state, amount, error = item
        except Exception:
            raise Held("provider_receipt_validation_failed") from None
        if (state not in ("received", "rejected", "unknown")
                or error not in ("", "provider_rejected", "provider_outcome_unknown", "response_invalid")
                or (amount is not None and (type(amount) is not int or amount < 0))):
            raise Held("media_receipt_invalid")
        decoded.append(item)
    # Reconcile all durable same-attempt evidence, even if the original commit
    # preceded a crash before its settlement. No receipt takes precedence over a
    # contradictory amount, and unknown evidence cannot erase a provable charge.
    known = {item[1] for item in decoded if item[1] is not None}
    if attempt.cost_microusd is not None:
        known.add(attempt.cost_microusd)
    if len(known) > 1:
        raise Conflict("Recovered metering conflicts with retained charge evidence")
    amount = next(iter(known), None)
    state, _, error = decoded[-1]
    if attempt.recovery_receipt_json:
        state = "received" if amount is not None else "unknown"
        error = "response_invalid" if amount is not None else "provider_outcome_unknown"
    if original_pending:
        attempt.settled_at = stamp()
    if recovery_pending:
        attempt.recovery_settled_at = stamp()
    attempt.cost_microusd, attempt.state, attempt.error_code = amount, state, error
    receipt = next(reversed(receipts.values()))
    from app.services.generation.provider_control import record_failure
    await record_failure(db, attempt.provider, attempt.account_key, receipt.get("status"), stamp(),
        accounting_unknown=amount is None)
    allocation = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id == attempt.id))
    if not allocation:
        raise Held("media_allocation_missing")
    from app.services.generation.recap_budget import settle_allocation
    await settle_allocation(db, allocation.id, amount, {"receipt_digests": {name: digest(value) for name, value in receipts.items()}, "attempt_id": attempt.id})
    return {"attempt_id": attempt.id, "state": attempt.state}


async def record_receipt(db, attempt_id, receipt, *, worker_id):
    """Internal transactional helper. HTTP route commits persist before decoding."""
    await persist_receipt(db, attempt_id, receipt, worker_id=worker_id)
    return await settle_receipt(db, attempt_id, worker_id=worker_id)


async def reconcile_media_receipts(maker):
    async with maker() as db:
        rows = (await db.scalars(select(RecapProviderAttempt).where(or_(
            (RecapProviderAttempt.receipt_json.is_not(None) & (RecapProviderAttempt.settled_at == 0)),
            (RecapProviderAttempt.recovery_receipt_json.is_not(None) & (RecapProviderAttempt.recovery_settled_at == 0)))
            ).limit(100))).all()
        saved = [(row.id, row.worker_id) for row in rows]
    for attempt_id, worker_id in saved:
        try:
            async with maker.begin() as db:
                await settle_receipt(db, attempt_id, worker_id=worker_id)
        except (Held, Conflict):
            async with maker.begin() as db:
                await lock_control(db)
                row = await db.get(RecapProviderAttempt, attempt_id)
                row.state, row.error_code = "unknown", "response_invalid"


async def advance_media(maker):
    """API projector joins published article -> normal script queue -> media checkpoints."""
    await reconcile_media_receipts(maker)
    async with maker.begin() as db:
        await lock_control(db)
        episodes = (await db.scalars(select(RecapEpisode).where(RecapEpisode.lifecycle.in_(("ready", "waiting_for_article")),
            RecapEpisode.hold == "", RecapEpisode.admitted_at > 0).order_by(RecapEpisode.observed_at.desc()).limit(50))).all()
        for episode in episodes:
            try:
                async with db.begin_nested():
                    from app.services.recap_video.qualification import qualification_status
                    from app.services.generation.recap_models import RecapStandingAuthorization
                    qualified=await qualification_status(db,episode.series_id,episode.season)
                    if qualified['automatic']:
                        standing=await db.get(RecapStandingAuthorization,qualified['standing_id'])
                        await prepare_preflight(db,episode.episode_id,actor_id=standing.actor_id,
                            reason='Current season standing policy metadata verification')
                    await require_media_preflight(db, episode.episode_id)
                    selections = await PUBLISHED_SCRIPT_SELECTIONS(db, episode.series_id) if PUBLISHED_SCRIPT_SELECTIONS else ()
                    await prepare_episode_script(db, episode.episode_id, cache_dir=get_settings().cache_dir,
                        published_script_ids=selections)
            except Held:
                # Source/prose remain independent; unavailable media spends nothing.
                continue
        scripts = (await db.scalars(select(ContentArtifact).where(ContentArtifact.feature == "recap_video",
            ~ContentArtifact.id.in_(select(RecapStage.script_id))).order_by(ContentArtifact.created_at).limit(25))).all()
        for script in scripts:
            episode = await db.get(RecapEpisode, json.loads(script.payload_json).get("episode_id", ""))
            if not episode or episode.hold:
                continue
            try:
                async with db.begin_nested():
                    await start_media(db, script.id)
            except Held as exc:
                # Media recovery belongs to the checkpoint/operation, never the
                # source hold shared with the independently publishable article.
                job = await db.get(GenerationOperation, script.operation_id)
                if job:
                    job.reason = exc.code
    from app.services.recap_video.qualification import advance_qualified_publication
    await advance_qualified_publication(maker)
