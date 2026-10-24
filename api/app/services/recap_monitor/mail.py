"""Help-only durable delivery. Resend idempotency expires after 24 hours."""
import json
import logging

import httpx
from sqlalchemy import select, update

from app.services.generation.store import digest, dump
from app.services.recap_monitor.models import RecapMonitorAlert

log = logging.getLogger(__name__)
WINDOW = 23 * 3600  # Leave margin before the provider's 24-hour expiration.


def message(item, recipient, sender):
    # Only allowlisted operational summaries; never include raw errors/receipts.
    fields = ('league_name', 'season', 'week', 'reason', 'action', 'job_id',
              'last_progress_at', 'settled_microusd', 'unknown_cost_count',
              'calls_used', 'max_calls', 'remaining_calls', 'recovery_attempts')
    lines = ['The weekly recap monitor needs help.']
    lines.extend(f'{key}: {item[key]}' for key in fields if key in item)
    lines.append('Review: https://dynasty.tomkeefe.ai/admin')
    lines.append('This email grants no new AI calls or spending authority.')
    return {'from': sender, 'to': [recipient],
            'subject': 'Public Dynasty recap monitor needs help', 'text': '\n'.join(lines)}


async def resend(key, payload, api_key):
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.post('https://api.resend.com/emails', json=payload,
            headers={'Authorization': 'Bearer ' + api_key, 'Idempotency-Key': key,
                     'User-Agent': 'public-dynasty-recap-monitor/1.0'})
        response.raise_for_status()
        ident = response.json().get('id')
        if not isinstance(ident, str) or not ident:
            raise ValueError('email_response_invalid')
        return ident


async def deliver(maker, scope, recipient_digest, recipient, sender, transport, now):
    count = 0
    async with maker() as db:
        ids = list((await db.scalars(select(RecapMonitorAlert.id).where(
            RecapMonitorAlert.scope_digest == scope,
            RecapMonitorAlert.state.in_(('pending', 'sending')),
            RecapMonitorAlert.next_attempt_at <= now,
            RecapMonitorAlert.lease_until <= now).limit(10))).all())
    for ident in ids:
        async with maker.begin() as db:
            # Atomic update locks the row before reading across SQLite/Postgres.
            claimed = await db.execute(update(RecapMonitorAlert).where(
                RecapMonitorAlert.id == ident, RecapMonitorAlert.state.in_(('pending', 'sending')),
                RecapMonitorAlert.lease_until <= now, RecapMonitorAlert.next_attempt_at <= now,
            ).values(lease_until=now + 120))
            if claimed.rowcount != 1:
                continue
            row = await db.get(RecapMonitorAlert, ident)
            if row.recipient_digest != recipient_digest:
                row.state, row.error = 'quarantined', 'email_recipient_changed'
                continue
            saved = json.loads(row.payload_json)
            payload = message(saved, recipient, sender)
            envelope = digest(payload)
            if row.first_attempt_at and (now - row.first_attempt_at >= WINDOW
                    or saved.get('email_envelope_digest') != envelope):
                row.state, row.error = 'quarantined', 'email_outcome_unresolved'
                log.error('Recap monitor email quarantined reason=%s', row.error)
                continue
            row.first_attempt_at = row.first_attempt_at or now
            row.payload_json = dump({**saved, 'email_envelope_digest': envelope})
            row.state, row.next_attempt_at = 'sending', now + 300
        # No transaction held while sending. Crash replays the exact envelope/key.
        try:
            provider_id = await transport('recap-help/' + ident, payload)
        except Exception as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
            # Never log exception text, body, address, key, or envelope.
            log.warning('Recap monitor email failed type=%s status=%s', type(exc).__name__, status)
            async with maker.begin() as db:
                row = await db.get(RecapMonitorAlert, ident)
                row.error = 'email_auth_or_validation' if 400 <= status < 500 and status not in (408, 409, 429) else 'email_delivery_uncertain'
                if status == 429:
                    row.error = 'email_rate_limited'
                    try:
                        delay = int(exc.response.headers.get('retry-after', '300'))
                    except (TypeError, ValueError):
                        delay = 300
                    row.next_attempt_at = now + max(300, min(86400, delay))
                if row.error == 'email_auth_or_validation':
                    row.state = 'quarantined'
                row.lease_until = 0
            continue
        async with maker.begin() as db:
            row = await db.get(RecapMonitorAlert, ident)
            row.state, row.provider_id, row.error, row.lease_until = 'sent', provider_id, '', 0
        log.info('Recap monitor help email accepted alert=%s', ident)
        count += 1
    return count
