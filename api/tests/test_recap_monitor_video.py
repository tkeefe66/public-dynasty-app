import json

import pytest
from sqlalchemy import select

from app.services.generation.models import GenerationPolicy
from app.services.generation.recap_models import RecapEpisode
from app.services.generation.store import dump
from tests.test_generation_gateway import seed_job


@pytest.mark.asyncio
async def test_video_publication_proof_disappears_when_member_authority_is_withdrawn(maker, tmp_path, monkeypatch):
    # Mutation: trusting media_json alone would keep reporting completion after withdrawal.
    from app.services.generation.recap_models import RecapPublication
    from app.services.recap_monitor.evidence import video_evidence
    from app.services.recap_video.legacy_recovery import recover_false_withdrawal
    from tests.test_recap_legacy_recovery import recovery_fixture
    ident, legacy = await recovery_fixture(maker, tmp_path, monkeypatch)
    async with maker.begin() as db:
        preview = await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Review')
        await recover_false_withdrawal(db, ident, expected_revision=8,
            artifact_id='article', actor_id='owner', reason='Review', apply=True,
            expected_digest=preview['digest'])
        result = await video_evidence(db, 'synthetic', 2026, 4)
        assert result['status'] == 'published' and result['media_id'] == 'saved-video'
        row = await db.get(RecapPublication, legacy)
        row.withdrawn = True
        await db.flush()
        assert (await video_evidence(db, 'synthetic', 2026, 4))['status'] != 'published'


@pytest.mark.asyncio
async def test_video_evidence_requires_authorized_media_and_tracks_missing_enabled_work(maker):
    # Mutation: a published article or enabled feature alone counts as completed video.
    from app.services.recap_monitor.evidence import video_evidence
    await seed_job(maker)
    async with maker.begin() as db:
        policy = await db.get(GenerationPolicy, 'app')
        policy.value_json = dump({'paused': False, 'features': {'recap_video': {'mode': 'automatic'}}})
        await db.flush()
        missing = await video_evidence(db, 'synthetic', 2026, 7)
        assert missing['enabled'] and missing['status'] != 'published'
        episode = RecapEpisode(episode_id='episode', series_id='series', league_id='synthetic',
            season=2026, week=7, period_id='7', nfl_weeks_json='[7]', lifecycle='ready', hold='')
        db.add(episode)
        await db.flush()
        pending = await video_evidence(db, 'synthetic', 2026, 7)
        assert pending['status'] == 'pending'
        episode.observed_at += 3600
        await db.flush()
        assert (await video_evidence(db, 'synthetic', 2026, 7))['progress'] == pending['progress']
        episode.hold = 'source_changed'
        await db.flush()
        blocked = await video_evidence(db, 'synthetic', 2026, 7)
        assert blocked['status'] == 'blocked' and blocked['progress'] != pending['progress']
        policy.value_json = dump({'paused': False, 'features': {'recap_video': {'mode': 'disabled'}}})
        await db.flush()
        assert (await video_evidence(db, 'synthetic', 2026, 7))['status'] == 'disabled'
        assert not db.new and not db.dirty


@pytest.mark.asyncio
async def test_video_stall_alert_explains_video_and_deduplicates_until_disabled(maker):
    # Mutation: silently complete on text proof, send every hour, or label missing video as missing text.
    from app.services.recap_monitor.models import RecapMonitorAlert
    from app.services.recap_monitor.state import initialize, claim, finish
    await initialize(maker, 'scope', 100)
    item = dict(key='series:2026:7', status='pending', proof={'artifact_id': 'text'},
        video={'enabled': True, 'status': 'pending'}, progress='video-same', recoverable=False)
    for now in [100, 3701, 7302, 10903]:
        token = await claim(maker, 'scope', now)
        await finish(maker, 'scope', token, now, [item], 'recipient')
        async with maker() as db:
            alerts = (await db.scalars(select(RecapMonitorAlert))).all()
            assert len(alerts) == (0 if now < 7302 else 1)
    assert json.loads(alerts[0].payload_json)['reason'] == 'enabled_video_stalled'
    token = await claim(maker, 'scope', 14504)
    await finish(maker, 'scope', token, 14504, [{**item, 'status': 'complete',
        'video': {'enabled': False, 'status': 'disabled'}}], 'recipient')
    async with maker() as db:
        assert (await db.get(RecapMonitorAlert, alerts[0].id)).state == 'cancelled'
