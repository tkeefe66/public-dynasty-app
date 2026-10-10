"""Disposable PostgreSQL only; fixtures destroy this dedicated synthetic DB."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from tests.test_generation_postgres import pgmaker  # noqa: F401


@pytest.mark.asyncio
async def test_disposable_backup_restore_rehearsal_with_post_snapshot_revocation(pgmaker,tmp_path,monkeypatch):
    # Mutation: restore trusts old tokens, loses objects, or preserves recovery authority.
    from app.db.base import Base
    from app.services import backup_service as backup
    from app.services.generation.recap_models import RecapShareDecision,RecapRecoveryRequest,RecapPublicationControl
    from app.services.generation.recovery import export_restore_authority,restore_database,reconcile_restore,reopen_restore
    from app.services.generation.store import digest
    from app.services.recap_video.storage import LocalPrivateMediaStore
    from app.services.recap_video.publication import mode,serving_gate
    from app.services.generation.store import Held
    from tests.test_recap_retention import seed_asset
    from tests.test_backup_run import Recorder,_settings,FIXED_NOW
    from tests.helpers import maker_scope
    _,key,_=await seed_asset(pgmaker)
    source=LocalPrivateMediaStore(tmp_path/'source-media')
    source.put_verified(key,b'bytes',hashlib.sha256(b'bytes').hexdigest())
    async with pgmaker.begin() as db:
        db.add(RecapShareDecision(scope='edition:episode',revision=1,allowed=True,token='pre-backup-token',token_digest='prior'))
        db.add(RecapRecoveryRequest(id='lookup',attempt_id='attempt',worker_id='worker',actor_id='admin',
            identity_json='{}',request_digest='request',epoch='old',state='running',lease_until=9999999999,reason='Lookup'))
    monkeypatch.setattr(backup,'session_scope',maker_scope(pgmaker))
    cache=tmp_path/'cache';cache.mkdir();(cache/'private.json').write_text('{"draft":"synthetic"}')
    bucket=Recorder()
    manifest=await backup.run_backup(cache_dir=cache,settings=_settings(),_put_bytes=bucket.put_bytes,
        _put_file=bucket.put_file,_now=lambda:FIXED_NOW,_media_store=source)
    async with pgmaker.begin() as db:
        decision=await db.get(RecapShareDecision,'edition:episode')
        decision.revision=2;decision.allowed=False;decision.opted_out=True;decision.token=decision.token_digest=None
    for key_name,value in {'RECAP_PUBLICATION_MODE':'quarantine','GENERATION_EMERGENCY_PAUSE':'true',
            'RECAP_RESTORE_EPOCH':'synthetic-new-epoch','RECAP_SERVING_EPOCH':'synthetic-new-epoch',
            'GENERATION_EXECUTION_EPOCH':'synthetic-new-epoch'}.items():
        monkeypatch.setenv('TRADE_GRADER_'+key_name,value)
    async with pgmaker.begin() as db:
        authority=await export_restore_authority(db)
    monkeypatch.setenv('TRADE_GRADER_RECAP_RESTORE_EVIDENCE_DIGEST',digest(authority))
    # Same disposable database is emptied, then restored from the older real dump.
    async with pgmaker.kw['bind'].begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    destination=LocalPrivateMediaStore(tmp_path/'restored-media')
    measured={}
    for object_key,reference in manifest['media_objects'].items():
        body=bucket.objects[f"backups/{manifest['run_id']}/media/{object_key}"]
        destination.put_verified(object_key,body,reference['sha256'])
        measured[object_key]=destination.head(object_key)
    async with pgmaker.begin() as db:
        counts=await restore_database(db,bucket.objects[f"backups/{manifest['run_id']}/postgres.jsonl.gz"])
        assert counts==manifest['tables']
        report=await reconcile_restore(db,{**manifest,'current_authority':authority},measured)
        assert report['reconciled']
        assert (await db.get(RecapShareDecision,'edition:episode')).token is None
        lookup=await db.get(RecapRecoveryRequest,'lookup')
        assert lookup.state=='held' and lookup.lease_until==0
        await reopen_restore(db,expected_digest=digest(report),actor_id='synthetic-operator')
        assert not (await db.get(RecapPublicationControl,'global')).quarantined
    assert destination.read_range(key,0,4)==b'bytes'
    with pytest.raises(Held):mode()
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','legacy')
    with pytest.raises(Held):mode()
    monkeypatch.setenv('TRADE_GRADER_RECAP_PUBLICATION_MODE','database')
    async with pgmaker() as db:
        assert (await serving_gate(db)).epoch=='synthetic-new-epoch'


@pytest.mark.asyncio
async def test_reference_wins_gc_race_and_storage_has_no_global_lock(pgmaker,tmp_path):
    # Mutation: reuse pre-lock reference state or hold global lock during delete I/O.
    from tests.test_recap_retention import seed_asset,DAY
    from app.services.recap_video.retention import retention_candidates,claim_deletions,finish_deletions
    from app.services.generation.recap_models import RecapPublicationApproval,RecapAsset
    from app.services.generation.store import lock_control
    ident,key,stage=await seed_asset(pgmaker)
    async with pgmaker() as db:proposal=await retention_candidates(db,120*DAY)
    async with pgmaker.begin() as owner:
        await lock_control(owner)
        async def collect():
            async with pgmaker.begin() as db:return await claim_deletions(db,proposal,now=120*DAY)
        pending=asyncio.create_task(collect())
        await asyncio.sleep(.05)
        owner.add(RecapPublicationApproval(episode_id='episode',scope_json=json.dumps({'media_id':stage}),reviewer_id='admin',reason='Approved master'))
    assert await asyncio.wait_for(pending,5)==[]
    async with pgmaker() as db:assert await db.get(RecapAsset,ident)
    # Separate unreferenced object is claimable. Probe lock while its unlink waits.
    _,key2,_=await seed_asset(pgmaker,created=2,kind='render')
    async with pgmaker.begin() as db:
        await claim_deletions(db,await retention_candidates(db,120*DAY),now=120*DAY)
    import threading
    entered,release=threading.Event(),threading.Event()
    class Store:
        def delete_unreferenced(self,key):
            assert key==key2
            entered.set();assert release.wait(5)
    deleting=asyncio.create_task(finish_deletions(pgmaker,Store()))
    assert await asyncio.to_thread(entered.wait,5)
    try:
        async with pgmaker.begin() as db:await asyncio.wait_for(lock_control(db),2)
    finally:release.set()
    assert await deleting==1


@pytest.mark.asyncio
async def test_0019_migration_preserves_all_existing_evidence(pgmaker):
    # Mutation: migration rewrites reviewed proof or omits durable pin/deletion tables.
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.services.generation.recap_models import RecapBackupPoint,RecapObjectDeletion,RecapRestoreReport,RecapShareDecision
    async with pgmaker.begin() as db:
        db.add(RecapShareDecision(scope='edition:proof',revision=7,allowed=False,opted_out=True))
    path=Path(__file__).parents[1]/'migrations/versions/0019_recap_retention.py'
    spec=importlib.util.spec_from_file_location('retention_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    async with pgmaker.kw['bind'].begin() as connection:
        def upgrade(conn):
            for model in (RecapBackupPoint,RecapObjectDeletion,RecapRestoreReport):model.__table__.drop(conn)
            with Operations.context(MigrationContext.configure(conn)):migration.upgrade()
        await connection.run_sync(upgrade)
    async with pgmaker() as db:
        assert (await db.get(RecapShareDecision,'edition:proof')).revision==7
        for model in (RecapBackupPoint,RecapObjectDeletion,RecapRestoreReport):
            assert list((await db.scalars(select(model))).all())==[]
