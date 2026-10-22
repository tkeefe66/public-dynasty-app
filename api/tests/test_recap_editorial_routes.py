"""Editorial HTTP boundaries derive identity and never accept a client verdict."""
import sys
from types import SimpleNamespace

import pytest

from app.services.generation.store import digest


@pytest.mark.asyncio
async def test_editorial_http_binds_episode_and_authenticated_review_identity(client, maker, tmp_path, monkeypatch):
    # Mutation: trust client reviewer identity or let one episode approve another's script.
    from tests.test_recap_video_script import seed, approved_payload
    from app.auth.deps import require_admin
    from app.db.session import get_db
    from app.main import app
    ident, saved = await seed(maker, tmp_path, monkeypatch)
    script = approved_payload(saved)['script']
    script.pop('reviews')
    calls = []
    async def preview(db, **kwargs):
        calls.append(kwargs)
        return {'preview_id': 'preview', 'digest': 'a'*64, 'script_digest': digest(kwargs['script']),
                'narration_maximum_microusd': 200000}
    monkeypatch.setitem(sys.modules, 'app.services.recap_video.editorial', SimpleNamespace(preview_editorial=preview))
    async def dependency():
        async with maker() as db:
            yield db
            await db.commit()
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id='owner', is_admin=True)
    body = {'operation_id': 'job', 'script': script, 'reason': 'Reviewed exact corrected script',
            'checks': {key: True for key in ('facts', 'article_agreement', 'coverage', 'spoken_numbers', 'premise_variety')}}
    route = f'/api/admin/generation/recap-episodes/{ident}/editorial-preview'
    assert client.post(route, json={**body, 'reviewer_identity': 'someone else'}).status_code == 422
    assert client.post(route.replace(ident, 'other-episode'), json=body).status_code == 404
    assert not calls
    response = client.post(route, json=body)
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    review = calls[0]['semantic_review']
    assert calls[0]['actor_id'] == 'owner'
    assert review['reviewer_identity'] == 'Authenticated administrator owner'
    assert review['reviewer_kind'] == 'human_editorial_reviewer'
    assert review['script_sha256'] == digest(script)
    assert set(review['checked_segment_ids']) == {'opening', 'closing', *[s['id'] for s in script['segments']]}


def test_editorial_http_requires_admin(client, monkeypatch):
    # Mutation: mount editorial actions without the admin dependency.
    from app.auth.deps import get_current_user, require_admin
    from app.main import app
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_admin, None)
    monkeypatch.setenv('TRADE_GRADER_AUTH_BACKEND_SECRET', 'editorial-test-secret-at-least-32-bytes')
    base = '/api/admin/generation/recap-episodes/synthetic'
    assert client.get(base+'/editorial-source?operation_id=job').status_code == 401
    assert client.post(base+'/editorial-preview', json={}).status_code == 401
    assert client.post(base+'/editorial-approve', json={}).status_code == 401
