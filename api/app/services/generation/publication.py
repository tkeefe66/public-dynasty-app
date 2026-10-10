"""Replayable projections; PostgreSQL artifacts remain authoritative."""
import json
import logging

from sqlalchemy import select

from app.services.generation.models import ContentArtifact, GenerationOutbox
from app.services.generation.store import Held, digest, lock_control

log = logging.getLogger(__name__)


def project_analyst(cache_dir, row, previous):
    from app.services.analyst_store import AnalystEdition, AnalystStore
    store = AnalystStore(cache_dir)
    data = json.loads(row.payload_json)
    with store.claim(row.league_id) as acquired:
        if not acquired:
            raise Held("archive_busy")
        original = store.edition_path(row.league_id, data["season"], data["week"])
        target = (original if row.revision == 1 else
                  original.parent / "revisions" / original.stem / f"{row.revision:06d}.json")
        if target.exists():
            actual = AnalystEdition.model_validate_json(target.read_text()).model_dump()
            if digest(actual) != row.digest:
                raise Held("archive_revision_conflict")
            return
        if previous:
            p = json.loads(previous.payload_json)
            path = (original if previous.revision == 1 else original.parent / "revisions" /
                    original.stem / f"{previous.revision:06d}.json")
            if not path.exists() or digest(AnalystEdition.model_validate_json(
                    path.read_text()).model_dump()) != digest(p):
                raise Held("archive_predecessor_changed")
        # A stale file-only writer cannot be overwritten by a new revision.
        current = next((e for e in store.editions(row.league_id)
            if (e["season"], e["week"]) == (data["season"], data["week"])), None)
        if current and current["revision"] >= row.revision:
            raise Held("archive_revision_conflict")
        store._write_once(target, data)


async def drain(maker, cache_dir, *, execution_role="api-projector"):
    if execution_role != "api-projector":
        raise Held("api_projector_required")
    async with maker() as db:
        ids = list((await db.scalars(select(GenerationOutbox.id).where(
            GenerationOutbox.delivered.is_(False), GenerationOutbox.error == ""
        ).order_by(GenerationOutbox.created_at).limit(100))).all())
    for ident in ids:
        # Short file projection is serialized with DB mutations; no provider I/O.
        async with maker.begin() as db:
            control = await lock_control(db)
            if control.hold == "restore_quarantine":
                return
            item = await db.get(GenerationOutbox, ident, populate_existing=True)
            if item.delivered:
                continue
            try:
                payload = json.loads(item.payload_json)
                if item.kind == "recap_publication":
                    from app.services.recap_video.publication import project_publication
                    await project_publication(db, item, cache_dir)
                elif item.kind == "artifact":
                    row = await db.get(ContentArtifact, payload["artifact_id"])
                    if row.feature == "recap_video":
                        raise Held("private_script_not_reader_content")
                    if row.feature == "analyst":
                        from app.services.recap_video.readiness import require_readiness
                        episode = await require_readiness(db, row.series_id, json.loads(row.facts_json), league_id=row.league_id)
                        previous = (await db.get(ContentArtifact, payload["expected_artifact"])
                                    if payload.get("expected_artifact") else None)
                        project_analyst(cache_dir, row, previous)
                        if episode:
                            episode.article_digest = row.digest
                    else:
                        from app.services.chain_cache import ChainCache
                        from app.services.generation.artifacts import overlay
                        cache = ChainCache(cache_dir)
                        entry = cache.read(row.league_id, max_age_seconds=10**10)
                        if entry:
                            await overlay(db, entry, row.series_id)
                            cache.write(row.league_id, entry)
                # Telemetry is read from the ledger; do not duplicate legacy JSONL spend.
                item.delivered = True
            except Held as exc:
                if exc.code not in ("archive_busy", "schedule_incomplete", "source_error", "games_unresolved",
                        "facts_unstable", "release_not_due", "schedule_inventory_unqualified", "bracket_unavailable",
                        "publication_paused", "public_serving_quarantined"):
                    item.error = exc.code
                log.warning("publication held id=%s reason=%s", ident, exc.code)
            except Exception:
                item.error = "projection_failed"
                log.exception("publication failed id=%s", ident)
