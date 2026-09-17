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
from contextlib import contextmanager, nullcontext
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
    revision: int = Field(default=1, ge=1)
    correction_note: str | None = None
    original_markdown: str | None = None


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
        editions = []
        for p in sorted(self.league_dir(league_id).glob("*.json"), reverse=True):
            original = AnalystEdition.model_validate_json(p.read_text()).model_dump()
            revisions = sorted((p.parent / "revisions" / p.stem).glob("*.json"))
            if revisions:
                latest = AnalystEdition.model_validate_json(revisions[-1].read_text()).model_dump()
                if (latest["season"], latest["week"]) != (original["season"], original["week"]):
                    raise ValueError("Analyst revision belongs to a different edition")
                latest["original_markdown"] = original["markdown"]
                editions.append(latest)
            else:
                editions.append(original)
        return editions

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
        self._write_once(path, data)

    def save_correction(self, league_id: str, edition: dict, reason: str, *, claimed: bool = False) -> None:
        """Explicit operator correction; never called by automatic generation."""
        if not reason.strip():
            raise ValueError("A correction needs a reader-visible reason")
        data = AnalystEdition.model_validate(edition).model_dump()
        with (nullcontext(True) if claimed else self.claim(league_id)) as acquired:
            if not acquired:
                raise RuntimeError("Analyst generation is in progress; retry correction later")
            current = next((e for e in self.editions(league_id)
                            if (e["season"], e["week"]) == (data["season"], data["week"])), None)
            if current is None:
                raise ValueError("Cannot correct an edition that has not been published")
            data.update(revision=current["revision"] + 1, correction_note=reason.strip(), original_markdown=None)
            original = self.edition_path(league_id, data["season"], data["week"])
            path = original.parent / "revisions" / original.stem / f'{data["revision"]:06d}.json'
            self._write_once(path, data)

    @staticmethod
    def _write_once(path: Path, data: dict) -> None:
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
