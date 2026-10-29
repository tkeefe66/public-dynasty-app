"""Yahoo credentials, free collection, paid-stage doubles, correction and rollover."""
import copy
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from app.services.generation.models import (
    GenerationOperation,
    GenerationPolicy,
    LeagueSeason,
    ProviderAttempt,
)
from app.services.generation.policy import Policy
from app.services.generation.recap_models import RecapEpisode, RecapPublicationControl
from app.services.generation.store import dump
from sqlalchemy import select

from tests.test_generation_yahoo_authorization import LEAGUE, seed_yahoo
from tests.test_recap_automatic_corrections import ReviewedTransport, run_correction
from tests.test_recap_collector import Sources
from tests.test_recap_readiness import snapshot


class WeeklyYahoo(Sources):
    scores = None

    async def get_recap_source(self, path):
        value = await super().get_recap_source(path)
        if path.endswith('/users'):
            for user in value['data']:
                user['display_name'] = user['user_id']
        if '/matchups/' in path:
            week = int(path.rsplit('/', 1)[1])
            value['data'] = copy.deepcopy(self.scores[week])
        return value


@pytest.mark.asyncio
async def test_yahoo_weekly_publication_correction_and_rollover(maker, tmp_path, monkeypatch):
    from app.routes.analyst import analyst_archive
    from app.services.generation.planner import collect_analyst
    from app.services.recap_video.automatic_correction import allowance
    from app.services.recap_video.collector import collect_recap
    await seed_yahoo(maker)
    monkeypatch.setenv('TRADE_GRADER_ADMIN_EMAILS', 'owner@test.local')
    monkeypatch.setenv('TRADE_GRADER_CACHE_DIR', str(tmp_path))
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE', 'database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH', 'test-serving')
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EXECUTION_EPOCH', 'test-epoch')
    async with maker.begin() as db:
        (await db.get(GenerationOperation, 'job')).state = 'cancelled'
        policy = Policy(paused=False, recap_text_reconciliation=True)
        policy.features['analyst'].mode = 'automatic'
        policy.features['recap_video'].paused = True
        (await db.get(GenerationPolicy, 'app')).value_json = dump(policy.model_dump())
        db.add(RecapPublicationControl(id='global', epoch='test-serving', reconciliation_digest='test', quarantined=False))
    @asynccontextmanager
    async def fence():
        async with maker.begin() as db:
            yield db
    async def inventory(season):
        return {'season': season, 'version': 'yahoo-test', 'revision': 'yahoo-test', 'games': [
            {'event_id': f'game-{w}', 'source_id': f'source-{w}', 'home': 'BUF', 'away': 'NE',
             'week': w, 'gameday': f'2026-10-{11 + (w - 4) * 7}',
             'kickoff': f'2026-10-{11 + (w - 4) * 7}T17:00:00Z'} for w in (4, 5)],
            'source_bytes': {}, 'provenance': {}}
    async def scoreboard(season, week):
        game = (await inventory(season))['games'][week - 4]
        return {'games': [{**game, 'completed': True, 'status': 'STATUS_FINAL', 'state': 'post'}]}
    monkeypatch.setattr('app.services.recap_video.collector.fetch_inventory', inventory)
    monkeypatch.setattr('app.services.recap_video.collector.fetch_week_evidence', scoreboard)
    client = WeeklyYahoo()
    client.scores = {w: copy.deepcopy(snapshot()['scores']['4']) for w in (4, 5)}
    transport = ReviewedTransport()
    start = int(datetime(2026, 10, 13, 14, tzinfo=UTC).timestamp())
    for week in (4, 5):
        client.week = week + 1
        now = start + (week - 4) * 7 * 86400
        async with maker.begin() as db:
            (await db.get(LeagueSeason, LEAGUE)).latest_week = week
        for at in (now, now + 3600):
            assert await collect_recap(client, LEAGUE, tmp_path, fence, at)
        async with maker.begin() as db:
            await collect_analyst(db, LEAGUE, 'series', tmp_path)
        root_id = await run_correction(maker, tmp_path, transport)
        async with maker() as db:
            assert len((await analyst_archive(LEAGUE, db))['editions']) == week - 3
            root = await db.get(GenerationOperation, root_id)
            assert root.connection_generation == 'original' and root.max_calls == 6
        # Unused bench points do not hide text or buy another draft.
        client.scores[week][0]['players_points']['p3'] = '27.5'
        await collect_recap(client, LEAGUE, tmp_path, fence, now + 4500)
        async with maker() as db:
            assert len((await analyst_archive(LEAGUE, db))['editions']) == week - 3
        client.scores[week][0]['points'] = '103.27'
        client.scores[week][0]['players_points']['p1'] = '102.26'
        await collect_recap(client, LEAGUE, tmp_path, fence, now + 5400)
        async with maker() as db:
            assert len((await analyst_archive(LEAGUE, db))['editions']) == week - 4
        await collect_recap(client, LEAGUE, tmp_path, fence, now + 9000)
        await run_correction(maker, tmp_path, transport)
        async with maker() as db:
            assert len((await analyst_archive(LEAGUE, db))['editions']) == week - 3
            assert await allowance(db, root.subject, root_id) == 2
            assert (await db.get(GenerationOperation, root_id)).max_calls == 6
            episode = await db.scalar(select(RecapEpisode).where(RecapEpisode.week == week))
            assert episode.article_digest
            from app.services.recap_video.readiness import EpisodeKey, _authority_reason
            assert await _authority_reason(db, EpisodeKey('series', 2026, str(week)), LEAGUE,
                                           media_checkpoint=True) == 'recap_workflow_disabled'
    assert len(transport.requests) == 8
    async with maker() as db:
        assert len(list((await db.scalars(select(ProviderAttempt))).all())) == 8
        assert json.loads((await db.get(GenerationPolicy, 'app')).value_json) == policy.model_dump()
    # Unsupported new postseason must not poison supported earlier corrections.
    client.week = 16
    await collect_recap(client, LEAGUE, tmp_path, fence, start + 9 * 86400)
    async with maker() as db:
        episodes = list((await db.scalars(select(RecapEpisode))).all())
        assert len(episodes) == 2 and all(e.hold != 'source_error' for e in episodes)
        assert len((await analyst_archive(LEAGUE, db))['editions']) == 2
