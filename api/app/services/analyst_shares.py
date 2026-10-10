"""Revocable, edition-scoped public capabilities on the persistent volume.

Share tokens are credentials: never log them. Reads return only the published
article. The generation archive and share state are separate from cache TTLs.
File locks assume the same shared volume as AnalystStore (one API replica).
"""
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from contextlib import contextmanager

from app.services.analyst_store import AnalystEdition, AnalystStore


class AnalystShares:
    def __init__(self, cache_dir):
        self.archive = AnalystStore(cache_dir)
        self.index = cache_dir / "analyst_shares"

    def _path(self, league_id, season, week):
        path = self.archive.edition_path(league_id, season, week)
        return path.parent / "shares" / path.name

    @contextmanager
    def _lock(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / ".share.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
            try:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
                os.replace(f.name, path)
            finally:
                if os.path.exists(f.name):
                    os.unlink(f.name)

    def state(self, league_id, season, week):
        path = self._path(league_id, season, week)
        return json.loads(path.read_text()) if path.exists() else {"token": None}

    def edition(self, league_id, season, week):
        # One malformed edition cannot hold every other share in this league.
        path = self.archive.edition_path(league_id, season, week)
        if not path.exists():
            return None
        original = AnalystEdition.model_validate_json(path.read_text()).model_dump()
        revisions = sorted((path.parent/'revisions'/path.stem).glob('*.json'))
        edition = AnalystEdition.model_validate_json(revisions[-1].read_text()).model_dump() if revisions else original
        if (edition['season'], edition['week']) != (season, week):
            raise ValueError('Analyst revision belongs to a different edition')
        if edition['edition_type'] != 'roast':
            return None
        if revisions:
            edition['original_markdown'] = original['markdown'] if original['edition_type'] == 'roast' else None
        return edition

    def create(self, league_id, season, week):
        if self.edition(league_id, season, week) is None:
            return None
        path = self._path(league_id, season, week)
        with self._lock(path):
            state = self.state(league_id, season, week)
            if state.get("token"):
                return state
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            self._write(self.index / f"{digest}.json", {"league_id": league_id, "season": season, "week": week})
            self._write(path, {"token": token})
            return {"token": token}

    def revoke(self, league_id, season, week):
        path = self._path(league_id, season, week)
        with self._lock(path):
            self._write(path, {"token": None})

    def resolve_target(self, token):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        path = self.index / f"{digest}.json"
        if not path.exists():
            return None
        target = json.loads(path.read_text())
        state = self.state(**target)
        if not hmac.compare_digest(state.get("token") or "", token):
            return None
        return target

    def resolve(self, token):
        target = self.resolve_target(token)
        return self.edition(**target) if target else None
