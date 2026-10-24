"""Renew TTL-only Yahoo evidence outside generation's global transaction."""

import logging

from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.db.models import LeagueMembership, User, YahooConnection, YahooLeagueGrant
from app.services.generation.commands import require_actor, require_owner
from app.services.generation.models import (
    GenerationCandidate,
    GenerationOperation,
    ProviderAttempt,
    stamp,
)
from app.services.generation.store import Held, audit, lock_control, resolve_policy
from app.services.generation.yahoo_backoff import throttle_error
from app.services.yahoo_connection import YahooConnectionService
from sleeper_dynasty.api.yahoo import YahooDataError

log = logging.getLogger(__name__)


async def renew_expired_grant(maker, operation_id: str, generation: int, *, stage: int | None = None):
    """Refresh only the saved actor's unchanged grant before a new paid action.

    Call before acquiring generation's global lock. The dispatch/publication
    transaction must still recheck require_actor afterward: renewal cannot grant
    permission across a concurrent disconnect, reconnect, or membership change.
    Existing receipts keep their offline replay path, including invalid or
    unresolved checkpoints whose existing gateway checks must decide the result.
    """
    async with maker() as db:
        job = await require_owner(db, operation_id, generation)
        if ".l." not in job.league_id:
            return
        if stage is not None and await db.scalar(select(ProviderAttempt.id).where(
                ProviderAttempt.operation_id == job.id, ProviderAttempt.stage == stage)):
            return
        await _renew_actor_grant(db, job)


async def _renew_actor_grant(db, job):
    try:
        await require_actor(db, job)
        return
    except Held as exc:
        if exc.code != "provider_grant_changed":
            raise
    # require_actor already checked the saved user's permissions/membership.
    # Distinguish expiration from revocation without relaxing its TTL fence.
    connection = await db.get(YahooConnection, job.actor_id, populate_existing=True)
    grant = await db.get(YahooLeagueGrant, (job.actor_id, job.league_id), populate_existing=True)
    if (not connection or connection.status != "connected" or not grant
            or connection.generation != job.connection_generation
            or grant.generation != connection.generation):
        raise Held("provider_grant_changed")
    if grant.expires_at > stamp():
        return  # A concurrent verification renewed this same connection.
    log.info("Revalidating expired Yahoo grant actor=%s league=%s", job.actor_id, job.league_id)
    await YahooConnectionService(db).ensure_grant(job.actor_id, job.league_id)
    await db.commit()
    log.info("Revalidated Yahoo grant actor=%s league=%s", job.actor_id, job.league_id)


async def renew_automatic_grants(maker, candidates):
    """Bounded free preflight; locked admission must recheck the same principal.

    Until an operation saves its actor, any eligible administrator may own it.
    Cache each connection's result for this pass, including failures, so many
    candidates cannot multiply a throttled Yahoo verification.
    """
    renewed, checked, unavailable = {}, {}, {}
    for candidate, _ in candidates:
        if ".l." not in candidate.league_id:
            continue
        async with maker() as db:
            owners = (await db.scalars(select(User.id).join(
                LeagueMembership, LeagueMembership.user_id == User.id).where(
                    User.is_admin.is_(True), User.email.in_(get_settings().admin_email_list),
                    LeagueMembership.league_id == candidate.league_id))).all()
        failures = []
        for owner_id in owners:
            async with maker() as db:
                connection = await db.get(YahooConnection, owner_id)
                generation = connection.generation if connection else ""
                identity = (owner_id, candidate.league_id, generation)
                account = (owner_id, generation)
                # Verification discovers the whole account. A provider failure
                # must not repeat once for every league belonging to that owner.
                if account in unavailable:
                    checked[identity] = unavailable[account]
                if identity not in checked:
                    principal = GenerationOperation(kind="generation", actor_id=owner_id,
                        league_id=candidate.league_id, connection_generation=generation)
                    try:
                        await _renew_actor_grant(db, principal)
                        db.expire_all()
                        await require_actor(db, principal)
                        checked[identity] = ""
                    except (Held, HTTPException, YahooDataError) as exc:
                        code = ("yahoo_rate_limited" if throttle_error(exc) else
                            exc.code if isinstance(exc, Held) else "provider_grant_changed"
                            if isinstance(exc, HTTPException) and exc.status_code in (401, 403, 409)
                            else "yahoo_authorization_unavailable")
                        checked[identity] = code
                        if code in ("yahoo_rate_limited", "yahoo_authorization_unavailable"):
                            unavailable[account] = code
                        log.warning("Yahoo admission authorization failed actor=%s league=%s reason=%s",
                                    owner_id, candidate.league_id, code)
            if checked[identity]:
                failures.append(checked[identity])
            else:
                renewed[(candidate.key, candidate.digest, owner_id)] = generation
                break
        if failures and len(failures) == len(owners):
            code = "yahoo_rate_limited" if "yahoo_rate_limited" in failures else failures[0]
            async with maker.begin() as db:
                await lock_control(db)
                current = await db.get(GenerationCandidate, candidate.key)
                if (not current or current.digest != candidate.digest
                        or current.event != candidate.event or current.hold):
                    continue
                policy = await resolve_policy(db, current.series_id)
                feature = policy["policy"]["features"][current.feature]
                if policy["blocked_by"] or feature["paused"] or feature["mode"] != "automatic":
                    continue
                current.hold, current.eligible_at = code, 0
                audit(db, "scheduler", "candidate_authorization_held", current.key, code)
    return renewed
