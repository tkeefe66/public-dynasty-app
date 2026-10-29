import json

import pytest
from fastapi import Response

from app.routes import analyst_sharing
from app.services.generation.models import GenerationPolicy
from app.services.generation.recap_models import RecapEpisode, RecapAttention, RecapStage
from app.services.generation.store import Held, dump
from tests.test_generation_gateway import seed_job


async def seed(maker):
    await seed_job(maker)
    async with maker.begin() as db:
        (await db.get(GenerationPolicy, 'app')).value_json = dump({'paused': False,
            'features': {'recap_video': {'mode': 'automatic'}}})
        db.add(RecapEpisode(episode_id='episode', series_id='series', league_id='synthetic',
            season=2026, week=7, period_id='7', nfl_weeks_json='[7]', lifecycle='ready', hold=''))


@pytest.mark.asyncio
async def test_missing_media_explains_held_episode_without_private_details(maker, monkeypatch):
    # Mutation: returning media=None without status hides the blocked newest video.
    await seed(maker)
    monkeypatch.setattr(analyst_sharing, 'authority_mode', lambda: 'database')
    async def unavailable(*args):
        raise Held('public_unavailable')
    monkeypatch.setattr(analyst_sharing.publication, 'authorize_member_read', unavailable)
    async with maker.begin() as db:
        (await db.get(RecapEpisode, 'episode')).hold = 'private source https://secret.invalid'
        result = await analyst_sharing.member_media('synthetic', Response(), 2026, 7, db)
        assert result['media'] is None
        assert result['video_status']['status'] == 'blocked'
        assert result['video_status']['reason'] == 'source_review'
        assert 'secret' not in json.dumps(result)


@pytest.mark.asyncio
async def test_preparation_attention_cannot_look_pending_and_resolved_does_not_block(maker):
    # Mutation: ignoring active preparation attention misreports the stalled pipeline.
    from app.services.recap_video.member_status import video_status
    await seed(maker)
    async with maker.begin() as db:
        attention = RecapAttention(key='attention', episode_id='episode', state='needs_attention', reason='private exception')
        db.add(attention)
        await db.flush()
        result = await video_status(db, 'synthetic', 2026, 7)
        assert result['status'] == 'blocked' and result['reason'] == 'preparation_review'
        assert 'private' not in json.dumps(result)
        attention.state = 'resolved'
        await db.flush()
        assert (await video_status(db, 'synthetic', 2026, 7))['status'] == 'pending'
        assert not db.new and not db.dirty


@pytest.mark.asyncio
async def test_intentionally_skipped_video_is_terminal(maker):
    # Mutation: leaving skipped video enabled makes monitoring wait forever.
    from app.services.recap_video.member_status import video_status
    await seed(maker)
    async with maker.begin() as db:
        (await db.get(RecapEpisode, 'episode')).lifecycle = 'video_skipped'
        await db.flush()
        result = await video_status(db, 'synthetic', 2026, 7)
        assert result['status'] == 'unavailable'
        assert result['enabled'] is False


@pytest.mark.asyncio
async def test_newer_preflight_does_not_mask_blocked_narration(maker):
    # Mutation: selecting the highest revision including preflight hides held media work.
    from app.services.recap_video.member_status import video_status
    await seed(maker)
    async with maker.begin() as db:
        for kind, revision, stage_state in [('narration', 1, 'held'), ('preflight', 2, 'succeeded')]:
            db.add(RecapStage(episode_id='episode', revision=revision, execution_revision=1,
                kind=kind, script_id='script', operation_id='job', input_json='{}',
                input_digest='input', policy_digest='policy', state=stage_state))
        await db.flush()
        result = await video_status(db, 'synthetic', 2026, 7)
        assert result['status'] == 'blocked' and result['reason'] == 'preparation_review'
        assert not db.new and not db.dirty


@pytest.mark.asyncio
async def test_disabled_and_historical_are_not_promised_a_video(maker):
    # Mutation: treating every missing media record as pending promises historical video.
    from app.services.recap_video.member_status import video_status
    await seed(maker)
    async with maker.begin() as db:
        assert (await video_status(db, 'synthetic', 2026, 6))['status'] == 'unavailable'
        assert (await video_status(db, 'other-league', 2026, 7))['status'] == 'unavailable'
        policy = await db.get(GenerationPolicy, 'app')
        policy.value_json = dump({'paused': False, 'features': {'recap_video': {'mode': 'disabled'}}})
        await db.flush()
        result = await video_status(db, 'synthetic', 2026, 7)
        assert result['status'] == 'disabled' and result['enabled'] is False


@pytest.mark.asyncio
async def test_current_stage_attention_blocks_but_replaced_stage_does_not(maker):
    # Mutation: omit needs_attention or include failures from replaced executions.
    from app.services.recap_video.member_status import video_status
    await seed(maker)
    async with maker.begin() as db:
        stage = RecapStage(episode_id='episode', revision=1, execution_revision=1,
            kind='narration', script_id='script', operation_id='job', input_json='{}',
            input_digest='input', policy_digest='policy', state='needs_attention')
        db.add(stage)
        await db.flush()
        assert (await video_status(db, 'synthetic', 2026, 7))['status'] == 'blocked'
        db.add(RecapStage(episode_id='episode', revision=1, execution_revision=2,
            kind='narration', script_id='script', operation_id='job', input_json='{}',
            input_digest='input', policy_digest='policy', state='queued'))
        await db.flush()
        assert (await video_status(db, 'synthetic', 2026, 7))['status'] == 'pending'
