"""Receipt-only recovery of a demonstrably false legacy withdrawal."""
import json

import pytest
from sqlalchemy import func, select

from app.services.generation.models import (ArtifactHead, ContentArtifact, GenerationAudit,
    GenerationOperation, ProviderAttempt)
from app.services.generation.recap_models import (RecapEpisode, RecapObservation,
    RecapPublication, RecapShareDecision)
from app.services.generation.store import Held, digest, dump
from tests.test_recap_publication import ready_article, legacy_for_canonical


def legacy_claim_fixture():
    source = {'week': 4, 'roster_positions': ['QB', 'FLEX'], 'participants': [
        {'owner_name': 'A', 'roster_id': 1, 'settings': {'wins': 1, 'losses': 0, 'ties': 0, 'fpts': 30, 'fpts_decimal': 0}},
        {'owner_name': 'B', 'roster_id': 2, 'settings': {'wins': 0, 'losses': 1, 'ties': 0, 'fpts': 20, 'fpts_decimal': 0}}],
        'scores': {'4': [
            {'roster_id': 1, 'matchup_id': 1, 'points': '30', 'starters': ['q1', 'r1'], 'players': ['q1', 'r1', 'r3'], 'players_points': {'q1': '20', 'r1': '10', 'r3': '15'}},
            {'roster_id': 2, 'matchup_id': 1, 'points': '20', 'starters': ['q2', 'r2'], 'players': ['q2', 'r2'], 'players_points': {'q2': '15', 'r2': '5'}}]}}
    def player(name, points, position, owner):
        return {'owner': owner, 'player': name + ' (' + position + ', XX)', 'position': position, 'points': points}
    facts = {'week': 4, 'lineups': [{'owner': 'A', 'starters': [player('Q1', 20, 'QB', 'A'), player('R1', 10, 'RB', 'A')]},
        {'owner': 'B', 'starters': [player('Q2', 15, 'QB', 'B'), player('R2', 5, 'RB', 'B')]}],
        'player_context': {'players': [{'player': name.upper(), 'player_id': name, 'position': 'QB' if name.startswith('q') else 'RB'} for name in ['q1','q2','r1','r2','r3']]},
        'matchups': [{'winner': 'A', 'loser': 'B', 'winner_points': 30, 'loser_points': 20, 'margin': 10, 'tied': False}],
        'standings': [{'owner': 'A', 'wins': 1, 'losses': 0, 'ties': 0, 'points_for': 30}, {'owner': 'B', 'wins': 0, 'losses': 1, 'ties': 0, 'points_for': 20}],
        'bench_regret': [{'owner': 'A', 'legal_swaps': [{'benched_player': player('R3',15,'RB','A'), 'started_player': player('R1',10,'RB','A'), 'slot': 'FLEX', 'points_gained': 5,
            'matchup_effect': {'team_points':35,'opponent_points':20,'margin':15,'result':'win'}}]}]}
    return facts, source


def test_legacy_claim_evidence_uses_frozen_ids_and_period_lineups():
    from app.services.recap_video.legacy_recovery import legacy_claim_evidence
    facts, source = legacy_claim_fixture()
    proof = legacy_claim_evidence(facts, source)
    assert proof['starters'] == 4 and proof['swaps'] == 1 and proof['standings'] == 2


@pytest.mark.parametrize('change', ['identity', 'duplicate_name', 'starter_order', 'points', 'missing_owner', 'standings', 'slot', 'bench', 'effect', 'pairing'])
def test_legacy_claim_evidence_rejects_unproved_facts(change):
    from app.services.recap_video.legacy_recovery import legacy_claim_evidence
    facts, source = legacy_claim_fixture()
    if change == 'identity': facts['player_context']['players'][0]['player_id'] = 'unknown'
    elif change == 'duplicate_name': facts['player_context']['players'].append(dict(facts['player_context']['players'][0]))
    elif change == 'starter_order': facts['lineups'][0]['starters'].reverse()
    elif change == 'points': facts['lineups'][0]['starters'][0]['points'] = 21
    elif change == 'missing_owner': facts['lineups'].pop()
    elif change == 'standings': facts['standings'][0]['wins'] = 2
    elif change == 'slot': facts['bench_regret'][0]['legal_swaps'][0]['slot'] = 'RB'
    elif change == 'bench': source['scores']['4'][0]['players'].remove('r3')
    elif change == 'effect': facts['bench_regret'][0]['legal_swaps'][0]['matchup_effect']['margin'] = 100
    elif change == 'pairing': source['scores']['4'][1]['matchup_id'] = 2
    with pytest.raises(Held, match='legacy_claim_evidence'):
        legacy_claim_evidence(facts, source)


@pytest.mark.parametrize('bad_source', [False, True])
def test_news_correction_requires_original_named_source_opportunity_count(bad_source):
    from types import SimpleNamespace
    from app.services.recap_video.legacy_recovery import reviewed_slot_correction
    facts, source = legacy_claim_fixture()
    facts['player_context']['players'][2]['news'] = [{'id':'saved-news', 'text':'Finished with 15 opportunities.'}]
    before = '**R1** contributed 10 points on 15 touches.'
    data = dict(facts=facts, markdown='**R1** dropped **10** from the RB slot. ' + before,
        revision=1, season=2026, week=4, league_name='Synthetic', generated_at='2026-01-01', model='saved')
    row = SimpleNamespace(media_id='saved', media_json='{}')
    review = dict(article_digest=digest(data), media_digest=digest(['saved','{}']),
        reviewed_sections=['prose','news','forecasts','bets','media'], reason='Verified original source terminology',
        slot_corrections=[dict(owner='A',player='R1',points='10',old_slot='RB',new_slot='FLEX')],
        news_corrections=[dict(player='R1',news_id='missing' if bad_source else 'saved-news',count=15,before=before)])
    if bad_source:
        with pytest.raises(Held, match='legacy_news_correction_unproved'):
            reviewed_slot_correction(data, source, row, review)
    else:
        result = reviewed_slot_correction(data, source, row, review)
        assert '15 opportunities' in result['markdown'] and '15 touches' not in result['markdown']


async def recovery_fixture(maker, tmp_path, monkeypatch):
    from app.services.analyst_store import AnalystStore
    from app.services.recap_video.publication import public_article, withdraw_edition
    from tests.test_recap_competitive_facts import live_change
    ident = await ready_article(maker, tmp_path, monkeypatch)
    legacy, _ = await legacy_for_canonical(maker)
    async with maker.begin() as db:
        article = await db.get(ContentArtifact, 'article')
        article.created_at = 100
        article.operation_id = 'original-approved'
        data = json.loads(article.payload_json)
        AnalystStore(tmp_path).save('synthetic', data)
        row = await db.get(RecapPublication, legacy)
        row.article_json = dump(public_article(data))
        row.article_digest = digest(public_article(data))
        row.published_at = 200
        row.media_id, row.media_json = 'saved-video', dump({'id': 'saved-video', 'storage': 'legacy'})
        row.enabled = False
        share = await db.get(RecapShareDecision, 'edition:' + legacy)
        share.allowed, share.opted_out = False, True
        db.add(GenerationOperation(id='original-approved', kind='generation', league_id='synthetic',
            series_id='series', feature='analyst', subject=article.subject, state='succeeded',
            artifact_id='article', calls=1, max_calls=1, created_at=50, updated_at=100))
        db.add(ProviderAttempt(id='saved-receipt', operation_id='original-approved', stage=1,
            generation=1, request_digest='request', request_json='{}', model='saved-model',
            state='received', usage_state='known', receipt_json='{}', cost_microusd=5))
        episode = await db.get(RecapEpisode, ident)
        episode.admitted_at, episode.article_digest = 0, ''
        episode.lifecycle, episode.hold = 'correction', 'recap_facts_changed'
        old = await db.get(RecapObservation, episode.latest_observation_id)
        old.observed_at = 300
        source = json.loads(old.snapshot_json)
        changed = live_change(source)
        db.add(RecapObservation(id='latest', episode_id=ident, observed_at=5000,
            snapshot_json=dump(changed), snapshot_digest=digest(changed),
            facts_digest='legacy-raw', decision='recap_facts_changed'))
        episode.latest_observation_id = 'latest'
        await withdraw_edition(db, 'synthetic', 2026, 4, expected_revision=7,
            actor_id='api-observer', reason='recap_facts_changed')
        await db.flush()
        audit = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == 'recap_publication_withdrawn'))
        audit.created_at = 400
    return ident, legacy


@pytest.mark.asyncio
async def test_recovery_dry_run_and_apply_preserve_paid_content_and_sharing(maker, tmp_path, monkeypatch):
    # Mutation: preview mutates, apply generates content, or recovery restores a public link.
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        row = await db.get(RecapPublication, legacy)
        before = (row.article_json, row.media_id, row.media_json, row.enabled)
        share = await db.get(RecapShareDecision, 'edition:' + legacy)
        share_before = (share.allowed, share.opted_out, share.token, share.revision)
        counts = [await db.scalar(select(func.count()).select_from(model))
            for model in (GenerationOperation, ProviderAttempt, GenerationAudit)]
        preview = await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Reviewed false live-roster drift')
        assert row.withdrawn and row.authority_revision == 8
        assert counts == [await db.scalar(select(func.count()).select_from(model))
            for model in (GenerationOperation, ProviderAttempt, GenerationAudit)]
        result = await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Reviewed false live-roster drift',
            apply=True, expected_digest=preview['digest'])
        assert result['applied'] and not row.withdrawn
        assert row.authority_revision == row.projected_revision == 9
        assert before == (row.article_json, row.media_id, row.media_json, row.enabled)
        assert share_before == (share.allowed, share.opted_out, share.token, share.revision)
        assert (await db.get(RecapEpisode, ident)).hold == 'historical_approval_required'
        assert counts[:2] == [await db.scalar(select(func.count()).select_from(model))
            for model in (GenerationOperation, ProviderAttempt)]


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['score', 'reverted_score', 'reason', 'head', 'article', 'receipt', 'revision', 'admin', 'missing_source', 'different_source'])
async def test_recovery_rejects_unproved_or_changed_evidence(maker, tmp_path, monkeypatch, change):
    # Mutation: clear withdrawal without checking historical truth, authority and original output.
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        if change in ('score', 'reverted_score'):
            latest = await db.get(RecapObservation, 'latest')
            source = json.loads(latest.snapshot_json)
            source['scores']['4'][0]['points'] = '900.00'
            if change == 'score':
                latest.snapshot_json = dump(source)
                latest.snapshot_digest = digest(source)
            else:
                db.add(RecapObservation(id='intermediate', episode_id=ident, observed_at=4500,
                    snapshot_json=dump(source), snapshot_digest=digest(source), facts_digest='changed', decision='facts_unstable'))
        elif change == 'reason':
            audit = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == 'recap_publication_withdrawn'))
            audit.reason = 'manual_withdrawal'
        elif change == 'head':
            (await db.get(ArtifactHead, 'article-subject')).artifact_id = 'new-unreviewed'
        elif change == 'article':
            row = await db.get(RecapPublication, legacy)
            data = {**json.loads(row.article_json), 'markdown': 'Unreviewed replacement'}
            row.article_json, row.article_digest = dump(data), digest(data)
        elif change == 'receipt':
            (await db.get(ProviderAttempt, 'saved-receipt')).usage_state = 'unknown'
        elif change in ('missing_source', 'different_source'):
            from app.services.recap_video.publication import public_article
            artifact = await db.get(ContentArtifact, 'article')
            data = json.loads(artifact.payload_json)
            if change == 'missing_source':
                del data['facts']['source_snapshot']
            else:
                data['facts']['source_snapshot']['scores']['4'][0]['points'] = '88.00'
            artifact.payload_json, artifact.digest = dump(data), digest(data)
            row = await db.get(RecapPublication, legacy)
            row.article_json, row.article_digest = dump(public_article(data)), digest(public_article(data))
        with pytest.raises(Held):
            await recover_false_withdrawal(db, ident, expected_revision=99 if change == 'revision' else 8,
                artifact_id='article', actor_id='missing' if change == 'admin' else 'owner', reason='Review')
        assert (await db.get(RecapPublication, legacy)).withdrawn


@pytest.mark.asyncio
async def test_recovery_apply_rejects_changed_preview(maker, tmp_path, monkeypatch):
    # Mutation: a preview remains valid after sharing authority changes.
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        preview = await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Review')
        (await db.get(RecapShareDecision, 'edition:' + legacy)).revision += 1
        with pytest.raises(Held, match='recovery_preview_changed'):
            await recover_false_withdrawal(db, ident, expected_revision=8,
                artifact_id='article', actor_id='owner', reason='Review', apply=True,
                expected_digest=preview['digest'])


@pytest.mark.asyncio
async def test_recovered_authority_still_requires_original_files_on_read(maker, tmp_path, monkeypatch):
    # Mutation: DB recovery bypasses article_current and serves an unreviewed file.
    from app.services.analyst_store import AnalystStore
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    from app.services.recap_video.publication import authorize_member_read
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        preview = await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Review')
        await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Review', apply=True,
            expected_digest=preview['digest'])
        assert (await authorize_member_read(db, 'synthetic', 2026, 4))['media']['id'] == 'saved-video'
        path = AnalystStore(tmp_path).edition_path('synthetic', 2026, 4)
        path.write_text(dump({**json.loads(path.read_text()), 'markdown': 'Unreviewed replacement'}))
        with pytest.raises(Held, match='public_unavailable'):
            await authorize_member_read(db, 'synthetic', 2026, 4)


async def named_recovery_fixture(maker, tmp_path, monkeypatch):
    import hashlib
    from app.services.analyst_media import ASSETS
    from app.services.analyst_store import AnalystStore
    from app.services.recap_video.periods import build_participants
    from app.services.recap_video.publication import public_article
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    facts, named = legacy_claim_fixture()
    async with maker.begin() as db:
        observations = (await db.scalars(select(RecapObservation).where(RecapObservation.episode_id == ident))).all()
        for observation in observations:
            source = json.loads(observation.snapshot_json)
            source.update(named)
            for p in source['participants']:
                p['owner_id'] = 'owner-' + str(p['roster_id'])
            for row in source['scores']['4']:
                row['starters_points'] = [row['players_points'][p] for p in row['starters']]
            source.update(build_participants(source['participants'], source['scores'], source['bracket'], source))
            observation.snapshot_json, observation.snapshot_digest = dump(source), digest(source)
        artifact = await db.get(ContentArtifact, 'article')
        data = json.loads(artifact.payload_json)
        data['facts'] = facts
        data['markdown'] = '**R1** dropped **10** from the RB slot.'
        from app.services.analyst_store import AnalystEdition
        data = AnalystEdition.model_validate(data).model_dump()
        artifact.payload_json, artifact.digest = dump(data), digest(data)
        operation = await db.get(GenerationOperation, 'original-approved')
        operation.payload_json = dump({'facts': facts})
        AnalystStore(tmp_path).edition_path('synthetic', 2026, 4).write_text(dump(data))
        row = await db.get(RecapPublication, legacy)
        row.article_json, row.article_digest = dump(public_article(data)), digest(public_article(data))
        files = {}
        for name in ASSETS:
            path = tmp_path / name
            path.write_bytes(b'original-reviewed-media-' + name.encode())
            files[name] = dict(path=str(path), bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        row.media_json = dump({'id':row.media_id, 'storage':'legacy', 'files':files})
        review = dict(article_digest=artifact.digest, media_digest=digest([row.media_id,row.media_json]),
            reviewed_sections=['prose','news','forecasts','bets','media'], reason='Corrected starter slot against saved period lineup.',
            slot_corrections=[dict(owner='A',player='R1',points='10',old_slot='RB',new_slot='FLEX')])
    return ident, legacy, review


@pytest.mark.asyncio
async def test_named_fact_recovery_appends_correction_and_preserves_original_receipts(maker, tmp_path, monkeypatch):
    from app.services.generation.models import GenerationOutbox
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    from app.services.recap_video.publication import authorize_member_read
    ident, legacy, review = await named_recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        original = await db.get(ContentArtifact, 'article')
        original_bytes = original.payload_json
        row = await db.get(RecapPublication, legacy)
        media_before = row.media_json
        args = dict(expected_revision=8, artifact_id='article', actor_id='owner', reason='Verified correction',
                    editorial_review=review, cache_dir=tmp_path)
        preview = await recover_false_withdrawal(db, ident, **args)
        assert preview['correction_revision'] == original.revision + 1 and row.withdrawn
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1
        result = await recover_false_withdrawal(db, ident, **args, apply=True, expected_digest=preview['digest'])
        replacement = await db.get(ContentArtifact, result['corrected_artifact_id'])
        assert original.payload_json == original_bytes
        assert replacement.operation_id is None
        assert (await db.get(GenerationOperation, 'original-approved')).artifact_id == original.id
        assert (await db.get(ArtifactHead, original.subject)).artifact_id == replacement.id
        assert row.media_json == media_before and not row.enabled
        assert (await db.get(RecapShareDecision, 'edition:' + legacy)).opted_out
        delivered = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == 'artifact:' + replacement.id))
        assert delivered.delivered
        served = await authorize_member_read(db, 'synthetic', 2026, 4)
        assert served['article']['markdown'] == '**R1** dropped **10** from a FLEX slot.'
        assert served['media']['id'] == row.media_id


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['media', 'review', 'slot', 'anchor', 'predecessor'])
async def test_named_fact_recovery_rejects_changed_review_and_assets(maker, tmp_path, monkeypatch, change):
    from app.services.analyst_store import AnalystStore
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    ident, legacy, review = await named_recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        args = dict(expected_revision=8, artifact_id='article', actor_id='owner', reason='Verified correction',
                    editorial_review=review, cache_dir=tmp_path)
        preview = await recover_false_withdrawal(db, ident, **args)
        if change == 'media': (tmp_path / 'audio.mp3').write_bytes(b'changed media')
        elif change == 'review': review['article_digest'] = 'changed'
        elif change == 'slot': review['slot_corrections'][0]['new_slot'] = 'TE'
        elif change == 'anchor': review['slot_corrections'][0]['points'] = '10.0'
        else: AnalystStore(tmp_path).edition_path('synthetic', 2026, 4).write_text('{}')
        with pytest.raises((Held, ValueError)):
            await recover_false_withdrawal(db, ident, **args, apply=True, expected_digest=preview['digest'])
        assert (await db.get(RecapPublication, legacy)).withdrawn
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1


@pytest.mark.asyncio
async def test_named_recovery_retries_after_file_written_but_transaction_rolled_back(maker, tmp_path, monkeypatch):
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    ident, legacy, review = await named_recovery_fixture(maker, tmp_path, monkeypatch)
    args = dict(expected_revision=8, artifact_id='article', actor_id='owner', reason='Verified correction',
                editorial_review=review, cache_dir=tmp_path)
    async with maker.begin() as db:
        preview = await recover_false_withdrawal(db, ident, **args)
    with pytest.raises(RuntimeError, match='simulated commit failure'):
        async with maker.begin() as db:
            await recover_false_withdrawal(db, ident, **args, apply=True, expected_digest=preview['digest'])
            raise RuntimeError('simulated commit failure')
    async with maker.begin() as db:
        assert (await db.get(RecapPublication, legacy)).withdrawn
        assert await db.scalar(select(func.count()).select_from(ContentArtifact)) == 1
        result = await recover_false_withdrawal(db, ident, **args, apply=True, expected_digest=preview['digest'])
        assert result['applied']
        assert not (await db.get(RecapPublication, legacy)).withdrawn
