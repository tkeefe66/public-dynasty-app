"""CAS leases and durable alert fingerprints; no provider or recovery calls."""
import json
from datetime import datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.services.generation.store import digest, dump
from app.services.recap_monitor.models import RecapMonitorAlert, RecapMonitorState

ZONE = ZoneInfo('America/Denver')
MONITOR = 'weekly-recaps'


def next_monday(now):
    local = datetime.fromtimestamp(now, ZONE)
    day = local.date() + timedelta(days=(0 - local.weekday()) % 7)
    due = datetime.combine(day, time(22, 30), ZONE)
    if due.timestamp() <= now:
        due = datetime.combine(day + timedelta(days=7), time(22, 30), ZONE)
    return int(due.timestamp())


def next_check(now, observations):
    due = [next_monday(now)]
    for item in observations:
        if item['status'] == 'inactive':
            continue
        # Publication can be withdrawn after completion. Recheck it hourly;
        # a stale generation gate must not defer that verification.
        gate = 0 if item['status'] == 'complete' else item.get('gate', 0)
        due.append(gate + 60 if gate > now else now + 3600)
    return min(due)


async def initialize(maker, scope, start_at):
    # Explicit setup, never an implicit reset of missing/restored monitor state.
    async with maker.begin() as db:
        row = await db.get(RecapMonitorState, MONITOR)
        if row:
            if row.scope_digest != scope:
                raise ValueError('monitor_scope_changed: review existing state before cutover')
            return
        db.add(RecapMonitorState(id=MONITOR, scope_digest=scope, next_check_at=start_at))


async def claim(maker, scope, now):
    token = str(uuid4())
    async with maker.begin() as db:
        result = await db.execute(update(RecapMonitorState).where(
            RecapMonitorState.id == MONITOR, RecapMonitorState.scope_digest == scope,
            RecapMonitorState.next_check_at <= now, RecapMonitorState.lease_until <= now,
        ).values(lease_token=token,
                 lease_until=now + 300,
                 next_check_at=now + 3600, last_started_at=now))
        return token if result.rowcount == 1 else None


async def finish(maker, scope, token, now, observations, recipient):
    async with maker.begin() as db:
        row = await db.scalar(select(RecapMonitorState).where(
            RecapMonitorState.id == MONITOR).with_for_update())
        if not row or row.scope_digest != scope or row.lease_token != token or row.lease_until <= now:
            return False
        previous = json.loads(row.state_json).get('observations', {})
        keys = {item['key'] for item in observations}
        # Source outages cannot erase tracked publications or their already-used
        # recovery attempts. Completion is a current observation, not retirement.
        observations = [*observations, *(item for key, item in previous.items()
            if key not in keys and item.get('period') and item.get('status') != 'inactive')]
        current, active = {}, set()
        for value in observations:
            old = previous.get(value['key'], {})
            item = {**old, **value}
            item['recovery_attempts'] = max(item.get('recovery_attempts', 0), old.get('recovery_attempts', 0))
            same = item.get('progress') == old.get('progress') and item['status'] == old.get('status')
            count = old.get('unchanged', 0) + 1 if same and now - old.get('checked_at', now) >= 3500 else 0
            item.update(unchanged=count, checked_at=now)
            if item['status'] == 'pending' and count >= 2:
                video_stalled = item.get('proof') and item.get('video', {}).get('enabled')
                item.update(status='help', reason='enabled_video_stalled' if video_stalled else 'eligible_recap_stalled',
                            action='Review saved video preparation and publication in Admin; no additional AI calls are authorized'
                            if video_stalled else 'Investigate saved work; no additional AI calls are authorized')
            # Retain pending's original status for consecutive comparisons.
            current[item['key']] = {**item, 'status': value['status']}
            if item['status'] != 'help':
                continue
            ident = digest([scope, item['key'], item.get('reason'), item.get('action')])
            active.add(ident)
            existing = await db.get(RecapMonitorAlert, ident)
            if not existing:
                db.add(RecapMonitorAlert(id=ident, scope_digest=scope,
                    recipient_digest=recipient, payload_json=dump(item), next_attempt_at=now))
            elif existing.state == 'cancelled' and not existing.first_attempt_at:
                existing.state, existing.payload_json, existing.next_attempt_at = 'pending', dump(item), now
        # Resolved ambiguous sends are quarantined; never replay stale help.
        for alert in (await db.scalars(select(RecapMonitorAlert).where(
                RecapMonitorAlert.scope_digest == scope, RecapMonitorAlert.state.in_(('pending', 'sending'))))).all():
            if alert.id not in active:
                alert.state = 'quarantined' if alert.first_attempt_at else 'cancelled'
                alert.error = 'blocker_resolved' if alert.first_attempt_at else ''
        row.state_json = dump({'observations': current})
        row.next_check_at = next_check(now, observations)
        row.last_finished_at, row.lease_until, row.lease_token = now, 0, ''
        return True
