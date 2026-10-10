"""API-only private immutable objects. Workers see leased API streams only."""
import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import Protocol

MAX_ASSET = 64 * 1024 * 1024
ORPHAN_GRACE_SECONDS = 7 * 86400


class PrivateMediaStore(Protocol):
    def put_verified(self, key: str, data: bytes, sha256: str) -> None: ...
    def head(self, key: str) -> dict: ...
    def read_range(self, key: str, start: int, end: int) -> bytes: ...
    def delete_unreferenced(self, key: str) -> None: ...


def valid_key(key):
    try:
        if str(uuid.UUID(key)) != key:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Private media object key invalid") from None
    return key


def verified(data, sha256):
    if not data or len(data) > MAX_ASSET or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("Private media object size or SHA256 mismatch")


def bounds(start, end, size):
    if type(start) is not int or type(end) is not int or not 0 <= start <= end < size:
        raise ValueError("Private media object range invalid")


class LocalPrivateMediaStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key):
        path = self.root / valid_key(key)
        if path.is_symlink():
            raise ValueError("Private media object symlink forbidden")
        return path

    def put_verified(self, key, data, sha256):
        verified(data, sha256)
        target = self._path(key)
        fd, temporary = tempfile.mkstemp(dir=self.root, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                raise ValueError("Private media object is immutable") from None
        finally:
            Path(temporary).unlink(missing_ok=True)

    def head(self, key):
        with os.fdopen(os.open(self._path(key), os.O_RDONLY | os.O_NOFOLLOW), "rb") as file:
            data = file.read(MAX_ASSET + 1)
        if not data or len(data) > MAX_ASSET:
            raise ValueError("Private media object size invalid")
        return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def read_range(self, key, start, end):
        path = self._path(key)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as file:
            bounds(start, end, os.fstat(file.fileno()).st_size)
            file.seek(start)
            data = file.read(end - start + 1)
        if len(data) != end - start + 1:
            raise ValueError("Private media object truncated")
        return data

    def delete_unreferenced(self, key):
        # Caller must establish no references and grace period under API control.
        self._path(key).unlink(missing_ok=True)

    def older_than(self, cutoff):
        for path in self.root.iterdir():
            try:
                valid_key(path.name)
            except ValueError:
                continue
            if not path.is_symlink() and path.is_file() and path.stat().st_mtime <= cutoff:
                yield path.name


class S3PrivateMediaStore:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def put_verified(self, key, data, sha256):
        verified(data, sha256)
        self.client.put_object(Bucket=self.bucket, Key=valid_key(key), Body=data,
            Metadata={"sha256": sha256}, IfNoneMatch="*", ContentType="application/octet-stream")

    def head(self, key):
        row = self.client.head_object(Bucket=self.bucket, Key=valid_key(key))
        return {"size": row["ContentLength"], "sha256": row.get("Metadata", {}).get("sha256", "")}

    def read_range(self, key, start, end):
        bounds(start, end, self.head(key)["size"])
        response = self.client.get_object(Bucket=self.bucket, Key=valid_key(key), Range=f"bytes={start}-{end}")
        body = response["Body"]
        try:
            data = body.read(end - start + 2)
        finally:
            body.close()
        if len(data) != end - start + 1:
            raise ValueError("Private media object range response invalid")
        return data

    def delete_unreferenced(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=valid_key(key))

    def older_than(self, cutoff):
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket):
            for row in page.get("Contents", []):
                try:
                    valid_key(row["Key"])
                except ValueError:
                    continue
                if row["LastModified"].timestamp() <= cutoff:
                    yield row["Key"]


def configured_store():
    from app.config import get_settings
    from app.services.generation.store import Held
    config = get_settings()
    if config.media_bucket:
        import boto3
        from botocore.config import Config
        return S3PrivateMediaStore(boto3.client("s3", endpoint_url=config.media_bucket_endpoint or None,
            config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 0})), config.media_bucket)
    if config.media_asset_root is not None:
        return LocalPrivateMediaStore(config.media_asset_root)
    raise Held("media_storage_unconfigured")


async def cleanup_unregistered(db, store, now, *, grace_seconds=ORPHAN_GRACE_SECONDS):
    """API maintenance hook for Task10; no new scheduler or worker deletion route.

    Preserve every registered object, including unselected late receipt evidence.
    Only incomplete uploads without any DB reference age out, after seven days.
    """
    from sqlalchemy import select
    from app.services.generation.recap_models import RecapAsset
    from app.services.generation.store import lock_control
    import asyncio
    if grace_seconds < ORPHAN_GRACE_SECONDS:
        raise ValueError("Private media orphan grace must be at least seven days")
    candidates = await asyncio.to_thread(lambda: list(store.older_than(now - grace_seconds)))
    await lock_control(db)
    registered = set((await db.scalars(select(RecapAsset.storage_key))).all())
    removed = 0
    for key in candidates:
        if key not in registered:
            await asyncio.to_thread(store.delete_unreferenced, key)
            removed += 1
    return removed
