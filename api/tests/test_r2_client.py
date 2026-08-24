from pathlib import Path

import pytest

from app.config import Settings
from app.services import r2


def _settings(**over):
    base = dict(
        backup_enabled=True,
        r2_account_id="acct123",
        r2_bucket="dynasty-backups",
        r2_access_key_id="AK",
        r2_secret_access_key="SK",
    )
    base.update(over)
    return Settings(**base)


CREDS = ("acct123", "dynasty-backups", "AK", "SK")


class FakeClient:
    def __init__(self):
        self.calls = []

    def put_object(self, **kw):
        body = kw["Body"]
        self.calls.append(
            (kw["Bucket"], kw["Key"], body if isinstance(body, bytes) else body.read())
        )


def test_put_bytes_sends_bucket_key_and_body():
    fake = FakeClient()
    r2.put_bytes_sync(*CREDS, "backups/run/x.json", b"hello",
                      _client_factory=lambda *a: fake)
    assert fake.calls == [("dynasty-backups", "backups/run/x.json", b"hello")]


def test_put_file_streams_the_file(tmp_path: Path):
    p = tmp_path / "cache.tar.gz"
    p.write_bytes(b"tarbytes")
    fake = FakeClient()
    r2.put_file_sync(*CREDS, "backups/run/cache.tar.gz", p,
                     _client_factory=lambda *a: fake)
    assert fake.calls == [("dynasty-backups", "backups/run/cache.tar.gz", b"tarbytes")]


def test_the_settings_object_never_crosses_into_the_r2_layer():
    """A failed upload's traceback reaches Sentry with frame locals attached.
    Settings' repr carries the database URL, the auth secret and both R2 keys,
    so these functions take resolved primitives only."""
    seen = []

    def factory(account_id, access_key_id, secret_access_key):
        seen.append((account_id, access_key_id, secret_access_key))
        return FakeClient()

    r2.put_bytes_sync(*CREDS, "k", b"v", _client_factory=factory)
    assert seen == [("acct123", "AK", "SK")]


def test_endpoint_is_account_scoped():
    assert r2.endpoint_url("acct123") == "https://acct123.r2.cloudflarestorage.com"


def test_the_real_boto3_client_constructs():
    """Every other test injects _client_factory, so nothing else exercises the
    real boto3 kwargs. A bad Config kwarg should fail here, not at 09:00 UTC in
    production."""
    client = r2._client("acct123", "AK", "SK")
    assert client.meta.endpoint_url == "https://acct123.r2.cloudflarestorage.com"


def test_checksums_are_not_calculated_unless_required():
    """botocore >= 1.36 defaults to "when_supported", which adds CRC32 trailers
    to PutObject and has historically broken non-AWS S3 endpoints incl. R2."""
    import botocore

    if tuple(int(p) for p in botocore.__version__.split(".")[:2]) < (1, 36):
        pytest.skip("botocore predates request_checksum_calculation")
    assert r2._checksum_kwargs() == {"request_checksum_calculation": "when_required"}
    client = r2._client("acct123", "AK", "SK")
    assert client.meta.config.request_checksum_calculation == "when_required"


@pytest.mark.parametrize(
    "missing",
    ["r2_account_id", "r2_bucket", "r2_access_key_id", "r2_secret_access_key"],
)
def test_not_configured_when_any_r2_value_is_missing(missing):
    assert _settings(**{missing: ""}).backup_configured is False


def test_not_configured_when_disabled():
    assert _settings(backup_enabled=False).backup_configured is False


def test_configured_when_enabled_and_complete():
    assert _settings().backup_configured is True
