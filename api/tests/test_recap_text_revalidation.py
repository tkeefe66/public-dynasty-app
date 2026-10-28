import copy
import json

import pytest

from app.services.generation.store import Held, digest, dump


@pytest.mark.parametrize('change', ['bench', 'starter', 'total', 'prose', 'bench_claim'])
def test_only_unreferenced_bench_adjustment_can_be_reviewed(change):
    # Mutation: waive a changed starter, result, or bench claim along with a bench score.
    from app.services.recap_video.text_revalidation import bench_changes
    from tests.test_recap_readiness import snapshot
    original = snapshot()
    current = copy.deepcopy(original)
    current['scores']['4'][0]['players_points']['p3'] = '19.9'
    edition = {'markdown': 'The starters tied.', 'facts': {'source_snapshot': original}}
    if change == 'starter':
        current['scores']['4'][0]['players_points']['p1'] = '98'
    if change == 'total':
        current['scores']['4'][0]['points'] = '99'
    if change == 'prose':
        edition['markdown'] = 'A player scored 20.00.'
    if change == 'bench_claim':
        edition['markdown'] = 'The bench was the difference.'
    if change == 'bench':
        assert len(bench_changes(edition, current)) == 1
    else:
        with pytest.raises(Held):
            bench_changes(edition, current)


@pytest.mark.asyncio
async def test_review_restores_only_exact_text_and_expires_on_further_change(maker, tmp_path, monkeypatch):
    # Mutation: review restores media, accepts stale preview, or survives changed article/source.
    from sqlalchemy import func, select
    from app.routes.analyst import analyst_archive
    from app.services.analyst_store import AnalystStore
    from app.services.generation.models import ContentArtifact, GenerationOperation, ProviderAttempt
    from app.services.generation.recap_models import RecapEpisode, RecapObservation
    from app.services.recap_video.text_revalidation import revalidate
    from tests.test_recap_publication import ready_article
    ident = await ready_article(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        artifact = await db.get(ContentArtifact, 'article')
        edition = json.loads(artifact.payload_json)
        AnalystStore(tmp_path).save('synthetic', edition)
        artifact.operation_id = 'reviewed-job'
        db.add(GenerationOperation(id='reviewed-job', kind='generation', feature='analyst',
            league_id='synthetic', series_id='series', subject=artifact.subject,
            state='succeeded', artifact_id=artifact.id, calls=2, max_calls=2))
        for stage in (1, 2):
            body = {'content': [] if stage == 1 else [{'type': 'tool_use', 'name': 'submit_recap_review', 'input': {'approved': True}}]}
            db.add(ProviderAttempt(id=f'receipt-{stage}', operation_id='reviewed-job', stage=stage,
                generation=1, request_digest='request', request_json='{}', model='saved',
                state='received', usage_state='known', cost_microusd=10, receipt_json=dump({'body': body})))
        episode = await db.get(RecapEpisode, ident)
        original = await db.get(RecapObservation, episode.latest_observation_id)
        current = json.loads(original.snapshot_json)
        current['scores']['4'][0]['players_points']['p3'] = '19.9'
        db.add(RecapObservation(id='corrected', episode_id=ident, observed_at=9000,
            snapshot_json=dump(current), snapshot_digest=digest(current), facts_digest='changed', decision='recap_facts_changed'))
        episode.latest_observation_id = 'corrected'
        episode.source_digest = digest(current)
        episode.observed_at, episode.stable_since = 9000, 5000
        episode.lifecycle, episode.hold = 'correction', 'recap_facts_changed'
        await db.flush()
        assert not (await analyst_archive('synthetic', db))['editions']
        preview = await revalidate(db, ident, actor_id='owner', reviewer='Codex', reason='Reviewed all text; changed bench score is unused')
        assert not (await analyst_archive('synthetic', db))['editions']
        with pytest.raises(Held, match='preview_changed'):
            await revalidate(db, ident, actor_id='owner', reviewer='Codex', reason='Reviewed all text; changed bench score is unused', apply=True, expected_digest='stale')
        before = await db.scalar(select(func.count()).select_from(ProviderAttempt))
        await revalidate(db, ident, actor_id='owner', reviewer='Codex', reason='Reviewed all text; changed bench score is unused', apply=True, expected_digest=preview['digest'])
        assert (await analyst_archive('synthetic', db))['editions'][0]['markdown'] == edition['markdown']
        assert episode.lifecycle == 'correction' and episode.hold == 'recap_facts_changed'
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == before
        current['observed_at'] = 10000
        db.add(RecapObservation(id='later', episode_id=ident, observed_at=10000,
            snapshot_json=dump(current), snapshot_digest=digest(current), facts_digest='changed', decision='recap_facts_changed'))
        episode.latest_observation_id, episode.source_digest = 'later', digest(current)
        episode.observed_at = 10000
        await db.flush()
        assert (await analyst_archive('synthetic', db))['editions'][0]['markdown'] == edition['markdown']
        current['scores']['4'][0]['points'] = '99'
        corrected = await db.get(RecapObservation, 'later')
        corrected.snapshot_json, corrected.snapshot_digest = dump(current), digest(current)
        episode.source_digest = digest(current)
        assert not (await analyst_archive('synthetic', db))['editions']
