import copy
import json

import pytest
from sqlalchemy import select

from app.services.generation.store import digest, dump, Held

from tests.test_recap_readiness import snapshot


def test_period_text_contract_excludes_only_unavailable_bench_evidence():
    # Mutation: let raw unused bench scores enter writer/reviewer dependencies.
    from app.services.recap_video.collector import edition_from_snapshot
    from sleeper_dynasty.llm.recap_packet import ArchivedPacket, editorial_facts
    original = snapshot()
    original['pairings'][0].update(scores=['100.0100', '100.0100'], winner=None,
                                  source_id='matchup:1', result='tie')
    edition = edition_from_snapshot(original, generated_at=5000)
    packet = editorial_facts(ArchivedPacket(edition['facts']))
    assert edition['facts']['text_contract'] == 'period-text-v1'
    assert 'p3' not in packet['source_snapshot']['scores']['4'][0]['players_points']
    assert 'p3' in edition['facts']['source_snapshot']['scores']['4'][0]['players_points']
    from app.services.recap_video.text_authority import text_source_digest
    changed = copy.deepcopy(original)
    changed['scores']['4'][0]['players_points']['p3'] = '19.9'
    assert text_source_digest(edition, original) == text_source_digest(edition, changed)
    changed['scores']['4'][0]['players_points']['p1'] = '19.9'
    assert text_source_digest(edition, original) != text_source_digest(edition, changed)


def test_legacy_text_keeps_full_dependencies():
    from app.services.recap_video.text_authority import text_source_digest
    original = snapshot()
    changed = copy.deepcopy(original)
    changed['scores']['4'][0]['players_points']['p3'] = '19.9'
    assert text_source_digest({'facts': {}}, original) != text_source_digest({'facts': {}}, changed)


async def published(maker, tmp_path, monkeypatch):
    from tests.test_recap_publication import ready_article
    from app.services.analyst_store import AnalystEdition, AnalystStore
    from app.services.generation.models import ContentArtifact, GenerationOperation, GenerationPolicy, ProviderAttempt
    from app.services.generation.recap_models import RecapEpisode
    ident = await ready_article(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        artifact = await db.get(ContentArtifact, 'article')
        edition = AnalystEdition.model_validate_json(artifact.payload_json).model_dump()
        artifact.payload_json, artifact.digest = dump(edition), digest(edition)
        AnalystStore(tmp_path).save('synthetic', edition)
        artifact.operation_id = 'original'
        episode = await db.get(RecapEpisode, ident)
        episode.article_digest = artifact.digest
        episode.stable_since, episode.observed_at = 1000, 4600
        policy = await db.get(GenerationPolicy, 'app')
        settings = json.loads(policy.value_json)
        settings['features']['analyst']['mode'] = 'automatic'
        settings['features']['recap_video']['mode'] = 'automatic'
        policy.value_json = dump(settings)
        db.add(GenerationOperation(id='original', kind='generation', feature='analyst',
            league_id='synthetic', series_id='series', subject=artifact.subject,
            state='succeeded', artifact_id=artifact.id, calls=2, max_calls=6, epoch='test-epoch',
            payload_json=dump({'edition': edition, 'season': 2026, 'week': 4}), actor_id='owner'))
        for stage in (1, 2):
            body = {'content': [] if stage == 1 else [{'type': 'tool_use', 'name': 'submit_recap_review', 'input': {'approved': True}}]}
            db.add(ProviderAttempt(id=f'original-{stage}', operation_id='original', stage=stage,
                generation=1, request_digest='request', request_json='{}', model='saved',
                state='received', usage_state='known', cost_microusd=10, settled_at=4600, receipt_json=dump({'body': body})))
    return ident


@pytest.mark.asyncio
async def test_old_editorial_recovery_retains_existing_serving_rules(maker, tmp_path, monkeypatch):
    from app.routes.analyst import analyst_archive
    from app.services.generation.models import ContentArtifact
    from app.services.generation.recap_models import RecapEpisode
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        artifact = await db.get(ContentArtifact, 'article')
        artifact.operation_id = None
        artifact.provenance = 'reviewed_receipt_only_correction'
        artifact.facts_json = dump({'editorial_recovery': {'artifact_digest': 'original'}})
        assert len((await analyst_archive('synthetic', db))['editions']) == 1
        episode = await db.get(RecapEpisode, ident)
        episode.lifecycle, episode.hold = 'correction', 'recap_facts_changed'
        assert not (await analyst_archive('synthetic', db))['editions']


@pytest.mark.asyncio
async def test_legacy_managed_article_without_source_retains_existing_serving_rules(maker, tmp_path, monkeypatch):
    from app.routes.analyst import analyst_archive
    from app.services.generation.models import ContentArtifact
    from app.services.generation.recap_models import RecapEpisode
    from app.services.analyst_store import AnalystStore
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        artifact = await db.get(ContentArtifact, 'article')
        edition = json.loads(artifact.payload_json)
        edition['facts'].pop('source_snapshot')
        edition['facts'].pop('text_contract')
        artifact.payload_json, artifact.digest = dump(edition), digest(edition)
        AnalystStore(tmp_path).edition_path('synthetic', 2026, 4).unlink()
        AnalystStore(tmp_path).save('synthetic', edition)
        episode = await db.get(RecapEpisode, ident)
        episode.article_digest = artifact.digest
        assert len((await analyst_archive('synthetic', db))['editions']) == 1
        episode.lifecycle, episode.hold = 'correction', 'recap_facts_changed'
        assert not (await analyst_archive('synthetic', db))['editions']


@pytest.mark.asyncio
async def test_unused_bench_change_keeps_text_readable_without_operator(maker, tmp_path, monkeypatch):
    # Mutation: media correction continues to remove unaffected text.
    from app.routes.analyst import analyst_archive
    from app.services.generation.recap_models import RecapEpisode, RecapObservation
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        original = json.loads((await db.get(RecapObservation, episode.latest_observation_id)).snapshot_json)
        original['scores']['4'][0]['players_points']['p3'] = '19.9'
        await observe_period(db, EpisodeKey('series', 2026, '4'), original, 9000)
        assert len((await analyst_archive('synthetic', db))['editions']) == 1


@pytest.mark.asyncio
async def test_explicit_extra_pair_is_idempotent_and_does_not_change_policy(maker, tmp_path, monkeypatch):
    from app.services.recap_video.automatic_correction import allowance, approve_extra_pair
    from app.services.generation.models import GenerationOperation, GenerationPolicy
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        root = await db.get(GenerationOperation, 'original')
        root.max_calls = 2
        policy = (await db.get(GenerationPolicy, 'app')).value_json
        assert await allowance(db, root.subject, root.id) == 0
        for _ in range(2):
            await approve_extra_pair(db, root.id, actor_id='owner', authorization_key='user-approved-pair',
                                     reason='User explicitly approved one additional draft/review pair')
        assert await allowance(db, root.subject, root.id) == 2
        assert root.max_calls == 2
        assert (await db.get(GenerationPolicy, 'app')).value_json == policy
        source = await changed_source(db, ident, '102')
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600)
    transport = ReviewedTransport()
    await run_correction(maker, tmp_path, transport)
    async with maker() as db:
        assert await allowance(db, root.subject, root.id) == 0
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_material_correction_is_stable_idempotent_and_uses_remaining_allowance(maker, tmp_path, monkeypatch):
    # Mutation: each refresh buys six new calls or releases unstable source facts.
    from app.services.generation.recap_models import RecapEpisode, RecapObservation
    from app.services.generation.models import GenerationCandidate, GenerationOperation
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.recap_video.periods import build_participants
    from app.services.generation.commands import authorize_candidate
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        source = json.loads((await db.get(RecapObservation, episode.latest_observation_id)).snapshot_json)
        source['scores']['4'][0]['points'] = '101.01'
        source['scores']['4'][0]['players_points']['p1'] = '100'
        source.update(build_participants(source['participants'], source['scores'], source['bracket'], source))
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000)
        assert not list((await db.scalars(select(GenerationCandidate))).all())
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600)
        candidates = list((await db.scalars(select(GenerationCandidate))).all())
        assert len(candidates) == 1
        candidate = candidates[0]
        assert not candidate.hold
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 16200)
        assert len(list((await db.scalars(select(GenerationCandidate))).all())) == 1
        job = await authorize_candidate(db, candidate.key, actor_id='owner', actor_kind='scheduler',
            reason='Automatic correction', authorization_key='automatic-test')
        assert job.max_calls == 4
        assert (await db.get(GenerationOperation, 'original')).max_calls == 6


async def changed_source(db, ident, points='101.01'):
    from app.services.generation.recap_models import RecapEpisode, RecapObservation
    from app.services.recap_video.periods import build_participants
    episode = await db.get(RecapEpisode, ident)
    source = json.loads((await db.get(RecapObservation, episode.latest_observation_id)).snapshot_json)
    source['scores']['4'][0]['points'] = points
    source.update(build_participants(source['participants'], source['scores'], source['bracket'], source))
    return source


class ReviewedTransport:
    def __init__(self):
        self.requests = []
        self.after_first = None

    async def send(self, request):
        from tests.test_generation_gateway import BODY
        from app.services.generation.transport import Receipt
        self.requests.append(request)
        if len(self.requests) == 1 and self.after_first:
            await self.after_first()
        review = request.get('tool_choice', {}).get('name') == 'submit_recap_review'
        content = ([{'type': 'tool_use', 'id': 'review', 'name': 'submit_recap_review',
                     'input': {'approved': True, 'checks': []}}] if review else
                   [{'type': 'text', 'text': '## owner-1 vs owner-2\n\nThe corrected result is in.'}])
        body = {**BODY, 'model': request['model'], 'content': content,
                'stop_reason': 'tool_use' if review else 'end_turn'}
        return Receipt(200, json.dumps(body), {'request-id': f'fake-{len(self.requests)}'})


async def run_correction(maker, tmp_path, transport, *, project=True):
    from app.services.generation.worker import automatic_candidates
    from app.services.generation.commands import authorize_candidate
    from app.services.generation.models import stamp
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway
    from app.services.generation.artifacts import save_artifact
    from app.services.generation.publication import drain
    async with maker.begin() as db:
        candidates = await automatic_candidates(db)
        assert len(candidates) == 1
        candidate, key = candidates[0]
        job = await authorize_candidate(db, candidate.key, actor_id='owner', actor_kind='scheduler',
                                        reason='Automatic correction', authorization_key=key)
        job.state, job.lease_until = 'running', stamp() + 600
    result = await generate(job, Gateway(maker, transport, epoch='test-epoch'))
    async with maker.begin() as db:
        await save_artifact(db, job.id, job.generation, result)
    if project:
        await drain(maker, tmp_path)
    return job.id


@pytest.mark.asyncio
async def test_weekly_correction_lifecycle_with_real_writer_gateway_projection_and_rollover(maker, tmp_path, monkeypatch):
    # Mutation: allow six fresh calls per correction; hide corrected text behind old media;
    # buy a duplicate after rollover; or send raw bench facts to draft/review.
    from app.routes.analyst import analyst_archive
    from app.services.generation.models import GenerationOperation, GenerationPolicy, LeagueSeason
    from app.services.generation.recap_models import RecapPublication
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.recap_video.publication import public_article, authorize_member_read
    from app.services.generation.worker import automatic_candidates
    from app.services.recap_monitor.evidence import publication_proof
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        old = (await analyst_archive('synthetic', db))['editions'][0]
        db.add(RecapPublication(episode_id=ident, series_id='series', league_id='synthetic', season=2026, week=4,
            article_revision=1, share_revision=0, facts_digest='',
            article_json=dump(public_article(old)), article_digest=digest(public_article(old)),
            epoch='test-serving', authority_revision=1, projected_revision=1, media_json='{}'))
        original_policy = (await db.get(GenerationPolicy, 'app')).value_json
    transport = ReviewedTransport()
    for index in range(2):
        async with maker.begin() as db:
            source = await changed_source(db, ident, str(102 + index))
            await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000 + index * 10000)
            assert not (await analyst_archive('synthetic', db))['editions']
            await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600 + index * 10000)
            # A rollover must not remove previously admitted correction authority.
            (await db.get(LeagueSeason, 'synthetic')).latest_week = 5
        await run_correction(maker, tmp_path, transport)
        async with maker.begin() as db:
            assert len((await analyst_archive('synthetic', db))['editions']) == 1
            proof = await publication_proof(db, tmp_path, 'synthetic', 2026, 4)
            assert proof and proof['member_serving_readable']
            assert not await automatic_candidates(db)
            assert (await db.get(RecapPublication, ident)).withdrawn
            with pytest.raises(Held):
                await authorize_member_read(db, 'synthetic', 2026, 4)
            await observe_period(db, EpisodeKey('series', 2026, '4'), source, 13000 + index * 10000)
            assert not await automatic_candidates(db)
    assert len(transport.requests) == 4
    assert all('"p3"' not in json.dumps(request) for request in transport.requests)
    async with maker.begin() as db:
        assert (await db.get(GenerationPolicy, 'app')).value_json == original_policy
        assert sum(j.calls for j in (await db.scalars(select(GenerationOperation).where(
            GenerationOperation.subject == 'article-subject'))).all()) == 6
        source = await changed_source(db, ident, '110')
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 33000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 36600)
        assert not await automatic_candidates(db)
        assert not (await analyst_archive('synthetic', db))['editions']



@pytest.mark.asyncio
@pytest.mark.parametrize('gate', ['paused', 'budget', 'unknown', 'source_changed'])
async def test_correction_dispatch_gates_make_zero_provider_calls(maker, tmp_path, monkeypatch, gate):
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.generation.worker import automatic_candidates
    from app.services.generation.commands import authorize_candidate
    from app.services.generation.models import GenerationPolicy, ProviderAttempt, stamp
    from app.services.generation.recap_models import RecapBudgetPolicy
    from app.services.generation.recap_budget import RecapCaps
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        source = await changed_source(db, ident, '102')
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600)
        candidate, key = (await automatic_candidates(db))[0]
        job = await authorize_candidate(db, candidate.key, actor_id='owner', actor_kind='scheduler',
                                        reason='Automatic correction', authorization_key=key)
        job.state, job.lease_until = 'running', stamp() + 600
        if gate == 'paused':
            row = await db.get(GenerationPolicy, 'app')
            policy = json.loads(row.value_json)
            policy['paused'] = True
            row.value_json = dump(policy)
        elif gate == 'budget':
            db.add(RecapBudgetPolicy(series_id='series', revision=1,
                caps_json=dump(RecapCaps(combined_episode_microusd=1).model_dump())))
        elif gate == 'unknown':
            receipt = await db.get(ProviderAttempt, 'original-1')
            receipt.state, receipt.cost_microusd = 'unknown', None
        else:
            source = await changed_source(db, ident, '103')
            await observe_period(db, EpisodeKey('series', 2026, '4'), source, 14000)
    transport = ReviewedTransport()
    with pytest.raises(Held):
        await generate(job, Gateway(maker, transport, epoch='test-epoch'))
    assert transport.requests == []


@pytest.mark.asyncio
async def test_restored_text_requires_current_execution_authority(maker, tmp_path, monkeypatch):
    from app.routes.analyst import analyst_archive
    from app.services.generation.models import GenerationOperation
    await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        (await db.get(GenerationOperation, 'original')).epoch = 'old-restored-epoch'
        assert not (await analyst_archive('synthetic', db))['editions']


@pytest.mark.asyncio
async def test_external_epoch_change_blocks_old_text_and_correction_allowance(maker, tmp_path, monkeypatch):
    from app.routes.analyst import analyst_archive
    from app.services.recap_video.automatic_correction import allowance
    from app.services.generation.models import GenerationOperation
    await published(maker, tmp_path, monkeypatch)
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EXECUTION_EPOCH', 'new-external-epoch')
    async with maker() as db:
        original = await db.get(GenerationOperation, 'original')
        assert not (await analyst_archive('synthetic', db))['editions']
        with pytest.raises(Held, match='recap_correction_root_epoch_changed'):
            await allowance(db, original.subject, original.id)


@pytest.mark.asyncio
async def test_bench_change_preserves_pending_correction(maker, tmp_path, monkeypatch):
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.generation.worker import automatic_candidates
    from app.services.generation.commands import authorize_candidate
    from app.services.generation.models import GenerationCandidate
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        source = await changed_source(db, ident, '102')
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600)
        candidate, key = (await automatic_candidates(db))[0]
        job = await authorize_candidate(db, candidate.key, actor_id='owner', actor_kind='scheduler',
                                        reason='Automatic correction', authorization_key=key)
        job.state, job.reason = 'held', 'facts_unstable'
        source['scores']['4'][0]['players_points']['p3'] = '22'
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 14000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 17600)
        assert job.state == 'held'
        assert len(list((await db.scalars(select(GenerationCandidate))).all())) == 1


@pytest.mark.asyncio
async def test_new_source_between_save_and_projection_recovers_without_rebuying_original(maker, tmp_path, monkeypatch):
    from app.routes.analyst import analyst_archive
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.generation.publication import drain
    from app.services.generation.models import ContentArtifact, GenerationOperation
    ident = await published(maker, tmp_path, monkeypatch)
    transport = ReviewedTransport()
    async with maker.begin() as db:
        source = await changed_source(db, ident, '102')
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600)
    obsolete = await run_correction(maker, tmp_path, transport, project=False)
    async with maker.begin() as db:
        source = await changed_source(db, ident, '103')
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 14000)
    await drain(maker, tmp_path)
    async with maker.begin() as db:
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 17600)
    await run_correction(maker, tmp_path, transport)
    async with maker() as db:
        served = (await analyst_archive('synthetic', db))['editions']
        assert len(served) == 1 and served[0]['revision'] == 3
        job = await db.get(GenerationOperation, obsolete)
        assert job.calls == 2 and await db.get(ContentArtifact, job.artifact_id)
    assert len(transport.requests) == 4


@pytest.mark.asyncio
async def test_worker_resumes_correction_after_source_outage_without_rebuying_draft(maker, tmp_path, monkeypatch):
    from app.services.generation.worker import Worker, automatic_candidates
    from app.services.generation.commands import authorize_candidate
    from app.services.generation.models import GenerationOperation
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.generation.publication import drain
    from app.routes.analyst import analyst_archive
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        source = await changed_source(db, ident, '102')
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600)
        candidate, key = (await automatic_candidates(db))[0]
        await authorize_candidate(db, candidate.key, actor_id='owner', actor_kind='scheduler',
                                  reason='Automatic correction', authorization_key=key)
    async def outage():
        broken = copy.deepcopy(source)
        broken['observed_games'] = []
        async with maker.begin() as db:
            await observe_period(db, EpisodeKey('series', 2026, '4'), broken, 14000)
    transport = ReviewedTransport()
    transport.after_first = outage
    worker = Worker(maker, tmp_path, transport=transport, epoch='test-epoch')
    assert await worker.tick()
    async with maker.begin() as db:
        job = await db.scalar(select(GenerationOperation).where(GenerationOperation.id != 'original',
            GenerationOperation.feature == 'analyst'))
        assert job.state == 'queued' and job.calls == 1
        job.next_attempt_at = 0
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 15000)
    assert await worker.tick()
    await drain(maker, tmp_path)
    async with maker() as db:
        assert len((await analyst_archive('synthetic', db))['editions']) == 1
    assert len(transport.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['bench', 'outage'])
async def test_transient_source_after_save_keeps_projection_replayable(maker, tmp_path, monkeypatch, change):
    from app.routes.analyst import analyst_archive
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.generation.publication import drain
    from app.services.generation.models import GenerationOperation, GenerationOutbox
    ident = await published(maker, tmp_path, monkeypatch)
    transport = ReviewedTransport()
    async with maker.begin() as db:
        source = await changed_source(db, ident, '102')
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600)
    operation = await run_correction(maker, tmp_path, transport, project=False)
    transient = copy.deepcopy(source)
    if change == 'bench':
        transient['scores']['4'][0]['players_points']['p3'] = '23'
    else:
        transient['observed_games'] = []
    async with maker.begin() as db:
        await observe_period(db, EpisodeKey('series', 2026, '4'), transient, 14000)
    await drain(maker, tmp_path)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, operation)
        outbox = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + job.artifact_id))
        assert outbox.error == ''
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 15000)
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 18600)
    await drain(maker, tmp_path)
    async with maker() as db:
        assert len((await analyst_archive('synthetic', db))['editions']) == 1
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_legacy_reviewed_baseline_recovers_equivalent_text_only(maker, tmp_path, monkeypatch):
    from app.routes.analyst import analyst_archive
    from app.services.generation.models import ArtifactHead, ContentArtifact, ProviderAttempt
    from app.services.generation.recap_models import RecapEpisode, RecapObservation
    from app.services.generation.publication import project_analyst
    from app.services.generation.models import GenerationOutbox
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        original = await db.get(ContentArtifact, 'article')
        edition = json.loads(original.payload_json)
        edition['revision'] = 2
        edition['facts'].pop('source_snapshot')
        edition['facts'].pop('text_contract')
        observation = await db.get(RecapObservation, episode.latest_observation_id)
        receipts = list((await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == 'original'))).all())
        proof = {'article_id': original.id, 'article_digest': original.digest,
            'corrected_digest': digest(edition), 'baseline_observation_id': observation.id,
            'observation_digests': [[observation.id, observation.snapshot_digest]],
            'editorial_review': {'reviewer': 'independent', 'reason': 'Previously reviewed complete article'},
            'legacy_claim_proof': {'facts_digest': digest(json.loads(original.payload_json)['facts'])},
            'receipt_digests': sorted((r.id, digest([r.receipt_json, r.cost_microusd])) for r in receipts),
            'serving_epoch': 'test-serving'}
        revision = ContentArtifact(id='legacy-reviewed', feature='analyst', subject=original.subject,
            series_id='series', league_id='synthetic', revision=2, payload_json=dump(edition),
            digest=digest(edition), facts_json=dump({'recovery_proof': proof}),
            provenance='reviewed_receipt_only_correction')
        project_analyst(tmp_path, revision, original)
        db.add(revision)
        head = await db.get(ArtifactHead, original.subject)
        head.artifact_id, head.revision = revision.id, 2
        db.add(GenerationOutbox(key='artifact:'+revision.id, kind='artifact', delivered=True,
            payload_json=dump({'artifact_id': revision.id})))
        episode.article_digest = ''
        episode.lifecycle, episode.hold = 'correction', 'recap_facts_changed'
        await db.flush()
        assert len((await analyst_archive('synthetic', db))['editions']) == 1
        proof['corrected_digest'] = 'wrong'
        revision.facts_json = dump({'recovery_proof': proof})
        assert not (await analyst_archive('synthetic', db))['editions']


@pytest.mark.asyncio
async def test_source_outage_does_not_erase_last_proved_text(maker, tmp_path, monkeypatch):
    from app.routes.analyst import analyst_archive
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        source = await changed_source(db, ident, '100.0100')
        source['scores']['4'][0]['players_points']['p3'] = '19'
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000)
        source['observed_games'] = []
        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 10000)
        assert len((await analyst_archive('synthetic', db))['editions']) == 1


@pytest.mark.asyncio
async def test_explicit_withdrawal_never_recovers_as_automatic_text(maker, tmp_path, monkeypatch):
    from app.routes.analyst import analyst_archive
    from app.services.generation.recap_models import RecapPublication
    from app.services.recap_video.publication import public_article, withdraw_edition
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        old = (await analyst_archive('synthetic', db))['editions'][0]
        db.add(RecapPublication(episode_id=ident, series_id='series', league_id='synthetic', season=2026, week=4,
            article_revision=1, share_revision=0, facts_digest='', article_json=dump(public_article(old)),
            article_digest=digest(public_article(old)), epoch='test-serving', authority_revision=1,
            projected_revision=1, media_json='{}'))
        await db.flush()
        await withdraw_edition(db, 'synthetic', 2026, 4, expected_revision=1,
                              actor_id='api-observer', reason='recap_facts_changed')
        await withdraw_edition(db, 'synthetic', 2026, 4, expected_revision=2,
                              actor_id='owner', reason='Take this article down')
        assert not (await analyst_archive('synthetic', db))['editions']


@pytest.mark.asyncio
async def test_source_reversion_reuses_only_unspent_allowance(maker, tmp_path, monkeypatch):
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.generation.worker import automatic_candidates
    from app.services.generation.commands import authorize_candidate
    ident = await published(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        for index, points in enumerate(('102', '103', '102')):
            source = await changed_source(db, ident, points)
            await observe_period(db, EpisodeKey('series', 2026, '4'), source, 9000 + index * 5000)
            await observe_period(db, EpisodeKey('series', 2026, '4'), source, 12600 + index * 5000)
            candidates = await automatic_candidates(db)
            assert len(candidates) == 1
            candidate, key = candidates[0]
            job = await authorize_candidate(db, candidate.key, actor_id='owner', actor_kind='scheduler',
                                            reason='Automatic correction', authorization_key=key)
            assert job.max_calls == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('mid_draft', ['total', 'bench', 'reversion'])
async def test_full_week_from_unfinished_games_to_next_week(maker, tmp_path, monkeypatch, mid_draft):
    from tests.test_generation_gateway import seed_job
    from app.services.generation.models import GenerationOperation, GenerationPolicy, LeagueSeason
    from app.services.generation.policy import Policy
    from app.services.generation.recap_models import RecapPublicationControl
    from app.services.analyst_store import AnalystStore
    from app.services.recap_video.collector import edition_from_snapshot
    from app.services.recap_video.periods import build_participants
    from app.services.recap_video.readiness import observe_period, EpisodeKey
    from app.services.generation.planner import collect_analyst
    from app.routes.analyst import analyst_archive
    await seed_job(maker)
    monkeypatch.setenv('TRADE_GRADER_ADMIN_EMAILS', 'owner@test.local')
    monkeypatch.setenv('TRADE_GRADER_CACHE_DIR', str(tmp_path))
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE', 'database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH', 'test-serving')
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EXECUTION_EPOCH', 'test-epoch')
    async with maker.begin() as db:
        (await db.get(GenerationOperation, 'job')).state = 'cancelled'
        policy = Policy(paused=False)
        for feature in ('analyst', 'recap_video'):
            policy.features[feature].mode = 'automatic'
        (await db.get(GenerationPolicy, 'app')).value_json = dump(policy.model_dump())
        db.add(RecapPublicationControl(id='global', epoch='test-serving', reconciliation_digest='test', quarantined=False))
    transport = ReviewedTransport()
    for week in (4, 5):
        source = snapshot()
        source.update(week=week, period_id=str(week), nfl_weeks=[week], current_period_id=str(week))
        source['scores'] = {str(week): source['scores']['4']}
        source['starters'] = {str(week): source['starters']['4']}
        source.update(build_participants(source['participants'], source['scores'], source['bracket'], source))
        async with maker.begin() as db:
            (await db.get(LeagueSeason, 'synthetic')).latest_week = week
            unfinished = copy.deepcopy(source)
            unfinished['observed_games'][0]['completed'] = False
            unfinished['observed_games'][0]['status'] = 'STATUS_IN_PROGRESS'
            await observe_period(db, EpisodeKey('series', 2026, str(week)), unfinished, week * 10000)
            assert len((await analyst_archive('synthetic', db))['editions']) == week - 4
            await observe_period(db, EpisodeKey('series', 2026, str(week)), source, week * 10000 + 1000)
            await observe_period(db, EpisodeKey('series', 2026, str(week)), source, week * 10000 + 4600)
            AnalystStore(tmp_path).save('synthetic', edition_from_snapshot(source, generated_at=week * 10000 + 4600))
            await collect_analyst(db, 'synthetic', 'series', tmp_path)
        if week == 4:
            async def correct_during_draft():
                if mid_draft in ('total', 'reversion'):
                    source['scores']['4'][0]['points'] = '103'
                else:
                    source['scores']['4'][0]['players_points']['p3'] = '21'
                source.update(build_participants(source['participants'], source['scores'], source['bracket'], source))
                async with maker.begin() as db:
                    await observe_period(db, EpisodeKey('series', 2026, '4'), source, 45000)
            transport.after_first = correct_during_draft
            if mid_draft in ('total', 'reversion'):
                with pytest.raises(Held, match='facts_unstable|recap_facts_changed'):
                    await run_correction(maker, tmp_path, transport)
                async with maker.begin() as db:
                    job = await db.scalar(select(GenerationOperation).where(GenerationOperation.feature == 'analyst'))
                    # Same transition performed by Worker.tick after the fenced send.
                    job.state, job.reason = 'held', 'recap_facts_changed'
                    if mid_draft == 'reversion':
                        source['scores']['4'][0]['points'] = snapshot()['scores']['4'][0]['points']
                        source.update(build_participants(source['participants'], source['scores'], source['bracket'], source))
                        await observe_period(db, EpisodeKey('series', 2026, '4'), source, 45001)
                    await observe_period(db, EpisodeKey('series', 2026, '4'), source, 48601)
        await run_correction(maker, tmp_path, transport)
        async with maker() as db:
            assert len((await analyst_archive('synthetic', db))['editions']) == week - 3
    assert len(transport.requests) == (4 if mid_draft == 'bench' else 5)
    async with maker.begin() as db:
        from app.services.generation.recap_budget import episode_identity
        older = await changed_source(db, episode_identity('series', 2026, '4'), '107')
        await observe_period(db, EpisodeKey('series', 2026, '4'), older, 60000)
        assert [e['week'] for e in (await analyst_archive('synthetic', db))['editions']] == [5]
