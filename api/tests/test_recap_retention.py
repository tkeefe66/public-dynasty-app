"""Retention thresholds and authority fences, using synthetic objects only."""
import hashlib
import json
import uuid

import pytest
from app.services.generation.recap_models import RecapAsset, RecapStage, RecapRecovery

DAY = 86400


def test_failed_take_threshold_and_uncertainty():
    # Mutation: use >90 or ignore unresolved/reference guards.
    from app.services.recap_video.retention import can_remove_failed_take
    assert not can_remove_failed_take(age_days=89, unresolved=False, referenced=False)
    assert can_remove_failed_take(age_days=90, unresolved=False, referenced=False)
    assert not can_remove_failed_take(age_days=120, unresolved=True, referenced=False)
    assert not can_remove_failed_take(age_days=120, unresolved=False, referenced=True)


async def seed_asset(maker, *, kind='narrate', state='failed', mime='audio/mpeg', created=1):
    identity, key = str(uuid.uuid4()), str(uuid.uuid4())
    stage_id = str(uuid.uuid4())
    async with maker.begin() as db:
        db.add(RecapStage(id=stage_id, episode_id='episode', revision=1, kind=kind,
            script_id='script', operation_id='job', input_json='{}', input_digest='inputs',
            policy_digest='policy', state=state, created_at=created))
        db.add(RecapAsset(id=identity, stage_id=stage_id, generation=1, digest=hashlib.sha256(b'bytes').hexdigest(),
            size=5, media_type=mime, storage_key=key, created_at=created))
    return identity, key, stage_id


@pytest.mark.asyncio
async def test_failed_take_candidates_and_archived_free_evidence(maker):
    # Mutation: expire an asset even when archived recovery evidence references it.
    from app.services.recap_video.retention import retention_candidates
    identity, key, stage = await seed_asset(maker)
    async with maker() as db:
        assert await retention_candidates(db, 1+89*DAY) == []
        assert [x['storage_key'] for x in await retention_candidates(db, 1+90*DAY)] == [key]
    async with maker.begin() as db:
        db.add(RecapRecovery(episode_id='episode', stage_id=stage, action='resume_free',
            before_json=json.dumps({'asset_ids':[identity]}), actor_id='admin', reason='Saved evidence'))
    async with maker() as db:
        assert await retention_candidates(db, 1+120*DAY) == []


@pytest.mark.asyncio
async def test_stale_candidate_new_reference_and_backup_pin(maker):
    # Mutation: execute proposal without rechecking backup/live references under lock.
    from app.services.recap_video.retention import retention_candidates, claim_deletions
    from app.services.generation.recap_models import RecapBackupPoint
    _, key, _ = await seed_asset(maker)
    async with maker() as db:
        candidates = await retention_candidates(db, 1+90*DAY)
    async with maker.begin() as db:
        db.add(RecapBackupPoint(run_id='synthetic-point', state='complete', objects_json=json.dumps({key:{'sha256':'hash','size':5}}),
            authority_json='{}', created_at=1, expires_at=1000*DAY))
    async with maker.begin() as db:
        assert await claim_deletions(db, candidates, now=1+100*DAY) == []


@pytest.mark.asyncio
async def test_disposable_frame_has_seven_day_grace(maker):
    # Mutation: treat disposable renderer frames as 90-day takes or remove at six days.
    from app.services.recap_video.retention import retention_candidates
    _, key, _ = await seed_asset(maker, kind='render', mime='image/png')
    async with maker() as db:
        assert await retention_candidates(db, 1+6*DAY) == []
        assert [x['storage_key'] for x in await retention_candidates(db, 1+7*DAY)] == [key]


@pytest.mark.asyncio
async def test_backup_snapshot_pins_survive_upload_and_match_dump(maker, tmp_path, monkeypatch):
    # Mutation: derive references by rereading live DB after dump, or release pins before manifest.
    from app.services import backup_service as backup
    from app.services.recap_video.storage import LocalPrivateMediaStore
    from app.services.generation.recap_models import RecapBackupPoint
    from app.services.recap_video.retention import retention_candidates
    from tests.helpers import maker_scope
    from tests.test_backup_run import Recorder, _settings, FIXED_NOW
    identity, key, _ = await seed_asset(maker)
    store = LocalPrivateMediaStore(tmp_path/'media')
    store.put_verified(key,b'bytes',hashlib.sha256(b'bytes').hexdigest())
    monkeypatch.setattr(backup,'session_scope',maker_scope(maker))
    rec = Recorder()
    async def put(*args, **kwargs):
        async with maker() as db:
            assert await retention_candidates(db, 200*DAY) == []
        await rec.put_bytes(*args, **kwargs)
    cache=tmp_path/'cache'
    cache.mkdir()
    manifest=await backup.run_backup(cache_dir=cache,settings=_settings(),_put_bytes=put,
        _put_file=rec.put_file,_now=lambda:FIXED_NOW,_media_store=store)
    assert manifest['media_objects'][key] == {'sha256':hashlib.sha256(b'bytes').hexdigest(),'size':5}
    assert list(rec.objects)[-1].endswith('/manifest.json')
    assert rec.objects[f"backups/{manifest['run_id']}/media/{key}"] == b'bytes'
    async with maker() as db:
        pin=await db.get(RecapBackupPoint,manifest['run_id'])
        assert pin.state == 'complete' and key in json.loads(pin.objects_json)


@pytest.mark.asyncio
async def test_snapshot_barrier_and_deletion_crash_recovery(maker,tmp_path):
    # Mutation: delete through active snapshot, or retain control lock during unlink.
    from app.services.recap_video.retention import claim_deletions, finish_deletions, retention_candidates, require_registerable
    from app.services.generation.recap_models import RecapBackupPoint, RecapObjectDeletion
    from app.services.generation.store import Held
    from app.services.recap_video.storage import LocalPrivateMediaStore
    _,key,_=await seed_asset(maker)
    store=LocalPrivateMediaStore(tmp_path)
    store.put_verified(key,b'bytes',hashlib.sha256(b'bytes').hexdigest())
    async with maker() as db:
        proposal=await retention_candidates(db,100*DAY)
    async with maker.begin() as db:
        db.add(RecapBackupPoint(run_id='barrier',state='snapshot',created_at=1,expires_at=200*DAY))
    async with maker.begin() as db:
        assert await claim_deletions(db,proposal,now=100*DAY) == []
        (await db.get(RecapBackupPoint,'barrier')).state='retired'
    async with maker.begin() as db:
        assert await claim_deletions(db,proposal,now=100*DAY) == [key]
    async with maker.begin() as db:
        with pytest.raises(Held,match='media_object_retired'):
            await require_registerable(db,key)
    # Simulate process loss after unlink, before marking done.
    store.delete_unreferenced(key)
    assert await finish_deletions(maker,store) == 1
    assert await finish_deletions(maker,store) == 0
    async with maker() as db:
        assert (await db.get(RecapObjectDeletion,key)).state == 'deleted'


@pytest.mark.asyncio
async def test_new_live_reference_and_unresolved_paid_ancestor_defeat_proposal(maker):
    # Mutation: stale proposal ignores a new active descendant/unknown original take.
    from app.services.recap_video.retention import claim_deletions,retention_candidates
    from app.services.generation.recap_models import RecapProviderAttempt
    _,key,stage=await seed_asset(maker)
    async with maker() as db:
        proposal=await retention_candidates(db,120*DAY)
        assert proposal
    async with maker.begin() as db:
        db.add(RecapStage(id='descendant',episode_id='episode',revision=2,kind='speech_check',script_id='script',
            operation_id='job',input_json='{}',input_digest='new',policy_digest='policy',predecessor_id=stage))
    async with maker.begin() as db:
        assert await claim_deletions(db,proposal,now=120*DAY)==[]
        (await db.get(RecapStage,'descendant')).state='failed'
        db.add(RecapProviderAttempt(stage_id=stage,episode_id='episode',series_id='series',operation_id='job',
            provider='synthetic',account_key='synthetic',worker_id='worker',generation=1,epoch='old',
            request_digest='request',request_json='{}',pricing_json='{}',authority_digest='authority',state='abandoned'))
    async with maker() as db:
        assert await retention_candidates(db,120*DAY)==[]


@pytest.mark.asyncio
async def test_backup_failure_and_expiry_require_proven_absence_and_stopped_owner(maker):
    # Mutation: expire pins by clock alone, ignore incomplete listing, or retire active upload.
    from app.services.generation.recap_models import RecapBackupPoint
    from app.services.backup_service import retire_backup_point
    from app.services.generation.store import Held
    async with maker.begin() as db:
        db.add(RecapBackupPoint(run_id='point',state='uploading',created_at=1,expires_at=30*DAY))
    async with maker.begin() as db:
        with pytest.raises(Held):
            await retire_backup_point(db,'point',absent_keys=[],listing_complete=True,uploader_stopped=True,now=40*DAY)
        (await db.get(RecapBackupPoint,'point')).state='failed'
    for keys,complete,stopped in [([],False,True),([],True,False),(['backups/point/manifest.json'],True,True)]:
        async with maker.begin() as db:
            with pytest.raises(Held):
                await retire_backup_point(db,'point',absent_keys=keys,listing_complete=complete,uploader_stopped=stopped,now=40*DAY)
    async with maker.begin() as db:
        await retire_backup_point(db,'point',absent_keys=[],listing_complete=True,uploader_stopped=True,now=40*DAY)
        assert (await db.get(RecapBackupPoint,'point')).state=='retired'


@pytest.mark.asyncio
async def test_orphan_pending_attempt_reference_prevents_unlink(maker,tmp_path):
    # Mutation: orphan cleanup checks registered assets but misses pending request keys.
    import os
    from app.services.generation.recap_models import RecapProviderAttempt
    from app.services.recap_video.storage import LocalPrivateMediaStore,cleanup_unregistered
    key=str(uuid.uuid4())
    store=LocalPrivateMediaStore(tmp_path)
    store.put_verified(key,b'bytes',hashlib.sha256(b'bytes').hexdigest())
    os.utime(tmp_path/key,(1,1))
    async with maker.begin() as db:
        db.add(RecapProviderAttempt(stage_id='pending',episode_id='episode',series_id='series',operation_id='job',
            provider='synthetic',account_key='synthetic',worker_id='worker',generation=1,epoch='old',
            request_digest='request',request_json=json.dumps({'pending_key':key}),pricing_json='{}',authority_digest='authority'))
    assert await cleanup_unregistered(maker,store,100*DAY)==0
    assert store.head(key)['size']==5


@pytest.mark.asyncio
async def test_abandoned_uploader_cannot_publish_after_retirement(maker,monkeypatch):
    # Mutation: late uploader writes a manifest after its pin has been released.
    from app.services import backup_service as backup
    from app.services.generation.recap_models import RecapBackupPoint
    from app.services.generation.store import Held
    from tests.helpers import maker_scope
    monkeypatch.setattr(backup,'session_scope',maker_scope(maker))
    async with maker.begin() as db:
        db.add(RecapBackupPoint(run_id='point',state='uploading',created_at=1,expires_at=30*DAY))
    async with maker.begin() as db:
        await backup.abandon_backup_point(db,'point',uploader_stopped=True)
        await backup.retire_backup_point(db,'point',absent_keys=[],listing_complete=True,uploader_stopped=True,now=40*DAY)
    with pytest.raises(Held,match='backup_upload_fenced'):
        await backup.require_upload_owner('point')
