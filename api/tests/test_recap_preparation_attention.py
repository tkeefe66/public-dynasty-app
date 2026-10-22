"""Preparation failures stay visible without stopping independent article work."""
from types import SimpleNamespace
import json

import pytest
from sqlalchemy import select

from app.services.generation.recap_models import RecapAttention, RecapEpisode
from app.services.generation.models import GenerationPolicy
from app.services.generation.store import Held
from app.services.recap_video import qualification as q, workflow as w
from tests.test_recap_workflow import seed_media


@pytest.mark.asyncio
async def test_preparation_attention_retries_resolves_and_reopens(maker, tmp_path, monkeypatch):
    ident, _ = await seed_media(maker, tmp_path, monkeypatch)
    monkeypatch.setattr(w, 'PREFLIGHT_CONFIG', lambda: {'voice': 'synthetic'})
    failure = ['media_calibration_changed']

    async def calibration(db, series_id, season):
        if failure[0]:
            raise Held(failure[0])
        return SimpleNamespace(id='calibration', actor_id='owner')

    monkeypatch.setattr(q, 'calibration', calibration)
    async with maker.begin() as db:
        policy = await db.get(GenerationPolicy, 'app')
        value = json.loads(policy.value_json)
        value['features']['recap_video'].update(mode='automatic', paused=False)
        policy.value_json = json.dumps(value)
    for reason in ('media_calibration_changed', 'media_calibration_changed', '', 'media_preflight_metadata_changed'):
        failure[0] = reason
        await w.advance_media(maker)
        async with maker() as db:
            rows = (await db.scalars(select(RecapAttention).where(RecapAttention.episode_id == ident))).all()
            assert len(rows) == 1
            assert rows[0].state == ('needs_attention' if reason else 'resolved')
            assert rows[0].reason == reason
            episode = await db.get(RecapEpisode, ident)
            assert episode.hold == ''
            assert episode.lifecycle != 'held'
            from app.services.recap_video.admin_actions import episode_view
            view = await episode_view(db, ident)
            assert view['reason'] == reason
