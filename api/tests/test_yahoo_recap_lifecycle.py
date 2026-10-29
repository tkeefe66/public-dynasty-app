"""Yahoo credentials, free collection, paid-stage doubles, correction and rollover."""
import copy
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

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


class PlayoffYahoo(WeeklyYahoo):
    """Normalized Yahoo source, including explicit owners without a matchup."""

    async def get_recap_source(self, path):
        value = await super().get_recap_source(path)
        if path.endswith('/users'):
            value['data'] = [{'user_id': f'owner-{i}', 'display_name': f'owner-{i}'} for i in range(1, 9)]
        elif path.endswith('/rosters'):
            value['data'] = [{'roster_id': i, 'owner_id': f'owner-{i}'} for i in range(1, 9)]
        elif path.endswith(f'/league/{LEAGUE}'):
            value['data']['settings'].update(recap_provider='yahoo', end_week=17, playoff_week_start=15)
        value['raw'] = dump(value['data'])
        return value


def yahoo_round(week, pairs):
    rows = []
    for number, (left, right, status) in enumerate(pairs, 1):
        pair = {'rosters': [left, right], 'winner': left, 'loser': right,
                'status': status, 'source_id': f'yahoo:{week}:{number}'}
        for rid, points in ((left, '101.01'), (right, '100.01')):
            row = copy.deepcopy(snapshot()['scores']['4'][0])
            row.update(roster_id=rid, matchup_id=number, points=points)
            row['players_points']['p1'] = '100.00' if rid == left else '99.00'
            if week >= 15:
                row['recap_matchup'] = copy.deepcopy(pair)
            rows.append(row)
    for rid in sorted(set(range(1, 9)) - {r['roster_id'] for r in rows}):
        rows.append({'roster_id': rid, 'matchup_id': None, 'points': None,
                     'players': [], 'starters': [], 'players_points': {}, 'recap_status': 'not_scheduled'})
    return rows


class PlayoffReviewedTransport(ReviewedTransport):
    """Exercise real draft/review plumbing with deterministic, free receipts."""

    pairings = ()

    async def send(self, request):
        from app.services.generation.transport import Receipt
        receipt = await super().send(request)
        body = json.loads(receipt.body)
        if request.get('tool_choice', {}).get('name') != 'submit_recap_review':
            body['content'] = [{'type': 'text', 'text': '\n\n'.join(
                f'## owner-{left} vs owner-{right}\n\nThe reviewed result is in.'
                for left, right, _ in self.pairings)}]
        return Receipt(receipt.status, dump(body), receipt.headers)


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


@pytest.mark.asyncio
@pytest.mark.parametrize('season_year', [2026, 2027])
async def test_yahoo_regular_to_championship_correction_and_season_end(
        maker, tmp_path, monkeypatch, season_year):
    # Regression targets: exclude bye owners; discard placement/consolation;
    # invent a fourth round; overwrite source winner; buy repeat drafts; reset budgets.
    from app.routes.analyst import analyst_archive
    from app.services.generation.planner import collect_analyst
    from app.services.generation.recap_models import RecapObservation
    from app.services.generation.worker import automatic_candidates
    from app.services.recap_monitor.evidence import publication_proof
    from app.services.recap_video.automatic_correction import allowance
    from app.services.recap_video.collector import collect_recap
    from app.services.recap_video.periods import eligible_release

    await seed_yahoo(maker)
    monkeypatch.setenv('TRADE_GRADER_ADMIN_EMAILS', 'owner@test.local')
    monkeypatch.setenv('TRADE_GRADER_CACHE_DIR', str(tmp_path))
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE', 'database')
    monkeypatch.setenv('TRADE_GRADER_RECAP_SERVING_EPOCH', 'test-serving')
    monkeypatch.setenv('TRADE_GRADER_GENERATION_EXECUTION_EPOCH', 'test-epoch')
    async with maker.begin() as db:
        (await db.get(GenerationOperation, 'job')).state = 'cancelled'
        (await db.get(LeagueSeason, LEAGUE)).season = season_year
        policy = Policy(paused=False, recap_text_reconciliation=True)
        policy.features['analyst'].mode = 'automatic'
        policy.features['recap_video'].paused = True
        saved_policy = dump(policy.model_dump())
        (await db.get(GenerationPolicy, 'app')).value_json = saved_policy
        db.add(RecapPublicationControl(id='global', epoch='test-serving', reconciliation_digest='test', quarantined=False))

    @asynccontextmanager
    async def fence():
        async with maker.begin() as db:
            yield db

    games = {}
    for week in range(14, 18):
        day = (datetime(season_year, 9, 13) + timedelta(weeks=week - 1)).date().isoformat()
        games[week] = {'event_id': f'game-{week}', 'source_id': f'source-{week}',
                       'home': 'BUF', 'away': 'NE', 'week': week, 'gameday': day,
                       'kickoff': f'{day}T17:00:00Z'}

    async def inventory(season):
        assert season == season_year
        return {'season': season, 'version': 'yahoo-playoffs', 'revision': 'yahoo-playoffs',
                'games': list(games.values()), 'source_bytes': {}, 'provenance': {}}

    async def scoreboard(season, week):
        assert season == season_year
        return {'games': [{**games[week], 'completed': True, 'status': 'STATUS_FINAL', 'state': 'post'}]}

    monkeypatch.setattr('app.services.recap_video.collector.fetch_inventory', inventory)
    monkeypatch.setattr('app.services.recap_video.collector.fetch_week_evidence', scoreboard)
    pairings = {
        14: [(1, 2, 'regular'), (3, 4, 'regular'), (5, 6, 'regular'), (7, 8, 'regular')],
        15: [(3, 6, 'title'), (4, 5, 'title'), (7, 8, 'consolation')],
        16: [(1, 4, 'title'), (2, 3, 'title'), (5, 6, 'placement'), (7, 8, 'consolation')],
        17: [(1, 2, 'title'), (3, 4, 'placement'), (5, 6, 'placement'), (7, 8, 'consolation')],
    }
    client = PlayoffYahoo()
    client.season = season_year
    client.scores = {week: yahoo_round(week, pairs) for week, pairs in pairings.items()}
    transport = PlayoffReviewedTransport()
    root_ids = []
    for index, week in enumerate(range(14, 18), 1):
        now = eligible_release(games[week]['gameday'])
        client.week = week + 1
        transport.pairings = pairings[week]
        async with maker.begin() as db:
            (await db.get(LeagueSeason, LEAGUE)).latest_week = week
        for at in (now, now + 3600):
            assert await collect_recap(client, LEAGUE, tmp_path, fence, at)
        async with maker.begin() as db:
            await collect_analyst(db, LEAGUE, 'series', tmp_path)
        root_ids.append(await run_correction(maker, tmp_path, transport))
        async with maker() as db:
            assert len((await analyst_archive(LEAGUE, db))['editions']) == index
            proof = await publication_proof(db, tmp_path, LEAGUE, season_year, week)
            assert proof and proof['member_serving_readable']
            episode = await db.scalar(select(RecapEpisode).where(RecapEpisode.week == week))
            assert episode.period_id == ('14' if week == 14 else f'playoff:{week - 14}')
            observed = json.loads((await db.get(RecapObservation, episode.latest_observation_id)).snapshot_json)
            assert len(observed['participants']) == 8
            assert len(observed['pairings']) == len(pairings[week])
            assert {p['status'] for p in observed['pairings']} == {p[2] for p in pairings[week]}
            if week == 15:
                assert {p['roster_id'] for p in observed['participants'] if p['status'] == 'not_scheduled'} == {1, 2}
            assert (await db.get(GenerationOperation, root_ids[-1])).max_calls == 6
        # Repeated collection/planning must retain one published draft/review pair.
        await collect_recap(client, LEAGUE, tmp_path, fence, now + 4500, force=True)
        async with maker.begin() as db:
            await collect_analyst(db, LEAGUE, 'series', tmp_path)
            assert not await automatic_candidates(db)
        assert len(transport.requests) == index * 2

    # A championship correction flips both authoritative winner and exact scores.
    now = eligible_release(games[17]['gameday']) + 5400
    championship = client.scores[17][:2]
    championship[1]['points'] = '103.01'
    championship[1]['players_points']['p1'] = '102.00'
    for row in championship:
        row['recap_matchup'].update(winner=2, loser=1)
    await collect_recap(client, LEAGUE, tmp_path, fence, now, force=True)
    async with maker() as db:
        assert len((await analyst_archive(LEAGUE, db))['editions']) == 3
    # Reconcile this admitted championship after the provider season has ended.
    client.week = 19
    async with maker.begin() as db:
        (await db.get(LeagueSeason, LEAGUE)).latest_week = 18
    await collect_recap(client, LEAGUE, tmp_path, fence, now + 3600, force=True)
    await run_correction(maker, tmp_path, transport)
    for at in (now + 4500, now + 9000):
        await collect_recap(client, LEAGUE, tmp_path, fence, at, force=True)
        async with maker.begin() as db:
            await collect_analyst(db, LEAGUE, 'series', tmp_path)
            assert not await automatic_candidates(db)
    async with maker() as db:
        assert len((await analyst_archive(LEAGUE, db))['editions']) == 4
        proof = await publication_proof(db, tmp_path, LEAGUE, season_year, 17)
        assert proof and proof['member_serving_readable']
        episodes = list((await db.scalars(select(RecapEpisode))).all())
        assert {e.period_id for e in episodes} == {'14', 'playoff:1', 'playoff:2', 'playoff:3'}
        final = next(e for e in episodes if e.week == 17)
        observed = json.loads((await db.get(RecapObservation, final.latest_observation_id)).snapshot_json)
        title = next(p for p in observed['pairings'] if p['status'] == 'title')
        assert title['winner'] == 2 and title['loser'] == 1
        root = await db.get(GenerationOperation, root_ids[-1])
        assert await allowance(db, root.subject, root.id) == 2
        for ident in root_ids:
            assert (await db.get(GenerationOperation, ident)).max_calls == 6
        assert (await db.get(GenerationPolicy, 'app')).value_json == saved_policy
        assert len(list((await db.scalars(select(ProviderAttempt))).all())) == 10
    assert len(transport.requests) == 10
