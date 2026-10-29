import json
from datetime import datetime

import pytest


def test_config_has_explicit_scope_floor_and_no_paid_provider_credentials(monkeypatch):
    # Mutation: default to all leagues, backfill the previous week, or accept arbitrary recipients.
    from app.services.recap_monitor.runner import Config
    monkeypatch.setenv('TRADE_GRADER_RECAP_MONITOR_CONFIG', json.dumps(dict(
        owner_id='existing-owner', series_ids=['series'], first_season=2026, first_week=7,
        start_at='2026-10-26T22:30:00-06:00')))
    config = Config.load()
    assert config.first_week == 7 and config.series_ids == ('series',)
    assert config.start_at == int(datetime.fromisoformat('2026-10-26T22:30:00-06:00').timestamp())
    monkeypatch.setenv('TRADE_GRADER_RECAP_MONITOR_CONFIG', '{}')
    with pytest.raises(ValueError):
        Config.load()


@pytest.mark.asyncio
async def test_future_start_records_cloud_heartbeat_without_source_or_recovery(maker, monkeypatch, tmp_path):
    # Mutation: a 60-second wake audits recaps before the persisted next-useful check.
    from app.services.recap_monitor.runner import Config, tick
    from app.services.recap_monitor.state import initialize
    from app.services.recap_monitor.models import RecapMonitorState
    config = Config('owner', ('series',), 2026, 7, 10000)
    await initialize(maker, config.scope, config.start_at)
    async def forbidden(*args):
        pytest.fail('Future cycle must not fetch sources, recover, or send email')
    await tick(config, maker, tmp_path, now=100, collect=forbidden, send=forbidden)
    async with maker() as db:
        row = await db.get(RecapMonitorState, 'weekly-recaps')
        assert row.heartbeat_at == 100 and row.last_started_at == 0 and row.next_check_at == 10000


def test_current_period_uses_schedule_week_not_hardcoded_increment():
    # Mutation: derive edition as provider week minus one before provider rollover.
    from app.services.recap_monitor.collect import current_week
    now = int(datetime.fromisoformat('2026-10-26T22:30:00-06:00').timestamp())
    games = [dict(week=7, kickoff='2026-10-23T00:00:00Z'), dict(week=8, kickoff='2026-10-30T00:00:00Z')]
    assert current_week(games, now) == 7


@pytest.mark.asyncio
async def test_due_cloud_cycle_persists_help_and_delivers_once(maker, monkeypatch, tmp_path):
    # Mutation: timer never executes due work, or repeated eligible checks resend a help alert.
    from app.services.recap_monitor import runner
    from app.services.recap_monitor.state import initialize
    from app.services.recap_monitor.models import RecapMonitorState
    from app.db.models import User
    monkeypatch.setenv('TRADE_GRADER_ADMIN_EMAILS','owner@example.test')
    monkeypatch.setenv('RESEND_API_KEY','synthetic')
    monkeypatch.setenv('RECAP_MONITOR_FROM_EMAIL','recaps@example.test')
    async with maker.begin() as db:
        db.add(User(id='owner',google_sub='synthetic',email='owner@example.test',is_admin=True))
    config=runner.Config('owner',('series',),2026,7,100)
    await initialize(maker,config.scope,100)
    sent=[]
    async def collect(*args):
        return [dict(key='series:2026:7',status='help',reason='calls_exhausted',action='Approve calls')]
    async def send(ident,payload,key):
        sent.append((ident,payload))
        return 'provider-id'
    monkeypatch.setattr(runner,'resend',send)
    for now in [100,3701]:
        monkeypatch.setattr(runner.time,'time',lambda:now)
        await runner.tick(config,maker,tmp_path,now=now,collect=collect)
    assert len(sent)==1
    async with maker() as db:
        row=await db.get(RecapMonitorState,'weekly-recaps')
        assert row.last_finished_at==3701 and row.next_check_at==7301


@pytest.mark.asyncio
async def test_unfinished_games_prevent_edition_audit(maker,monkeypatch,tmp_path):
    # Mutation: run publication/job audit while a scoring-period game is unfinished.
    from types import SimpleNamespace
    from app.services.recap_monitor import collect as source
    from app.services.recap_monitor.runner import Config
    from app.db.models import User
    from app.services.generation.models import LeagueSeries,LeagueSeason
    monkeypatch.setenv('TRADE_GRADER_ADMIN_EMAILS','owner@example.test')
    async with maker.begin() as db:
        db.add(User(id='owner',google_sub='synthetic',email='owner@example.test',is_admin=True))
        # Captured production access shape: admin can read a Sleeper league without membership.
        db.add(LeagueSeries(id='series',name='Synthetic'))
        db.add(LeagueSeason(league_id='league',series_id='series',season=2026,provider='sleeper',provider_key='league',verified_at=1))
    class FakeClient:
        async def get_nfl_state(self):return dict(season=2026,season_type='regular',week=7)
        async def get_league(self,*args):return SimpleNamespace(playoff_week_start=15,playoff_round_type=0,num_playoff_teams=6),None
        async def close(self):pass
    game=dict(event_id='synthetic-game',week=7,home='H',away='A',kickoff='2026-10-23T00:00:00Z')
    async def inventory(*args):return dict(games=[game])
    async def evidence(*args):return dict(games=[{**game,'completed':False,'status':'STATUS_IN_PROGRESS'}])
    async def connected(*args,**kwargs):return FakeClient()
    async def forbidden(*args):pytest.fail('Edition audit while games unfinished')
    monkeypatch.setattr(source,'SleeperClient',FakeClient)
    monkeypatch.setattr(source,'fetch_inventory',inventory)
    monkeypatch.setattr(source,'fetch_week_evidence',evidence)
    monkeypatch.setattr(source,'connected_client',connected)
    monkeypatch.setattr(source,'publication_proof',forbidden)
    now=int(datetime.fromisoformat('2026-10-26T22:30:00-06:00').timestamp())
    items=await source.collect(Config('owner',('series',),2026,7,now),maker,tmp_path,now,{})
    assert len(items)==1 and items[0]['status']=='waiting' and items[0]['gate']>now


@pytest.mark.asyncio
@pytest.mark.parametrize('video, expected', [
    ({'status': 'disabled', 'enabled': False}, 'complete'),
    ({'status': 'published', 'enabled': True, 'media_id': 'saved-media'}, 'complete'),
    ({'status': 'pending', 'enabled': True, 'reason': 'video_processing'}, 'pending'),
    ({'status': 'blocked', 'enabled': True, 'reason': 'video_budget_blocked',
      'message': 'Review saved video budget in Admin'}, 'help'),
])
async def test_completed_previous_week_is_rechecked_after_rollover(maker, monkeypatch, tmp_path, video, expected):
    # Mutation: exclude completed prior periods so a later withdrawal is never inspected.
    from types import SimpleNamespace
    from app.services.recap_monitor import collect as source
    from app.services.recap_monitor.runner import Config
    from app.db.models import User
    from app.services.generation.models import LeagueSeries, LeagueSeason
    monkeypatch.setenv('TRADE_GRADER_ADMIN_EMAILS', 'owner@example.test')
    async with maker.begin() as db:
        db.add(User(id='owner', google_sub='synthetic', email='owner@example.test', is_admin=True))
        db.add(LeagueSeries(id='series', name='Synthetic'))
        db.add(LeagueSeason(league_id='league', series_id='series', season=2026,
                           provider='sleeper', provider_key='league', verified_at=1))
    class FakeClient:
        async def get_nfl_state(self): return dict(season=2026, season_type='regular', week=8)
        async def get_league(self, *args):
            return SimpleNamespace(playoff_week_start=15, playoff_round_type=0, num_playoff_teams=6), None
        async def close(self): pass
    games = [dict(event_id=f'game-{week}', week=week, home='H', away='A', kickoff=kickoff)
             for week, kickoff in [(7, '2026-10-23T00:00:00Z'), (8, '2026-10-30T00:00:00Z')]]
    async def inventory(*args): return dict(games=games)
    async def evidence(year, week):
        return dict(games=[{**g, 'completed': True, 'status': 'STATUS_FINAL'} for g in games if g['week'] == week])
    async def connected(*args, **kwargs): return FakeClient()
    async def proof(db, cache, league, year, week):
        return {'artifact_id': f'current-{week}', 'member_serving_readable': True}
    async def video_proof(*args):
        return video
    async def forbidden(*args):
        pytest.fail('Published text must not enter text job recovery or budgeting for missing video')
    monkeypatch.setattr(source, 'SleeperClient', FakeClient)
    monkeypatch.setattr(source, 'fetch_inventory', inventory)
    monkeypatch.setattr(source, 'fetch_week_evidence', evidence)
    monkeypatch.setattr(source, 'connected_client', connected)
    monkeypatch.setattr(source, 'publication_proof', proof)
    monkeypatch.setattr(source, 'video_evidence', video_proof, raising=False)
    monkeypatch.setattr(source, 'job_evidence', forbidden)
    monkeypatch.setattr(source, 'get_budget_view', forbidden)
    now = int(datetime.fromisoformat('2026-11-02T22:30:00-07:00').timestamp())
    previous = {'series:2026:7': dict(series_id='series', season=2026, status='complete',
                recovery_attempts=2, period={'period_id': '7', 'week': 7, 'nfl_weeks': [7]})}
    items = await source.collect(Config('owner', ('series',), 2026, 7, now), maker, tmp_path, now, previous)
    assert {item['week'] for item in items} == {7, 8}
    prior = next(item for item in items if item['week'] == 7)
    assert prior['proof']['artifact_id'] == 'current-7'
    assert prior['recovery_attempts'] == 2
    assert prior['status'] == expected
    assert prior.get('recoverable') is False
    assert prior['video'] == video
