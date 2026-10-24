"""Railway API task; minute wake-ups consult persisted due time before source I/O."""
import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select, update

from app.services.generation.models import GenerationControl
from app.services.generation.store import digest, dump
from app.services.recap_monitor.collect import collect, owner
from app.services.recap_monitor.mail import deliver, resend
from app.services.recap_monitor.models import RecapMonitorAlert, RecapMonitorState
from app.services.recap_monitor.recovery import recover
from app.services.recap_monitor.state import MONITOR, claim, finish

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    owner_id: str
    series_ids: tuple[str, ...]
    first_season: int
    first_week: int
    start_at: int

    @property
    def scope(self):
        return digest(asdict(self))

    @classmethod
    def load(cls):
        try:
            raw = json.loads(os.environ['TRADE_GRADER_RECAP_MONITOR_CONFIG'])
            start = datetime.fromisoformat(raw['start_at'])
            ids = tuple(sorted(raw['series_ids']))
            if (not raw['owner_id'] or not ids or len(ids) != len(set(ids))
                    or any(not isinstance(i, str) or not i for i in ids)
                    or type(raw['first_season']) is not int or raw['first_season'] < 2026
                    or type(raw['first_week']) is not int or raw['first_week'] not in range(1, 19)
                    or start.tzinfo is None):
                raise ValueError
            return cls(raw['owner_id'], ids, raw['first_season'], raw['first_week'], int(start.timestamp()))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('monitor_configuration_invalid: explicit owner, series, first edition and zoned start required') from exc


async def recovery_step(config, maker, token, item, now):
    async with maker.begin() as db:
        row = await db.scalar(select(RecapMonitorState).where(RecapMonitorState.id == MONITOR).with_for_update())
        if row.scope_digest != config.scope or row.lease_token != token or row.lease_until <= int(time.time()):
            return {**item, 'status': 'pending'}
        saved = json.loads(row.state_json)
        observations = saved.setdefault('observations', {})
        old = observations.get(item['key'], {})
        item['recovery_attempts'] = max(item.get('recovery_attempts', 0), old.get('recovery_attempts', 0))
        result = await recover(db, item, config.owner_id, now)
        observations[item['key']] = {**old, **result}
        row.state_json = dump(saved)
        return result


async def tick(config, maker, cache_dir, *, now=None, collect=collect, send=deliver):
    now = int(time.time()) if now is None else now
    async with maker.begin() as db:
        control = await db.get(GenerationControl, 'global')
        if control and control.hold in ('restore_quarantine', 'restore_reconciled'):
            raise ValueError('monitor_restore_review_required')
        beat = await db.execute(update(RecapMonitorState).where(
            RecapMonitorState.id == MONITOR, RecapMonitorState.scope_digest == config.scope
        ).values(heartbeat_at=now))
        if beat.rowcount != 1:
            raise ValueError('monitor_setup_required: initialize scope-bound durable state first')
    token = await claim(maker, config.scope, now)
    if token:
        async with maker() as db:
            row = await db.get(RecapMonitorState, MONITOR)
            previous = json.loads(row.state_json).get('observations', {})
        try:
            async with asyncio.timeout(240):
                items = await collect(config, maker, cache_dir, now, previous)
                for index, item in enumerate(items):
                    if item.get('recoverable') and item['status'] == 'pending':
                        items[index] = await recovery_step(config, maker, token, item, now)
                recipient = await owner(maker, config)
                await finish(maker, config.scope, token, int(time.time()), items, digest(recipient.email.lower()))
                log.info('Recap monitor cycle completed observations=%s', len(items))
        except Exception as exc:
            log.warning('Recap monitor cycle failed type=%s; durable next check retained', type(exc).__name__)
            # A monitor-wide source failure follows the same two-check escalation.
            try:
                recipient = await owner(maker, config)
                await finish(maker, config.scope, token, int(time.time()), [dict(
                    key='monitor-source', status='pending', progress=type(exc).__name__,
                    reason='monitor_source_unavailable', action='Investigate monitor source access and Railway logs')],
                    digest(recipient.email.lower()))
            except Exception:
                log.error('Recap monitor could not persist failure; inspect Railway API logs')
    async with maker() as db:
        pending = await db.scalar(select(RecapMonitorAlert.id).where(
            RecapMonitorAlert.scope_digest == config.scope,
            RecapMonitorAlert.state.in_(('pending', 'sending')),
            RecapMonitorAlert.next_attempt_at <= now).limit(1))
    if pending:
        recipient = await owner(maker, config)
        key, sender = os.getenv('RESEND_API_KEY', ''), os.getenv('RECAP_MONITOR_FROM_EMAIL', '')
        if not key or not sender or '\n' in sender or '\r' in sender:
            raise ValueError('monitor_email_configuration_missing')
        async def transport(ident, payload):
            return await resend(ident, payload, key)
        await send(maker, config.scope, digest(recipient.email.lower()), recipient.email, sender, transport, now)


async def monitor_loop(cache_dir):
    from app.db.engine import get_sessionmaker
    while True:
        try:
            await tick(Config.load(), get_sessionmaker(), cache_dir)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error('Recap monitor task failed type=%s; next wake in 60 seconds', type(exc).__name__)
        await asyncio.sleep(60)
