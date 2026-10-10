"""Synthetic transport only; regression tests for final workflow boundaries."""
import json
import os
import time

import pytest
from sqlalchemy import select

from app.services.generation.store import Held


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    from app.config import Settings
    monkeypatch.setitem(Settings.model_config, 'env_file', None)
    for key in list(os.environ):
        if key.startswith('TRADE_GRADER_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('TRADE_GRADER_CACHE_DIR', str(tmp_path))
    monkeypatch.setenv('TRADE_GRADER_ADMIN_EMAILS', 'owner@test.local')
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EXECUTION_EPOCH', 'test-epoch')


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['denver', 'utc'])
async def test_later_physical_request_consumes_dispatch_month(maker, monkeypatch, boundary):
    # Mutation: allocation reservation month hides later physical sends from new-month admission.
    from datetime import datetime
    from app.services.generation.gateway import Gateway
    from app.services.generation import recap_budget as b
    from app.services.generation.recap_models import RecapBudgetAllocation
    from tests.test_recap_budget_ledger import analyst_job, at, allocation
    from tests.test_generation_gateway import REQUEST, BODY, FakeTransport
    clock = at if boundary == 'denver' else lambda s: int(datetime.fromisoformat(s+'+00:00').timestamp())
    first, second = clock('2026-10-31T23:59:00'), clock('2026-11-01T00:01:00')
    monkeypatch.setattr(time, 'time', lambda: first)
    await analyst_job(maker)
    request = {**REQUEST, 'model': 'claude-sonnet-4-6'}
    gateway = Gateway(maker, FakeTransport(body=json.dumps({**BODY, 'model': request['model']})), epoch='test-epoch')
    await gateway.invoke('job', 1, 1, request)
    monkeypatch.setattr(time, 'time', lambda: second)
    await gateway.invoke('job', 1, 2, request)
    async with maker.begin() as db:
        await b.release_unsubmitted(db, 'job', 'test-finished')
        view = await b.get_budget_view(db, 'series', b.episode_identity('series', 2026, '4'), second)
        balance = view['balances']['combined_month_microusd'] if boundary == 'denver' else view['app_limit']['balance']
        assert balance['known_microusd'] == 105
        rows = (await db.scalars(select(RecapBudgetAllocation))).all()
        assert all(a.created_at == first for a in rows)  # Reservation provenance is retained.
        if boundary == 'denver':
            await b.save_caps(db, 'series', b.RecapCaps(combined_month_microusd=105), 0, 'owner', 'Exact month limit', False)
        else:
            from app.repositories.app_settings import set_setting
            await set_setting(db, 'llm_monthly_budget_usd', '0.000105')
        with pytest.raises(Held, match='combined_month|legacy_budget_reached'):
            await b.reserve_plan(db, 'competitor', 'series', 'competing', [allocation(1, category='written')], second)


@pytest.mark.asyncio
@pytest.mark.parametrize('renewal', ['admin', 'standing'])
async def test_progressed_preview_exposes_free_renewal_after_week_rollover(maker, tmp_path, monkeypatch, renewal):
    # Mutation: renewal is hidden once stages exist, or reruns historical new-admission checks.
    from app.services.recap_video import workflow as w
    from app.services.recap_video.admin_actions import episode_view, apply_action
    from app.services.generation.models import LeagueSeason, stamp
    from app.services.generation.recap_models import RecapEpisode, RecapStage
    from tests.test_recap_workflow import seed_media, fence
    real = w.require_media_preflight
    ident, mid = await seed_media(maker, tmp_path, monkeypatch, 'media_check')
    evidence = await w.require_media_preflight(None, ident)
    monkeypatch.setattr(w, 'require_media_preflight', real)
    monkeypatch.setattr(w, 'PREFLIGHT_CONFIG', lambda: {'voice': 'synthetic'})
    async def validate(db, stage, result):
        return evidence
    monkeypatch.setitem(w.RESULT_VALIDATORS, 'preflight', validate)
    async with maker.begin() as db:
        proof = await w.prepare_preflight(db, ident, actor_id='owner', reason='Synthetic initial preflight')
        lease = await w.claim_stage(db, 'worker', {'preflight'}, stamp())
        await w.complete_stage(db, **fence(lease), result={'status': 'ok', 'asset_ids': [], 'report': {}})
        proof.created_at = stamp() - w.PREFLIGHT_MAX_AGE
        (await db.get(RecapEpisode, ident)).lifecycle = 'review'
        (await db.get(RecapStage, mid)).state = 'succeeded'
        (await db.get(LeagueSeason, 'synthetic')).latest_week = 5
        view = await episode_view(db, ident)
        assert 'renew_preflight' in view['actions']
        if renewal == 'admin':
            await apply_action(db, ident, actor_id='owner', expected_revision=view['revision'],
                action='renew_preflight', reason='Review finished preview after delay')
        else:
            from app.services.generation.recap_models import RecapStandingAuthorization
            db.add(RecapStandingAuthorization(id='standing-renewal', series_id='series', season=2026,
                calibration_id='synthetic-existing', review_ids_json='[]', actor_id='owner'))
    if renewal == 'standing':
        from app.services.recap_video import qualification as q
        async def status(*args): return {'automatic': True, 'standing_id': 'standing-renewal'}
        async def publication(*args): pass  # This test exercises free orchestration; full publication tested separately.
        monkeypatch.setattr(q, 'qualification_status', status)
        monkeypatch.setattr(q, 'advance_qualified_publication', publication)
        await w.advance_media(maker)
    async with maker.begin() as db:
        lease = await w.claim_stage(db, 'worker', {'preflight'}, stamp())
        assert lease
        await w.complete_stage(db, **fence(lease), result={'status': 'ok', 'asset_ids': [], 'report': {}})
        await w._current(db, await db.get(RecapStage, mid), now=stamp())
        assert await w.claim_stage(db, 'worker', {'narrate'}, stamp()) is None


@pytest.mark.asyncio
async def test_complete_video_plan_blocks_script_when_narration_cannot_fit(maker, tmp_path, monkeypatch):
    # Mutation: reserve only script calls, stranding a purchased script without narration allowance.
    from tests.test_recap_video_script import seed
    from tests.test_recap_narration_adapters import qualified
    from tests.test_generation_gateway import REQUEST, BODY, FakeTransport
    from app.services.recap_video import workflow as w, elevenlabs as el
    from app.services.generation.gateway import Gateway
    from app.services.generation.recap_budget import RecapCaps, save_caps
    from app.services.generation.models import GenerationOperation
    from app.services.generation.store import digest, dump
    from types import SimpleNamespace
    ident, _ = await seed(maker, tmp_path, monkeypatch)
    approval = qualified(monkeypatch)
    approval['rate_snapshot']['microusd_per_character'] = 80
    evidence = await el.validate_preflight(None, SimpleNamespace(episode_id=ident), {'report': approval['metadata']})
    async def preflight(db, episode_id): return evidence
    monkeypatch.setattr(w, 'require_media_preflight', preflight)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, 'job')
        value = json.loads(job.payload_json)
        value['media_qualification_digest'] = digest(evidence)
        job.payload_json = dump(value)
        await save_caps(db, 'series', RecapCaps(video_episode_microusd=2_500_000), 0, 'owner', 'Script fits; full episode does not', False)
    request = {**REQUEST, 'model': 'claude-sonnet-4-6'}
    transport = FakeTransport(body=json.dumps({**BODY, 'model': request['model']}))
    with pytest.raises(Held, match='recap_budget_video_episode'):
        await Gateway(maker, transport, epoch='test-epoch').invoke('job', 1, 1, request)
    assert transport.sends == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['none', 'unknown_original', 'unrelated_unknown', 'stale_disposition', 'current_unknown'])
async def test_explicit_replacement_settlement_new_review_selects_and_projects(maker, tmp_path, monkeypatch, invalid):
    # Mutation: every abandoned ancestor blocks review, or replacement bypasses current manual review.
    from app.services.recap_video import workflow as w, qualification as q, publication as p
    from app.services.recap_video.admin_actions import approve_replacement, replacement_preview, active_stages
    from app.services.generation import recap_models as m
    from app.services.generation.models import stamp, GenerationOutbox
    from app.services.generation.store import dump, digest, resolve_policy
    from app.services.generation.recap_budget import reconcile_allocation
    from tests.test_recap_workflow import fence, result
    from tests.test_recap_qualification import qualified_series
    ident, _ = await qualified_series(maker, tmp_path, monkeypatch, review_target=False)
    async with maker.begin() as db:
        config = await resolve_policy(db, 'series')
        stages = await active_stages(db, ident)
        for s in stages:
            s.policy_digest = digest([config['policy']['features']['recap_video'], config['revisions'], await w.require_media_preflight(db, ident)])
        paid = next(s for s in stages if s.kind == 'narrate')
        original = await db.get(m.RecapProviderAttempt, 'narration-0')
        original.stage_id, original.state, original.cost_microusd = paid.id, 'unknown', None
        paid.state = 'held'
        db.add(m.RecapBudgetPlan(id='original', episode_id=ident, series_id='series', plan_key='original', digest='original'))
        db.add(m.RecapBudgetAllocation(id='original', plan_id='original', key=paid.id, operation_id='job', category='video',
            attempt_id=original.id, month_key='2026-10', max_microusd=100, outstanding_microusd=100, rate_json='{}'))
        preview = await replacement_preview(db, ident)
        await approve_replacement(db, ident, preview_digest=preview['digest'], maximum_microusd=preview['maximum_microusd'],
            actor_id='owner', reason='Explicit bounded replacement', disposition_evidence='Exact original history is permanently unavailable; provider evidence retained.')
        await reconcile_allocation(db, 'original', 17, {'invoice': 'original-charge'}, 'owner', 'Settle original charge')
        assert original.state == 'abandoned'
    for kind in ('narrate', 'speech_check', 'render', 'media_check'):
        async with maker.begin() as db:
            lease = await w.claim_stage(db, 'worker', {kind}, stamp())
            assert lease, kind
            if kind == 'narrate':
                authority = await w.authorize_dispatch(db, **fence(lease), worker_id='worker')
                await w.record_receipt(db, authority['attempt_id'], {'status': 200, 'request': digest(authority['request'])}, worker_id='worker')
            await w.complete_stage(db, **fence(lease), result=result(lease))
            mid = lease['stage_id']
    async def verified(*args): return {}, 'script'
    monkeypatch.setattr(p, 'verified_media', verified)
    if invalid != 'none':
        async with maker.begin() as db:
            if invalid == 'unknown_original':
                (await db.get(m.RecapProviderAttempt, 'narration-0')).cost_microusd = None
            elif invalid == 'unrelated_unknown':
                from app.services.generation.store import data
                original = await db.get(m.RecapProviderAttempt, 'narration-0')
                db.add(m.RecapProviderAttempt(**{**data(original), 'id': 'unrelated', 'stage_id': 'unrelated', 'state': 'unknown'}))
            elif invalid == 'current_unknown':
                (await db.get(m.RecapProviderAttempt, authority['attempt_id'])).state = 'unknown'
            else:
                recovery = await db.scalar(select(m.RecapRecovery).where(m.RecapRecovery.action == 'bounded_replacement_authority'))
                value = json.loads(recovery.before_json)
                value['input_digest'] = 'stale'
                recovery.before_json = dump(value)
            with pytest.raises(Held):
                await q.review_binding(db, ident, mid)
            assert await p.authority_for_episode(db, await db.get(m.RecapEpisode, ident)) is None
        return
    async with maker.begin() as db:
        with pytest.raises(Held, match='replacement_finished_review_required'):
            await q.record_standing_approval(db, ident, 0, mid)
    async with maker.begin() as db:
        preview = await p.preview_publication(db, ident, 0, mid)
    async with maker.begin() as db:
        proof = await q.record_preview_approval(db, ident, 0, 'owner', dict(media_id=mid, preview_digest=preview['digest'],
            reason='Fresh finished replacement review', checks={key: 'Synthetic retained evidence for this exact replacement' for key in
                ('factual_coverage', 'performance', 'physical_phone', 'message_preview')}))
        assert (await q.qualification_status(db, 'series', 2026))['passed'] == 3
    async with maker.begin() as db:
        await p.select_publication(db, ident, 0, mid, proof)
    async with maker.begin() as db:
        item = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == f'recap-publication:{ident}:1'))
        await p.project_publication(db, item, tmp_path)
        assert (await p.authority_for_episode(db, await db.get(m.RecapEpisode, ident))).projected_revision == 1
        assert (await db.get(m.RecapProviderAttempt, 'narration-0')).state == 'abandoned'


@pytest.mark.asyncio
async def test_concrete_chunks_atomically_replace_envelope(maker, tmp_path, monkeypatch):
    # Mutation: release on script completion, double reserve chunks, or leave a gap after failed binding.
    from tests.test_recap_video_script import seed
    from tests.test_generation_gateway import REQUEST, BODY, FakeTransport
    from app.services.generation.gateway import Gateway
    from app.services.generation import recap_budget as b
    from app.services.generation.recap_models import RecapBudgetAllocation
    from app.services.generation.models import GenerationOperation
    from app.services.recap_video.narration_budget import bind_chunks
    from app.services.recap_video.elevenlabs import qualification, MODEL
    from app.services.generation.recovery import financial_digest
    ident, _ = await seed(maker, tmp_path, monkeypatch)
    request = {**REQUEST, 'model': 'claude-sonnet-4-6'}
    await Gateway(maker, FakeTransport(body=json.dumps({**BODY, 'model': request['model']})), epoch='test-epoch').invoke('job', 1, 1, request)
    async with maker.begin() as db:
        await b.release_unsubmitted(db, 'job', 'operation_completed')
        envelope = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.key == 'narration-envelope'))
        assert envelope.outstanding_microusd == 42_000
        approved = await qualification(db, ident)
        req = {'model_id': MODEL, 'inputs': [{'voice_id': approved['config']['voice_id'], 'text': 'A full submitted sentence.'}], 'settings': approved['config']['settings']}
        maximum = len(req['inputs'][0]['text']) * 7
        allocations = [dict(key='chunk', category='video', operation_id='chunk', max_microusd=maximum, rate_snapshot=approved['rate_snapshot'])]
        before = await financial_digest(db)
        await b.save_caps(db, 'series', b.RecapCaps(video_episode_microusd=105), 0, 'owner', 'Admission changes while binding', True)
        with pytest.raises(Held, match='video_episode'):
            await bind_chunks(db, 'script', 'job', ident, 'series', allocations, [req], int(time.time()))
        await db.refresh(envelope)
        assert envelope.actual_microusd is None and envelope.outstanding_microusd == 42_000
        await b.save_caps(db, 'series', b.RecapCaps(), 1, 'owner', 'Restore allowance', False)
        plan = await bind_chunks(db, 'script', 'job', ident, 'series', allocations, [req], int(time.time()))
        assert plan == await bind_chunks(db, 'script', 'job', ident, 'series', allocations, [req], int(time.time()))
        balance = (await b.get_budget_view(db, 'series', ident, int(time.time())))['balances']['video_episode_microusd']
        assert balance['known_microusd'] == 105 and balance['reserved_microusd'] == maximum
        assert envelope.actual_microusd == 0 and await financial_digest(db) != before
        assert json.loads(envelope.rate_json)['max_submitted_characters'] == 6000


def test_narration_envelope_counts_every_submitted_character_without_truncation():
    # Mutation: count only segment bodies, omit join spaces/tags, or truncate oversized coverage.
    from sleeper_dynasty.engine.recap_narration import narration_chunks
    script = {'opening': 'o'*2000, 'segments': [{'id': 'owner', 'text': 's'*2000}], 'closing': 'c'*2000}
    assert sum(len(c['text']) for c in narration_chunks(script)) == 6000
    script['segments'].append({'id': 'last-owner', 'text': '[angry] x'})
    with pytest.raises(ValueError, match='narration_exceeds_envelope'):
        narration_chunks(script)
    assert script['segments'][-1]['id'] == 'last-owner'


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['denver', 'utc'])
async def test_unknown_later_dispatch_and_late_receipt_keep_dispatch_month(maker, monkeypatch, boundary):
    # Mutation: settlement moves later physical dispatch back to reservation month or forward to receipt month.
    from datetime import datetime
    from app.services.generation.gateway import Gateway
    from app.services.generation.transport import Receipt
    from app.services.generation.models import ProviderAttempt
    from app.services.generation import recap_budget as b
    from tests.test_recap_budget_ledger import analyst_job, at
    from tests.test_generation_gateway import REQUEST, BODY, FakeTransport
    clock = at if boundary == 'denver' else lambda s: int(datetime.fromisoformat(s+'+00:00').timestamp())
    first, sent, received = [clock(value) for value in ('2026-10-31T23:59:00', '2026-11-01T00:01:00', '2026-12-01T00:01:00')]
    monkeypatch.setattr(time, 'time', lambda: first)
    await analyst_job(maker)
    request = {**REQUEST, 'model': 'claude-sonnet-4-6'}
    body = json.dumps({**BODY, 'model': request['model']})
    gateway = Gateway(maker, FakeTransport(body=body), epoch='test-epoch')
    await gateway.invoke('job', 1, 1, request)
    monkeypatch.setattr(time, 'time', lambda: sent)
    gateway.transport = FakeTransport(lost=True)
    with pytest.raises(Held, match='provider_outcome_unknown'):
        await gateway.invoke('job', 1, 2, request)
    async with maker() as db:
        attempt = await db.scalar(select(ProviderAttempt).where(ProviderAttempt.stage == 2))
        attempt_id = attempt.id
        view = await b.get_budget_view(db, 'series', None, received)
        balance = view['balances']['combined_month_microusd'] if boundary == 'denver' else view['app_limit']['balance']
        assert balance['carry_forward_microusd'] > 0 and balance['unknown_count'] == 1
    monkeypatch.setattr(time, 'time', lambda: received)
    await gateway.record_receipt(attempt_id, Receipt(200, body, {}))
    async with maker() as db:
        for when, expected in ((sent, 105), (received, 0)):
            view = await b.get_budget_view(db, 'series', None, when)
            balance = view['balances']['combined_month_microusd'] if boundary == 'denver' else view['app_limit']['balance']
            assert balance['known_microusd'] == expected


@pytest.mark.asyncio
async def test_media_cancellation_releases_envelope_but_retains_unknown_send(maker, tmp_path, monkeypatch):
    # Mutation: cancel releases paid unknown exposure or leaves never-submitted narration reserved forever.
    from tests.test_recap_video_script import seed
    from tests.test_generation_gateway import REQUEST, FakeTransport
    from app.services.generation.gateway import Gateway
    from app.services.generation.recap_models import RecapBudgetAllocation
    from app.services.recap_video.workflow import cancel_media
    ident, _ = await seed(maker, tmp_path, monkeypatch)
    with pytest.raises(Held, match='provider_outcome_unknown'):
        await Gateway(maker, FakeTransport(lost=True), epoch='test-epoch').invoke('job', 1, 1, {**REQUEST, 'model': 'claude-sonnet-4-6'})
    async with maker.begin() as db:
        await cancel_media(db, ident, 'owner', 'Cancel unused continuation')
        allocations = (await db.scalars(select(RecapBudgetAllocation))).all()
        assert next(a for a in allocations if a.key == 'narration-envelope').actual_microusd == 0
        paid = next(a for a in allocations if a.attempt_id)
        assert paid.actual_microusd is None and paid.outstanding_microusd == paid.max_microusd


@pytest.mark.asyncio
async def test_delayed_finished_preview_renews_then_reviews_through_public_actions(maker, tmp_path, monkeypatch):
    # Mutation: a delayed finished video cannot reach fresh review after free renewal and week rollover.
    from tests.test_recap_qualification import qualified_series
    from tests.test_recap_workflow import fence
    from app.services.recap_video import workflow as w, qualification as q, publication as p
    from app.services.recap_video.admin_actions import episode_view, apply_action, active_stages
    from app.services.generation.models import stamp, LeagueSeason
    from app.services.generation.store import digest, resolve_policy
    real = w.require_media_preflight
    ident, mid = await qualified_series(maker, tmp_path, monkeypatch, review_target=False)
    evidence = await w.require_media_preflight(None, ident)
    monkeypatch.setattr(w, 'require_media_preflight', real)
    monkeypatch.setattr(w, 'PREFLIGHT_CONFIG', lambda: {'voice': 'synthetic'})
    async def validator(*args): return evidence
    monkeypatch.setitem(w.RESULT_VALIDATORS, 'preflight', validator)
    async def verified(*args): return {}, 'script'
    monkeypatch.setattr(p, 'verified_media', verified)
    async with maker.begin() as db:
        config = await resolve_policy(db, 'series')
        for stage in await active_stages(db, ident):
            stage.policy_digest = digest([config['policy']['features']['recap_video'], config['revisions'], evidence])
        original = await w.prepare_preflight(db, ident, actor_id='owner', reason='Original free proof')
        lease = await w.claim_stage(db, 'worker', {'preflight'}, stamp())
        await w.complete_stage(db, **fence(lease), result={'status': 'ok', 'asset_ids': [], 'report': {}})
        original.created_at = stamp() - w.PREFLIGHT_MAX_AGE
        (await db.get(LeagueSeason, 'synthetic')).latest_week = 5
        with pytest.raises(Held, match='media_qualification_expired'):
            await p.preview_publication(db, ident, 0, mid)
        view = await episode_view(db, ident)
        await apply_action(db, ident, actor_id='owner', expected_revision=view['revision'],
            action='renew_preflight', reason='Delayed finished preview review')
        lease = await w.claim_stage(db, 'worker', {'preflight'}, stamp())
        await w.complete_stage(db, **fence(lease), result={'status': 'ok', 'asset_ids': [], 'report': {}})
    async with maker.begin() as db:
        preview = await p.preview_publication(db, ident, 0, mid)
    async with maker.begin() as db:
        proof = await q.record_preview_approval(db, ident, 0, 'owner', dict(media_id=mid, preview_digest=preview['digest'],
            reason='Finished review after free renewal', checks={key: 'Synthetic retained exact finished review evidence' for key in
                ('factual_coverage', 'performance', 'physical_phone', 'message_preview')}))
    async with maker.begin() as db:
        assert (await p.select_publication(db, ident, 0, mid, proof))['authority_revision'] == 1
        assert await w.claim_stage(db, 'worker', {'narrate'}, stamp()) is None
