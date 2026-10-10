import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from app.services.generation.recap_models import RecapEpisode, RecapObservation, RecapPublication, RecapStage
from app.services.generation.store import Conflict, dump
from tests.test_recap_publication import ready_article, legacy_for_canonical


@pytest.mark.asyncio
async def test_changed_facts_withdraw_legacy_edition_before_any_repair(maker, tmp_path, monkeypatch):
    # Mutation: only look up canonical identity, leaving legacy public content readable.
    from app.services.recap_video.corrections import observe_correction
    ident = await ready_article(maker, tmp_path, monkeypatch)
    legacy, _ = await legacy_for_canonical(maker)
    async with maker.begin() as db:
        episode = await db.get(RecapEpisode, ident)
        snapshot = json.loads((await db.get(RecapObservation, episode.latest_observation_id)).snapshot_json)
        snapshot['scores']['4'][0]['points'] = '99.000'
        result = await observe_correction(db, ident, snapshot, 6400)
        assert result['withdrawn'] == [legacy]
    async with maker() as db:
        row = await db.get(RecapPublication, legacy)
        assert row.withdrawn and row.authority_revision == 8
        assert (await db.get(RecapEpisode, ident)).hold == 'recap_facts_changed'


@pytest.mark.asyncio
async def test_prior_week_change_withdraws_bound_later_episode(maker, tmp_path, monkeypatch):
    # Mutation: invalidate only changed week, leaving later streak/standings authority public.
    from app.services.recap_video.corrections import bind_dependencies, observe_correction
    ident = await ready_article(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        source = await db.get(RecapEpisode, ident)
        later = RecapEpisode(episode_id='later', series_id='series', season=2026, period_id='5',
            league_id='synthetic', week=5, nfl_weeks_json='[5]', facts_digest='later-facts')
        db.add(later)
        db.add(RecapPublication(episode_id='later', series_id='series', league_id='synthetic', season=2026,
            week=5, article_revision=1, article_digest='later', article_json='{}', facts_digest='later-facts',
            share_revision=1, epoch='test-serving',media_id='later-take',media_json='{}'))
        await db.flush()
        await bind_dependencies(db, later)
        snapshot = json.loads((await db.get(RecapObservation, source.latest_observation_id)).snapshot_json)
        await observe_correction(db, ident, snapshot, 6400)
        assert not (await db.get(RecapPublication,'later')).withdrawn
        snapshot['scores']['4'][0]['points'] = '99.000'
        await observe_correction(db, ident, snapshot, 10000)
        assert (await db.get(RecapPublication, 'later')).withdrawn
        assert later.hold == 'recap_dependency_changed'


def test_reconciliation_cadence_uses_release_week_friday_in_denver():
    # Mutation: continue 15-minute checks forever or use UTC Friday boundary.
    from app.services.recap_video.periods import next_reconciliation
    def ts(value):
        return int(datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('America/Denver')).timestamp())
    release = ts('2026-10-06T08:00:00')
    friday = ts('2026-10-09T23:59:00')
    saturday = ts('2026-10-10T00:00:00')
    assert next_reconciliation(release, friday) == friday + 900
    assert next_reconciliation(release, saturday) == saturday + 86400


@pytest.mark.asyncio
async def test_speech_recovery_preserves_paid_and_old_evidence_and_fences_lease(maker, tmp_path, monkeypatch):
    # Mutation: overwrite held transcript, resubmit paid narration, or preserve old lease.
    from tests.test_recap_speech_reviews import reviewed_artifact, approve
    from app.services.recap_video.corrections import resume_free
    ident, speech_id = await reviewed_artifact(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        await approve(db)
        speech = await db.get(RecapStage, speech_id)
        speech.state, speech.reason, speech.result_json = 'held', 'input_revision_required', dump({'transcript':'original'})
        speech.generation = 7
        paid = await db.scalar(select(RecapStage).where(RecapStage.kind == 'narrate'))
        paid_before = (paid.id, paid.generation, paid.state, paid.result_json)
    async with maker.begin() as db:
        result = await resume_free(db, ident, stage_id=speech_id, expected_generation=7,
            actor_id='owner', reason='Reviewed spelling; preserve original narration')
        assert result['generation'] == 8
        speech = await db.get(RecapStage, speech_id)
        assert json.loads(speech.input_json)['speech_review']['aliases'] == {'avery':['averie']}
        assert speech.state == 'queued' and not speech.lease_until
        paid = await db.scalar(select(RecapStage).where(RecapStage.kind == 'narrate'))
        assert (paid.id, paid.generation, paid.state, paid.result_json) == paid_before
        from app.services.generation.recap_models import RecapRecovery
        saved = (await db.scalars(select(RecapRecovery))).all()
        assert json.loads(saved[0].before_json)['result_json'] == dump({'transcript':'original'})
        with pytest.raises(Conflict):
            await resume_free(db, ident, stage_id=speech_id, expected_generation=7, actor_id='owner', reason='stale')


@pytest.mark.asyncio
async def test_bounded_replacement_retains_unknown_obligation_and_original_script(maker, tmp_path, monkeypatch):
    # Mutation: replacement releases uncertain money, rewrites script or reuses old dispatch authority.
    from tests.test_recap_workflow import seed_media, fence
    from app.services.recap_video import workflow
    from app.services.recap_video.admin_actions import replacement_preview, approve_replacement
    from app.services.generation.recap_models import RecapProviderAttempt, RecapBudgetAllocation
    from app.services.generation.models import ContentArtifact, stamp
    ident, _ = await seed_media(maker, tmp_path, monkeypatch, 'narrate')
    async with maker.begin() as db:
        lease = await workflow.claim_stage(db, 'original-worker', {'narrate'}, stamp())
        authority = await workflow.authorize_dispatch(db, **fence(lease), worker_id='original-worker')
        attempt = await db.get(RecapProviderAttempt, authority['attempt_id'])
        attempt.state = 'unknown'
        script_before = (await db.get(ContentArtifact, 'script')).payload_json
        preview = await replacement_preview(db, ident)
        assert preview['requests'] == 1 and preview['maximum_microusd'] == 100
    async with maker.begin() as db:
        result = await approve_replacement(db, ident, preview_digest=preview['digest'],
            maximum_microusd=100, actor_id='owner', reason='Explicit bounded replacement',disposition_evidence='No uniquely recoverable result after exact request review')
        assert result['execution_revision'] == 2
        attempt = await db.get(RecapProviderAttempt, authority['attempt_id'])
        assert attempt.state == 'abandoned' and attempt.cost_microusd is None
        old = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id == attempt.id))
        assert old.outstanding_microusd == 100
        assert (await db.get(ContentArtifact, 'script')).payload_json == script_before
        next_lease = await workflow.claim_stage(db, 'original-worker', {'narrate'}, stamp())
        assert next_lease['stage_id'] != lease['stage_id']
        fresh = await workflow.authorize_dispatch(db, **fence(next_lease),worker_id='original-worker')
        assert fresh['attempt_id'] != authority['attempt_id']
        with pytest.raises(Conflict):
            await approve_replacement(db, ident, preview_digest=preview['digest'],
                maximum_microusd=100, actor_id='owner', reason='Duplicate click',disposition_evidence='No uniquely recoverable result after exact request review')


@pytest.mark.asyncio
async def test_failed_free_validation_persists_exact_evidence_without_paid_retake(maker,tmp_path,monkeypatch):
    # Mutation: roll back failed measurements, leaving a running lease and no actionable explanation.
    from tests.test_recap_workflow import seed_media, fence
    from app.services.recap_video import workflow
    from app.services.generation.models import stamp
    from app.services.generation.store import Held
    _,target=await seed_media(maker,tmp_path,monkeypatch,'render')
    async def reject(db,stage,result):
        stage.evidence_json=dump({'issues':['scene_timing_ambiguous']})
        raise Held('render_script_mapping_ambiguous')
    monkeypatch.setitem(workflow.RESULT_VALIDATORS,'render',reject)
    async with maker.begin() as db:
        lease=await workflow.claim_stage(db,'renderer',{'render'},stamp())
        result={'status':'ok','asset_ids':[],'report':{'timing':'ambiguous'}}
        assert (await workflow.complete_stage(db,**fence(lease),result=result))['state']=='held'
    async with maker() as db:
        row=await db.get(RecapStage,target)
        assert row.reason=='render_script_mapping_ambiguous' and json.loads(row.result_json)==result
        assert json.loads(row.evidence_json)['issues']==['scene_timing_ambiguous']


@pytest.mark.asyncio
@pytest.mark.parametrize('corrupt',[False,True])
async def test_recovered_audio_resumes_only_free_descendants_with_unknown_money_retained(maker,tmp_path,monkeypatch,corrupt):
    # Mutation: use receipt alone as content approval, lose reservation, or submit narration again.
    import hashlib
    from app.services.recap_video import workflow
    from app.services.generation.models import stamp
    from app.services.generation.recap_models import RecapProviderAttempt,RecapBudgetAllocation,RecapStage
    from app.services.recap_video.admin_actions import apply_action,episode_view
    from app.services.generation.recap_models import RecapAsset
    from tests.test_recap_workflow import seed_media,fence
    ident,_=await seed_media(maker,tmp_path,monkeypatch,'narrate')
    async with maker.begin() as db:
        lease=await workflow.claim_stage(db,'worker',{'narrate'},stamp())
        sent=await workflow.authorize_dispatch(db,**fence(lease),worker_id='worker')
        attempt=await db.get(RecapProviderAttempt,sent['attempt_id'])
        identity={'request_id':'synthetic-request','history_item_id':'synthetic-history'}
        await workflow.persist_identity(db,attempt.id,identity,worker_id='worker')
        attempt.state='unknown'
        stage=await db.get(RecapStage,attempt.stage_id)
        stage.state='held'
        asset=RecapAsset(stage_id=stage.id,generation=attempt.generation,storage_key='recovered',digest=hashlib.sha256(b'audio').hexdigest(),size=5,media_type='audio/mpeg')
        db.add(asset);await db.flush()
        attempt.recovery_receipt_json=dump({'request_digest':attempt.request_digest,'identity':identity,'outcome':'recovered',
            'audio_sha256':asset.digest,'audio_size':5,'asset':{'asset_id':asset.id,'digest':asset.digest,'size':5}})
        allocations=(await db.scalars(select(RecapBudgetAllocation))).all()
        before=[(a.id,a.outstanding_microusd) for a in allocations]
        view=await episode_view(db,ident)
    from app.services.recap_video import storage
    class Store:
        def read_range(self,*args):return b'wrong' if corrupt else b'audio'
    monkeypatch.setattr(storage,'configured_store',lambda:Store())
    if corrupt:
        from app.services.generation.store import Held
        async with maker.begin() as db:
            with pytest.raises(Held,match='recovered_audio_hash_mismatch'):
                await apply_action(db,ident,actor_id='owner',expected_revision=view['revision'],action='resume_recovered_audio',reason='Review exact recovered audio')
            assert (await db.get(RecapStage,lease['stage_id'])).state=='held'
        return
    async with maker.begin() as db:
        await apply_action(db,ident,actor_id='owner',expected_revision=view['revision'],action='resume_recovered_audio',reason='Review exact recovered audio')
        assert (await db.get(RecapProviderAttempt,sent['attempt_id'])).cost_microusd is None
        assert [(a.id,a.outstanding_microusd) for a in (await db.scalars(select(RecapBudgetAllocation))).all()]==before
        assert (await db.get(RecapStage,lease['stage_id'])).state=='succeeded'
        assert await workflow.claim_stage(db,'worker',{'narrate'},stamp()) is None
        speech=await workflow.claim_stage(db,'worker',{'speech_check'},stamp())
        assert speech and speech['allowed_assets']==[asset.id]


@pytest.mark.asyncio
async def test_correction_proposal_uses_new_facts_and_explicit_saved_base_without_paid_job(maker,tmp_path,monkeypatch):
    from app.services.recap_video.corrections import observe_correction
    from app.services.recap_video.admin_actions import apply_action,episode_view
    from app.services.generation.models import GenerationCandidate,GenerationOperation
    from sqlalchemy import func
    ident=await ready_article(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        from app.services.generation.models import ArtifactHead,ContentArtifact
        from app.services.generation.artifacts import subject_key
        (await db.get(ArtifactHead,'article-subject')).subject=subject_key('analyst','series',2026,4)
        (await db.get(ContentArtifact,'article')).subject=subject_key('analyst','series',2026,4)
        episode=await db.get(RecapEpisode,ident)
        source=json.loads((await db.get(RecapObservation,episode.latest_observation_id)).snapshot_json)
        source['scores']['4'][0]['points']='99.000'
        await observe_correction(db,ident,source,6400)
        await observe_correction(db,ident,source,11000)
        before=await db.scalar(select(func.count()).select_from(GenerationOperation))
        view=await episode_view(db,ident)
        await apply_action(db,ident,actor_id='owner',expected_revision=view['revision'],action='review_correction',reason='Review corrected score')
        candidate=await db.scalar(select(GenerationCandidate).where(GenerationCandidate.key.startswith('correction:')))
        assert candidate is not None and json.loads(candidate.payload_json)['correction_base']
        assert json.loads(candidate.payload_json)['recap_facts_digest']==episode.facts_digest
        assert await db.scalar(select(func.count()).select_from(GenerationOperation))==before
