"""Help-only durable delivery. Resend idempotency expires after 24 hours."""
import json
import logging
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

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
    reason = str(item.get('reason', 'Review required')).replace('_', ' ')
    cause = item.get('job_reason')
    if cause == 'results_not_ready' or item.get('reason') == 'results_not_ready':
        week = item.get('readiness_week') or item.get('week', '?')
        reason = f"Week {week} results are incomplete. Provider scores or lineups are not ready; AI writing has not started."
    elif item.get('reason') == 'recap_dependency_changed':
        reason = 'This recap is blocked because earlier-week evidence was marked as changed. Data refreshes may succeed while writing remains blocked.'
    elif cause:
        reason += '. Job cause: ' + str(cause).replace('_', ' ')
    action = str(item.get('action', 'Review the recap monitor in the admin dashboard.'))
    labels = {'league_name': 'League', 'season': 'Season', 'week': 'Week',
              'job_id': 'Job ID', 'last_progress_at': 'Last progress',
              'settled_microusd': 'Settled spending', 'unknown_cost_count': 'Unpriced requests',
              'calls_used': 'Calls used', 'max_calls': 'Call limit',
              'remaining_calls': 'Calls remaining', 'recovery_attempts': 'Recovery attempts'}
    details = [(labels[key], f"${item[key] / 1_000_000:.2f}" if key == 'settled_microusd'
                else datetime.fromtimestamp(item[key], ZoneInfo('America/Denver')).strftime('%b %d, %I:%M %p %Z')
                if key == 'last_progress_at' and item[key]
                else str(item[key])) for key in fields if key in labels and key in item]
    lines = ['Your weekly recap needs attention', '', 'WHAT HAPPENED', reason,
             '', 'WHAT TO DO', action]
    if details:
        lines.extend(['', 'DETAILS', *(f'{label}: {value}' for label, value in details)])
    lines.extend(['', 'Open recap admin: https://dynasty.tomkeefe.ai/admin', '',
                  'No new AI calls or spending are authorized by this email.'])
    rows = ''.join(f'<tr><th scope="row" style="padding:6px 16px 6px 0;text-align:left;'
                   f'font-weight:normal;color:#59616d;vertical-align:top">{escape(label)}</th>'
                   f'<td style="padding:6px 0;overflow-wrap:anywhere">{escape(value)}</td></tr>'
                   for label, value in details)
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;background:#f5f6f8;color:#202630;font-family:Arial,Helvetica,sans-serif">
<main style="max-width:560px;margin:0 auto;padding:32px 24px;background:#ffffff">
<h1 style="font-size:26px;line-height:1.25;margin:0 0 28px">Your weekly recap needs attention</h1>
<h2 style="font-size:16px;margin:0 0 8px">What happened</h2>
<p style="font-size:16px;line-height:1.6;margin:0 0 24px">{escape(reason)}</p>
<h2 style="font-size:16px;margin:0 0 8px">What to do</h2>
<p style="font-size:16px;line-height:1.6;margin:0 0 24px;white-space:pre-line">{escape(action)}</p>
{'<h2 style="font-size:16px;margin:0 0 8px">Details</h2><table style="font-size:14px;line-height:1.5;border-collapse:collapse;margin:0 0 24px">' + rows + '</table>' if rows else ''}
<p style="margin:0 0 28px"><a href="https://dynasty.tomkeefe.ai/admin" style="display:inline-block;
background:#163a32;color:#ffffff;padding:14px 20px;border-radius:6px;font-size:16px;
font-weight:bold;text-decoration:none">Open recap admin</a></p>
<p style="border-top:1px solid #e1e4e8;padding-top:20px;margin:0;color:#59616d;font-size:13px;line-height:1.6">
No new AI calls or spending are authorized by this email.<br>Public Dynasty · Recap monitor</p>
</main></body></html>'''
    return {'from': sender, 'to': [recipient],
            'subject': 'Public Dynasty recap monitor needs help', 'text': '\n'.join(lines), 'html': html}


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
