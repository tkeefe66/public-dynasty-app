import json

import httpx
import pytest


def test_email_layout_escapes_details_and_keeps_readable_text_fallback():
    from app.services.recap_monitor.mail import message
    payload = message(dict(reason='calls_exhausted', action='Review <draft> & approve',
                           league_name='<script>league</script>', settled_microusd=1250000),
                      'owner@example.test', 'recaps@example.test')
    assert '<script>' not in payload['html']
    assert '&lt;script&gt;league&lt;/script&gt;' in payload['html']
    assert 'Review &lt;draft&gt; &amp; approve' in payload['html']
    assert 'href="https://dynasty.tomkeefe.ai/admin"' in payload['html']
    assert '\n\nWHAT HAPPENED\ncalls exhausted\n\nWHAT TO DO\n' in payload['text']
    assert 'Settled spending: $1.25' in payload['text']


@pytest.mark.asyncio
async def test_routine_run_never_sends_and_help_deduplicates(maker):
    # Mutation: send routine completion or resend a previously accepted help email.
    from app.services.recap_monitor.mail import deliver
    from app.services.recap_monitor.state import initialize, claim, finish
    await initialize(maker, 'scope', 100)
    token = await claim(maker, 'scope', 100)
    await finish(maker, 'scope', token, 100, [{'key': 'one', 'status': 'complete'}], 'recipient')
    sent = []
    async def transport(key, payload):
        sent.append((key, payload))
        return 'email-id'
    assert await deliver(maker, 'scope', 'recipient', 'owner@example.test', 'recaps@example.test', transport, 100) == 0
    token = await claim(maker, 'scope', 10**10)
    await finish(maker, 'scope', token, 10**10, [dict(key='one', status='help', reason='calls_exhausted', action='Approve calls')], 'recipient')
    assert await deliver(maker, 'scope', 'recipient', 'owner@example.test', 'recaps@example.test', transport, 10**10) == 1
    assert await deliver(maker, 'scope', 'recipient', 'owner@example.test', 'recaps@example.test', transport, 10**10 + 60) == 0
    assert len(sent) == 1 and sent[0][1]['to'] == ['owner@example.test']
    assert 'needs help' in sent[0][1]['subject'] and 'Approve calls' in sent[0][1]['text']


@pytest.mark.asyncio
async def test_unknown_delivery_reuses_same_payload_then_quarantines(maker):
    # Mutation: make a fresh idempotency key after timeout or retry past 24 hours.
    from sqlalchemy import select
    from app.services.recap_monitor.mail import deliver
    from app.services.recap_monitor.models import RecapMonitorAlert
    from app.services.recap_monitor.state import initialize, claim, finish
    await initialize(maker, 'scope', 100)
    token = await claim(maker, 'scope', 100)
    await finish(maker, 'scope', token, 100, [dict(key='one', status='help', reason='stuck', action='Review')], 'recipient')
    sent = []
    async def timeout(key, payload):
        sent.append((key, json.dumps(payload, sort_keys=True)))
        raise httpx.ReadTimeout('secret-bearing message must not be persisted')
    for now in [100, 1000]:
        await deliver(maker, 'scope', 'recipient', 'owner@example.test', 'recaps@example.test', timeout, now)
    assert len(sent) == 2 and sent[0] == sent[1]
    await deliver(maker, 'scope', 'recipient', 'owner@example.test', 'recaps@example.test', timeout, 100 + 24*3600)
    assert len(sent) == 2
    async with maker() as db:
        row = await db.scalar(select(RecapMonitorAlert))
        assert row.state == 'quarantined' and row.error == 'email_outcome_unresolved'
        assert 'secret' not in row.payload_json


@pytest.mark.asyncio
async def test_changed_recipient_cannot_receive_old_alert(maker):
    # Mutation: send private league diagnostics to a newly configured recipient.
    from app.services.recap_monitor.models import RecapMonitorAlert
    from app.services.recap_monitor.mail import deliver
    from sqlalchemy import select
    async with maker.begin() as db:
        db.add(RecapMonitorAlert(id='alert', scope_digest='scope', recipient_digest='old', payload_json='{}'))
    async def fail(*args):
        pytest.fail('No send to a changed recipient')
    await deliver(maker, 'scope', 'new', 'new@example.test', 'recaps@example.test', fail, 100)
    async with maker() as db:
        assert (await db.scalar(select(RecapMonitorAlert))).state == 'quarantined'


@pytest.mark.asyncio
async def test_email_rate_limit_preserves_known_retry_time(maker):
    # Mutation: ignore provider Retry-After and send another request too early.
    from app.services.recap_monitor.models import RecapMonitorAlert
    from app.services.recap_monitor.mail import deliver
    from sqlalchemy import select
    async with maker.begin() as db:
        db.add(RecapMonitorAlert(id='alert',scope_digest='scope',recipient_digest='recipient',payload_json='{}'))
    async def limited(*args):
        response=httpx.Response(429,headers={'retry-after':'3600'},request=httpx.Request('POST','https://api.resend.com/emails'))
        response.raise_for_status()
    await deliver(maker,'scope','recipient','owner@example.test','recaps@example.test',limited,100)
    async with maker() as db:
        row=await db.scalar(select(RecapMonitorAlert))
        assert row.next_attempt_at==3700 and row.error=='email_rate_limited'
