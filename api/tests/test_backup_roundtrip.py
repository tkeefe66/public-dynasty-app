"""Offline end-to-end round trip of the whole backup/restore pipeline,
against a fake R2 (a plain dict), no network and no Docker.

This is the closest thing to Task 8's verified dry run that can run in CI: it
proves dump -> archive -> manifest -> upload -> download -> restore is lossless
for both stores. It does NOT prove anything about the real R2 network path,
real Postgres, or scripts/restore.py's own CLI/production-guard behavior --
see the report for what a real dry run would still need to cover.
"""

import sys
import tarfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.models import AppSetting, LeagueMembership, PageEvent, SideBet, User
from app.services.backup_service import load_database, run_backup
from tests.helpers import maker_scope

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from restore import safe_extract  # noqa: E402


def _settings():
    return Settings(
        backup_enabled=True, r2_account_id="a", r2_bucket="b",
        r2_access_key_id="k", r2_secret_access_key="s",
    )


class FakeBucket:
    """Stand-in for R2: an in-memory dict keyed by object key, with the same
    put_bytes/put_file shape run_backup injects (see Recorder in
    test_backup_run.py) plus a get() for the restore side."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put_bytes(self, account_id, bucket, key_id, secret, key, body, **kw):
        self.objects[key] = body

    async def put_file(self, account_id, bucket, key_id, secret, key, path, **kw):
        self.objects[key] = path.read_bytes()

    def get(self, key: str) -> bytes:
        return self.objects[key]


def _seed_rows():
    """A handful of rows spread across every table, distinct from
    test_backup_dump.py's fixture so this test isn't just re-running that
    one under a different name."""
    u1 = User(
        id="u-1", google_sub="g-1", email="a@b.c", name="Ann",
        sleeper_user_id="s-1", sleeper_username="ann", is_admin=True,
        active_days=5,
        last_active_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
    )
    u2 = User(
        id="u-2", google_sub="g-2", email="b@b.c", name="Bo",
        sleeper_user_id=None, sleeper_username=None, is_admin=False,
        active_days=0, last_active_at=None,
        created_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    )
    m1 = LeagueMembership(
        id="m-1", user_id="u-1", league_id="L1", league_name="The League",
        sleeper_roster_id=4,
        added_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    )
    m2 = LeagueMembership(
        id="m-2", user_id="u-2", league_id="L1", league_name="The League",
        sleeper_roster_id=7,
        added_at=datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc),
    )
    s1 = AppSetting(
        key="llm_monthly_budget_usd", value="25.0",
        updated_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
    )
    e1 = PageEvent(
        id="e-1", user_id="u-1", league_id="L1",
        route="/league/[id]", path="/league/L1",
        created_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
    )
    e2 = PageEvent(
        id="e-2", user_id="u-2", league_id=None,
        route="/admin", path="/admin",
        created_at=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )
    b1 = SideBet(
        id="b-1", league_id="L1", season=2025, description="last place buys",
        amount_cents=5000, side_a_owner_id="o-1", side_b_owner_id="o-2",
        status="settled", winner_owner_id="o-1",
        made_at=date(2025, 9, 1), settled_at=date(2026, 1, 5),
        created_by_user_id="u-1", settled_by_user_id=None,
        created_at=datetime(2025, 9, 1, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
    )
    return [u1, u2, m1, m2, s1, e1, e2, b1]


def _seed_cache_files(cache_dir: Path) -> dict[str, bytes]:
    """A few nested JSON files under the cache dir. Returns {relpath: bytes}
    for the byte-for-byte comparison after restore."""
    files = {
        "chain_L1.json": b'{"league_id": "L1"}',
        "snapshots/2026-08-01.json": b'{"prices": {"1": 9000}}',
        "adp/daily/2026-08-01.json": b'{"adp": []}',
    }
    for rel, body in files.items():
        path = cache_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return files


async def _rows(maker, table):
    async with maker() as db:
        res = await db.execute(select(table))
        return [dict(r) for r in res.mappings()]


@pytest.mark.asyncio
async def test_full_backup_then_restore_pipeline_round_trips_db_and_cache(
    tmp_path, maker, monkeypatch
):
    # --- Arrange: seed the source DB and a source cache dir. ---
    async with maker() as db:
        for obj in _seed_rows():
            db.add(obj)
        await db.commit()

    source_cache = tmp_path / "source-cache"
    source_cache.mkdir()
    seeded_files = _seed_cache_files(source_cache)

    monkeypatch.setattr("app.services.backup_service.session_scope", maker_scope(maker))

    # --- Act 1: run the real backup pipeline into a fake bucket. ---
    bucket = FakeBucket()
    manifest = await run_backup(
        cache_dir=source_cache, settings=_settings(),
        _put_bytes=bucket.put_bytes, _put_file=bucket.put_file,
    )

    run_id = manifest["run_id"]
    prefix = f"backups/{run_id}"
    assert sorted(bucket.objects) == [
        f"{prefix}/cache.tar.gz",
        f"{prefix}/manifest.json",
        f"{prefix}/postgres.jsonl.gz",
    ]

    # --- Act 2: restore into a second, empty DB and a second, empty cache dir. ---
    target_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'restored.db'}")
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    target_maker = async_sessionmaker(target_engine, expire_on_commit=False)

    db_blob = bucket.get(f"{prefix}/postgres.jsonl.gz")
    async with target_maker() as db:
        restored_counts = await load_database(db, db_blob)
        await db.commit()

    target_cache = tmp_path / "restored-cache"
    target_cache.mkdir()
    tar_blob = bucket.get(f"{prefix}/cache.tar.gz")
    tar_path = tmp_path / "cache.tar.gz"
    tar_path.write_bytes(tar_blob)
    with tarfile.open(tar_path) as tar:
        # The same guard the restore script uses — imported, not re-implemented,
        # so a hole can only ever be fixed in one place.
        extracted = safe_extract(tar, target_cache)

    # --- Assert: database rows equal the originals, table by table. ---
    assert restored_counts == manifest["tables"]
    for table in Base.metadata.sorted_tables:
        source_rows = await _rows(maker, table)
        target_rows = await _rows(target_maker, table)
        assert source_rows == target_rows, table.name

    await target_engine.dispose()

    # --- Assert: cache files match byte-for-byte. ---
    assert extracted == manifest["cache"]["members"] == len(seeded_files)
    for rel, body in seeded_files.items():
        restored_path = target_cache / rel
        assert restored_path.is_file(), rel
        assert restored_path.read_bytes() == body, rel

    # --- Assert: manifest counts match what actually came back. ---
    assert manifest["tables"] == {
        "users": 2, "league_memberships": 2, "app_settings": 1,
        "page_events": 2, "side_bets": 1,
    }
    assert manifest["cache"]["members"] == 3
