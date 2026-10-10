"""Public authority fixtures retain old files to detect fallback and resurrection."""
import asyncio
import hashlib
import importlib
from types import SimpleNamespace

import pytest

from app.deps import get_cache_dir
from app.services.generation.store import Held
from tests.test_analyst_sharing import seed
from tests.test_analyst_media import attach


@pytest.fixture
def published_fixture(client, maker, tmp_path, monkeypatch):
    publication = importlib.import_module('app.services.recap_video.publication')
    from app.db.session import get_db
    from app.main import app
    seed()
    manifest = attach(tmp_path)
    token = client.post('/api/league/test/analyst/2026/1/share').json()['token']
    async def setup():
        async with maker.begin() as db:
            report = await publication.reconcile_legacy(db, get_cache_dir())
            monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE', 'quarantine')
            await publication.reconcile_legacy(db, get_cache_dir(), expected_digest=report['digest'], apply=True, epoch='test-serving')
    asyncio.run(setup())
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE', 'database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH', 'test-serving')
    async def dependency():
        async with maker.begin() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    async def change(**values):
        from app.services.generation.recap_models import RecapPublication
        async with maker.begin() as db:
            row = await db.get(RecapPublication, publication.legacy_episode_id('test', 2026, 1))
            for key, value in values.items():
                setattr(row, key, value)
    return SimpleNamespace(token=token, manifest=manifest, maker=maker,
        url=f'/api/public/analyst/{token}',
        media_url=f'/api/public/analyst/{token}/media/{manifest["id"]}/video.mp4',
        withdraw=lambda: asyncio.run(change(withdrawn=True)), module=publication)


def test_withdrawn_edition_does_not_serve_old_manifest(client, published_fixture):
    # Mutation: fall back to a valid filesystem manifest after DB withdrawal.
    f = published_fixture
    assert client.get(f.media_url).status_code == 200
    f.withdraw()
    for method in ('get', 'head'):
        for headers in ({}, {'Range': 'bytes=0-9'}):
            response = getattr(client, method)(f.media_url, headers=headers)
            assert response.status_code in (404, 410)
            assert 'no-store' in response.headers['cache-control']
    page = client.get(f.url)
    assert page.status_code == 200
    assert page.json()['status'] == 'withdrawn'
    assert page.json()['markdown'] == ''
    assert page.json()['media'] is None
    assert client.get('/api/league/test/analyst').json()['editions'] == []


def test_db_mode_never_falls_back_on_missing_epoch(client, published_fixture, monkeypatch):
    # Mutation: a restored/missing authority row revives a still-valid file token.
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH', 'new-external-epoch')
    assert client.get(published_fixture.url).status_code == 503
    assert client.head(published_fixture.media_url).status_code == 503


def test_database_outage_never_falls_back_to_retained_files(client, published_fixture, monkeypatch):
    # Mutation: on DB outage return the old valid filesystem share/bundle.
    from sqlalchemy.exc import OperationalError
    async def unavailable(*args):
        raise OperationalError('synthetic', {}, Exception('offline'))
    monkeypatch.setattr(published_fixture.module, 'authorize_public_read', unavailable)
    for url in (published_fixture.url, published_fixture.media_url):
        response = client.get(url)
        assert response.status_code == 503
        assert response.headers['retry-after'] == '5'
        assert 'no-store' in response.headers['cache-control']


def test_restore_hold_blocks_old_tokens_even_when_generation_pause_does_not(client,published_fixture):
    # Mutation: restored generation quarantine leaves a backed-up public token active.
    from app.services.generation.models import GenerationControl
    async def quarantine():
        async with published_fixture.maker.begin() as db:
            row = await db.get(GenerationControl,'global')
            row.hold = 'restore_quarantine'
    asyncio.run(quarantine())
    assert client.get(published_fixture.url).status_code == 503


def test_corrected_legacy_article_hides_old_media_and_authenticated_archive(client, published_fixture):
    # Mutation: article revision changes but retained selected media stays visible.
    from app.services.analyst_store import AnalystStore
    archive = AnalystStore(get_cache_dir())
    edition = archive.published_editions('test')[0]
    archive.save_correction('test', {**edition, 'markdown':'New score'}, 'Correct score')
    assert client.get(published_fixture.url).json()['status'] == 'withdrawn'
    assert client.get(published_fixture.media_url).status_code == 404
    assert client.get('/api/league/test/analyst').json()['editions'] == []


def test_current_db_revoke_and_guessed_private_assets_fail_closed(client, published_fixture):
    # Mutation: authorize a guessed bundle or cached token after DB-only revoke.
    f = published_fixture
    for name in ('episode.json', 'audio.wav', 'qa.json'):
        assert client.get(f.media_url.rsplit('/', 1)[0]+'/'+name).status_code == 404
    assert client.get(f.media_url.replace(f.manifest['id'], 'b'*32)).status_code == 404
    assert client.delete('/api/league/test/analyst/2026/1/share').status_code == 200
    assert client.get(f.url).status_code == 404
    assert client.get(f.media_url, headers={'Range': 'bytes=0-1'}).status_code == 404


def test_private_stream_single_ranges_and_hashes(client, published_fixture, tmp_path):
    # Mutation: range off-by-one, missing HEAD headers, or serving storage redirects.
    f = published_fixture
    expected = (tmp_path/'video.mp4').read_bytes()
    full = client.get(f.media_url)
    assert hashlib.sha256(full.content).digest() == hashlib.sha256(expected).digest()
    for value, wanted in [('bytes=8-15', expected[8:16]), ('bytes=-8', expected[-8:]), ('bytes=8-', expected[8:])]:
        response = client.get(f.media_url, headers={'Range': value})
        assert response.status_code == 206
        assert response.content == wanted
    for value in ('bytes=99999-', 'bytes=0-1,3-4', 'bytes=-0'):
        response = client.get(f.media_url, headers={'Range': value})
        assert response.status_code == 416
        assert response.headers['x-content-type-options'] == 'nosniff'
    assert client.head(f.media_url).headers['content-length'] == str(len(expected))


@pytest.mark.asyncio
async def test_legacy_reconcile_preserves_active_token_not_historical_indexes(client, maker, tmp_path, monkeypatch):
    # Mutation: importing each global index resurrects previously revoked tokens.
    p = importlib.import_module('app.services.recap_video.publication')
    from app.services.analyst_shares import AnalystShares
    from app.services.generation.recap_models import RecapShareDecision
    from sqlalchemy import select
    seed()
    store = AnalystShares(get_cache_dir())
    old = store.create('test', 2026, 1)['token']
    store.revoke('test', 2026, 1)
    current = store.create('test', 2026, 1)['token']
    before = {str(path):path.read_bytes() for path in get_cache_dir().rglob('*') if path.is_file()}
    async with maker.begin() as db:
        report = await p.reconcile_legacy(db, get_cache_dir())
        assert (await db.scalars(select(RecapShareDecision))).all() == []
        monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE', 'quarantine')
        await p.reconcile_legacy(db, get_cache_dir(), expected_digest=report['digest'], apply=True, epoch='external')
        rows = (await db.scalars(select(RecapShareDecision))).all()
        assert [r.token_digest for r in rows] == [hashlib.sha256(current.encode()).hexdigest()]
        assert rows[0].token_digest != hashlib.sha256(old.encode()).hexdigest()
    assert before == {str(path):path.read_bytes() for path in get_cache_dir().rglob('*') if path.is_file()}


@pytest.mark.asyncio
async def test_worker_cannot_select_or_forge_approval(maker):
    # Mutation: treat a caller-supplied approved:true as publication authorization.
    p = importlib.import_module('app.services.recap_video.publication')
    async with maker.begin() as db:
        with pytest.raises(Held, match='publication_approval_required'):
            await p.select_publication(db, 'unknown', 0, None, {'approved': True, 'role': 'worker'})


@pytest.mark.asyncio
async def test_malformed_legacy_edition_only_holds_that_edition(client,maker,monkeypatch):
    # Mutation: one corrupt edition prevents reconciliation of another valid share.
    from app.services.recap_video import publication as p
    from app.services.analyst_shares import AnalystShares
    from app.services.analyst_store import AnalystStore
    data = seed()
    shares, archive = AnalystShares(get_cache_dir()), AnalystStore(get_cache_dir())
    shares.create('test',2026,1)
    archive.save('test',{**data,'week':2})
    token = shares.create('test',2026,2)['token']
    archive.edition_path('test',2026,1).write_text('{malformed')
    async with maker.begin() as db:
        report = await p.reconcile_legacy(db,get_cache_dir())
        assert report['editions'] == 1 and len(report['holds']) == 1
        monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','quarantine')
        await p.reconcile_legacy(db,get_cache_dir(),apply=True,expected_digest=report['digest'],epoch='external')
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH','external')
    async with maker() as db:
        assert (await p.authorize_public_read(db,token,None,0))['article']['week'] == 2


@pytest.mark.asyncio
async def test_reconcile_refuses_token_change_since_dry_run(client,maker,monkeypatch):
    # Mutation: stale dry-run lets import recreate a token revoked after inspection.
    from app.services.recap_video import publication as p
    from app.services.analyst_shares import AnalystShares
    seed()
    shares = AnalystShares(get_cache_dir())
    shares.create('test',2026,1)
    async with maker() as db:
        report = await p.reconcile_legacy(db,get_cache_dir())
    shares.revoke('test',2026,1)
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','quarantine')
    async with maker.begin() as db:
        with pytest.raises(Held,match='legacy_reconciliation_changed'):
            await p.reconcile_legacy(db,get_cache_dir(),apply=True,expected_digest=report['digest'],epoch='external')


async def ready_article(maker, tmp_path, monkeypatch):
    from tests.test_recap_video_script import seed as seed_article
    from app.services.generation.recap_models import RecapPublicationControl, RecapShareDecision
    ident, _ = await seed_article(maker, tmp_path, monkeypatch)
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE', 'database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH', 'test-serving')
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EXECUTION_EPOCH', 'test-epoch')
    async with maker.begin() as db:
        db.add(RecapPublicationControl(id='global', epoch='test-serving', reconciliation_digest='synthetic-inventory', quarantined=False))
        db.add(RecapShareDecision(scope='series:series', allowed=True, opted_out=False))
    return ident


async def legacy_for_canonical(maker):
    from app.services.recap_video import publication as p
    from app.services.generation.recap_models import RecapPublication, RecapShareDecision
    old = p.legacy_episode_id('synthetic', 2026, 4)
    token = 'k'*43
    async with maker.begin() as db:
        db.add(RecapPublication(episode_id=old, series_id='legacy-series', league_id='synthetic',
            season=2026, week=4, article_revision=1, article_digest='old', article_json='{}',
            facts_digest='', share_revision=3, authority_revision=7, projected_revision=7, epoch='test-serving'))
        db.add(RecapShareDecision(scope='edition:'+old, revision=3, allowed=True, opted_out=False,
            token=token, token_digest=hashlib.sha256(token.encode()).hexdigest()))
        future = await db.get(RecapShareDecision, 'series:series')
        future.allowed, future.opted_out = False, True
    return old, token


@pytest.mark.asyncio
async def test_legacy_adoption_preserves_token_permissions_history_and_episode(maker,tmp_path,monkeypatch):
    # Mutation: insert a duplicate episode/publication or mint a fresh share during correction.
    from app.services.recap_video import publication as p
    from app.services.generation.recap_models import RecapPublication, RecapShareDecision, RecapEpisode, RecapPublicationSelection
    from app.services.generation.models import GenerationOutbox
    from app.services.generation.store import dump
    from sqlalchemy import select
    ident = await ready_article(maker,tmp_path,monkeypatch)
    old, token = await legacy_for_canonical(maker)
    async with maker.begin() as db:
        db.add(RecapPublicationSelection(episode_id=old,series_id='series',script_id='old-script',authority_revision=6))
        old_item = GenerationOutbox(key='old-publication',kind='recap_publication',payload_json=dump(dict(episode_id=old,authority_revision=7)))
        db.add(old_item)
        approval = await approve_current(db,ident,7,None,reviewer=SimpleNamespace(id='admin',is_admin=True),reason='Corrected article')
    async with maker.begin() as db:
        await p.select_publication(db,ident,7,None,approval)
        row = await db.get(RecapPublication,ident)
        assert row.authority_revision == 8 and row.series_id == 'series'
        assert await db.get(RecapPublication,old) is None
        assert await db.get(RecapShareDecision,'edition:'+old) is None
        share = await db.get(RecapShareDecision,'edition:'+ident)
        assert share.token == token and share.revision == 3 and not share.opted_out
        future = await db.get(RecapShareDecision,'series:series')
        assert not future.allowed and future.opted_out
        assert len((await db.scalars(select(RecapEpisode))).all()) == 1
        history = await db.scalar(select(RecapPublicationSelection))
        assert history.episode_id == ident and history.script_id == 'old-script'
        item = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key=='old-publication'))
        await p.project_publication(db,item,tmp_path)
        assert row.projected_revision == 0


@pytest.mark.asyncio
async def test_material_correction_withdraws_by_edition_before_legacy_adoption(client,published_fixture):
    # Mutation: correction looks up only a new canonical ID and leaves the old token live.
    p = published_fixture.module
    assert hasattr(p,'withdraw_edition'), 'Task10 must withdraw by logical edition before paid repair'
    async with published_fixture.maker.begin() as db:
        await p.withdraw_edition(db,'test',2026,1,expected_revision=1,actor_id='admin',reason='Material facts changed')
    assert client.get(published_fixture.url).json()['status'] == 'withdrawn'
    assert client.get(published_fixture.media_url).status_code == 404
    assert client.get('/api/league/test/analyst').json()['editions'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['optout','managed','stale'])
async def test_legacy_adoption_denies_optout_managed_reassignment_and_stale_review(maker,tmp_path,monkeypatch,change):
    from app.services.recap_video import publication as p
    from app.services.generation.recap_models import RecapPublication, RecapShareDecision
    from app.services.generation.store import Conflict
    ident = await ready_article(maker,tmp_path,monkeypatch)
    old, _ = await legacy_for_canonical(maker)
    async with maker.begin() as db:
        proof = await approve_current(db,ident,7,None,reviewer=SimpleNamespace(id='admin',is_admin=True),reason='Review')
    async with maker.begin() as db:
        row = await db.get(RecapPublication,old)
        if change == 'optout':
            share = await db.get(RecapShareDecision,'edition:'+old)
            share.allowed, share.opted_out = False, True
        elif change == 'managed':
            row.article_id = 'already-managed'
        else:
            row.authority_revision += 1
    async with maker.begin() as db:
        with pytest.raises((Held,Conflict)):
            await p.select_publication(db,ident,7,None,proof)
        assert await db.get(RecapPublication,old) is not None
        assert await db.get(RecapPublication,ident) is None


@pytest.mark.asyncio
async def test_review_binds_the_preview_the_operator_actually_saw(maker, tmp_path, monkeypatch):
    # Mutation: silently approve the new source when it changed after preview.
    from app.services.recap_video import publication as p
    from app.services.generation.recap_models import RecapEpisode
    ident = await ready_article(maker, tmp_path, monkeypatch)
    assert hasattr(p, 'preview_publication'), 'Approval must bind an explicit finished preview'
    async with maker.begin() as db:
        preview = await p.preview_publication(db, ident, 0, None)
    async with maker.begin() as db:
        (await db.get(RecapEpisode,ident)).source_digest = 'changed-after-preview'
    async with maker.begin() as db:
        with pytest.raises(Held, match='publication_preview_changed'):
            await p.record_approval(db, ident, 0, None, reviewer=SimpleNamespace(id='admin', is_admin=True),
                reason='Reviewed', preview_digest=preview['digest'])


@pytest.mark.asyncio
async def test_article_without_video_remains_readable_through_global_pause(maker, tmp_path, monkeypatch):
    # Mutation: require ready video, or apply generation pause to valid existing reads.
    from app.services.recap_video import publication as p
    from app.services.generation.recap_models import RecapPublication
    from app.services.generation.models import GenerationControl
    from app.services.generation.publication import drain
    ident = await ready_article(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        approval = await approve_current(db, ident, 0, None, reviewer=SimpleNamespace(id='admin', is_admin=True), reason='Reviewed article')
    async with maker.begin() as db:
        await p.select_publication(db, ident, 0, None, approval)
    await drain(maker, tmp_path)
    async with maker.begin() as db:
        row = await db.get(RecapPublication, ident)
        token = (await p.share_state(db, row))['token']
        (await db.get(GenerationControl, 'global')).hold = 'operator_pause'
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EMERGENCY_PAUSE', 'true')
    async with maker.begin() as db:
        value = await p.authorize_public_read(db, token, None, 0)
        assert value['article']['markdown'] == 'Correct published roast.'
        assert value['article']['media'] is None
        assert 'facts' not in value['article']
        with pytest.raises(Held, match='publication_paused'):
            await approve_current(db, ident, 1, None, reviewer=SimpleNamespace(id='admin', is_admin=True), reason='New approval')


@pytest.mark.asyncio
async def test_authenticated_reader_never_returns_stale_file_beside_current_managed_authority(maker,tmp_path,monkeypatch):
    # Mutation: validate DB source but still return a different filesystem article.
    from app.routes.analyst import analyst_archive
    from app.services.analyst_store import AnalystStore
    from app.services.recap_video import publication as p
    from app.services.generation.models import ContentArtifact
    import json
    ident = await ready_article(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        approval = await approve_current(db,ident,0,None,reviewer=SimpleNamespace(id='admin',is_admin=True),reason='Review')
    async with maker.begin() as db:
        await p.select_publication(db,ident,0,None,approval)
        article = json.loads((await db.get(ContentArtifact,'article')).payload_json)
    AnalystStore(tmp_path).save('synthetic',article)
    async with maker() as db:
        assert (await analyst_archive('synthetic',db))['editions'][0]['markdown'] == 'Correct published roast.'
    AnalystStore(tmp_path).edition_path('synthetic',2026,4).write_text(json.dumps({**article,'markdown':'Stale filesystem article'}))
    async with maker() as db:
        editions = (await analyst_archive('synthetic',db))['editions']
        assert not editions or all(item['markdown'] == 'Correct published roast.' for item in editions)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['article','facts','source','policy','epoch','revoke','future'])
async def test_selection_rechecks_current_authority_after_review(maker, tmp_path, monkeypatch, change):
    # Mutation: trust an old preview approval after any bound authority changes.
    from app.services.recap_video import publication as p
    from app.services.generation.recap_models import RecapEpisode, RecapShareDecision
    from app.services.generation.models import ArtifactHead, GenerationPolicy
    from app.services.generation.store import Conflict
    ident = await ready_article(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        approval = await approve_current(db, ident, 0, None, reviewer=SimpleNamespace(id='admin', is_admin=True), reason='Reviewed article')
    async with maker.begin() as db:
        if change == 'article':
            (await db.get(ArtifactHead, 'article-subject')).revision = 2
        elif change in ('facts', 'source'):
            setattr(await db.get(RecapEpisode, ident), change+'_digest', 'changed')
        elif change == 'policy':
            (await db.get(GenerationPolicy, 'app')).revision += 1
        elif change == 'revoke':
            db.add(RecapShareDecision(scope='edition:'+ident, allowed=False, opted_out=True))
        elif change == 'future':
            (await db.get(RecapShareDecision, 'series:series')).allowed = False
        else:
            monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH', 'changed')
    async with maker.begin() as db:
        with pytest.raises((Held, Conflict)):
            await p.select_publication(db, ident, 0, None, approval)


@pytest.mark.asyncio
async def test_pause_before_projection_keeps_outbox_pending(maker, tmp_path, monkeypatch):
    # Mutation: acknowledge projection before pause check or failed file installation.
    from app.services.recap_video import publication as p
    from app.services.generation.models import GenerationOutbox
    from app.services.generation.recap_models import RecapPublication
    from app.services.generation.publication import drain
    from sqlalchemy import select
    ident = await ready_article(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        proof = await approve_current(db, ident, 0, None, reviewer=SimpleNamespace(id='admin', is_admin=True), reason='Review')
    async with maker.begin() as db:
        await p.select_publication(db, ident, 0, None, proof)
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EMERGENCY_PAUSE', 'true')
    await drain(maker, tmp_path)
    async with maker() as db:
        item = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.kind == 'recap_publication'))
        assert not item.delivered and item.error == ''
        assert (await db.get(RecapPublication, ident)).projected_revision == 0
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EMERGENCY_PAUSE', 'false')
    await drain(maker, tmp_path)
    async with maker() as db:
        assert (await db.get(RecapPublication, ident)).projected_revision == 1


@pytest.mark.asyncio
async def test_premise_history_uses_delivered_selections_and_dedupes_six_episodes(maker):
    # Mutation: infer publication from current head or count unpublished corrections.
    from app.services.recap_video import publication as p
    from app.services.generation import recap_models as m
    assert hasattr(m, 'RecapPublicationSelection'), 'Publication needs durable delivered selection history'
    async with maker.begin() as db:
        for index in range(8):
            db.add(m.RecapPublicationSelection(episode_id=f'episode-{index}', series_id='series',
                script_id=f'script-{index}', authority_revision=1))
        db.add(m.RecapPublicationSelection(episode_id='episode-7', series_id='series', script_id='script-7-corrected', authority_revision=2))
        db.add(m.RecapPublicationSelection(episode_id='foreign', series_id='elsewhere', script_id='foreign-script', authority_revision=1))
    async with maker() as db:
        assert await p.published_script_selections(db, 'series') == ['script-7-corrected','script-6','script-5','script-4','script-3','script-2']


async def approve_current(db, ident, revision, media_id, *, reviewer, reason):
    from app.services.recap_video import publication as p
    preview = await p.preview_publication(db, ident, revision, media_id)
    return await p.record_approval(db, ident, revision, media_id, reviewer=reviewer,
        reason=reason, preview_digest=preview['digest'])


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled',[True,False])
async def test_member_http_consent_before_selection_is_independent_of_future_permission(client,maker,tmp_path,monkeypatch,enabled):
    # Mutation: require publication before permission, or turn edition consent into league/media approval.
    from app.main import app
    from app.db.session import get_db
    from app.auth.deps import require_league_member
    from app.services.recap_video import publication as p
    from app.services.generation.recap_models import RecapPublication, RecapPublicationApproval, RecapPublicationSelection, RecapShareDecision
    from sqlalchemy import select
    ident = await ready_article(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        future = await db.get(RecapShareDecision,'series:series')
        future.allowed, future.opted_out = not enabled, enabled
    async def dependency():
        async with maker.begin() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[require_league_member] = lambda: SimpleNamespace(id='member',is_admin=False)
    url = '/api/league/synthetic/analyst/2026/4/share'
    response = client.post(url) if enabled else client.delete(url)
    assert response.status_code == 200, response.text
    assert client.get(url).json() == response.json()
    async with maker() as db:
        future = await db.get(RecapShareDecision,'series:series')
        assert future.allowed == (not enabled) and future.opted_out == enabled
        assert (await db.scalars(select(RecapPublicationApproval))).all() == []
        assert (await db.scalars(select(RecapPublicationSelection))).all() == []
        if enabled:
            row = await db.get(RecapPublication,ident)
            assert row and not row.media_id and row.media_json == '{}'
        else:
            assert await db.get(RecapPublication,ident) is None
    if enabled:
        from fastapi.testclient import TestClient
        overrides = app.dependency_overrides.copy()
        app.dependency_overrides.clear()
        app.dependency_overrides[get_db] = dependency
        try:
            with TestClient(app) as anonymous:
                public = anonymous.get('/api/public/analyst/'+response.json()['token'])
                assert public.status_code == 200 and public.json()['markdown'] == 'Correct published roast.'
                assert public.json()['media'] is None and 'facts' not in public.json()
        finally:
            app.dependency_overrides.update(overrides)
    else:
        async with maker.begin() as db:
            with pytest.raises(Held,match='edition_sharing_opted_out'):
                await approve_current(db,ident,0,None,reviewer=SimpleNamespace(id='admin',is_admin=True),reason='Review')


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['unchanged','source_hold','source_digest','script_head','actor','preflight'])
async def test_projector_rechecks_current_media_authority_without_storage_io(maker,tmp_path,monkeypatch,change):
    # Mutation: select -> invalidate authority -> drain still installs or acknowledges.
    from tests.test_recap_workflow import seed_media
    from app.services.recap_video import publication as p, workflow
    from app.services.generation.publication import drain
    from app.services.generation.models import ArtifactHead, GenerationOperation, GenerationOutbox
    from app.services.generation.recap_models import RecapEpisode, RecapStage, RecapPublication, RecapPublicationControl, RecapShareDecision
    from sqlalchemy import select
    ident, media_id = await seed_media(maker,tmp_path,monkeypatch,'media_check')
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH','test-serving')
    async with maker.begin() as db:
        db.add(RecapPublicationControl(id='global',epoch='test-serving',reconciliation_digest='synthetic',quarantined=False))
        db.add(RecapShareDecision(scope='series:series',allowed=True,opted_out=False))
        (await db.get(RecapStage,media_id)).state = 'succeeded'
    # Byte verification is outside this authority-only test; encoded integration covers that boundary.
    async def bytes_checked(*args):
        return {}, 'script'
    monkeypatch.setattr(p,'verified_media',bytes_checked)
    async with maker.begin() as db:
        proof = await approve_current(db,ident,0,media_id,reviewer=SimpleNamespace(id='admin',is_admin=True),reason='Review')
    async with maker.begin() as db:
        await p.select_publication(db,ident,0,media_id,proof)
    async with maker.begin() as db:
        if change == 'source_hold':
            (await db.get(RecapEpisode,ident)).hold = 'source_unavailable'
        elif change == 'source_digest':
            (await db.get(RecapEpisode,ident)).source_digest = 'changed'
        elif change == 'script_head':
            (await db.get(ArtifactHead,'video-subject')).hold = 'script_withdrawn'
        elif change == 'actor':
            (await db.get(GenerationOperation,'job')).actor_id = 'removed'
    if change == 'preflight':
        async def unqualified(*args):
            raise Held('media_qualification_expired')
        monkeypatch.setattr(workflow,'require_media_preflight',unqualified)
    def forbidden_store():
        raise AssertionError('Projector must not repeat object reads while holding control')
    monkeypatch.setattr(p,'configured_store',forbidden_store)
    await drain(maker,tmp_path)
    async with maker() as db:
        row = await db.get(RecapPublication,ident)
        item = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.kind=='recap_publication'))
        if change == 'unchanged':
            assert row.projected_revision == 1 and item.delivered
            assert (tmp_path/'recap_publications').exists()
        else:
            assert row.projected_revision == 0 and not item.delivered
            assert not (tmp_path/'recap_publications').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['source_hold','head_hold','stale_digest','results','pause','epoch'])
async def test_member_article_bootstrap_rejects_stale_held_private_or_quarantined_authority(client,maker,tmp_path,monkeypatch,change):
    # Mutation: member consent bypasses current article/readiness/serving authority.
    import json
    from app.main import app
    from app.db.session import get_db
    from app.services.generation.models import ArtifactHead, ContentArtifact
    from app.services.generation.recap_models import RecapEpisode, RecapPublication, RecapShareDecision
    from app.services.generation.store import digest,dump
    from sqlalchemy import select
    ident = await ready_article(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode,ident)
        if change == 'source_hold':
            episode.hold = 'source_unavailable'
        elif change == 'head_hold':
            (await db.get(ArtifactHead,'article-subject')).hold = 'article_withdrawn'
        elif change in ('stale_digest','results'):
            artifact = await db.get(ContentArtifact,'article')
            value = json.loads(artifact.payload_json)
            value['edition_type'] = 'results' if change == 'results' else 'roast'
            value['markdown'] = 'Private or changed bytes'
            artifact.payload_json = dump(value)
            if change == 'results':
                artifact.digest = episode.article_digest = digest(value)
    if change == 'pause':
        monkeypatch.setenv('TRADE_GRADER_GENERATION_EMERGENCY_PAUSE','true')
    if change == 'epoch':
        monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH','changed')
    async def dependency():
        async with maker.begin() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    response = client.post('/api/league/synthetic/analyst/2026/4/share')
    assert response.status_code in (404,503) and 'token' not in response.json()
    async with maker() as db:
        assert await db.get(RecapPublication,ident) is None
        assert (await db.scalars(select(RecapShareDecision).where(RecapShareDecision.scope.like('edition:%')))).all() == []


@pytest.mark.asyncio
async def test_http_pre_episode_optout_survives_canonical_creation_and_explicit_reenable(client,maker,tmp_path,monkeypatch):
    # Mutation: creating canonical identity loses logical-edition opt-out or defaults sharing on.
    from app.main import app
    from app.db.session import get_db
    from app.services.recap_video import publication as p
    from app.services.generation.recap_models import RecapEpisode, RecapShareDecision
    from app.services.generation.store import data
    ident = await ready_article(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode,ident)
        saved = data(episode)
        await db.delete(episode)
    async def dependency():
        async with maker.begin() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    url = '/api/league/synthetic/analyst/2026/4/share'
    assert client.delete(url).status_code == 200
    async with maker.begin() as db:
        db.add(RecapEpisode(**saved))
    async with maker.begin() as db:
        with pytest.raises(Held,match='edition_sharing_opted_out'):
            await approve_current(db,ident,0,None,reviewer=SimpleNamespace(id='admin',is_admin=True),reason='Review')
    assert client.get(url).json() == {'token':None}
    response = client.post(url)
    assert response.status_code == 200
    assert client.get('/api/public/analyst/'+response.json()['token']).status_code == 200
    async with maker() as db:
        assert await db.get(RecapShareDecision,'edition:'+p.legacy_episode_id('synthetic',2026,4)) is None
        share = await db.get(RecapShareDecision,'edition:'+ident)
        assert share.allowed and not share.opted_out and share.revision == 2
        assert (await db.get(RecapShareDecision,'series:series')).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize('edition_type',['roast','results'])
async def test_member_http_can_share_only_exact_published_legacy_roast_without_media(client,maker,tmp_path,monkeypatch,edition_type):
    from app.main import app
    from app.db.session import get_db
    from app.services.analyst_store import AnalystStore
    await ready_article(maker,tmp_path,monkeypatch)
    article = seed(edition_type)
    async def dependency():
        async with maker.begin() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    response = client.post('/api/league/test/analyst/2026/1/share')
    if edition_type == 'results':
        assert response.status_code == 404
        return
    assert response.status_code == 200
    url = '/api/public/analyst/'+response.json()['token']
    public = client.get(url)
    assert public.status_code == 200 and public.json()['markdown'] == article['markdown']
    assert public.json()['media'] is None and 'private' not in public.text.lower()
    AnalystStore(get_cache_dir()).save_correction('test',{**article,'markdown':'Corrected roast'},'Correct facts')
    assert client.get(url).json()['status'] == 'withdrawn'
