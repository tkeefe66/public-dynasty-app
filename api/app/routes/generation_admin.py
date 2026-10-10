"""Owner-only generation control. All writes require a reason and revision."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, select

from app.auth.deps import require_admin
from app.config import get_settings
from app.db.models import LeagueMembership
from app.db.session import get_db
from app.services.generation import administration as commands
from app.services.generation.candidate_status import classify_candidates
from app.services.generation.league_names import attach_league_names
from app.services.generation.models import (
    ContentArtifact,
    GenerationAudit,
    GenerationCandidate,
    GenerationControl,
    GenerationOperation,
    GenerationOutbox,
    LeagueSeason,
    LeagueSeries,
    ProviderAttempt,
)
from app.services.generation.policy import StrictModel
from app.services.generation.registry import set_series
from app.services.generation.store import Conflict, Held, data, resolve_policy

router = APIRouter(prefix="/api/admin/generation", dependencies=[Depends(require_admin)])
DB = Annotated[object, Depends(get_db)]
Owner = Annotated[object, Depends(require_admin)]


class Reason(StrictModel):
    reason: str = Field(min_length=1, max_length=1000)


class PolicyChange(Reason):
    expected_revision: int = Field(ge=0)
    value: dict


class ControlChange(Reason):
    expected_revision: int = Field(ge=0)
    action: Literal["pause", "activate", "resume", "clear_provider", "reset_breaker"]
    workers_stopped: bool = False
    feature: str = ""


class SeriesChange(Reason):
    expected_revision: int = Field(ge=1)
    lifecycle: Literal["active", "retired", "pending_verification"]
    profile: Literal["dynasty", "keeper", "redraft"]
    activate: bool = False


class Preview(Reason):
    candidates: list[str] = Field(min_length=1, max_length=1000)


class BatchJobs(Reason):
    job_ids: list[str] = Field(min_length=1, max_length=1000)
    action: Literal["resume", "cancel"]


class Apply(Reason):
    preview_id: str
    digest: str


class CatchUp(Reason):
    series_id: str = ""


class JobAction(Reason):
    expected_generation: int
    expected_state: str
    action: Literal["cancel", "resume"]


class AttemptAction(Reason):
    expected_state: str
    action: Literal["abandon_unknown", "not_sent"]
    workers_stopped: bool
    evidence: str = Field(min_length=1, max_length=4000)


class ProjectionRetry(Reason):
    expected_error: str


class Correction(Reason):
    expected_artifact: str


async def execute(command):
    try:
        return await command
    except (Conflict, Held) as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
async def overview(db: DB):
    from app.services.generation.recap_models import ProviderAccountControl, RecapProviderAttempt
    control = await db.get(GenerationControl, "global")
    rows = (await db.execute(select(GenerationOperation.state, func.count()).group_by(
        GenerationOperation.state))).all()
    known = await db.scalar(select(func.coalesce(func.sum(ProviderAttempt.cost_microusd), 0)))
    unknown = await db.scalar(select(func.count()).select_from(ProviderAttempt).where(
        ProviderAttempt.cost_microusd.is_(None)))
    media_known = await db.scalar(select(func.coalesce(func.sum(RecapProviderAttempt.cost_microusd), 0)))
    media_unknown = await db.scalar(select(func.count()).select_from(RecapProviderAttempt).where(RecapProviderAttempt.cost_microusd.is_(None)))
    providers = [data(row) for row in (await db.scalars(select(ProviderAccountControl))).all()]
    return {"providers": providers, "control": data(control) if control else {"id": "global", "revision": 0,
        "hold": "activation_required", "epoch": "", "provider_hold": "", "breakers_json": "{}"},
        "effective": await resolve_policy(db), "jobs": dict(rows),
        "known_cost_microusd": int(known + media_known), "unknown_cost_attempts": unknown + media_unknown,
        "execution_epoch_configured": bool(get_settings().generation_execution_epoch),
        "emergency_paused": get_settings().generation_emergency_pause}


@router.get("/leagues")
async def leagues(db: DB, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    rows = (await db.scalars(select(LeagueSeries).order_by(LeagueSeries.created_at, LeagueSeries.id)
        .offset(offset).limit(limit + 1))).all()
    result = []
    for row in rows[:limit]:
        seasons = (await db.scalars(select(LeagueSeason).where(LeagueSeason.series_id == row.id)
            .order_by(LeagueSeason.season.desc()))).all()
        members = await db.scalar(select(func.count()).select_from(LeagueMembership).where(
            LeagueMembership.league_id.in_([s.league_id for s in seasons])))
        result.append({**data(row), "seasons": [data(s) for s in seasons], "members": members,
            "effective": await resolve_policy(db, row.id)})
    return {"records": result, "next_offset": offset + limit if len(rows) > limit else None}


@router.get("/policy/{scope}")
async def get_policy(scope: str, db: DB):
    return await execute(commands.policy_view(db, scope))


@router.put("/policy/{scope}")
async def policy(scope: str, body: PolicyChange, db: DB, owner: Owner):
    return await execute(commands.update_policy(db, scope, body.value, body.expected_revision, owner.id, body.reason))


@router.post("/control")
async def control(body: ControlChange, db: DB, owner: Owner):
    return await execute(commands.control_action(db, body, owner.id))


@router.put("/leagues/{series_id}")
async def series(series_id: str, body: SeriesChange, db: DB, owner: Owner):
    row = await execute(set_series(db, series_id, expected_revision=body.expected_revision,
        lifecycle=body.lifecycle, profile=body.profile, actor=owner.id, reason=body.reason, activate=body.activate))
    return data(row)


@router.get("/records/{kind}")
async def records(kind: Literal["jobs", "attempts", "candidates", "artifacts", "audit", "outbox"],
                  db: DB, owner: Owner, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                  series_id: str = "", state: str = "", view: Literal["all", "review"] = "all",
                  feature: Literal["", "trade_story", "gm_rating_blurb", "franchise_blurb", "analyst", "recap_video"] = ""):
    model = {"jobs": GenerationOperation, "attempts": ProviderAttempt, "candidates": GenerationCandidate,
        "artifacts": ContentArtifact, "audit": GenerationAudit, "outbox": GenerationOutbox}[kind]
    query = select(model)
    if feature:
        if kind not in ("jobs", "candidates", "artifacts"):
            raise HTTPException(422, "Content filtering is available for jobs, candidates, and saved content only")
        query = query.where(model.feature == feature)
    if series_id and hasattr(model, "series_id"):
        query = query.where(model.series_id == series_id)
    if state and hasattr(model, "state"):
        query = query.where(model.state == state)
    order = model.observed_at if kind == "candidates" else model.created_at
    key = model.key if kind == "candidates" else model.id
    query = query.order_by(order.desc(), key)
    statuses = {}
    if kind == "candidates" and view == "review":
        # Filtering after pagination would produce empty first pages and make
        # Select all miss actionable records behind completed/automatic work.
        # Scan bounded batches: saved candidate facts can be large, and review
        # pages need only the requested slice plus one record for the next link.
        rows, raw_offset, matched = [], 0, 0
        while len(rows) <= limit:
            candidates = (await db.scalars(query.offset(raw_offset).limit(100))).all()
            batch_status = await classify_candidates(db, candidates, actor_id=owner.id)
            for row in candidates:
                if not batch_status[row.key]["reviewable"]:
                    continue
                if matched >= offset:
                    rows.append(row)
                    statuses[row.key] = batch_status[row.key]
                matched += 1
                if len(rows) > limit:
                    break
            if len(candidates) < 100:
                break
            raw_offset += 100
    else:
        rows = (await db.scalars(query.offset(offset).limit(limit + 1))).all()
        if kind == "candidates":
            statuses = await classify_candidates(db, rows[:limit], actor_id=owner.id)
    safe = []
    for row in rows[:limit]:
        item = data(row)
        if kind in ("candidates", "jobs"):
            item["label"] = commands.candidate_label(row)
        if kind == "candidates":
            item.update(statuses[row.key])
        for name in ("payload_json", "facts_json", "request_json", "receipt_json", "policy_json"):
            if name in item:
                item["has_" + name.removesuffix("_json")] = bool(item.pop(name))
        safe.append(item)
    if kind in ("jobs", "candidates"):
        await attach_league_names(db, safe)
    return {"records": safe, "next_offset": offset + limit if len(rows) > limit else None}


@router.get("/jobs/{job_id}")
async def job_detail(job_id: str, db: DB):
    row = await db.get(GenerationOperation, job_id)
    if not row:
        raise HTTPException(404, "Job not found")
    attempts = (await db.scalars(select(ProviderAttempt).where(
        ProviderAttempt.operation_id == job_id).order_by(ProviderAttempt.stage))).all()
    job = data(row)
    await attach_league_names(db, [job])
    return {"job": job, "attempts": [data(a) for a in attempts]}


@router.post("/jobs/{job_id}")
async def job(job_id: str, body: JobAction, db: DB, owner: Owner):
    return await execute(commands.job_action(db, job_id, body, owner.id))


@router.post("/jobs/batch/preview")
async def batch_job_preview(body: BatchJobs, db: DB, owner: Owner):
    from app.services.generation.bulk_jobs import preview_jobs
    return await execute(preview_jobs(db, body.job_ids, body.action, owner.id, body.reason))


@router.post("/jobs/batch/apply")
async def batch_job_apply(body: Apply, db: DB, owner: Owner):
    from app.services.generation.bulk_jobs import apply_jobs
    return await execute(apply_jobs(db, body.preview_id, body.digest, owner.id, body.reason))


@router.post("/attempts/{attempt_id}/resolve")
async def attempt(attempt_id: str, body: AttemptAction, db: DB, owner: Owner):
    return await execute(commands.resolve_attempt(db, attempt_id, body, owner.id))


@router.post("/campaigns/preview")
async def preview(body: Preview, db: DB, owner: Owner):
    return await execute(commands.preview(db, body.candidates, owner.id, body.reason))


@router.post("/campaigns/catch-up/preview")
async def catchup_preview(body: CatchUp, db: DB, owner: Owner):
    from app.services.generation.catchup import preview_catchup
    return await execute(preview_catchup(db, owner.id, body.reason, body.series_id))


@router.post("/outbox/{ident}/retry")
async def retry_projection(ident: str, body: ProjectionRetry, db: DB, owner: Owner):
    return await execute(commands.retry_projection(db, ident, body, owner.id))


@router.post("/artifacts/{ident}/correction")
async def correction(ident: str, body: Correction, db: DB, owner: Owner):
    return await execute(commands.propose_correction(db, ident, body, owner.id))


@router.post("/campaigns/apply")
async def apply(body: Apply, db: DB, owner: Owner):
    return await execute(commands.apply_campaign(db, body.preview_id, body.digest, owner.id, body.reason))


class ProviderReset(Reason):
    provider: Literal["anthropic", "elevenlabs"]
    account_key: str = Field(min_length=1, max_length=64, pattern="^[A-Za-z0-9_-]+$")
    expected_revision: int = Field(ge=1)


@router.post("/provider/reset")
async def reset_provider(body: ProviderReset, db: DB, owner: Owner):
    from app.services.generation.provider_control import reset_provider as reset
    return await execute(reset(db, body.provider, body.account_key, body.expected_revision, owner.id, body.reason))
