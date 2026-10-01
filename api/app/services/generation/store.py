"""Transactional generation state. The global row serializes short mutations."""
from __future__ import annotations

import hashlib
import json
import logging
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.services.generation.models import (
    GenerationAudit,
    GenerationControl,
    GenerationPolicy,
    LeagueSeries,
)
from app.services.generation.policy import effective

log = logging.getLogger(__name__)


class Conflict(ValueError):
    pass


class OwnershipLost(Conflict):
    pass


class Held(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def dump(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(dump(value).encode()).hexdigest()


def data(row) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


async def lock_control(db) -> GenerationControl:
    """Bootstrap only on mutation. PostgreSQL lock covers all admission gates."""
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    await db.execute(insert(GenerationControl).values(id="global").on_conflict_do_nothing())
    return await db.scalar(select(GenerationControl).where(
        GenerationControl.id == "global").with_for_update().execution_options(populate_existing=True))


def audit(db, actor: str, action: str, target: str, reason: str,
          before: dict | None = None, after: dict | None = None):
    if not reason.strip():
        raise ValueError("An audit reason is required")
    db.add(GenerationAudit(actor_id=actor, action=action, target=target,
                           reason=reason, before_json=dump(before or {}),
                           after_json=dump(after or {})))
    log.info("generation transition action=%s target=%s actor=%s", action, target, actor)


async def resolve_policy(db, series_id: str = "", *, profile: str = "") -> dict:
    scopes = ["app"]
    series = await db.get(LeagueSeries, series_id) if series_id else None
    profile = series.profile if series else profile
    if profile:
        scopes.append("profile:" + profile)
    if series:
        scopes.append("series:" + series.id)
    rows = {r.scope: r for r in (await db.scalars(select(GenerationPolicy).where(
        GenerationPolicy.scope.in_(scopes)))).all()}
    layers = [(scope, json.loads(rows[scope].value_json)) for scope in scopes if scope in rows]
    # Absent app configuration cannot be implicitly activated by an override.
    if "app" not in rows:
        layers.insert(0, ("app", {"paused": True}))
    result = effective(layers)
    result["revisions"] = {scope: rows[scope].revision if scope in rows else 0 for scope in scopes}
    control = await db.get(GenerationControl, "global")
    result["control_revision"] = control.revision if control else 0
    result["epoch"] = control.epoch if control else ""
    if not control or control.hold:
        result["blocked_by"].append(control.hold if control else "activation_required")
    if control and control.provider_hold:
        result["blocked_by"].append(control.provider_hold)
    if series:
        if series.lifecycle != "active":
            result["blocked_by"].append("series_" + series.lifecycle)
        if series.hold:
            result["blocked_by"].append(series.hold)
    result["blocked_by"] = list(dict.fromkeys(result["blocked_by"]))
    return result


async def save_policy(db, scope: str, value: dict, expected_revision: int,
                      actor: str, reason: str) -> GenerationPolicy:
    await lock_control(db)
    if (scope not in ("app", "profile:dynasty", "profile:keeper", "profile:redraft")
            and (not scope.startswith("series:") or not await db.get(LeagueSeries, scope[7:]))):
        raise ValueError("Unknown policy scope")
    # Validate partial documents after overlaying registered defaults.
    effective([("validation", value)])
    row = await db.get(GenerationPolicy, scope)
    previous_revision = row.revision if row else 0
    if previous_revision != expected_revision:
        raise Conflict("Settings changed. Reload and preview the new values.")
    before = json.loads(row.value_json) if row else {}
    if row is None:
        row = GenerationPolicy(scope=scope, revision=1, value_json=dump(value))
        db.add(row)
    else:
        row.revision += 1
        row.value_json = dump(value)
    audit(db, actor, "policy_saved", scope, reason,
          {"revision": previous_revision, "value": before},
          {"revision": row.revision, "value": value})
    await db.flush()
    return row


@asynccontextmanager
async def transaction(maker):
    async with maker() as db, db.begin():
        yield db
