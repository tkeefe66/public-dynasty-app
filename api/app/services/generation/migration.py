"""Import existing local prose without provider I/O or generation authorization."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from app.services.generation.models import ArtifactHead, ContentArtifact, LeagueSeason
from app.services.generation.planner import collect_analyst, import_chain
from app.services.generation.store import Held, audit, data, digest, lock_control


async def reconcile_legacy(db, cache_dir):
    control = await lock_control(db)
    if not control.hold:
        raise Held("Pause paid generation before importing legacy content")
    root = Path(cache_dir)
    files, blocked = {}, []
    for path in sorted(root.glob("chain_*.json")):
        raw_bytes = path.read_bytes()
        files[path.name] = hashlib.sha256(raw_bytes).hexdigest()
        raw = json.loads(raw_bytes)
        league_id = raw.get("league_id")
        if path.name != f"chain_{league_id}.json":
            raise ValueError("Cache filename and league identity disagree")
        season = await db.get(LeagueSeason, league_id)
        if not season:
            blocked.append({"league_id": league_id, "reason": "Refresh free provider data to verify league identity first"})
            continue
        await import_chain(db, raw, season.series_id)
    # Also cover archives whose disposable chain cache was deleted.
    for season in (await db.scalars(select(LeagueSeason))).all():
        await collect_analyst(db, season.league_id, season.series_id, root)
    for path in sorted((root / "analyst").rglob("*.json")):
        files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    await db.flush()
    artifacts = [data(row) for row in (await db.scalars(select(ContentArtifact).order_by(
        ContentArtifact.subject, ContentArtifact.revision))).all()]
    conflicts = [data(row) for row in (await db.scalars(select(ArtifactHead).where(
        ArtifactHead.hold != ""))).all()]
    report = {"artifact_count": len(artifacts), "artifact_digest": digest(artifacts),
        "source_files": files, "source_digest": digest(files), "blocked": blocked, "conflicts": conflicts}
    audit(db, "migration", "legacy_reconciled", "global",
        "Import existing prose without authorizing paid work", after=report)
    return report
