"""Provider-confirmed league continuity; names never establish identity."""
import json

from sqlalchemy import select

from app.services.generation.models import LeagueSeason, LeagueSeries, stamp
from app.services.generation.policy import paid_capabilities
from app.services.generation.store import audit, dump, lock_control


async def register_entry(db, entry, *, verified: bool = False) -> LeagueSeason:
    await lock_control(db)
    chain = entry.chain or [{"league_id": entry.league_id,
                             "season": entry.league_season_by_id.get(entry.league_id, 0)}]
    provider = "yahoo" if ".l." in entry.league_id else "sleeper"
    # Only an actual provider history walk can link season records.
    ids = [str(row["league_id"]) for row in chain] if verified else [entry.league_id]
    if any((".l." in lid) != (provider == "yahoo") for lid in ids):
        raise ValueError("Provider history contains a foreign league identity")
    prior = list((await db.scalars(select(LeagueSeason).where(
        LeagueSeason.league_id.in_(ids)))).all())
    series_ids = {row.series_id for row in prior}
    current = next((row for row in prior if row.league_id == entry.league_id), None)
    if len(series_ids) > 1:
        for sid in series_ids:
            series = await db.get(LeagueSeries, sid)
            series.hold = "identity_conflict"
        if current:
            return current
        raise ValueError("Season mapping conflicts; owner must review existing series")
    series = await db.get(LeagueSeries, next(iter(series_ids))) if series_ids else None
    caps = paid_capabilities(entry.capabilities)
    if series is None:
        series = LeagueSeries(name=entry.league_name_by_id.get(entry.league_id, ""),
                              profile=caps["format"] if caps else "")
        db.add(series)
        await db.flush()
    by_id = {row.league_id: row for row in prior}
    for raw in chain:
        lid = str(raw["league_id"])
        if lid not in ids:
            continue
        row = by_id.get(lid)
        if row is None:
            row = LeagueSeason(league_id=lid, provider=provider, provider_key=lid,
                               series_id=series.id, season=int(raw.get("season") or 0))
            db.add(row)
        if lid == entry.league_id:
            row.capabilities_json = dump(caps or {})
            # A normalized default format is insufficient evidence.
            evidence = verified and bool(raw.get("format_verified", False)) and bool(caps)
            row.verified_at = stamp() if evidence else 0
            row.evidence_json = dump({"source": "provider_history" if verified else "legacy_cache",
                                      "chain": ids, "format_verified": bool(evidence)})
            period = getattr(entry, "generation_period", {}) or {}
            row.latest_week = int(period.get("week") or 0) if period.get("season") == row.season else 0
            current = row
    await db.flush()
    if current is None:
        raise ValueError("Current season missing from provider history")
    return current


async def set_series(db, series_id, *, expected_revision, lifecycle, profile,
                     actor, reason, activate=False):
    await lock_control(db)
    series = await db.get(LeagueSeries, series_id)
    if not series or series.revision != expected_revision:
        from app.services.generation.store import Conflict
        raise Conflict("League configuration changed; reload before saving")
    if lifecycle not in ("active", "retired", "pending_verification"):
        raise ValueError("Invalid league lifecycle")
    if profile not in ("dynasty", "keeper", "redraft"):
        raise ValueError("Choose a supported league profile")
    before = {"lifecycle": series.lifecycle, "profile": series.profile, "hold": series.hold}
    if activate:
        from app.db.models import LeagueMembership
        seasons = list((await db.scalars(select(LeagueSeason).where(
            LeagueSeason.series_id == series_id))).all())
        current = max(seasons, key=lambda s: s.season, default=None)
        if not current or not current.verified_at or not paid_capabilities(json.loads(current.capabilities_json)):
            raise ValueError("Refresh the current league to verify its capabilities before activation")
        if not await db.scalar(select(LeagueMembership.id).where(
                LeagueMembership.league_id == current.league_id).limit(1)):
            raise ValueError("The current league needs a member before activation")
        series.activated_at = stamp()
        series.activation_week = current.latest_week
        series.hold = ""
        from app.services.generation.administration import hold_backlog
        await hold_backlog(db, [series.id])
    series.lifecycle = lifecycle
    series.profile = profile
    series.revision += 1
    audit(db, actor, "series_saved", series_id, reason, before,
          {"lifecycle": lifecycle, "profile": profile, "hold": series.hold})
    return series
