#!/usr/bin/env python3
"""Offline recap retention and restore maintenance. No paid or publication calls.

Read/list backup access uses restore.py's separate read credential. Never adds
list/delete capability to API backup credentials. Status is safe and read-only;
all mutation commands require explicit named action and target database.
"""
import argparse
import asyncio
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'api'))


def list_exact_prefix(client,bucket,prefix):
    """No 403/timeout/partial pagination can be interpreted as absence."""
    keys=[]
    token=None
    seen=set()
    while True:
        response=client.list_objects_v2(Bucket=bucket,Prefix=prefix,
            **({'ContinuationToken':token} if token else {}))
        if type(response.get('IsTruncated')) is not bool:
            raise ValueError('Backup listing missing completion evidence')
        contents=response.get('Contents',[])
        if not isinstance(contents,list):
            raise ValueError('Backup listing malformed')
        for item in contents:
            key=item['Key']
            if not key.startswith(prefix):
                raise ValueError('Backup listing escaped requested prefix')
            keys.append(key)
        if not response['IsTruncated']:
            return keys
        token=response.get('NextContinuationToken')
        if not token or token in seen:
            raise ValueError('Backup listing pagination incomplete')
        seen.add(token)


def absent_prefix(client,bucket,run_id):
    # Negative control calibrates exact prefix filtering before trusting absence.
    control=f'backups/absence-control-{uuid.uuid4()}/'
    if list_exact_prefix(client,bucket,control):
        raise ValueError('Backup listing negative control failed')
    return list_exact_prefix(client,bucket,f'backups/{run_id}/')


async def execute(args):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from app.services.generation.recap_models import RecapBackupPoint,RecapObjectDeletion
    from app.services.generation.recovery import export_restore_authority,reconcile_restore,reopen_restore
    from app.services.generation.store import digest
    from app.services.recap_video.storage import LocalPrivateMediaStore,configured_store
    from restore import PRODUCTION_MARKERS,verify_external_gate,_client
    if any(marker in args.database_url for marker in PRODUCTION_MARKERS) and not args.allow_production:
        raise ValueError('Production-looking target requires --allow-production and separate operator authorization')
    if args.action in ('export-authority','reconcile','reopen'):
        verify_external_gate(args.quarantine_api_url,args.expected_restore_epoch)
    engine=create_async_engine(args.database_url)
    maker=async_sessionmaker(engine,expire_on_commit=False)
    try:
        if args.action == 'cleanup':
            from app.services.recap_video.retention import cleanup
            store=configured_store() if args.configured_media_store else LocalPrivateMediaStore(args.media_dir)
            return {'deleted':await cleanup(maker,store,int(time.time()))}
        if args.action == 'retire-backup':
            from app.services.backup_service import retire_backup_point
            keys=await asyncio.to_thread(absent_prefix,_client(),args.bucket,args.run_id)
            async with maker.begin() as db:
                await retire_backup_point(db,args.run_id,absent_keys=keys,listing_complete=True,
                    uploader_stopped=args.uploader_stopped,now=int(time.time()))
            return {'retired':args.run_id}
        if args.action == 'abandon-backup':
            from app.services.backup_service import abandon_backup_point
            async with maker.begin() as db:
                await abandon_backup_point(db,args.run_id,uploader_stopped=args.uploader_stopped)
            return {'fenced':args.run_id,'next':'Pins retained; wait for prefix expiry then retire-backup'}
        if args.action == 'export-authority':
            async with maker.begin() as db:
                authority=await export_restore_authority(db)
            # Never print tokens/current permission payloads to terminal/logs.
            with args.output.open('x') as file:
                import os
                os.chmod(args.output,0o600)
                json.dump(authority,file,sort_keys=True)
            return {'evidence_digest':digest(authority),'output':str(args.output)}
        if args.action == 'reconcile':
            manifest=json.loads(args.manifest.read_text())
            manifest.pop('current_authority',None)
            if args.current_authority:
                manifest['current_authority']=json.loads(args.current_authority.read_text())
            store=configured_store() if args.configured_media_store else LocalPrivateMediaStore(args.media_dir)
            objects={}
            for key,item in manifest.get('media_objects',{}).items():
                head=await asyncio.to_thread(store.head,key)
                if head['size']!=item['size']:
                    raise ValueError('Private media size differs from manifest')
                raw=await asyncio.to_thread(store.read_range,key,0,item['size']-1)
                objects[key]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
            async with maker.begin() as db:
                result=await reconcile_restore(db,manifest,objects)
            return {**result,'report_digest':digest(result)}
        if args.action == 'reopen':
            async with maker.begin() as db:
                result=await reopen_restore(db,expected_digest=args.report_digest,actor_id=args.actor)
            return {'reopened_report':result,'next':'Change external serving mode to database after all-instance verification; execution remains held.'}
        async with maker() as db:
            points=(await db.scalars(select(RecapBackupPoint))).all()
            pending=list((await db.scalars(select(RecapObjectDeletion.storage_key).where(RecapObjectDeletion.state=='pending'))).all())
        return {'recovery_points':[{'run_id':p.run_id,'state':p.state,'objects':len(json.loads(p.objects_json)),
            'expires_at':p.expires_at,'next':('Stop original upload process, then abandon-backup; pins remain' if p.state in ('snapshot','uploading')
                else 'Wait for lifecycle expiry, stop uploader, verify full prefix absence, then retire-backup' if p.state!='retired' else 'None')} for p in points],
            'pending_deletions':len(pending),'next':'Run cleanup to retry interrupted unlink' if pending else 'No pending unlink'}
    finally:
        await engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url',required=True)
    parser.add_argument('--allow-production',action='store_true')
    commands=parser.add_subparsers(dest='action',required=True)
    commands.add_parser('status')
    cleanup=commands.add_parser('cleanup')
    media=cleanup.add_mutually_exclusive_group(required=True)
    media.add_argument('--media-dir',type=Path)
    media.add_argument('--configured-media-store',action='store_true')
    retire=commands.add_parser('retire-backup')
    retire.add_argument('--run-id',required=True)
    retire.add_argument('--bucket',required=True)
    retire.add_argument('--uploader-stopped',action='store_true')
    abandon=commands.add_parser('abandon-backup')
    abandon.add_argument('--run-id',required=True)
    abandon.add_argument('--uploader-stopped',action='store_true')
    for name in ('export-authority','reconcile','reopen'):
        sub=commands.add_parser(name)
        sub.add_argument('--quarantine-api-url',required=True)
        sub.add_argument('--expected-restore-epoch',required=True)
        if name=='export-authority':
            sub.add_argument('--output',type=Path,required=True)
        elif name=='reconcile':
            sub.add_argument('--manifest',type=Path,required=True)
            sub.add_argument('--current-authority',type=Path)
            media=sub.add_mutually_exclusive_group(required=True)
            media.add_argument('--media-dir',type=Path)
            media.add_argument('--configured-media-store',action='store_true')
        else:
            sub.add_argument('--report-digest',required=True)
            sub.add_argument('--actor',required=True)
    try:
        print(json.dumps(asyncio.run(execute(parser.parse_args())),sort_keys=True))
    except Exception as exc:
        print(f'Maintenance failed ({type(exc).__name__}); authority/pins remain closed. Check target, configuration and storage access.',file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
