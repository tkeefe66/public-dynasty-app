"""Select current missing writing across leagues without provider calls."""
import json
from collections import Counter

from sqlalchemy import select

from app.config import get_settings
from app.db.models import LeagueMembership
from app.services.generation.administration import preview
from app.services.generation.commands import require_actor
from app.services.generation.models import (
    ArtifactHead,
    ContentArtifact,
    GenerationCandidate,
    GenerationOperation,
    LeagueSeason,
    LeagueSeries,
    stamp,
)
from app.services.generation.policy import paid_capabilities, supports_feature
from app.services.generation.store import Held, lock_control, resolve_policy


async def preview_catchup(db, actor, reason, series_id=""):
    control = await lock_control(db)
    if series_id and not await db.get(LeagueSeries, series_id):
        raise ValueError("League selection no longer exists; reload the league list")
    if control.hold or control.provider_hold or get_settings().generation_emergency_pause:
        raise ValueError("AI writing is paused; resolve the pause before previewing catch-up")
    seasons = (await db.scalars(select(LeagueSeason))).all()
    newest = {}
    for season in seasons:
        newest[season.series_id] = max(newest.get(season.series_id, 0), season.season)
    season_map = {s.league_id: s for s in seasons}
    series_map = {s.id: s for s in (await db.scalars(select(LeagueSeries))).all()}
    members = set((await db.scalars(select(LeagueMembership.league_id))).all())
    heads = {h.subject: h for h in (await db.scalars(select(ArtifactHead))).all()}
    artifacts = {a.id: a for a in (await db.scalars(select(ContentArtifact))).all()}
    operations = (await db.scalars(select(GenerationOperation).where(
        GenerationOperation.kind == "generation"))).all()
    occupied = {o.subject for o in operations if o.state in ("queued", "running", "held", "needs_attention")}
    finished = {(o.subject, o.request_digest) for o in operations if o.state == "succeeded"}
    query = select(GenerationCandidate).order_by(GenerationCandidate.key)
    if series_id:
        query = query.where(GenerationCandidate.series_id == series_id)
    keys, skipped, policies, actor_permissions = [], Counter(), {}, {}
    for row in (await db.scalars(query)).all():
        payload = json.loads(row.payload_json)
        season = season_map.get(row.league_id)
        series = series_map.get(row.series_id)
        why = ""
        if (not season or not series or series.lifecycle != "active" or series.hold
                or row.league_id not in members or not season.verified_at
                or season.season != newest[row.series_id]
                or payload.get("season") != season.season
                or not supports_feature(paid_capabilities(json.loads(season.capabilities_json)), season.provider, row.feature)):
            why = "league_unavailable"
        elif row.hold not in ("", "historical_approval_required", "missed_event_approval_required") or row.subject in occupied:
            why = "work_in_progress_or_needs_review"
        elif payload.get("correction_base"):
            why = "correction_requires_separate_review"
        elif not payload.get("facts"):
            why = "facts_unavailable"
        elif row.feature == "trade_story" and int(payload.get("event_at") or 0) < stamp() - 7 * 86400:
            why = "older_trade"
        elif row.feature == "analyst" and not 1 <= int(payload.get("week") or 0) <= season.latest_week:
            why = "week_not_completed"
        elif ((row.feature.endswith("blurb") and payload.get("week") != season.latest_week)
                or payload.get("target", {}).get("scope") not in (None, "all", str(season.season))):
            why = "older_summary"
        elif payload.get("phase") not in (None, "regular"):
            why = "outside_regular_season"
        head = heads.get(row.subject)
        artifact = artifacts.get(head.artifact_id) if head else None
        if not why and head and head.hold:
            why = "saved_content_needs_review"
        if not why and ((row.subject, row.digest) in finished or (artifact and (
                row.feature == "trade_story" or (row.feature == "analyst"
                and json.loads(artifact.payload_json).get("edition_type", "roast") == "roast")))):
            why = "already_completed"
        if not why and artifact and row.feature.endswith("blurb"):
            period = json.loads(artifact.payload_json).get("generation_period", {})
            if period == {"season": season.season, "week": season.latest_week}:
                why = "already_completed"
        if not why:
            if row.series_id not in policies:
                policies[row.series_id] = await resolve_policy(db, row.series_id)
            policy = policies[row.series_id]
            feature = policy["policy"]["features"][row.feature]
            if policy["blocked_by"] or feature["paused"] or feature["mode"] == "disabled":
                why = "writing_disabled_or_paused"
            elif json.loads(control.breakers_json).get(row.feature, {}).get("open"):
                why = "feature_safety_stop"
        if not why:
            if row.league_id not in actor_permissions:
                from app.db.models import YahooConnection
                connection = await db.get(YahooConnection, actor) if season.provider == "yahoo" else None
                try:
                    await require_actor(db, GenerationOperation(kind="generation", actor_id=actor,
                        league_id=row.league_id, connection_generation=connection.generation if connection else ""))
                    actor_permissions[row.league_id] = ""
                except Held as exc:
                    actor_permissions[row.league_id] = exc.code
            why = actor_permissions[row.league_id]
        if why:
            skipped[why] += 1
        else:
            keys.append(row.key)
    if len(keys) > 1000:
        raise ValueError("Catch-up exceeds 1,000 items; select one league and preview again")
    if not keys:
        raise ValueError("No current missing content is eligible for catch-up; refresh league data or review skipped work")
    result = await preview(db, keys, actor, reason)
    return {**result, "skipped": dict(skipped)}
