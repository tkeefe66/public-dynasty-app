"""Synthetic media bytes test access/transport; real playback is a separate smoke check."""
import pytest
from fastapi.testclient import TestClient

from app.deps import get_cache_dir
from app.main import app
from app.services.analyst_store import AnalystStore
from tests.test_analyst_sharing import seed


def attach(tmp_path, revision=1):
    from app.services.analyst_media import AnalystMedia
    files = {"video.mp4": b"\x00\x00\x00\x18ftypisom" + bytes(range(256)),
             "audio.mp3": b"ID3" + bytes(range(256)), "poster.jpg": b"\xff\xd8\xff" + b"poster",
             "captions.vtt": b"WEBVTT\n\n00:00.000 --> 00:01.000\nTest narration\n"}
    for name, content in files.items():
        (tmp_path / name).write_bytes(content)
    return AnalystMedia(get_cache_dir()).attach("test", 2026, 1, tmp_path, revision=revision, duration_seconds=2)


def test_media_publish_refuses_incomplete_bundle(client, tmp_path):
    # Mutation: switch the public manifest before every asset is present.
    seed()
    from app.services.analyst_media import AnalystMedia
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="video.mp4"):
        AnalystMedia(get_cache_dir()).attach("test", 2026, 1, empty, revision=1, duration_seconds=2)


def test_media_requires_live_share_and_supports_phone_ranges(client, tmp_path):
    # Mutation: serve assets without resolving the current token, or ignore byte ranges.
    seed()
    attach(tmp_path)
    token = client.post("/api/league/test/analyst/2026/1/share").json()["token"]
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    anonymous = TestClient(app)
    try:
        media = anonymous.get(f"/api/public/analyst/{token}").json()["media"]
        base = f"/api/public/analyst/{token}/media/{media['id']}"
        url = base + "/video.mp4"
        response = anonymous.get(url, headers={"Range": "bytes=8-15"})
        assert response.status_code == 206
        assert response.content == (tmp_path / "video.mp4").read_bytes()[8:16]
        assert response.headers["content-range"].startswith("bytes 8-15/")
        assert response.headers["content-length"] == "8"
        assert "no-store" in response.headers["cache-control"]
        assert anonymous.head(url).headers["content-length"] == str((tmp_path / "video.mp4").stat().st_size)
        unsatisfiable = anonymous.get(url, headers={"Range": "bytes=999999-"})
        assert unsatisfiable.status_code == 416
        assert "no-store" in unsatisfiable.headers["cache-control"]
        for name in ("video.mp4", "audio.mp3", "poster.jpg", "captions.vtt"):
            result = anonymous.get(base + "/" + name + "?download=true")
            assert result.status_code == 200
            assert "attachment" in result.headers["content-disposition"]
            assert result.content == (tmp_path / name).read_bytes()
        assert anonymous.get(base + "/manifest.json").status_code == 404
    finally:
        anonymous.close()
        app.dependency_overrides.update(overrides)
    client.delete("/api/league/test/analyst/2026/1/share")
    assert client.get(url).status_code == 404
    assert "no-store" in client.get(url).headers["cache-control"]
    assert client.head(url).status_code == 404


def test_corrected_edition_hides_old_video_and_old_asset_urls(client, tmp_path):
    # Mutation: keep stale narration visible after a correction changes the article revision.
    data = seed()
    attach(tmp_path)
    token = client.post("/api/league/test/analyst/2026/1/share").json()["token"]
    url = f"/api/public/analyst/{token}"
    old_id = client.get(url).json()["media"]["id"]
    AnalystStore(get_cache_dir()).save_correction("test", {**data, "markdown": "Corrected"}, "Fixed score")
    assert client.get(url).json()["media"] is None
    assert client.get(f"{url}/media/{old_id}/video.mp4").status_code == 404
    with pytest.raises(ValueError, match="revision"):
        attach(tmp_path)
    attach(tmp_path, revision=2)
    assert client.get(url).json()["media"] is not None


def test_media_publish_refuses_private_results(client, tmp_path):
    # Mutation: allow attaching media to a private results packet.
    seed("results")
    with pytest.raises(ValueError, match="published"):
        attach(tmp_path)


def test_new_bundle_retires_previous_asset_id(client, tmp_path):
    # Mutation: accept an arbitrary old bundle ID after a replacement has been published.
    seed()
    first = attach(tmp_path)
    second = attach(tmp_path)
    token = client.post("/api/league/test/analyst/2026/1/share").json()["token"]
    prefix = f"/api/public/analyst/{token}/media"
    assert first["id"] != second["id"]
    assert client.get(f"{prefix}/{first['id']}/video.mp4").status_code == 404
    assert client.get(f"{prefix}/{second['id']}/video.mp4").status_code == 200
