import gzip
import json
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.services.backup_service import run_backup
from tests.helpers import maker_scope

FIXED_NOW = datetime(2026, 8, 12, 9, 0, 0, tzinfo=timezone.utc)


def _settings():
    return Settings(
        backup_enabled=True, r2_account_id="a", r2_bucket="b",
        r2_access_key_id="k", r2_secret_access_key="s",
    )


class Recorder:
    """Same shape as r2.put_bytes/put_file: resolved primitives, no Settings."""

    def __init__(self):
        self.objects = {}
        self.creds = set()

    async def put_bytes(self, account_id, bucket, key_id, secret, key, body, **kw):
        self.creds.add((account_id, bucket, key_id, secret))
        self.objects[key] = body

    async def put_file(self, account_id, bucket, key_id, secret, key, path, **kw):
        self.creds.add((account_id, bucket, key_id, secret))
        self.objects[key] = path.read_bytes()


@pytest.mark.asyncio
async def test_run_uploads_three_objects_under_one_timestamped_prefix(
    tmp_path, maker, monkeypatch
):
    monkeypatch.setattr("app.services.backup_service.session_scope", maker_scope(maker))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "chain_L1.json").write_text("{}")

    rec = Recorder()
    manifest = await run_backup(
        cache_dir=cache, settings=_settings(),
        _put_bytes=rec.put_bytes, _put_file=rec.put_file, _now=lambda: FIXED_NOW,
    )

    prefix = "backups/2026-08-12T09-00-00Z"
    assert sorted(rec.objects) == [
        f"{prefix}/cache.tar.gz",
        f"{prefix}/manifest.json",
        f"{prefix}/postgres.jsonl.gz",
    ]
    assert manifest["run_id"] == "2026-08-12T09-00-00Z"
    assert manifest["cache"]["members"] == 1
    # Resolved primitives reach the R2 layer, never the Settings object.
    assert rec.creds == {("a", "b", "k", "s")}


@pytest.mark.asyncio
async def test_manifest_is_uploaded_last_so_it_marks_a_complete_run(
    tmp_path, maker, monkeypatch
):
    """A prefix without a manifest is an incomplete run; restore skips it. That
    invariant only holds if the manifest is the final PUT."""
    monkeypatch.setattr("app.services.backup_service.session_scope", maker_scope(maker))
    cache = tmp_path / "cache"
    cache.mkdir()

    order = []

    async def put_bytes(account_id, bucket, key_id, secret, key, body, **kw):
        order.append(key)

    async def put_file(account_id, bucket, key_id, secret, key, path, **kw):
        order.append(key)

    await run_backup(
        cache_dir=cache, settings=_settings(),
        _put_bytes=put_bytes, _put_file=put_file, _now=lambda: FIXED_NOW,
    )
    assert order[-1].endswith("/manifest.json")


@pytest.mark.asyncio
async def test_dumped_postgres_object_is_readable_gzip_jsonl(
    tmp_path, maker, monkeypatch
):
    monkeypatch.setattr("app.services.backup_service.session_scope", maker_scope(maker))
    cache = tmp_path / "cache"
    cache.mkdir()
    rec = Recorder()
    await run_backup(
        cache_dir=cache, settings=_settings(),
        _put_bytes=rec.put_bytes, _put_file=rec.put_file, _now=lambda: FIXED_NOW,
    )
    blob = rec.objects["backups/2026-08-12T09-00-00Z/postgres.jsonl.gz"]
    gzip.decompress(blob)  # must not raise

    manifest = json.loads(
        rec.objects["backups/2026-08-12T09-00-00Z/manifest.json"]
    )
    assert set(manifest["tables"]) == {
        "users", "league_memberships", "app_settings", "page_events", "side_bets",
    }
