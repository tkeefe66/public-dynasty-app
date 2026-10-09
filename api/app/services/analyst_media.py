"""Operator-published episode bundles on the existing persistent API volume.

One API replica/shared filesystem, like AnalystStore. Immutable bundles plus an
atomic manifest keep playback consistent during replacement. No public static
mount: every read rechecks the share token, publication, revision and bundle ID.
Before scaling replicas, move this storage boundary to private object storage.
"""
import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
from pathlib import Path

from app.services.analyst_shares import AnalystShares

log = logging.getLogger(__name__)
ASSETS = {"video.mp4": "video/mp4", "audio.mp3": "audio/mpeg",
          "poster.jpg": "image/jpeg", "captions.vtt": "text/vtt"}
LIMITS = {"video.mp4": 128 * 1024**2, "audio.mp3": 32 * 1024**2,
          "poster.jpg": 5 * 1024**2, "captions.vtt": 1024**2}


class AnalystMedia:
    def __init__(self, cache_dir):
        self.shares = AnalystShares(cache_dir)

    def _root(self, league_id, season, week):
        edition = self.shares.archive.edition_path(league_id, season, week)
        return edition.parent / "media" / edition.stem

    def attach(self, league_id, season, week, source: Path, *, revision, duration_seconds):
        """Publish a complete, reviewed bundle. Does not enable public sharing."""
        edition = self.shares.edition(league_id, season, week)
        if edition is None:
            raise ValueError("A published recap is required before attaching media.")
        if edition["revision"] != revision:
            raise ValueError("Article revision changed. Review the episode against the latest revision.")
        if not math.isfinite(duration_seconds) or not 0 < duration_seconds <= 1800:
            raise ValueError("Episode duration must be between zero and 1800 seconds.")
        for name, limit in LIMITS.items():
            path = source / name
            if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= limit:
                raise ValueError(f"Missing or oversized {name}. Supply the complete verified bundle.")
            with path.open("rb") as handle:
                head = handle.read(16)
            valid = {"video.mp4": head[4:8] == b"ftyp",
                     "audio.mp3": head.startswith(b"ID3") or (len(head) > 1 and head[0] == 255 and head[1] & 224 == 224),
                     "poster.jpg": head.startswith(b"\xff\xd8\xff"),
                     "captions.vtt": head.startswith(b"WEBVTT")}
            if not valid[name]:
                raise ValueError(f"Invalid {name} format. Re-export the episode before publishing.")
        root = self._root(league_id, season, week)
        manifest_path = root / "current.json"
        with self.shares._lock(manifest_path):
            bundle_id = secrets.token_hex(16)
            bundle = root / bundle_id
            bundle.mkdir()
            files = {}
            for name in ASSETS:
                dest = bundle / name
                shutil.copyfile(source / name, dest)
                with dest.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                    os.fsync(handle.fileno())
                files[name] = {"bytes": dest.stat().st_size, "sha256": digest}
            manifest = {"id": bundle_id, "revision": revision, "duration_seconds": duration_seconds, "files": files}
            # A concurrent correction leaves this hidden until a matching take is attached.
            self.shares._write(manifest_path, manifest)
        log.info("Recap media attached league=%s season=%s week=%s revision=%s", league_id, season, week, revision)
        return manifest

    def current(self, target, edition):
        root = self._root(**target)
        path = root / "current.json"
        if not path.exists():
            return None
        manifest = json.loads(path.read_text())
        if manifest["revision"] != edition["revision"]:
            return None
        if not re.fullmatch(r"[a-f0-9]{32}", manifest["id"]):
            raise ValueError("Invalid media manifest")
        for name in ASSETS:
            asset = root / manifest["id"] / name
            if not asset.is_file() or asset.is_symlink() or asset.stat().st_size != manifest["files"][name]["bytes"]:
                raise ValueError("Incomplete media bundle")
        return manifest

    @staticmethod
    def public_metadata(manifest):
        if manifest is None:
            return None
        return {"id": manifest["id"], "duration_seconds": manifest["duration_seconds"],
                "video_bytes": manifest["files"]["video.mp4"]["bytes"],
                "audio_bytes": manifest["files"]["audio.mp3"]["bytes"]}

    def resolve(self, token):
        target = self.shares.resolve_target(token)
        if target is None:
            return None
        edition = self.shares.edition(**target)
        if edition is None:
            return None
        return target, edition, self.current(target, edition)

    def asset(self, token, bundle_id, name):
        if name not in ASSETS:
            return None
        result = self.resolve(token)
        if result is None:
            return None
        target, edition, manifest = result
        if manifest is None or manifest["id"] != bundle_id:
            return None
        return self._root(**target) / manifest["id"] / name, edition
