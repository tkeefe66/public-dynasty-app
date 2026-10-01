"""Offline restore gate. Restored execution never inherits permission to spend."""
from sqlalchemy import delete, func, select

from app.db.base import Base
from app.services.generation.models import (
    GenerationControl,
    GenerationOperation,
    ProviderAttempt,
)
from app.services.generation.store import audit, lock_control


def bootstrap_control(row):
    return (row.id == "global" and row.epoch == "" and row.hold == "activation_required"
        and row.revision == 1 and not row.provider_hold and not row.cooldown_until
        and row.breakers_json == "{}")


async def quarantine(db):
    control = await lock_control(db)
    control.hold = "restore_quarantine"
    control.revision += 1
    jobs = (await db.scalars(select(GenerationOperation).where(
        GenerationOperation.state.in_(("queued", "running", "held", "needs_attention"))))).all()
    for job in jobs:
        job.generation += 1
        job.lease_until = 0
        job.state, job.reason = "held", "restore_reapproval_required"
    for attempt in (await db.scalars(select(ProviderAttempt).where(
            ProviderAttempt.state == "dispatching"))).all():
        attempt.state = "unknown"
    audit(db, "restore", "restore_quarantined", "global",
        "Restore cannot prove which post-snapshot requests executed; rotate epoch and reconcile before activation",
        after={"old_epoch": control.epoch, "held_jobs": len(jobs)})


async def restore_database(db, blob):
    """Accept only an empty migrated DB (including its pristine bootstrap row)."""
    from app.services.backup_service import load_database
    for table in Base.metadata.sorted_tables:
        count = await db.scalar(select(func.count()).select_from(table))
        if not count:
            continue
        row = await db.get(GenerationControl, "global") if table.name == "generation_control" else None
        if count != 1 or not row or not bootstrap_control(row):
            raise ValueError(f"Restore target is not empty: {table.name}")
        await db.execute(delete(GenerationControl))
    counts = await load_database(db, blob)
    await quarantine(db)
    return counts
