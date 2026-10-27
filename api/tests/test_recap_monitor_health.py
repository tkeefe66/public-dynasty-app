from types import SimpleNamespace

import pytest

from app.services.recap_monitor import health as module
from app.services.recap_monitor.models import RecapMonitorState
from app.services.recap_monitor.state import MONITOR


@pytest.mark.asyncio
@pytest.mark.parametrize('change,reason', [
    ({}, ''),
    ({'heartbeat_at': 699}, 'monitor_heartbeat_stale'),
    ({'last_started_at': 600, 'last_finished_at': 500}, 'monitor_cycle_stalled'),
    ({'next_check_at': 399}, 'monitor_check_overdue'),
    ({'scope_digest': 'changed'}, 'monitor_configuration_invalid'),
])
async def test_watchdog_health_detects_stale_work_but_allows_weekly_idle(maker, monkeypatch, change, reason):
    # Mutation: rely only on API HTTP 200, or treat legitimate weekly idle as an outage.
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(recap_monitor_enabled=True))
    monkeypatch.setattr(module.Config, 'load', lambda: SimpleNamespace(scope='scope'))
    monkeypatch.setenv('RESEND_API_KEY', 'synthetic')
    monkeypatch.setenv('RECAP_MONITOR_FROM_EMAIL', 'recaps@example.test')
    async with maker.begin() as db:
        values = dict(id=MONITOR, scope_digest='scope', heartbeat_at=1000,
                      next_check_at=600000, last_started_at=1, last_finished_at=2)
        db.add(RecapMonitorState(**{**values, **change}))
    async with maker() as db:
        result = await module.health(db, 1000)
    assert result['healthy'] == (reason == '')
    assert result['reason'] == reason


@pytest.mark.asyncio
async def test_watchdog_endpoint_requires_worker_auth(app, maker, tmp_path, monkeypatch):
    # Mutation: expose monitor diagnostics publicly or omit the deployed endpoint.
    from httpx import ASGITransport, AsyncClient
    from app.routes import media_worker
    from tests.test_recap_workflow import seed_media
    await seed_media(maker, tmp_path, monkeypatch)
    monkeypatch.setattr(media_worker, 'get_sessionmaker', lambda: maker)
    monkeypatch.setenv('TRADE_GRADER_MEDIA_WORKER_TOKEN', 'synthetic-worker-secret-' * 3)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        path = '/api/internal/media/recap-monitor-health'
        assert (await client.get(path)).status_code == 403
        response = await client.get(path, headers={'Authorization': 'Bearer ' + 'synthetic-worker-secret-' * 3})
        assert response.status_code == 200
        assert response.json()['healthy'] is False
        assert set(response.json()) == {'healthy', 'reason', 'checked_at', 'heartbeat_at'}
