"""Bounded waits for complete recap inputs, never paid retry authorization."""
import json
import logging

from sqlalchemy import select

from app.services.generation.models import ProviderAttempt, stamp
from app.services.generation.store import audit, dump

log = logging.getLogger(__name__)
MAX_WAIT = 48 * 3600


class ResultsNotReady(ValueError):
    def __init__(self, week):
        self.week = int(week)
        super().__init__(f"Week {self.week} results are incomplete; waiting for complete provider scores and lineups")


async def defer_results(db, job, error):
    if job.kind != "analyst_refresh" or job.calls or job.max_calls:
        return False
    if await db.scalar(select(ProviderAttempt.id).where(
            ProviderAttempt.operation_id == job.id).limit(1)):
        return False
    now = stamp()
    prior = json.loads(job.progress_json)
    since = prior.get("readiness_since", now) if prior.get("week") == error.week else now
    expired = now - since >= MAX_WAIT
    job.retry_count += 1
    delay = min(900 * 2 ** min(job.retry_count - 1, 4), 6 * 3600)
    job.next_attempt_at = 0 if expired else now + delay
    job.state = "needs_attention" if expired else "queued"
    job.reason = "results_not_ready"
    job.worker_id, job.lease_until, job.updated_at = "", 0, now
    job.progress_json = dump(dict(stage="waiting_for_results", week=error.week,
        readiness_since=since, retry_at=job.next_attempt_at,
        message=str(error) + (". Waiting exceeded 48 hours; inspect provider data." if expired
                             else ". The free import will retry automatically.")))
    audit(db, job.actor_id, "refresh_readiness_wait", job.id, job.reason,
          after=dict(week=error.week, next_attempt_at=job.next_attempt_at, expired=expired))
    log.info("Recap results wait operation=%s week=%s retry_at=%s expired=%s",
             job.id, error.week, job.next_attempt_at, expired)
    return True
