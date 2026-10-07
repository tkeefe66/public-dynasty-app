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
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from sleeper_dynasty.api.player_context import safe_source_url


class AnalystSource(BaseModel):
    publisher: str
    title: str
    published_at: str | None = None
    url: str | None = None

    @field_validator("url", mode="before")
    @classmethod
    def safe_url(cls, value):
        for domain in ("rotowire.com", "rotoballer.com", "fantasypros.com", "nflverse.com"):
            safe = safe_source_url(value, domain)
            if safe:
                return safe
        return None


class AnalystEdition(BaseModel):
    season: int = Field(ge=2000, le=2200)
    week: int = Field(ge=1, le=18)
    league_name: str
    generated_at: str
    model: str
    edition_type: Literal["roast", "results"] = "roast"
    markdown: str = Field(min_length=1)
    facts: dict
    outlook: dict | None = None
    lore: str | None = None
    revision: int = Field(default=1, ge=1)
    correction_note: str | None = None
    original_markdown: str | None = None
    sources: list[AnalystSource] = Field(default_factory=list)
    context_note: str | None = None


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

    def published_editions(self, league_id: str) -> list[dict]:
        """Reader archive contains AI roasts only; results are private job inputs.

        Keep legacy packets and their revisions intact for managed generation,
        but never expose a results fallback through archive or public sharing.
        """
        published = []
        for edition in self.editions(league_id):
            if edition["edition_type"] != "roast":
                continue
            original = AnalystEdition.model_validate_json(self.edition_path(
                league_id, edition["season"], edition["week"]).read_text())
            if original.edition_type != "roast":
                edition = {**edition, "original_markdown": None}
            published.append(edition)
        return published

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

    def start_attempt(self, league_id: str, season: int, week: int, now: float) -> bool:
        """Persist backoff under the generation claim, shared by every trigger.

        A crash or deploy also retains the cooldown. Attempts are per edition,
        never a reason to delay a new week's first attempt or replace a saved one.
        """
        edition = self.edition_path(league_id, season, week)
        path = edition.parent / "attempts" / edition.name
        prior = json.loads(path.read_text()) if path.exists() else {}
        if now < prior.get("retry_at", 0):
            return False
        count = int(prior.get("count", 0)) + 1
        delay = (1800, 3600, 10800, 21600)[min(count - 1, 3)]
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"count": count, "started_at": now, "retry_at": now + delay}
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".attempt-")
        temp = Path(temporary)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return True

    def save_correction(self, league_id: str, edition: dict, reason: str, *, claimed: bool = False) -> None:
        """Append an operator correction or approved results-to-roast revision."""
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
