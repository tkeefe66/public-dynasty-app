"""Durable, free-only collection retries; no sleeping worker or new authorization."""
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.services.generation.commands import FREE_REFRESH_KINDS
from app.services.generation.models import ProviderAttempt, stamp
from app.services.generation.store import audit, dump
from sleeper_dynasty.api.yahoo import YahooRateLimitError

log = logging.getLogger(__name__)


def throttle_error(exc):
    """Discovery/OAuth preserve the typed cause while returning HTTP errors to UI."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, YahooRateLimitError):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__
    return None


async def defer_refresh(db, job, error):
    # Corrupt/misclassified paid jobs must never acquire automatic retry rights.
    if job.kind not in FREE_REFRESH_KINDS or job.calls or job.max_calls:
        return False
    if await db.scalar(select(ProviderAttempt.id).where(
            ProviderAttempt.operation_id == job.id).limit(1)):
        return False
    now = stamp()
    job.retry_count += 1
    delay = max(min(900 * 2 ** min(job.retry_count - 1, 5), 21600), error.retry_after)
    job.next_attempt_at = now + delay
    job.state, job.reason = "queued", "yahoo_rate_limited"
    job.worker_id, job.lease_until = "", 0
    job.updated_at = now
    retry_time = datetime.fromtimestamp(job.next_attempt_at, UTC).strftime("%H:%M UTC")
    job.progress_json = dump({"stage": "cooldown", "retry_at": job.next_attempt_at,
        "message": f"Yahoo rate limit. Saved progress is safe; sync resumes automatically after {retry_time}."})
    audit(db, job.actor_id, "refresh_deferred", job.id, "yahoo_rate_limited",
          after={"next_attempt_at": job.next_attempt_at, "retry_count": job.retry_count})
    log.warning("Yahoo refresh deferred operation=%s retry=%s next_attempt_at=%s",
                job.id, job.retry_count, job.next_attempt_at)
    return True
