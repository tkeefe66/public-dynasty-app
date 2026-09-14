"""Permanent, write-once weekly editions, independent of ChainCache TTL/schema.

The archive lives on the existing persistent volume and is included in its
backups. Atomic publication and a process-wide file lock protect simultaneous
manual/scheduled refreshes. Corruption is an error, never permission to rewrite.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, Field


class AnalystEdition(BaseModel):
    season: int = Field(ge=2000, le=2200)
    week: int = Field(ge=1, le=18)
    league_name: str
    generated_at: str
    model: str
    markdown: str = Field(min_length=1)
    facts: dict
    outlook: dict | None = None
    lore: str | None = None


class AnalystStore:
    def __init__(self, cache_dir: Path):
        self.root = Path(cache_dir) / "analyst"

    def league_dir(self, league_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", league_id):
            raise ValueError("Invalid league identifier")
        return self.root / league_id

    def edition_path(self, league_id: str, season: int, week: int) -> Path:
        if not 2000 <= season <= 2200 or not 1 <= week <= 18:
            raise ValueError("Invalid edition season or week")
        return self.league_dir(league_id) / f"{season}-{week:02d}.json"

    def editions(self, league_id: str) -> list[dict]:
        return [AnalystEdition.model_validate_json(p.read_text()).model_dump()
                for p in sorted(self.league_dir(league_id).glob("*.json"), reverse=True)]

    @contextmanager
    def claim(self, league_id: str):
        folder = self.league_dir(league_id)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / ".generation.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def save(self, league_id: str, edition: dict) -> None:
        data = AnalystEdition.model_validate(edition).model_dump()
        path = self.edition_path(league_id, data["season"], data["week"])
        path.parent.mkdir(parents=True, exist_ok=True)
        # Hard-link a fully flushed temp file. Unlike replace(), link() can
        # never overwrite an existing edition, even outside the claim lock.
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".edition-", suffix=".tmp", delete=False) as f:
            temp = Path(f.name)
            try:
                json.dump(data, f, ensure_ascii=False, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
                os.link(temp, path)
            finally:
                temp.unlink(missing_ok=True)
