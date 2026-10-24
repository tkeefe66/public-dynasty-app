from datetime import datetime

import pytest


def ts(value):
    return int(datetime.fromisoformat(value).timestamp())


def test_weekly_schedule_tracks_denver_dst():
    # Mutation: use fixed UTC offset or advance from completion instead of Monday.
    from app.services.recap_monitor.state import next_monday
    assert next_monday(ts('2026-10-27T10:00:00-06:00')) == ts('2026-11-02T22:30:00-07:00')
    assert next_monday(ts('2027-03-09T10:00:00-07:00')) == ts('2027-03-15T22:30:00-06:00')


def test_only_known_gates_skip_hourly_but_active_work_keeps_hourly():
    # Mutation: apply Tuesday gate to all leagues or poll a lone future gate hourly.
    from app.services.recap_monitor.state import next_check
    now = ts('2026-10-26T22:30:00-06:00')
    gate = ts('2026-10-27T08:00:00-06:00')
    assert next_check(now, [{'status': 'waiting', 'gate': gate}]) == gate + 60
    assert next_check(now, [{'status': 'waiting', 'gate': gate}, {'status': 'pending'}]) == now + 3600
    assert next_check(now, [{'status': 'complete'}]) == ts('2026-11-02T22:30:00-07:00')


@pytest.mark.asyncio
async def test_claim_fences_duplicates_and_expired_worker(maker):
    # Mutation: select then update without CAS; stale worker overwrites new lease.
    from app.services.recap_monitor.state import initialize, claim, finish
    await initialize(maker, 'scope', 100)
    first = await claim(maker, 'scope', 100)
    assert first and await claim(maker, 'scope', 100) is None
    assert await claim(maker, 'other', 5000) is None
    second = await claim(maker, 'scope', 4001)
    assert second and second != first
    assert not await finish(maker, 'scope', first, 4002, [], 'recipient')
    assert await finish(maker, 'scope', second, 4002, [], 'recipient')


@pytest.mark.asyncio
async def test_alert_dedup_survives_runs_and_cancels_recovered_help(maker):
    # Mutation: create one alert each run or send stale help after recovery.
    from sqlalchemy import select
    from app.services.recap_monitor.models import RecapMonitorAlert
    from app.services.recap_monitor.state import initialize, claim, finish
    await initialize(maker, 'scope', 100)
    help_item = dict(key='series:2026:7', status='help', reason='attempt_allowance_exhausted',
                     action='Approve additional exact-job calls', progress='same')
    token = await claim(maker, 'scope', 100)
    await finish(maker, 'scope', token, 100, [help_item], 'recipient')
    token = await claim(maker, 'scope', 3701)
    await finish(maker, 'scope', token, 3701, [help_item], 'recipient')
    async with maker() as db:
        rows = (await db.scalars(select(RecapMonitorAlert))).all()
        assert len(rows) == 1 and rows[0].state == 'pending'
    token = await claim(maker, 'scope', 7302)
    await finish(maker, 'scope', token, 7302, [{**help_item, 'status': 'complete'}], 'recipient')
    async with maker() as db:
        assert (await db.get(RecapMonitorAlert, rows[0].id)).state == 'cancelled'


@pytest.mark.asyncio
async def test_progress_stall_requires_two_eligible_checks(maker):
    # Mutation: alert on first normal queue wait or reset counter on every run.
    from app.services.recap_monitor.models import RecapMonitorAlert
    from app.services.recap_monitor.state import initialize, claim, finish
    from sqlalchemy import select
    await initialize(maker, 'scope', 100)
    item = dict(key='series:2026:7', status='pending', progress='same')
    for now in [100, 3701]:
        token = await claim(maker, 'scope', now)
        await finish(maker, 'scope', token, now, [item], 'recipient')
    async with maker() as db:
        assert not (await db.scalars(select(RecapMonitorAlert))).all()
    token = await claim(maker, 'scope', 7302)
    await finish(maker, 'scope', token, 7302, [item], 'recipient')
    async with maker() as db:
        assert len((await db.scalars(select(RecapMonitorAlert))).all()) == 1


@pytest.mark.asyncio
async def test_source_failure_retains_period_and_recovery_counter(maker):
    # Mutation: overwrite previous observations and grant a fresh recovery counter after a source outage.
    from app.services.recap_monitor.models import RecapMonitorState
    from app.services.recap_monitor.state import initialize, claim, finish
    import json
    await initialize(maker, 'scope', 100)
    item = dict(key='series:2026:playoff:3', status='pending', series_id='series',
                period={'period_id': 'playoff:3', 'week': 17, 'nfl_weeks': [16,17]}, recovery_attempts=2)
    token = await claim(maker, 'scope', 100)
    await finish(maker, 'scope', token, 100, [item], 'recipient')
    token = await claim(maker, 'scope', 3701)
    await finish(maker, 'scope', token, 3701, [dict(key='source', status='pending')], 'recipient')
    async with maker() as db:
        saved = json.loads((await db.get(RecapMonitorState, 'weekly-recaps')).state_json)['observations']
        assert saved[item['key']]['recovery_attempts'] == 2
        assert saved[item['key']]['period'] == item['period']


@pytest.mark.asyncio
async def test_resolved_sending_alert_stops_and_unsent_cancelled_alert_can_return(maker):
    # Mutation: retry stale sending alert, or permanently suppress a never-sent cancelled alert.
    from sqlalchemy import select
    from app.services.recap_monitor.models import RecapMonitorAlert
    from app.services.recap_monitor.state import initialize, claim, finish
    await initialize(maker, 'scope', 100)
    item = dict(key='one', status='help', reason='stuck', action='Review')
    async def cycle(now, items):
        token = await claim(maker, 'scope', now)
        assert token
        await finish(maker, 'scope', token, now, items, 'recipient')
    await cycle(100, [item])
    await cycle(3701, [{**item, 'status':'complete'}])
    await cycle(10**10, [item])
    async with maker.begin() as db:
        row = await db.scalar(select(RecapMonitorAlert))
        assert row.state == 'pending'
        row.state, row.first_attempt_at = 'sending', 10**10
    await cycle(10**10+3700, [{**item, 'status':'complete'}])
    async with maker() as db:
        assert (await db.scalar(select(RecapMonitorAlert))).state == 'quarantined'


@pytest.mark.asyncio
async def test_successful_source_read_retires_transient_outage(maker):
    # Mutation: retain synthetic source failures forever after the next successful scope read.
    from app.services.recap_monitor.state import initialize, claim, finish
    from app.services.recap_monitor.models import RecapMonitorState
    import json
    await initialize(maker,'scope',100)
    token=await claim(maker,'scope',100)
    await finish(maker,'scope',token,100,[dict(key='monitor-source',status='pending',progress='outage')],'recipient')
    token=await claim(maker,'scope',3701)
    await finish(maker,'scope',token,3701,[dict(key='edition',status='complete')],'recipient')
    async with maker() as db:
        assert 'monitor-source' not in json.loads((await db.get(RecapMonitorState,'weekly-recaps')).state_json)['observations']
