import json
import tarfile

from app.services.backup_service import archive_cache, build_manifest


def test_archive_contains_every_file_with_relative_names(tmp_path):
    cache = tmp_path / "cache"
    (cache / "snapshots" / "daily").mkdir(parents=True)
    (cache / "chain_L1.json").write_text('{"a":1}')
    (cache / "snapshots" / "daily" / "2026-08-01.json").write_text("[]")

    dest = tmp_path / "cache.tar.gz"
    members, size = archive_cache(cache, dest)

    assert members == 2
    assert size == dest.stat().st_size > 0
    with tarfile.open(dest) as tar:
        assert sorted(tar.getnames()) == [
            "chain_L1.json",
            "snapshots/daily/2026-08-01.json",
        ]


def test_archive_skips_in_flight_atomic_write_temp_files(tmp_path):
    """write_json_atomic leaves a `.<name>.<rand>.tmp` file mid-write. Those are
    a concurrent writer's private state, not cache content."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "chain_L1.json").write_text("{}")
    (cache / ".chain_L2.json.abc123.tmp").write_text("{partial")

    dest = tmp_path / "cache.tar.gz"
    members, _ = archive_cache(cache, dest)

    assert members == 1
    with tarfile.open(dest) as tar:
        assert tar.getnames() == ["chain_L1.json"]


def test_archive_skips_symlinks_so_the_backup_stays_restorable(tmp_path):
    """path.is_file() follows symlinks, but tar.add (dereference=False) would
    archive a symlink as a SYMTYPE member — which safe_extract in
    scripts/restore.py refuses, aborting the whole restore. A symlink must
    never make it into the tar."""
    cache = tmp_path / "cache"
    cache.mkdir()
    real = cache / "chain_L1.json"
    real.write_text("{}")
    (cache / "chain_L1_link.json").symlink_to(real)

    dest = tmp_path / "cache.tar.gz"
    members, _ = archive_cache(cache, dest)

    assert members == 1
    with tarfile.open(dest) as tar:
        assert tar.getnames() == ["chain_L1.json"]
        assert all(not m.issym() and not m.islnk() for m in tar.getmembers())


def test_archive_of_an_empty_dir_is_a_valid_empty_tar(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    dest = tmp_path / "cache.tar.gz"
    members, size = archive_cache(cache, dest)
    assert members == 0
    with tarfile.open(dest) as tar:
        assert tar.getnames() == []


def test_manifest_carries_everything_a_restore_needs_to_verify():
    m = build_manifest(
        run_id="2026-08-12T09-00-00Z",
        created_at="2026-08-12T09:00:00+00:00",
        table_counts={"users": 3, "side_bets": 7},
        tar_members=412,
        tar_bytes=20_481_003,
        alembic_revision="0007_side_bets",
        git_sha="abc1234",
    )
    assert m["run_id"] == "2026-08-12T09-00-00Z"
    assert m["tables"] == {"users": 3, "side_bets": 7}
    assert m["cache"] == {"members": 412, "bytes": 20_481_003}
    assert m["alembic_revision"] == "0007_side_bets"
    assert m["git_sha"] == "abc1234"
    assert isinstance(m["chain_cache_schema_version"], int)
    json.dumps(m)  # must be serializable as-is
