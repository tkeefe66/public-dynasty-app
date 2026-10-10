#!/usr/bin/env python3
"""Restore a Cloudflare R2 backup into a target database + cache directory.

Run from an operator machine, never from the app. The app's R2 token is write
scoped and this needs read access, so supply a separate read-only token as
R2_READ_ACCESS_KEY_ID / R2_READ_SECRET_ACCESS_KEY.

    python scripts/restore.py \\
        --database-url postgresql+asyncpg://localhost:5433/scratch \\
        --cache-dir /tmp/restored-cache

Selects the newest *complete* run by default (one with a manifest — see
pick_latest_run), verifies the payloads against that manifest, and refuses a
target that looks like production without --allow-production.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

RUN_PREFIX = "backups"
# Substrings that mean "this is the live database".
PRODUCTION_MARKERS = ("rlwy.net", "railway.internal")


def pick_latest_run(keys: list[str]) -> str | None:
    """Newest run id that has a manifest. Run ids sort lexically by time."""
    complete = sorted(
        k.split("/")[1] for k in keys if k.endswith("/manifest.json")
    )
    return complete[-1] if complete else None


class UnsafeMember(Exception):
    """A tar member that would write outside the destination, or that is not a
    plain file. Our own archives contain regular files only, so refusing is
    free — and refusing beats skipping, which would leave a member-count
    mismatch to explain instead of a name to look at."""


def safe_extract(tar: tarfile.TarFile, dest: Path) -> int:
    """Extract every member of ``tar`` into ``dest``, refusing anything unsafe.

    Vetting the members and then calling ``extractall()`` with no ``members=``
    argument extracts the *unvetted* set — including directories, symlinks and
    hardlinks. A symlink member ``x -> /etc`` followed by ``x/passwd`` writes
    outside the target. So the vetted list is what gets extracted.
    """
    members = tar.getmembers()
    for m in members:
        if not m.isfile():
            raise UnsafeMember(f"{m.name}: not a regular file")
        name = m.name
        if name.startswith("/") or Path(name).is_absolute():
            raise UnsafeMember(f"{name}: absolute path")
        if ".." in Path(name).parts:
            raise UnsafeMember(f"{name}: contains '..'")
    kwargs = {}
    if sys.version_info >= (3, 12):
        # Belt and braces: tarfile's own data filter, where it exists.
        kwargs["filter"] = "data"
    tar.extractall(dest, members=members, **kwargs)
    return len(members)


def _client():
    import boto3

    account = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_READ_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_READ_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _list_keys(client, bucket: str) -> list[str]:
    keys: list[str] = []
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": f"{RUN_PREFIX}/"}
        if token:
            kw["ContinuationToken"] = token
        page = client.list_objects_v2(**kw)
        keys += [o["Key"] for o in page.get("Contents", [])]
        if not page.get("IsTruncated"):
            return keys
        token = page["NextContinuationToken"]


def _get(client, bucket: str, key: str) -> bytes:
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()


async def _first_populated_table(database_url: str) -> tuple[str, int] | None:
    """(table, count) of the first non-empty table on the target, else None.

    The cache dir is guarded by an emptiness check; without the same guard on
    the database, restoring onto a populated target dies in a raw IntegrityError
    *after* `alembic upgrade head` has already touched it. Tables that do not
    exist yet (an unmigrated target) are empty by definition.
    """
    from sqlalchemy import func, inspect, select
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db import models  # noqa: F401 — registers tables on Base.metadata
    from app.db.base import Base

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            existing = set(
                await conn.run_sync(lambda c: inspect(c).get_table_names())
            )
            for table in Base.metadata.sorted_tables:
                if table.name not in existing:
                    continue
                n = await conn.scalar(select(func.count()).select_from(table))
                if n == 1 and table.name == "generation_control":
                    from types import SimpleNamespace
                    from app.services.generation.recovery import bootstrap_control
                    row = (await conn.execute(select(table))).mappings().one()
                    if bootstrap_control(SimpleNamespace(**row)):
                        continue
                if n:
                    return table.name, int(n)
        return None
    finally:
        await engine.dispose()


async def _alembic_revision(database_url: str) -> str | None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT version_num FROM alembic_version"))).first()
            return row[0] if row else None
    except Exception:
        return None
    finally:
        await engine.dispose()


async def _restore_db(database_url: str, blob: bytes, manifest=None, objects=None) -> dict[str, int]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.services.generation.recovery import restore_database

    engine = create_async_engine(database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as db:
            counts = await restore_database(db, blob)
            if manifest is not None:
                from app.services.generation.recovery import reconcile_restore
                report=await reconcile_restore(db,manifest,objects or {})
                print('  reconciliation: '+json.dumps(report,sort_keys=True))
            await db.commit()
        return counts
    finally:
        await engine.dispose()


def verify_external_gate(api_url, expected_epoch, manifest=None):
    """Read-only proof of responding API instance. Operator verifies ALL replicas."""
    import httpx
    from app.config import get_settings
    from app.services.generation.recovery import require_external_quarantine
    require_external_quarantine(manifest)
    if not expected_epoch or get_settings().recap_restore_epoch != expected_epoch:
        raise ValueError('Expected restore epoch does not match external deployment configuration')
    response=httpx.get(api_url.rstrip('/')+'/api/health/restore-gate',timeout=10,follow_redirects=False)
    response.raise_for_status()
    if response.json() != {'quarantined':True,'epoch_sha256':hashlib.sha256(expected_epoch.encode()).hexdigest()}:
        raise ValueError('API has not entered the expected restore quarantine; stop every instance before restore')


def restore_media(client,bucket,prefix,manifest,destination,*,configured=False):
    from app.services.recap_video.storage import LocalPrivateMediaStore,valid_key
    objects={}
    references=manifest.get('media_objects',{})
    if references and not destination and not configured:
        raise ValueError('Backup contains private media; --media-dir or --configured-media-store is required')
    if configured:
        from app.services.recap_video.storage import configured_store
        store=configured_store()
    else:
        store=LocalPrivateMediaStore(destination) if references else None
    for key,reference in references.items():
        valid_key(key)
        payload=_get(client,bucket,f'{prefix}/media/{key}')
        measured={'sha256':hashlib.sha256(payload).hexdigest(),'size':len(payload)}
        if measured != reference:
            raise ValueError('Backup media hash/size mismatch; keep restore quarantined')
        try:
            store.put_verified(key,payload,reference['sha256'])
        except Exception:
            # Existing immutable keys (or ambiguous PUT completion) are usable
            # only after independently reading and hashing their actual bytes.
            # Readback below distinguishes an existing correct object from
            # an actual write failure; no exception is accepted on its own.
            pass
        if store.head(key)['size'] != reference['size']:
            raise ValueError('Existing private media differs from backup')
        existing=store.read_range(key,0,reference['size']-1)
        if len(existing)!=reference['size'] or hashlib.sha256(existing).hexdigest()!=reference['sha256']:
            raise ValueError('Existing private media differs from backup')
        objects[key]=measured
    return objects


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--database-url", required=True,
                    help="SQLAlchemy async URL of the TARGET (must be migrated and empty)")
    ap.add_argument("--cache-dir", required=True, type=Path,
                    help="TARGET cache directory (must not exist or be empty)")
    media=ap.add_mutually_exclusive_group()
    media.add_argument('--media-dir',type=Path,help='Empty TARGET private media directory')
    media.add_argument('--configured-media-store',action='store_true',help='Restore into configured private object store')
    ap.add_argument('--quarantine-api-url',required=True,help='Already quarantined API; verifies responding instance only')
    ap.add_argument('--expected-restore-epoch',required=True)
    ap.add_argument('--current-authority',type=Path,help='Independent current authority export bound to deployment evidence digest')
    ap.add_argument("--run", default=None, help="run id; default = newest complete")
    ap.add_argument("--bucket", default=os.environ.get("R2_BUCKET", ""))
    ap.add_argument("--allow-production", action="store_true",
                    help="required to write to a Railway-looking target")
    ap.add_argument("--allow-schema-drift", action="store_true",
                    help="restore even when the code's alembic head is not the "
                         "revision the backup was taken at")
    args = ap.parse_args()

    # This precedes migrations, cache creation and object writes. The CLI cannot
    # rotate remote deployment configuration; operator must do that first.
    try:
        verify_external_gate(args.quarantine_api_url,args.expected_restore_epoch)
    except Exception as exc:
        print(f'refusing restore: external quarantine verification failed ({type(exc).__name__}); configure/restart all services first',file=sys.stderr)
        return 2

    if not args.bucket:
        print("error: --bucket or R2_BUCKET is required", file=sys.stderr)
        return 2

    if any(m in args.database_url for m in PRODUCTION_MARKERS) and not args.allow_production:
        print(
            "refusing: --database-url looks like production. Restoring over a live "
            "database is destructive and has no undo. Pass --allow-production if "
            "that is genuinely what you want.",
            file=sys.stderr,
        )
        return 2

    if args.cache_dir.exists() and any(args.cache_dir.iterdir()):
        print(f"refusing: {args.cache_dir} is not empty", file=sys.stderr)
        return 2
    if args.media_dir and args.media_dir.exists() and any(args.media_dir.iterdir()):
        print('refusing: private media target is not empty',file=sys.stderr)
        return 2

    populated = asyncio.run(_first_populated_table(args.database_url))
    if populated is not None:
        table, count = populated
        print(
            f"refusing: the target database is not empty — {table} already has "
            f"{count} row(s). Restore inserts rows, it does not merge; point "
            f"--database-url at an empty database or drop this one first.",
            file=sys.stderr,
        )
        return 2

    client = _client()
    run = args.run or pick_latest_run(_list_keys(client, args.bucket))
    if run is None:
        print("error: no complete backup run found", file=sys.stderr)
        return 1
    prefix = f"{RUN_PREFIX}/{run}"
    print(f"restoring run {run}")

    manifest = json.loads(_get(client, args.bucket, f"{prefix}/manifest.json"))
    verify_external_gate(args.quarantine_api_url,args.expected_restore_epoch,manifest)
    # Never accept a purported current-authority payload embedded in a backup.
    manifest.pop('current_authority',None)
    if args.current_authority:
        manifest['current_authority']=json.loads(args.current_authority.read_text())

    # --- Postgres ---
    print("  alembic upgrade head")
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(Path(__file__).resolve().parents[1] / "api"),
        env={**os.environ, "TRADE_GRADER_DATABASE_URL": args.database_url},
        check=True,
    )

    # `alembic upgrade head` runs the CODE's head, which may be newer than the
    # revision this backup was taken at. The manifest exists to make a restore
    # checkable — so check it.
    target_revision = asyncio.run(_alembic_revision(args.database_url))
    backup_revision = manifest.get("alembic_revision")
    if backup_revision != target_revision and not args.allow_schema_drift:
        print(
            f"refusing: schema drift — the backup was taken at alembic revision "
            f"{backup_revision!r}, the target is now at {target_revision!r}. The "
            f"dumped rows may not fit the migrated schema. Check out the code at "
            f"the backup's revision, or pass --allow-schema-drift if you have "
            f"confirmed the intervening migrations are additive.",
            file=sys.stderr,
        )
        return 1

    blob = _get(client, args.bucket, f"{prefix}/postgres.jsonl.gz")
    if manifest.get('database_sha256') and hashlib.sha256(blob).hexdigest() != manifest['database_sha256']:
        print('refusing: database dump hash mismatch',file=sys.stderr)
        return 1
    verify_external_gate(args.quarantine_api_url,args.expected_restore_epoch,manifest)
    objects=restore_media(client,args.bucket,prefix,manifest,args.media_dir,configured=args.configured_media_store)
    counts = asyncio.run(_restore_db(args.database_url, blob,manifest,objects))
    compatible_counts = ({k: counts.get(k) for k in manifest["tables"]} == manifest["tables"]
                         and all(v == 0 for k, v in counts.items() if k not in manifest["tables"]))
    if not compatible_counts:
        print(f"  MISMATCH: restored {counts}, manifest says {manifest['tables']}",
              file=sys.stderr)
        return 1
    print(f"  database OK: {counts}")
    print('  execution and public serving quarantined: review reconciliation, explicitly reopen, then change deployment mode')

    # --- Cache volume ---
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    tar_bytes = _get(client, args.bucket, f"{prefix}/cache.tar.gz")
    if len(tar_bytes) != manifest["cache"]["bytes"]:
        print(f"  MISMATCH: downloaded {len(tar_bytes)} bytes, manifest says "
              f"{manifest['cache']['bytes']} — truncated download", file=sys.stderr)
        return 1
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        try:
            extracted = safe_extract(tar, args.cache_dir)
        except UnsafeMember as exc:
            print(f"  refusing unsafe member: {exc}", file=sys.stderr)
            return 1
    if extracted != manifest["cache"]["members"]:
        print(f"  MISMATCH: extracted {extracted}, manifest says "
              f"{manifest['cache']['members']}", file=sys.stderr)
        return 1
    print(f"  cache OK: {extracted} files -> {args.cache_dir}")

    print(f"restore complete (schema v{manifest['chain_cache_schema_version']}, "
          f"alembic {manifest['alembic_revision']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
