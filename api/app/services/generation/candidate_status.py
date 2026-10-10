"""Read-only candidate eligibility shared by review lists and campaign commands.

Candidates are durable observations, not a queue of work that must be approved.
Saved artifacts and completed semantic events remain complete when refreshed
facts change. Explicit correction proposals are the way to revise saved prose.
"""
from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import select

from app.config import get_settings
from app.db.models import YahooConnection
from app.services.generation.commands import UNRESOLVED, require_actor
from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationControl,
    GenerationOperation,
    LeagueSeason,
    ProviderAttempt,
    stamp,
)
from app.services.generation.policy import paid_capabilities, supports_feature
from app.services.generation.store import Held, resolve_policy

REVIEWABLE_HOLDS = ("", "historical_approval_required", "missed_event_approval_required", "manual_approval_required")
ACTIVE_STATES = ("queued", "running", "held", "needs_attention")


def _period(payload):
    season, week = payload.get("season"), payload.get("week")
    if type(season) is int and season > 0 and type(week) is int and week >= 0:
        return {"season": season, "week": week}
    return None


def _completed(row, payload, operations, artifact):
    succeeded = [job for job in operations if job.state == "succeeded"]
    if any(job.request_digest == row.digest for job in succeeded):
        return True
    # A correction is a new explicit request, not the normal event it revises.
    if payload.get("correction_base"):
        return False
    if artifact:
        saved = json.loads(artifact.payload_json)
        if row.feature == "trade_story":
            return True
        if row.feature == "analyst" and saved.get("edition_type", "roast") == "roast":
            return True
        if row.feature.endswith("blurb") and _period(payload):
            if saved.get("generation_period") == _period(payload):
                return True
    # Successful operations retain immutable facts even if the latest candidate
    # digest has moved. A completed week is not newly missing after a refresh.
    for job in succeeded:
        if job.feature != row.feature:
            continue
        saved = json.loads(job.payload_json)
        if row.feature == "trade_story" or (_period(payload) and _period(saved) == _period(payload)):
            return True
    return False


def _status(availability, *, reason="", blocked_by=()):
    return {"availability": availability, "review_reason": reason,
            "reviewable": availability == "available" and bool(reason),
            "blocked_by": list(dict.fromkeys(blocked_by))}


async def _content_for(db, rows):
    subjects = {row.subject for row in rows}
    operations = defaultdict(list)
    for job in (await db.scalars(select(GenerationOperation).where(
            GenerationOperation.kind == "generation", GenerationOperation.subject.in_(subjects))
            .order_by(GenerationOperation.created_at.desc(), GenerationOperation.id))).all():
        operations[job.subject].append(job)
    heads = {head.subject: head for head in (await db.scalars(select(ArtifactHead).where(
        ArtifactHead.subject.in_(subjects)))).all()}
    artifacts = {artifact.id: artifact for artifact in (await db.scalars(select(ContentArtifact).where(
        ContentArtifact.id.in_([head.artifact_id for head in heads.values()])))).all()}
    return operations, heads, artifacts


async def completed_candidate_keys(db, rows):
    """Read semantic completion for automatic admission without granting work."""
    if not rows:
        return set()
    operations, heads, artifacts = await _content_for(db, rows)
    return {row.key for row in rows if _completed(row, json.loads(row.payload_json), operations[row.subject],
        artifacts.get(heads[row.subject].artifact_id) if row.subject in heads else None)}


async def classify_candidates(db, rows, *, actor_id):
    """Classify a batch without authorization, mutation, or provider calls."""
    if not rows:
        return {}
    subjects = {row.subject for row in rows}
    league_ids = {row.league_id for row in rows}
    operations, heads, artifacts = await _content_for(db, rows)
    unresolved = set((await db.scalars(select(GenerationOperation.subject).join(
        ProviderAttempt, ProviderAttempt.operation_id == GenerationOperation.id).where(
            GenerationOperation.subject.in_(subjects), ProviderAttempt.state.in_(UNRESOLVED)))).all())
    seasons = {season.league_id: season for season in (await db.scalars(select(LeagueSeason).where(
        LeagueSeason.league_id.in_(league_ids)))).all()}
    control = await db.get(GenerationControl, "global")
    from app.services.generation.provider_control import account_alias
    from app.services.generation.recap_models import ProviderAccountControl
    provider = await db.get(ProviderAccountControl, ("anthropic", account_alias("anthropic")))
    policies, permissions, eligibility = {}, {}, {}
    result = {}
    for row in rows:
        payload = json.loads(row.payload_json)
        jobs = operations[row.subject]
        pending = next((job for job in jobs if job.state in ACTIVE_STATES), None)
        if pending:
            result[row.key] = _status(pending.state)
            continue
        if row.subject in unresolved:
            result[row.key] = _status("blocked", blocked_by=["provider_outcome_unknown"])
            continue
        head = heads.get(row.subject)
        artifact = artifacts.get(head.artifact_id) if head else None
        if _completed(row, payload, jobs, artifact):
            result[row.key] = _status("completed")
            continue
        blocks = []
        if not payload.get("facts") and row.feature != "recap_video":
            blocks.append("facts_unavailable")
        if row.hold not in REVIEWABLE_HOLDS:
            blocks.append(row.hold)
        if head and head.hold:
            blocks.append(head.hold)
        correction = payload.get("correction_base")
        if correction and (not head or head.artifact_id != correction):
            blocks.append("correction_base_changed")
        season = seasons.get(row.league_id)
        if not season or not season.verified_at or not supports_feature(
                paid_capabilities(json.loads(season.capabilities_json)), season.provider, row.feature):
            blocks.append("capability_unknown_or_unsupported")
        if row.series_id not in policies:
            policies[row.series_id] = await resolve_policy(db, row.series_id)
        policy = policies[row.series_id]
        blocks.extend(policy["blocked_by"])
        feature = policy["policy"]["features"].get(row.feature)
        if not feature or feature["paused"] or feature["mode"] == "disabled":
            blocks.append("feature_paused")
        if get_settings().generation_emergency_pause:
            blocks.append("emergency_pause")
        if control and control.cooldown_until > stamp():
            blocks.append("provider_cooldown")
        if control and control.provider_hold:
            blocks.append(control.provider_hold)  # Legacy restore, before scoped migration.
        if provider and provider.hold:
            blocks.append(provider.hold)
        if provider and provider.cooldown_until > stamp():
            blocks.append("provider_cooldown")
        if row.feature == "recap_video":
            try:
                from app.services.recap_video.workflow import require_script_preflight
                from app.services.recap_video.contracts import require_script_inputs
                await require_script_preflight(db, payload)
                await require_script_inputs(db, row.series_id, row.league_id, payload)
            except Held as exc:
                blocks.append(exc.code)
        if control and json.loads(control.breakers_json).get(row.feature, {}).get("open"):
            blocks.append("feature_breaker_open")
        if not blocks:
            if row.league_id not in permissions:
                connection = await db.get(YahooConnection, actor_id) if season.provider == "yahoo" else None
                try:
                    await require_actor(db, GenerationOperation(kind="generation", actor_id=actor_id,
                        league_id=row.league_id, connection_generation=connection.generation if connection else ""))
                    permissions[row.league_id] = ""
                except Held as exc:
                    permissions[row.league_id] = exc.code
            if permissions[row.league_id]:
                blocks.append(permissions[row.league_id])
        if blocks:
            result[row.key] = _status("blocked", blocked_by=blocks)
            continue
        if correction:
            reason = "correction_approval_required"
        elif row.hold:
            reason = row.hold
        elif feature["mode"] == "manual":
            reason = "manual_approval_required"
        else:
            from app.services.generation.planner import automatic_eligibility
            eligibility_key = (row.league_id, row.feature, payload.get("season"), payload.get("week"),
                payload.get("event_at"), payload.get("phase"), payload.get("target", {}).get("scope"))
            if eligibility_key not in eligibility:
                eligibility[eligibility_key] = await automatic_eligibility(db, season, row.feature, payload, stamp())
            reason = eligibility[eligibility_key]
        result[row.key] = _status("available", reason=reason)
    return result


def require_available(status):
    if status["availability"] == "available":
        return
    if status["availability"] == "completed":
        raise Held("Content is already completed; request a correction from Saved content to revise it")
    if status["availability"] in ACTIVE_STATES:
        raise Held("This content already has work in progress or needing review")
    raise Held((status["blocked_by"] or ["Content is not available for approval"])[0])
