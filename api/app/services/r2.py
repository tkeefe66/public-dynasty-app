"""The only module that knows Cloudflare R2 exists.

R2 speaks the S3 API, so boto3 works against an account-scoped endpoint. Two
deliberate absences: there is no delete (retention is a bucket lifecycle rule)
and no list. That is hygiene — it keeps the app incapable of erasing or
enumerating backup history by accident, and no delete/list call may be added
here — but it is NOT an access control: R2 issues no put-only permission group,
so the credential this code holds ("Object Read & Write") can delete and
overwrite regardless of what our code calls. Bucket versioning is the control
that actually protects history. Restore reads with a separate read-scoped token
from an operator machine — see scripts/restore.py.

Every function takes resolved primitives rather than the ``Settings`` object on
purpose: a traceback captured by Sentry carries frame locals, and a Settings
repr contains the database URL, the auth secret, and both R2 keys. An R2 outage
is the expected failure here, so that path is routine, not exotic.

Objects are at most a few hundred MB against R2's ~5 GB single-PUT ceiling, so
no multipart handling is needed.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def endpoint_url(account_id: str) -> str:
    return f"https://{account_id}.r2.cloudflarestorage.com"


def _checksum_kwargs() -> dict:
    """botocore >= 1.36 defaults ``request_checksum_calculation`` to
    "when_supported", which adds CRC32 trailers / aws-chunked encoding to
    PutObject — a known breaker against non-AWS S3 endpoints including R2.
    Older botocore does not accept the kwarg at all (and does not need it)."""
    try:
        import botocore

        parts = tuple(int(p) for p in botocore.__version__.split(".")[:2])
    except Exception:
        return {}
    return {"request_checksum_calculation": "when_required"} if parts >= (1, 36) else {}


def _client(account_id: str, access_key_id: str, secret_access_key: str):
    import boto3
    from botocore.config import Config

    retries = {"retries": {"max_attempts": 3, "mode": "standard"}}
    try:
        config = Config(**retries, **_checksum_kwargs())
    except TypeError:
        # Version sniffing said the kwarg was supported and it wasn't. Better a
        # default-checksum client than no client at all.
        config = Config(**retries)

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url(account_id),
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
        config=config,
    )


def put_bytes_sync(
    account_id: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
    key: str,
    body: bytes,
    *,
    _client_factory=_client,
) -> None:
    client = _client_factory(account_id, access_key_id, secret_access_key)
    client.put_object(Bucket=bucket, Key=key, Body=body)
    log.info("r2: put %s (%d bytes)", key, len(body))


def put_file_sync(
    account_id: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
    key: str,
    path: Path,
    *,
    _client_factory=_client,
) -> None:
    client = _client_factory(account_id, access_key_id, secret_access_key)
    with open(path, "rb") as f:
        client.put_object(Bucket=bucket, Key=key, Body=f)
    log.info("r2: put %s (%d bytes)", key, path.stat().st_size)


async def put_bytes(
    account_id: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
    key: str,
    body: bytes,
    *,
    _client_factory=_client,
) -> None:
    await asyncio.to_thread(
        put_bytes_sync,
        account_id,
        bucket,
        access_key_id,
        secret_access_key,
        key,
        body,
        _client_factory=_client_factory,
    )


async def put_file(
    account_id: str,
    bucket: str,
    access_key_id: str,
    secret_access_key: str,
    key: str,
    path: Path,
    *,
    _client_factory=_client,
) -> None:
    await asyncio.to_thread(
        put_file_sync,
        account_id,
        bucket,
        access_key_id,
        secret_access_key,
        key,
        path,
        _client_factory=_client_factory,
    )
