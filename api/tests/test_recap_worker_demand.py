import pytest
from httpx import ASGITransport, AsyncClient
from app.services.generation.models import stamp
from app.services.generation.recap_models import RecapStage
from tests.test_recap_workflow import seed_media


@pytest.mark.asyncio
async def test_controller_demand_does_not_claim_or_expose_work(app, maker, tmp_path, monkeypatch):
    # Mutation: returning queued work regardless of prerequisites spins idle VMs;
    # acquiring a lease here prevents the real worker from executing it.
    from app.routes import media_worker as routes
    _, identity = await seed_media(maker, tmp_path, monkeypatch)
    monkeypatch.setattr(routes, 'get_sessionmaker', lambda: maker)
    monkeypatch.setenv('TRADE_GRADER_MEDIA_WORKER_TOKEN', 'synthetic-worker-secret-' * 3)
    headers = {'Authorization': 'Bearer ' + 'synthetic-worker-secret-' * 3}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        assert (await client.get('/api/internal/media/demand')).status_code == 403
        response = await client.get('/api/internal/media/demand', headers=headers)
        assert response.status_code == 200
        assert response.json() == {'needed': True}
        async with maker.begin() as db:
            stage = await db.get(RecapStage, identity)
            assert stage.state == 'queued' and not stage.worker_id
            stage.predecessor_id = 'missing'
        assert (await client.get('/api/internal/media/demand', headers=headers)).json() == {'needed': False}
        async with maker.begin() as db:
            stage = await db.get(RecapStage, identity)
            stage.predecessor_id = ''
            stage.next_attempt_at = stamp() + 300
        assert (await client.get('/api/internal/media/demand', headers=headers)).json() == {'needed': False}
        async with maker.begin() as db:
            stage = await db.get(RecapStage, identity)
            stage.state = 'running'
        assert (await client.get('/api/internal/media/demand', headers=headers)).json() == {'needed': True}
        async with maker.begin() as db:
            (await db.get(RecapStage, identity)).state = 'held'
        assert (await client.get('/api/internal/media/demand', headers=headers)).json() == {'needed': False}
