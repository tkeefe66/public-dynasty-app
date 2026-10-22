import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.services.generation.administration import control_action
from app.services.generation.models import GenerationAudit, GenerationControl, GenerationOperation
from app.services.generation.store import Conflict, dump


@pytest.mark.asyncio
async def test_recap_breaker_reset_preserves_failed_work_and_other_control_fences(maker):
    # Mutation: recap_video is omitted from registered reset features or reset resumes paid work.
    async with maker.begin() as db:
        control = GenerationControl(id='global', revision=7, epoch='saved-epoch', hold='owner_paused',
            breakers_json=dump({'recap_video': {'failures': 3, 'open': True},
                'analyst': {'failures': 2, 'open': True}}))
        job = GenerationOperation(id='failed-recap', kind='generation', feature='recap_video',
            subject='recap_video:synthetic', series_id='synthetic', league_id='synthetic',
            state='needs_attention', reason='execution_failed', calls=4, max_calls=4,
            payload_json='{"saved":true}', policy_json='{"unchanged":true}')
        db.add_all([control, job])
        await db.flush()
        before = (job.state, job.reason, job.calls, job.max_calls, job.payload_json, job.policy_json)
        body = SimpleNamespace(action='reset_breaker', feature='recap_video', expected_revision=7,
            reason='Verified underlying script validation fix')
        await control_action(db, body, 'synthetic-admin')
        assert json.loads(control.breakers_json) == {
            'recap_video': {'failures': 0, 'open': False}, 'analyst': {'failures': 2, 'open': True}}
        assert (control.revision, control.epoch, control.hold) == (8, 'saved-epoch', 'owner_paused')
        assert (job.state, job.reason, job.calls, job.max_calls, job.payload_json, job.policy_json) == before
        audit = await db.scalar(select(GenerationAudit).where(GenerationAudit.action == 'control_reset_breaker'))
        assert audit.actor_id == 'synthetic-admin' and audit.reason == body.reason
        with pytest.raises(Conflict, match='Control state changed'):
            await control_action(db, body, 'synthetic-admin')


@pytest.mark.asyncio
async def test_breaker_reset_still_rejects_unregistered_features(maker):
    async with maker.begin() as db:
        control = GenerationControl(id='global', revision=7, epoch='saved-epoch', breakers_json='{}')
        db.add(control)
        await db.flush()
        with pytest.raises(ValueError, match='registered feature'):
            await control_action(db, SimpleNamespace(action='reset_breaker', feature='invented',
                expected_revision=7, reason='Invalid feature'), 'synthetic-admin')
        assert control.revision == 7 and control.breakers_json == '{}'
