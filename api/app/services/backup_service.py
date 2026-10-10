"""Daily backup of both state stores to Cloudflare R2.

Postgres is dumped logically through SQLAlchemy reflection rather than
``pg_dump``: the schema is five tables of plain scalars, so a binary dump buys
no fidelity, and going through SQLAlchemy avoids pinning a client to the
server's major version *and* lets the whole path run against the SQLite dev
database — which is what makes the restore rehearsable.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import io
import json
import logging
import os
import tarfile
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Boolean, Date, DateTime, Integer, String, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import Base
from app.db import models  # noqa: F401 — registers every table on Base.metadata
from app.db.engine import session_scope
from app.repositories import app_settings
from app.services import r2
from app.services.chain_cache import SCHEMA_VERSION

log = logging.getLogger(__name__)

# The column types _encode/_decode round-trip. test_backup_dump.py asserts the
# schema never drifts outside this set.
SUPPORTED_COLUMN_TYPES = (String, Integer, Boolean, Date, DateTime)


def _encode(value):
    # datetime is a subclass of date — check it first or datetimes lose time.
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _decode(value, coltype):
    if value is None:
        return None
    if isinstance(coltype, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(coltype, Date):
        return date.fromisoformat(value)
    return value


async def dump_database(session: AsyncSession) -> tuple[bytes, dict[str, int]]:
    """Gzipped JSONL of every row in every table, plus per-table row counts.

    Read inside one REPEATABLE READ transaction so the dump is a point-in-time
    snapshot even while the app serves writes. Postgres only: SQLite's
    single-writer model already gives a consistent read and it rejects the
    isolation level outright.
    """
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        )

    counts: dict[str, int] = {}
    buf = io.BytesIO()
    # mtime=0 keeps the bytes deterministic for a given row set.
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        for table in Base.metadata.sorted_tables:
            n = 0
            # Streamed, not materialized: page_events grows without bound and
            # this runs in-process with the live API.
            result = await session.stream(select(table))
            try:
                async for row in result.mappings():
                    rec = {
                        "table": table.name,
                        "row": {k: _encode(v) for k, v in row.items()},
                    }
                    gz.write((json.dumps(rec) + "\n").encode())
                    n += 1
            finally:
                await result.close()
            counts[table.name] = n
    log.info("backup: dumped %s", counts)
    return buf.getvalue(), counts


async def load_database(session: AsyncSession, blob: bytes) -> dict[str, int]:
    """Insert every dumped row back. The target must already be migrated
    (``alembic upgrade head``) and empty.

    Inserts follow ``sorted_tables`` (FK-dependency order), so a membership
    never lands before the user it references.
    """
    by_table: dict[str, list[dict]] = {}
    with gzip.GzipFile(fileobj=io.BytesIO(blob), mode="rb") as gz:
        for raw in gz:
            rec = json.loads(raw)
            by_table.setdefault(rec["table"], []).append(rec["row"])

    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        rows = by_table.get(table.name) or []
        if rows:
            decoded = [
                {k: _decode(v, table.columns[k].type) for k, v in r.items()}
                for r in rows
            ]
            await session.execute(insert(table), decoded)
        counts[table.name] = len(rows)
    unknown = set(by_table) - set(Base.metadata.tables)
    if unknown:
        raise ValueError("Backup contains unsupported tables: " + ", ".join(sorted(unknown)))
    log.info("backup: restored %s", counts)
    return counts


def archive_cache(cache_dir: Path, dest: Path) -> tuple[int, int]:
    """tar.gz the whole cache directory into ``dest``.

    Returns (member count, byte size) for the manifest. In-flight temp files
    from write_json_atomic are skipped — they are a concurrent writer's private
    state and are guaranteed-partial by construction.
    """
    members = 0
    with tarfile.open(dest, "w:gz") as tar:
        for path in sorted(Path(cache_dir).rglob("*")):
            if path.is_symlink():
                # is_file() below follows symlinks and would accept this path,
                # but tar.add defaults to dereference=False, so it would land
                # in the tar as a SYMTYPE member. safe_extract (scripts/restore.py)
                # refuses any non-regular-file member on principle — that guard
                # is what stops a symlink member from writing outside the
                # restore destination — so one symlink here would make the
                # whole backup unrestorable. Skip it before is_file() can hide it.
                continue
            if not path.is_file():
                continue
            if path.name.startswith(".") and path.name.endswith(".tmp"):
                continue
            try:
                tar.add(path, arcname=str(path.relative_to(cache_dir)))
            except FileNotFoundError:
                # rglob snapshots the tree; a concurrent invalidate() can delete
                # a file before tar opens it. One missing cache file must not
                # abort the whole run — the cache is rebuildable.
                log.info("backup: skipped vanished cache file %s", path)
                continue
            members += 1
    return members, dest.stat().st_size


async def alembic_revision(session: AsyncSession) -> str | None:
    """Current migration head, read from the DB rather than the filesystem so
    the manifest records what the data actually is."""
    try:
        res = await session.execute(text("SELECT version_num FROM alembic_version"))
        row = res.first()
        return row[0] if row else None
    except Exception:
        # A SQLite dev DB created via metadata.create_all has no such table.
        return None


def git_sha() -> str:
    """Railway injects the deployed commit; empty elsewhere."""
    return os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")


def build_manifest(
    *,
    run_id: str,
    created_at: str,
    table_counts: dict[str, int],
    tar_members: int,
    tar_bytes: int,
    alembic_revision: str | None,
    git_sha: str,
) -> dict:
    """The receipt a restore checks itself against."""
    return {
        "run_id": run_id,
        "created_at": created_at,
        "tables": table_counts,
        "cache": {"members": tar_members, "bytes": tar_bytes},
        "alembic_revision": alembic_revision,
        "chain_cache_schema_version": SCHEMA_VERSION,
        "git_sha": git_sha,
    }


RUN_PREFIX = "backups"
RECOVERY_POINT_DAYS = 30  # Existing bucket lifecycle contract; never releases pins by age alone.


def snapshot_inventory(blob):
    """Derive media and authority from the EXACT dump, never a later DB read."""
    objects, authority = {}, {'share_decisions':[], 'publications':[], 'publication_epochs':[], 'execution_epochs':[]}
    for line in gzip.decompress(blob).splitlines():
        item = json.loads(line)
        row, table = item['row'], item['table']
        if table == 'recap_assets':
            objects[row['storage_key']] = {'sha256':row['digest'], 'size':row['size']}
        elif table == 'recap_share_decisions':
            authority['share_decisions'].append(row)
        elif table == 'recap_publications':
            authority['publications'].append(row)
        elif table == 'recap_publication_control':
            authority['publication_epochs'].append(row['epoch'])
        elif table == 'generation_control':
            authority['execution_epochs'].append(row['epoch'])
    return objects, authority


async def begin_snapshot(run_id, created_at):
    from app.services.generation.recap_models import RecapBackupPoint, RecapObjectDeletion
    from app.services.generation.store import Held, lock_control
    async with session_scope() as db:
        await lock_control(db)
        if await db.get(RecapBackupPoint, run_id):
            raise Held('backup_run_already_exists')
        if await db.scalar(select(RecapObjectDeletion).where(RecapObjectDeletion.state == 'pending').limit(1)):
            raise Held('backup_waiting_for_object_deletion')
        db.add(RecapBackupPoint(run_id=run_id,state='snapshot',created_at=created_at,
            expires_at=created_at+RECOVERY_POINT_DAYS*86400))


async def pin_snapshot(run_id, objects, authority):
    from app.services.generation.recap_models import RecapBackupPoint
    from app.services.generation.store import dump, lock_control
    async with session_scope() as db:
        await lock_control(db)
        row=await db.get(RecapBackupPoint,run_id)
        if row.state != 'snapshot':
            raise ValueError('Backup snapshot ownership changed')
        row.objects_json, row.authority_json = dump(objects), dump(authority)
        row.state='uploading'


async def backup_state(run_id, state):
    from app.services.generation.recap_models import RecapBackupPoint
    from app.services.generation.store import lock_control
    async with session_scope() as db:
        await lock_control(db)
        row=await db.get(RecapBackupPoint,run_id)
        if not row or row.state not in ('snapshot','uploading'):
            raise ValueError('Backup upload ownership changed; refuse publication')
        row.state=state


async def require_upload_owner(run_id):
    from app.services.generation.recap_models import RecapBackupPoint
    from app.services.generation.store import Held, lock_control
    async with session_scope() as db:
        await lock_control(db)
        row=await db.get(RecapBackupPoint,run_id)
        if not row or row.state != 'uploading':
            raise Held('backup_upload_fenced')


async def abandon_backup_point(db,run_id,*,uploader_stopped):
    """Operator confirms original API process stopped, then fences its old owner."""
    from app.services.generation.recap_models import RecapBackupPoint,RecapAsset
    from app.services.generation.store import Held,dump,lock_control,audit
    await lock_control(db)
    row=await db.get(RecapBackupPoint,run_id,populate_existing=True)
    if not row or row.state not in ('snapshot','uploading') or not uploader_stopped:
        raise Held('backup_stop_original_uploader_first')
    if row.state == 'snapshot':
        # Unknown snapshot boundary remains conservative until prefix retirement.
        row.objects_json=dump({a.storage_key:{'sha256':a.digest,'size':a.size}
            for a in (await db.scalars(select(RecapAsset))).all()})
    row.state='failed'
    audit(db,'offline-operator','backup_upload_abandoned',run_id,'Original uploading process confirmed stopped; pins remain')


async def retire_backup_point(db, run_id, *, absent_keys, listing_complete, uploader_stopped, now):
    """Offline operator only, with independently observed fully paginated listing.

    The API never lists/deletes backup history. Failed uploads and lifecycle
    expiry require this explicit reconciliation before they cease pinning media.
    """
    from app.services.generation.recap_models import RecapBackupPoint
    from app.services.generation.store import Held, audit, lock_control
    await lock_control(db)
    row=await db.get(RecapBackupPoint,run_id,populate_existing=True)
    if (not row or row.state not in ('failed','complete') or not uploader_stopped
            or not listing_complete or any(k.startswith(f'{RUN_PREFIX}/{run_id}/') for k in absent_keys)
            or now < (row.expires_at if row.state == 'complete' else row.created_at+7*86400)):
        raise Held('backup_retirement_unproven')
    row.state='retired'
    audit(db,'offline-operator','backup_pin_retired',run_id,'Stopped uploader and complete prefix absence verified')

STATUS_OK_KEY = "backup.last_ok_at"
STATUS_ERROR_KEY = "backup.last_error"
STATUS_RUN_KEY = "backup.last_run_id"


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


async def run_backup(
    *,
    cache_dir: Path,
    settings=None,
    _put_bytes=r2.put_bytes,
    _put_file=r2.put_file,
    _now=_utcnow,
    _media_store=None,
) -> dict:
    """Dump both stores and upload one run to R2. Returns the manifest.

    Raises on any failure — the caller records it. A failed run may leave one or
    two objects behind under its prefix; that is harmless because the manifest
    is written LAST, so a prefix without a manifest is an incomplete run and
    restore skips it.
    """
    settings = settings or get_settings()
    now = _now()
    run_id = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    prefix = f"{RUN_PREFIX}/{run_id}"

    await begin_snapshot(run_id, int(now.timestamp()))
    try:
        return await _upload_snapshot(run_id, prefix, now, cache_dir, settings,
            _put_bytes, _put_file, _media_store)
    except BaseException:
        # Pins survive ambiguous uploads, including a manifest PUT timeout.
        await backup_state(run_id, 'failed')
        raise


async def _upload_snapshot(run_id, prefix, now, cache_dir, settings, _put_bytes, _put_file, _media_store):
    async with session_scope() as db:
        blob, table_counts = await dump_database(db)
        revision = await alembic_revision(db)
    objects, authority = snapshot_inventory(blob)
    await pin_snapshot(run_id, objects, authority)

    with tempfile.TemporaryDirectory() as td:
        tar_path = Path(td) / "cache.tar.gz"
        members, tar_bytes = await asyncio.to_thread(
            archive_cache, Path(cache_dir), tar_path
        )

        # Resolved primitives, never the Settings object: a traceback out of
        # here reaches Sentry with frame locals attached.
        creds = (
            settings.r2_account_id,
            settings.r2_bucket,
            settings.r2_access_key_id,
            settings.r2_secret_access_key,
        )

        await _put_bytes(*creds, f"{prefix}/postgres.jsonl.gz", blob)
        await _put_file(*creds, f"{prefix}/cache.tar.gz", tar_path)
        if objects:
            from app.services.recap_video.storage import configured_store
            store = _media_store or configured_store()
            for key, reference in objects.items():
                payload = await asyncio.to_thread(store.read_range,key,0,reference['size']-1)
                if len(payload) != reference['size'] or hashlib.sha256(payload).hexdigest() != reference['sha256']:
                    raise ValueError('Backup private media hash/size mismatch')
                await _put_bytes(*creds,f'{prefix}/media/{key}',payload)

        manifest = build_manifest(
            run_id=run_id,
            created_at=now.isoformat(),
            table_counts=table_counts,
            tar_members=members,
            tar_bytes=tar_bytes,
            alembic_revision=revision,
            git_sha=git_sha(),
        )
        manifest.update(media_objects=objects, authority=authority,
            database_sha256=hashlib.sha256(blob).hexdigest(),
            expires_at=int(now.timestamp())+RECOVERY_POINT_DAYS*86400)
        # LAST: the manifest is this run's commit marker.
        await require_upload_owner(run_id)
        await _put_bytes(
            *creds, f"{prefix}/manifest.json", json.dumps(manifest).encode()
        )

    await backup_state(run_id, 'complete')

    log.info("backup: run %s complete (%d cache files)", run_id, members)
    return manifest


async def record_status(
    *, ok_at: str | None = None, error: str | None = None, run_id: str | None = None
) -> None:
    """Persist the last outcome to app_settings so a silently-broken backup is
    visible on /admin instead of discovered at restore time. Best-effort."""
    try:
        async with session_scope() as db:
            if ok_at is not None:
                await app_settings.set_setting(db, STATUS_OK_KEY, ok_at)
                await app_settings.set_setting(db, STATUS_ERROR_KEY, "")
            if error is not None:
                await app_settings.set_setting(db, STATUS_ERROR_KEY, error)
            if run_id is not None:
                await app_settings.set_setting(db, STATUS_RUN_KEY, run_id)
    except Exception:
        log.exception("backup: could not record status")


MARKER_NAME = "backup_last_run"


def _seconds_until(hour_utc: int, now: datetime) -> float:
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def _read_marker(cache_dir: Path) -> str | None:
    p = Path(cache_dir) / MARKER_NAME
    return p.read_text().strip() if p.exists() else None


def _write_marker(cache_dir: Path, day: str) -> None:
    (Path(cache_dir) / MARKER_NAME).write_text(day)


async def backup_loop(
    cache_dir: Path,
    *,
    settings=None,
    _run=run_backup,
    _sleep=asyncio.sleep,
    _now=_utcnow,
    _record=record_status,
    _max_cycles: int | None = None,
) -> None:
    """Back up once per UTC day, at or after ``backup_hour_utc``.

    Catch-up by design: the loop asks "is today already backed up, and are we
    past the hour?" rather than sleeping to a fixed instant. A service that is
    always redeployed at 09:30 would otherwise never fire a 09:00 job. The
    marker on the volume is what makes the catch-up safe to re-ask — it is
    written only after a *successful* run, so a failure retries within the hour.
    """
    settings = settings or get_settings()
    if not settings.backup_configured:
        log.info("backup: not configured; scheduler idle")
        return

    cycles = 0
    try:
        while _max_cycles is None or cycles < _max_cycles:
            cycles += 1
            now = _now()
            today = now.date().isoformat()
            if _read_marker(cache_dir) != today and now.hour >= settings.backup_hour_utc:
                try:
                    manifest = await _run(cache_dir=cache_dir, settings=settings)
                except Exception as exc:
                    log.exception("backup: run failed")
                    await _record(error=f"{type(exc).__name__}: {exc}")
                else:
                    # Record success FIRST. A marker write that fails (full or
                    # read-only volume) must not reclassify a good upload as a
                    # failure — that would also leave the day unmarked and fire
                    # a fresh full upload every hour for the rest of the day.
                    await _record(
                        ok_at=now.isoformat(), run_id=(manifest or {}).get("run_id")
                    )
                    try:
                        _write_marker(cache_dir, today)
                    except OSError:
                        log.exception("backup: could not write the day marker")
            # Cap the sleep at an hour so the day/hour check stays responsive
            # across clock changes and long-lived processes.
            await _sleep(min(_seconds_until(settings.backup_hour_utc, now), 3600))
    except asyncio.CancelledError:
        log.info("backup: scheduler cancelled")
        raise
