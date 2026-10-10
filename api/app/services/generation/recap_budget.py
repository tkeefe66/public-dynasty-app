"""Atomic budget obligations. All writers lock control, policy, then allocations.

ProviderAttempt remains the receipt of record. Linked allocations replace its
contribution in totals, never add a second charge. Unknown exposure survives
worker cancellation and carries into every later admission window.
"""
import json
import time
from datetime import UTC, datetime
from decimal import Decimal, ROUND_CEILING
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import select

from app.repositories.app_settings import get_monthly_budget
from app.services.generation.models import GenerationOperation, LeagueSeries, ProviderAttempt
from app.services.generation.policy import StrictModel
from app.services.generation.recap_models import RecapBudgetAllocation, RecapBudgetPlan, RecapBudgetPolicy
from app.services.generation.store import Conflict, Held, audit, digest, dump, lock_control

SAFE_INTEGER = 9_007_199_254_740_991


class RecapCaps(StrictModel):
    video_episode_microusd: int = Field(default=3_000_000, gt=0, le=SAFE_INTEGER)
    video_month_microusd: int = Field(default=15_000_000, gt=0, le=SAFE_INTEGER)
    combined_episode_microusd: int = Field(default=5_000_000, gt=0, le=SAFE_INTEGER)
    combined_month_microusd: int = Field(default=25_000_000, gt=0, le=SAFE_INTEGER)


class UnknownSeries(ValueError):
    pass


class InvalidBudgetRequest(ValueError):
    """Only client input errors map to 422; persisted corruption remains a 500."""


class Overcommitted(Conflict):
    def __init__(self, caps, affected):
        message = "Limits are below committed obligations; acknowledge_overcommitted is required"
        super().__init__(message)
        self.detail = dict(code="recap_budget_overcommitted", message=message,
            acknowledgment_required=True, proposed_caps=caps, affected=affected)


def remaining_microusd(cap: int, known: int, reserved: int) -> int:
    return max(0, cap - known - reserved)


def month_key(now: int, zone=ZoneInfo("America/Denver")) -> str:
    return datetime.fromtimestamp(now, zone).strftime("%Y-%m")


def episode_identity(series_id: str, season: int, period_id: str) -> str:
    return digest([series_id, season, period_id])


def operation_episode(job) -> str:
    """Actual collect_analyst envelope: season/week plus the source edition."""
    payload = json.loads(job.payload_json)
    season, week = payload.get("season"), payload.get("week")
    if type(season) is not int or type(week) is not int or season < 1 or week < 1:
        raise Held("recap_episode_identity_unknown")
    edition = payload.get("edition", {})
    if edition.get("season", season) != season or edition.get("week", week) != week:
        raise Held("recap_episode_identity_conflict")
    return episode_identity(job.series_id, season, str(week))


async def _policy_lock(db, series_id):
    # Global lock serializes bootstrap too: no select/insert race for absent policies.
    return await db.scalar(select(RecapBudgetPolicy).where(
        RecapBudgetPolicy.series_id == series_id).with_for_update()
        .execution_options(populate_existing=True))


def _caps(row):
    return RecapCaps.model_validate(json.loads(row.caps_json)) if row else RecapCaps()


async def _obligations(db):
    from app.services.generation.commands import UNRESOLVED_OUTCOMES
    attempts = (await db.execute(select(ProviderAttempt, GenerationOperation).outerjoin(
        GenerationOperation, GenerationOperation.id == ProviderAttempt.operation_id))).all()
    attempts_by_id = {attempt.id: attempt for attempt, _ in attempts}

    def unresolved_outcome(attempt):
        return (attempt.state in UNRESOLVED_OUTCOMES or
                (attempt.state == "received" and attempt.error_code == "response_invalid"))

    rows = (await db.execute(select(RecapBudgetAllocation, RecapBudgetPlan).join(
        RecapBudgetPlan, RecapBudgetPlan.id == RecapBudgetAllocation.plan_id))).all()
    bound = set()
    result = []
    for a, plan in rows:
        if a.attempt_id:
            bound.add(a.attempt_id)
        result.append(dict(series=plan.series_id, episode=plan.episode_id, category=a.category,
            month=a.month_key, app_month=month_key(a.created_at, UTC),
            known=a.actual_microusd or 0, reserved=a.outstanding_microusd,
            unknown=a.actual_microusd is None and (a.attempt_id is not None or a.state in ("unknown", "unbounded")),
            outcome_unknown=bool(a.attempt_id and (a.attempt_id not in attempts_by_id or
                unresolved_outcome(attempts_by_id[a.attempt_id]))),
            unbounded=a.state == "unbounded",
            attempt_id=a.attempt_id, state=a.state))
    # Existing immutable receipts are visible before backfill, including cancelled jobs.
    from app.services.generation.accounting import request_ceiling
    for a, job in attempts:
        if a.id in bound:
            continue
        category = "written" if job and job.feature == "analyst" else "managed"
        episode = None
        if category == "written":
            try:
                episode = operation_episode(job)
            except (Held, ValueError, TypeError):
                pass
        known = a.cost_microusd
        exposure = 0
        unbounded = False
        if known is None and a.state != "not_sent":
            try:
                exposure = request_ceiling(json.loads(a.request_json), json.loads(a.pricing_json))
            except (Held, ValueError, TypeError, KeyError):
                unbounded = True
        result.append(dict(series=job.series_id if job else None, episode=episode,
            category=category, month=month_key(a.created_at), app_month=month_key(a.created_at, UTC),
            known=known or 0, reserved=exposure, unknown=known is None and a.state != "not_sent",
            outcome_unknown=unresolved_outcome(a),
            unbounded=unbounded, attempt_id=a.id, state="historical_unknown" if known is None else "settled"))
    return result


def _balance(rows, cap, current_month=None, *, app=False):
    key = "app_month" if app else "month"
    current = [r for r in rows if current_month is None or r[key] == current_month]
    carry = sum(r["reserved"] for r in rows if current_month is not None and r[key] < current_month)
    known = sum(r["known"] for r in current)
    reserved = sum(r["reserved"] for r in current)
    unknown = sum(r["unknown"] for r in rows)
    unbounded = sum(r["unbounded"] for r in rows)
    # Informational subset of reserved + carry-forward; never subtract it again.
    uncertain = sum(r["reserved"] for r in rows if r["unknown"] and
                    (current_month is None or r[key] <= current_month))
    return dict(known_microusd=known, reserved_microusd=reserved,
        carry_forward_microusd=carry, uncertain_microusd=uncertain,
        unknown_count=unknown, unbounded_unknown_count=unbounded,
        remaining_microusd=None if unbounded or cap is None else remaining_microusd(cap, known, reserved + carry),
        overcommitted=cap is not None and known + reserved + carry > cap)


def _balances(rows, series_id, episode_id, caps, now):
    relevant = [r for r in rows if r["series"] == series_id and r["category"] in ("video", "written")]
    result = {}
    for key, cap in caps.model_dump().items():
        subset = [r for r in relevant if not key.startswith("video") or r["category"] == "video"]
        if "episode" in key:
            result[key] = (_balance([r for r in subset if r["episode"] == episode_id], cap)
                           if episode_id else None)
        else:
            result[key] = _balance(subset, cap, month_key(now))
    return result


async def _app_balance(db, rows, now):
    from app.config import get_settings
    from sleeper_dynasty.llm.cost_store import LlmCostStore
    value = Decimal(str(await get_monthly_budget(db)))
    cap = int((value * 1_000_000).to_integral_value(rounding=ROUND_CEILING)) if value > 0 else None
    # Legacy JSONL stores pre-controller charges; managed telemetry never appends it.
    legacy = int((sum((Decimal(str(r.get("cost_usd", 0) or 0))
        for r in LlmCostStore(get_settings().cache_dir).read_all()
        if str(r.get("ts", ""))[:7] == month_key(now, UTC)), Decimal(0)) * 1_000_000)
        .to_integral_value(rounding=ROUND_CEILING))
    balance = _balance(rows, cap, month_key(now, UTC), app=True)
    balance["known_microusd"] += legacy
    if cap is not None:
        committed = balance["known_microusd"] + balance["reserved_microusd"] + balance["carry_forward_microusd"]
        balance["remaining_microusd"] = None if balance["unbounded_unknown_count"] else max(0, cap - committed)
        balance["overcommitted"] = committed > cap
    return {"month_microusd": cap, "balance": balance}


async def get_budget_view(db, series_id: str, episode_id: str | None, now: int) -> dict:
    if not await db.get(LeagueSeries, series_id):
        raise UnknownSeries("League series not found")
    row = await db.get(RecapBudgetPolicy, series_id)
    caps = _caps(row)
    rows = await _obligations(db)
    uncertain = any(r["series"] == series_id and r["category"] != "managed" and
                    (r["unbounded"] or r["episode"] is None) for r in rows)
    return {"series_id": series_id, "revision": row.revision if row else 0,
        "caps": caps.model_dump(), "episode_id": episode_id,
        "month_key": month_key(now),
        "balances": _balances(rows, series_id, episode_id, caps, now),
        "app_limit": await _app_balance(db, rows, now),
        "media_automation_enabled": False,
        "enforcement_state": {"active": True, "reason": "historical_accounting_attention" if uncertain else ""}}


async def save_caps(db, series_id: str, caps: RecapCaps, expected_revision: int,
                    actor_id: str, reason: str, acknowledge_overcommitted: bool) -> dict:
    if not reason.strip():
        raise InvalidBudgetRequest("An audit reason is required")
    if not await db.get(LeagueSeries, series_id):
        raise UnknownSeries("League series not found")
    await lock_control(db)
    row = await _policy_lock(db, series_id)
    revision = row.revision if row else 0
    if revision != expected_revision:
        raise Conflict("Recap limits changed. Reload the saved values before saving.")
    before = {"revision": revision, "caps": json.loads(row.caps_json) if row else RecapCaps().model_dump()}
    now = int(time.time())
    obligations = await _obligations(db)
    episodes = {r["episode"] for r in obligations if r["series"] == series_id}
    affected = []
    for episode in sorted(episodes - {None}) + [None]:
        for scope, balance in _balances(obligations, series_id, episode, caps, now).items():
            if balance and balance["overcommitted"] and (("episode" in scope) == (episode is not None)):
                affected.append(dict(scope=scope, episode_id=episode, **balance))
    if affected and not acknowledge_overcommitted:
        raise Overcommitted(caps.model_dump(), affected)
    if row is None:
        row = RecapBudgetPolicy(series_id=series_id, revision=1, caps_json=dump(caps.model_dump()), updated_at=now)
        db.add(row)
    else:
        row.revision += 1
        row.caps_json = dump(caps.model_dump())
        row.updated_at = now
    audit(db, actor_id, "recap_caps_saved", series_id, reason, before,
        {"revision": row.revision, "caps": caps.model_dump(),
         "acknowledge_overcommitted": acknowledge_overcommitted})
    await db.flush()
    return await get_budget_view(db, series_id, None, now)


def _check_balances(rows, series_id, episode_id, caps, now):
    if any(r["series"] == series_id and r["category"] != "managed" and
           (r["unbounded"] or r["episode"] is None) for r in rows):
        raise Held("recap_historical_accounting_unknown")
    for key, value in _balances(rows, series_id, episode_id, caps, now).items():
        if value and value["overcommitted"]:
            raise Held("recap_budget_" + key.removesuffix("_microusd"))


async def _check_app(db, rows, now):
    app = await _app_balance(db, rows, now)
    if app["month_microusd"] is not None:
        if app["balance"]["unbounded_unknown_count"]:
            raise Held("legacy_budget_accounting_unknown")
        if app["balance"]["overcommitted"]:
            raise Held("legacy_budget_reached")


async def reserve_plan(db, episode_id: str, series_id: str, plan_key: str,
                       allocations: list[dict], now: int) -> str:
    return await _reserve(db, episode_id, series_id, plan_key, allocations, now)


async def _reserve(db, episode_id, series_id, plan_key, allocations, now, *, managed=False):
    await lock_control(db)
    if not await db.get(LeagueSeries, series_id):
        raise UnknownSeries("League series not found")
    policy = await _policy_lock(db, series_id)
    keys = set()
    for a in allocations:
        if (set(a) != {"key", "category", "max_microusd", "rate_snapshot", "operation_id"}
                or not isinstance(a["key"], str) or not a["key"] or a["key"] in keys
                or a["category"] not in (("managed",) if managed else ("written", "video"))
                or type(a["max_microusd"]) is not int or not 0 < a["max_microusd"] <= SAFE_INTEGER
                or not isinstance(a["rate_snapshot"], dict) or not a["rate_snapshot"]
                or not isinstance(a["operation_id"], str)):
            raise InvalidBudgetRequest("Invalid or duplicate budget allocation")
        keys.add(a["key"])
    if not allocations or not episode_id or not plan_key:
        raise InvalidBudgetRequest("Episode, plan key and allocations are required")
    fingerprint = digest([series_id, sorted(allocations, key=lambda a: a["key"])])
    previous = await db.scalar(select(RecapBudgetPlan).where(
        RecapBudgetPlan.episode_id == episode_id, RecapBudgetPlan.plan_key == plan_key))
    if previous:
        if previous.digest != fingerprint:
            raise Conflict("Budget plan key already binds different allocations")
        return previous.id
    if not managed:
        await backfill_written(db, series_id)
    rows = await _obligations(db)
    if any(r["episode"] == episode_id and (r["unknown"] or r["outcome_unknown"]) for r in rows):
        raise Held("recap_provider_outcome_unknown")
    proposed = rows + [dict(series=series_id, episode=episode_id, category=a["category"],
        known=0, reserved=a["max_microusd"], month=month_key(now), app_month=month_key(now, UTC),
        unknown=False, unbounded=False) for a in allocations]
    if not managed:
        _check_balances(proposed, series_id, episode_id, _caps(policy), now)
    await _check_app(db, proposed, now)
    plan = RecapBudgetPlan(episode_id=episode_id, series_id=series_id, plan_key=plan_key,
        digest=fingerprint, created_at=now)
    db.add(plan)
    await db.flush()
    for a in allocations:
        db.add(RecapBudgetAllocation(plan_id=plan.id, key=a["key"], category=a["category"],
            operation_id=a["operation_id"], max_microusd=a["max_microusd"],
            outstanding_microusd=a["max_microusd"], rate_json=dump(a["rate_snapshot"]),
            month_key=month_key(now), created_at=now))
    await db.flush()
    audit(db, "controller", "budget_reserved", plan.id, "Complete bounded plan reserved",
        after={"episode_id": episode_id, "allocations": allocations})
    return plan.id


async def settle_allocation(db, allocation_id: str, actual_microusd: int | None, evidence: dict) -> None:
    control = await lock_control(db)
    row = await db.get(RecapBudgetAllocation, allocation_id)
    if not row:
        raise InvalidBudgetRequest("Budget allocation not found")
    plan = await db.get(RecapBudgetPlan, row.plan_id)
    await _policy_lock(db, plan.series_id)
    row = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.id == allocation_id)
        .with_for_update().execution_options(populate_existing=True))
    if actual_microusd is not None and (type(actual_microusd) is not int or actual_microusd < 0):
        raise InvalidBudgetRequest("Actual usage must be nonnegative integer microusd or unknown")
    if not evidence:
        raise InvalidBudgetRequest("Settlement evidence is required")
    if row.actual_microusd is not None:
        if row.actual_microusd != actual_microusd:
            raise Conflict("Allocation already settled to different usage")
        return
    row.evidence_json = dump(evidence)
    if actual_microusd is None:
        row.state = "unknown"
    else:
        row.actual_microusd = actual_microusd
        row.outstanding_microusd = 0
        row.state = "settled"
        if actual_microusd > row.max_microusd:
            row.state = "overrun"
            control.provider_hold = "reservation_exceeded"
    audit(db, "accounting", "budget_settled", allocation_id, "Provider evidence reconciled",
        after={"actual_microusd": actual_microusd, "state": row.state, "evidence": evidence})
    await db.flush()


async def release_unsubmitted(db, operation_id: str, reason: str):
    """Cancellation/completion proves only never-bound future calls were not sent."""
    await lock_control(db)
    rows = list((await db.scalars(select(RecapBudgetAllocation).where(
        RecapBudgetAllocation.operation_id == operation_id,
        RecapBudgetAllocation.attempt_id.is_(None), RecapBudgetAllocation.actual_microusd.is_(None)
    ).order_by(RecapBudgetAllocation.id))).all())
    for row in rows:
        await settle_allocation(db, row.id, 0, {"non_submission": reason, "operation_id": operation_id})


async def backfill_written(db, series_id):
    """Bind old receipts by immutable operation/attempt, without altering receipts."""
    await lock_control(db)
    await _policy_lock(db, series_id)
    from app.services.generation.accounting import request_ceiling
    attempts = (await db.execute(select(ProviderAttempt, GenerationOperation).join(
        GenerationOperation, GenerationOperation.id == ProviderAttempt.operation_id).where(
        GenerationOperation.series_id == series_id, GenerationOperation.feature == "analyst")
        .order_by(ProviderAttempt.id))).all()
    for attempt, job in attempts:
        if await db.scalar(select(RecapBudgetAllocation.id).where(RecapBudgetAllocation.attempt_id == attempt.id)):
            continue
        try:
            episode = operation_episode(job)
        except (Held, ValueError, TypeError):
            continue  # Remains explicit unbound history in the view/admission hold.
        actual = attempt.cost_microusd
        maximum, state = actual or 0, "settled"
        if actual is None:
            if attempt.state == "not_sent":
                actual = 0
            else:
                state = "unknown"
                try:
                    maximum = request_ceiling(json.loads(attempt.request_json), json.loads(attempt.pricing_json))
                except (Held, ValueError, TypeError, KeyError):
                    state = "unbounded"
        plan = RecapBudgetPlan(episode_id=episode, series_id=series_id,
            plan_key="historical:" + attempt.id, digest=digest([job.id, attempt.id, attempt.request_digest]),
            created_at=attempt.created_at)
        db.add(plan)
        await db.flush()
        db.add(RecapBudgetAllocation(plan_id=plan.id, key=str(attempt.stage), category="written",
            operation_id=job.id, attempt_id=attempt.id, max_microusd=maximum,
            outstanding_microusd=maximum if actual is None else 0, actual_microusd=actual,
            rate_json=attempt.pricing_json, month_key=month_key(attempt.created_at),
            state=state, created_at=attempt.created_at,
            evidence_json=dump({"historical_attempt": attempt.id, "operation_state": job.state,
                                 "usage_state": attempt.usage_state})))
    await db.flush()


async def admit_provider_allocation(db, job, stage, request, saved, current, now):
    """Called inside the gateway's global lock immediately before durable dispatch."""
    from app.services.generation.accounting import BOUND_VERSION, WRAPPER_TOKEN_ALLOWANCE, bounded_plan, pricing, request_ceiling
    await lock_control(db)
    policy = await _policy_lock(db, job.series_id)
    maximum = request_ceiling(request, pricing(request["model"]))
    recap = job.feature == "analyst"
    episode = operation_episode(job) if recap else "managed:" + job.id
    if recap:
        await backfill_written(db, job.series_id)
    plan_key = "operation:" + job.id if recap else f"operation:{job.id}:stage:{stage}"
    plan = await db.scalar(select(RecapBudgetPlan).where(
        RecapBudgetPlan.episode_id == episode, RecapBudgetPlan.plan_key == plan_key))
    if plan is None:
        if recap:
            allocations = [a for a in bounded_plan(job.id, job.feature, saved, current, job.max_calls)
                           if int(a["key"]) > job.calls]
        else:
            rate = pricing(request["model"])
            rate.update(bound_version=BOUND_VERSION, max_serialized_bytes=len(dump(request)),
                max_output_tokens=request["max_tokens"], wrapper_tokens=WRAPPER_TOKEN_ALLOWANCE)
            allocations = [dict(key=str(stage), category="managed", operation_id=job.id,
                max_microusd=maximum, rate_snapshot=rate)]
        plan_id = await _reserve(db, episode, job.series_id, plan_key, allocations, now, managed=not recap)
    else:
        plan_id = plan.id
    row = await db.scalar(select(RecapBudgetAllocation).where(
        RecapBudgetAllocation.plan_id == plan_id, RecapBudgetAllocation.key == str(stage))
        .with_for_update().execution_options(populate_existing=True))
    if not row or row.attempt_id or row.actual_microusd is not None:
        raise Held("budget_allocation_unavailable")
    snapshot = json.loads(row.rate_json)
    if (len(dump(request)) > snapshot["max_serialized_bytes"]
            or request["max_tokens"] > snapshot["max_output_tokens"]
            or request["model"] != snapshot["model"] or maximum > row.max_microusd):
        raise Held("request_exceeds_reservation")
    obligations = await _obligations(db)
    if recap:
        _check_balances(obligations, job.series_id, episode, _caps(policy), now)
        if any(r["episode"] == episode and (r["unknown"] or r["outcome_unknown"]) for r in obligations):
            raise Held("recap_provider_outcome_unknown")
    await _check_app(db, obligations, now)
    return row


async def settle_attempt(db, attempt, evidence):
    allocation = await db.scalar(select(RecapBudgetAllocation).where(
        RecapBudgetAllocation.attempt_id == attempt.id))
    if allocation:
        await settle_allocation(db, allocation.id, attempt.cost_microusd, evidence)


async def reconcile_allocation(db, allocation_id, actual_microusd, evidence, actor_id, reason):
    """Explicit financial evidence resolves exposure, never invents generated content."""
    if not actor_id or not reason.strip() or not evidence or actual_microusd is None:
        raise InvalidBudgetRequest("Financial reconciliation requires actor, reason, amount and evidence")
    await lock_control(db)
    row = await db.get(RecapBudgetAllocation, allocation_id)
    if row is None:
        raise InvalidBudgetRequest("Budget allocation not found")
    await settle_allocation(db, allocation_id, actual_microusd,
        {"financial_reconciliation": evidence, "actor_id": actor_id, "reason": reason})
    if row.attempt_id:
        attempt = await db.get(ProviderAttempt, row.attempt_id)
        if attempt.cost_microusd is not None and attempt.cost_microusd != actual_microusd:
            raise Conflict("Financial reconciliation contradicts saved provider usage")
        if attempt.cost_microusd is None:
            attempt.cost_microusd = actual_microusd
            attempt.usage_state = "financially_reconciled"
    audit(db, actor_id, "budget_financial_reconciliation", allocation_id, reason,
        after={"actual_microusd": actual_microusd, "evidence": evidence})
    await db.flush()
