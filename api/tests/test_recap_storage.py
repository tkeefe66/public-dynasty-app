import hashlib
import uuid
import pytest
from app.services.recap_video.storage import LocalPrivateMediaStore


def test_immutable_verified_private_objects_and_ranges(tmp_path):
    store = LocalPrivateMediaStore(tmp_path)
    key = str(uuid.uuid4())
    data = b"saved synthetic audio"
    sha = hashlib.sha256(data).hexdigest()
    store.put_verified(key, data, sha)
    assert store.head(key)["sha256"] == sha
    assert store.read_range(key, 0, 4) == b"saved"
    with pytest.raises(ValueError):
        store.put_verified(key, b"changed", hashlib.sha256(b"changed").hexdigest())
    with pytest.raises(ValueError):
        store.put_verified(str(uuid.uuid4()), data, "0" * 64)
    with pytest.raises(ValueError):
        store.read_range(key, 0, len(data))
    with pytest.raises(ValueError):
        store.head("../outside")
    evil = str(uuid.uuid4())
    (tmp_path / evil).symlink_to(tmp_path / key)
    with pytest.raises(ValueError):
        store.head(evil)


def test_bucket_adapter_uses_conditional_private_put_and_bounded_range():
    from app.services.recap_video.storage import S3PrivateMediaStore
    from io import BytesIO
    calls = []
    data = b"private"
    sha = hashlib.sha256(data).hexdigest()
    class Bucket:
        def put_object(self, **kwargs): calls.append(kwargs)
        def head_object(self, **kwargs): return {"ContentLength": len(data), "Metadata": {"sha256": sha}}
        def get_object(self, **kwargs):
            calls.append(kwargs)
            return {"Body": BytesIO(b"pri")}
    store = S3PrivateMediaStore(Bucket(), "synthetic-private-bucket")
    key = str(uuid.uuid4())
    store.put_verified(key, data, sha)
    assert calls[0]["IfNoneMatch"] == "*" and "ACL" not in calls[0]
    assert store.read_range(key, 0, 2) == b"pri"
    assert calls[1]["Range"] == "bytes=0-2"


@pytest.mark.asyncio
async def test_orphan_grace_preserves_registered_receipt_assets(maker, tmp_path):
    from app.services.recap_video.storage import cleanup_unregistered
    from app.services.generation.recap_models import RecapAsset
    import os
    store = LocalPrivateMediaStore(tmp_path)
    old, registered, young = [str(uuid.uuid4()) for _ in range(3)]
    for key in (old, registered, young):
        store.put_verified(key, b"test", hashlib.sha256(b"test").hexdigest())
    for key in (old, registered):
        os.utime(tmp_path / key, (1, 1))
    async with maker.begin() as db:
        db.add(RecapAsset(stage_id="synthetic", generation=1, digest=hashlib.sha256(b"test").hexdigest(),
            size=4, media_type="audio/mpeg", storage_key=registered))
    async with maker.begin() as db:
        with pytest.raises(ValueError, match="seven days"):
            await cleanup_unregistered(db, store, 604801, grace_seconds=604799)
        assert await cleanup_unregistered(db, store, 604800) == 0
        assert await cleanup_unregistered(db, store, 604801) == 1
    assert not (tmp_path / old).exists()
    assert (tmp_path / registered).exists() and (tmp_path / young).exists()
