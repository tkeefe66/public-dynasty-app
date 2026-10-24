import json

import pytest


def test_completion_requires_full_inventory_and_defers_unfinished_games():
    # Mutation: treat empty/truncated scoreboard or HTTP success as week complete.
    from app.services.recap_monitor.evidence import game_gate
    expected = [dict(event_id='a', week=7, home='H', away='A', kickoff='2026-10-27T00:00:00Z')]
    assert game_gate(expected, [], 100)['status'] == 'help'
    live = [{**expected[0], 'completed': False, 'status': 'STATUS_IN_PROGRESS'}]
    assert game_gate(expected, live, 100)['status'] == 'waiting'
    assert game_gate(expected, [{**live[0], 'completed': True, 'status': 'STATUS_FINAL'}], 100)['status'] == 'ready'


@pytest.mark.asyncio
async def test_success_without_delivered_reviewed_article_is_not_publication(maker, tmp_path):
    # Mutation: consider succeeded job sufficient; results packets count as prose.
    from app.services.recap_monitor.evidence import publication_proof
    from app.services.generation.models import GenerationOperation
    async with maker.begin() as db:
        db.add(GenerationOperation(id='job', kind='generation', feature='analyst', league_id='league',
            series_id='series', state='succeeded', payload_json=json.dumps(dict(season=2026, week=7))))
    async with maker() as db:
        assert not await publication_proof(db, tmp_path, 'league', 2026, 7)


@pytest.mark.asyncio
async def test_exhausted_or_ambiguous_work_never_resumes(maker, monkeypatch):
    # Mutation: remaining dollars reopen calls; unknown provider request is resent.
    from app.services.recap_monitor.recovery import recover
    from app.services.generation.models import GenerationOperation, ProviderAttempt
    async with maker.begin() as db:
        db.add(GenerationOperation(id='job', kind='generation', feature='analyst', league_id='league',
            series_id='series', payload_json=json.dumps(dict(season=2026,week=7)),
            state='held', max_calls=2, calls=2, actor_id='owner'))
    item = dict(key='series:2026:7', job_id='job', recovery_attempts=0,league_id='league',series_id='series',season=2026,week=7)
    async with maker.begin() as db:
        result = await recover(db, item, 'owner', 100)
        assert result['status'] == 'help' and result['reason'] == 'attempt_allowance_exhausted'
        job = await db.get(GenerationOperation, 'job')
        assert job.calls == job.max_calls == 2 and job.state == 'held'
        job.max_calls = 4
        db.add(ProviderAttempt(id='unknown', operation_id='job', stage=1, generation=1,
            request_digest='x', request_json='{}', model='synthetic', state='unknown'))
    async with maker.begin() as db:
        result = await recover(db, item, 'owner', 100)
        assert result['status'] == 'help' and result['reason'] == 'provider_outcome_unknown'
        assert (await db.get(GenerationOperation, 'job')).state == 'held'


@pytest.mark.asyncio
async def test_recovery_reuses_free_job_and_is_bounded(maker, monkeypatch):
    # Mutation: create replacement operation or repeatedly resume a failing free job.
    from app.services.recap_monitor.recovery import recover
    from app.services.generation.models import GenerationOperation
    from app.services.generation import administration, resolution
    async def guidance(db, job):
        return dict(action='retry_refresh')
    async def action(db, ident, body, actor):
        job = await db.get(GenerationOperation, ident)
        assert ident == 'free' and actor == 'owner'
        job.state = 'queued'
    from app.db.models import User, LeagueMembership
    monkeypatch.setattr(resolution, 'resolution', guidance)
    monkeypatch.setattr(administration, 'job_action', action)
    async with maker.begin() as db:
        db.add(User(id='owner',google_sub='synthetic-owner',email='owner@example.test'))
        db.add(LeagueMembership(user_id='owner',league_id='league'))
        db.add(GenerationOperation(id='free', kind='analyst_refresh', league_id='league',
            state='needs_attention', reason='execution_failed', actor_id='owner', calls=0, max_calls=0))
    item = dict(key='series:2026:7', job_id='free', league_id='league', recovery_attempts=0)
    async with maker.begin() as db:
        out = await recover(db, item, 'owner', 100)
        assert out['status'] == 'pending' and out['recovery_attempts'] == 1
        assert (await db.get(GenerationOperation, 'free')).state == 'queued'
    async with maker.begin() as db:
        out = await recover(db, {**item, 'recovery_attempts': 2}, 'owner', 100)
        assert out['status'] == 'help' and out['reason'] == 'recovery_exhausted'


@pytest.mark.asyncio
async def test_complete_reviewed_article_needs_delivery_and_current_archive(maker, tmp_path, monkeypatch):
    # Mutation: ignore undelivered outbox, reject all corrected archive editions, or accept a mismatching archive.
    from app.services.analyst_store import AnalystEdition, AnalystStore
    from app.services.generation.models import GenerationOperation, ContentArtifact, ArtifactHead, ProviderAttempt, GenerationOutbox
    from app.services.generation.store import digest
    from app.services.recap_monitor.evidence import publication_proof
    monkeypatch.setenv('TRADE_GRADER_CACHE_DIR', str(tmp_path))
    edition = AnalystEdition(season=2026, week=7, league_name='Synthetic', generated_at='2026-10-27T10:00:00Z',
        model='synthetic', markdown='Reviewed article.', facts={}).model_dump()
    AnalystStore(tmp_path).save('league', edition)
    async with maker.begin() as db:
        db.add(GenerationOperation(id='job', kind='generation', feature='analyst', league_id='league',
            state='succeeded', artifact_id='artifact', calls=2, max_calls=4))
        db.add(ContentArtifact(id='artifact', operation_id='job', series_id='series', league_id='league',
            feature='analyst', subject='subject', revision=1, payload_json=json.dumps(edition), digest=digest(edition), provenance='managed'))
        db.add(ArtifactHead(subject='subject', artifact_id='artifact', revision=1))
        db.add(GenerationOutbox(id='outbox', key='artifact:artifact', kind='artifact', payload_json='{}', delivered=False))
        db.add(ProviderAttempt(id='review', operation_id='job', stage=2, generation=1, request_digest='x', request_json='{}', model='synthetic',
            state='received', usage_state='known', receipt_json=json.dumps({'body': {'content': [{'type':'tool_use', 'name':'submit_recap_review', 'input':{'approved':True}}]}})))
    async with maker.begin() as db:
        assert not await publication_proof(db, tmp_path, 'league', 2026, 7)
        (await db.get(GenerationOutbox, 'outbox')).delivered = True
    async with maker() as db:
        assert (await publication_proof(db, tmp_path, 'league', 2026, 7))['delivered']


@pytest.mark.asyncio
async def test_projection_recovery_does_not_need_more_call_allowance(maker, monkeypatch):
    # Mutation: exhausted AI counter prevents free replay of already reviewed saved publication.
    from app.services.recap_monitor.recovery import recover
    from app.services.generation.models import GenerationOperation, ContentArtifact, ArtifactHead, GenerationOutbox, ProviderAttempt
    from app.services.generation.store import digest
    data = dict(season=2026, week=7, markdown='Reviewed saved text')
    from app.db.models import User, LeagueMembership
    monkeypatch.setenv('TRADE_GRADER_ADMIN_EMAILS','owner@example.test')
    async with maker.begin() as db:
        db.add(User(id='owner',google_sub='synthetic-owner',email='owner@example.test',is_admin=True))
        db.add(LeagueMembership(user_id='owner',league_id='league'))
        db.add(GenerationOperation(id='job', actor_id='owner', kind='generation', feature='analyst', series_id='series',
            league_id='league', payload_json=json.dumps(dict(season=2026,week=7)), state='succeeded', subject='subject', artifact_id='artifact', calls=2,max_calls=2))
        db.add(ContentArtifact(id='artifact', operation_id='job', series_id='series', league_id='league', feature='analyst',
            subject='subject', payload_json=json.dumps(data), digest=digest(data), provenance='managed'))
        db.add(ArtifactHead(subject='subject', artifact_id='artifact', revision=1))
        db.add(GenerationOutbox(id='outbox', key='artifact:artifact', kind='artifact', payload_json='{}', error='projection_failed'))
        db.add(ProviderAttempt(id='draft', operation_id='job', stage=1,generation=1,request_digest='x',request_json='{}',model='synthetic',
            state='received',usage_state='known',cost_microusd=100,receipt_json=json.dumps({'body': {'content': []}})))
        db.add(ProviderAttempt(id='review', operation_id='job', stage=2,generation=1,request_digest='x',request_json='{}',model='synthetic',
            state='received',usage_state='known',cost_microusd=100,receipt_json=json.dumps({'body': {'content': [{'type':'tool_use','name':'submit_recap_review','input':{'approved':True}}]}})))
    async with maker.begin() as db:
        out = await recover(db, dict(job_id='job',season=2026,week=7,series_id='series',league_id='league'), 'owner', 100)
        assert out['status'] == 'pending'
        assert (await db.get(GenerationOutbox, 'outbox')).error == ''
        assert (await db.get(GenerationOperation, 'job')).max_calls == 2


@pytest.mark.asyncio
async def test_successful_refresh_and_queued_publication_are_normal_waits(maker):
    # Mutation: classify all succeeded jobs as failures needing immediate recovery/help email.
    from app.services.recap_monitor.evidence import requires_recovery
    from app.services.generation.models import GenerationOperation,GenerationOutbox
    async with maker.begin() as db:
        free=GenerationOperation(id='free',kind='analyst_refresh',league_id='league',state='succeeded')
        paid=GenerationOperation(id='paid',kind='generation',feature='analyst',league_id='league',state='succeeded',artifact_id='artifact')
        db.add_all([free,paid,GenerationOutbox(id='outbox',key='artifact:artifact',kind='artifact',payload_json='{}')])
    async with maker.begin() as db:
        assert not await requires_recovery(db,await db.get(GenerationOperation,'free'))
        assert not await requires_recovery(db,await db.get(GenerationOperation,'paid'))
        (await db.get(GenerationOutbox,'outbox')).error='projection_failed'
        assert await requires_recovery(db,await db.get(GenerationOperation,'paid'))
