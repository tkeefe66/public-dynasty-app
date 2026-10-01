"""Known usage and explicit uncertainty for all administrative cost surfaces."""
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.services.generation.models import GenerationOperation, ProviderAttempt


async def ledger_records(db):
    rows = (await db.execute(select(ProviderAttempt, GenerationOperation).join(
        GenerationOperation, GenerationOperation.id == ProviderAttempt.operation_id).where(
            ProviderAttempt.cost_microusd.is_not(None), ProviderAttempt.state != "not_sent"
        ).order_by(ProviderAttempt.created_at))).all()
    return [{"ts": datetime.fromtimestamp(a.created_at, UTC).isoformat(), "model": a.model,
        "writer": job.feature, "league_id": job.league_id, "cost_usd": a.cost_microusd / 1_000_000,
        "attempt_id": a.id} for a, job in rows]


async def unknown_count(db, cutoff=None):
    query = select(func.count()).select_from(ProviderAttempt).where(ProviderAttempt.cost_microusd.is_(None))
    if cutoff:
        query = query.where(ProviderAttempt.created_at >= int(cutoff.timestamp()))
    return await db.scalar(query)


async def month_known(db):
    start = int(datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    return (await db.scalar(select(func.coalesce(func.sum(ProviderAttempt.cost_microusd), 0))
        .where(ProviderAttempt.created_at >= start))) / 1_000_000
