"""Shared episode identities and pure readiness decisions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EpisodeKey:
    series_id: str
    season: int
    period_id: str


@dataclass(frozen=True)
class ReadinessDecision:
    ready: bool
    code: str
    eligible_at: int
    facts_digest: str


def require_media_measurements(report, episode, assets):
    """API checks raw measured evidence against immutable selected objects.

    Decoder execution remains the restricted authenticated worker's responsibility;
    media QA alone never grants publication or human performance qualification.
    """
    import math
    from media.timeline import digest, validate_episode, FONTS
    from app.services.generation.store import Held
    try:
        m = report["measurements"]
        from media.geometry import geometry_issues
        from media.audio_seams import seam_issues, RULES
        if (geometry_issues(report['render'].get('geometry'),episode) or m['seam_rules']!=RULES
                or m['chunk_timing']!=episode['chunk_timing']
                or seam_issues(m['source_seams'],episode['chunk_timing']) or seam_issues(m['encoded_seams'],episode['chunk_timing'])):
            raise ValueError()
        if (report["version"] != "recap-media-qa-1" or report["issues"] or report["decoded"] is not True
                or report["episode_digest"] != digest(episode) or validate_episode(episode)
                or report["render"]["layout_issues"] or report["render"]["fonts"] != FONTS
                or report["hashes"] != {name: assets[name].digest for name in ("video.mp4", "audio.wav", "render.json")}):
            raise ValueError()
        expected_frames = [("decoded-"+f["file"],f["time"]) for f in report["render"]["representative_frames"]]
        if (not expected_frames or [(f["file"],f["time"]) for f in m["representative_frames"]] != expected_frames
                or any(type(v) not in (float,int) or not math.isfinite(v) for key in ("peak_db","rms_db") for v in m[key])):
            raise ValueError()
        numeric = ("audio_start_ms", "video_start_ms", "sync_error_ms", "audio_duration", "video_duration", "source_duration", "bytes", "frames")
        if any(type(m[k]) not in (float, int) or not math.isfinite(m[k]) for k in numeric):
            raise ValueError()
        if (abs(m["audio_start_ms"]-m["video_start_ms"]) > 100 or m["sync_error_ms"] != abs(m["audio_start_ms"]-m["video_start_ms"])
                or abs(m["audio_duration"]-m["source_duration"]) > .1
                or m["source_duration"] > episode["duration"]+.1 or episode["duration"]-m["source_duration"] > 2
                or abs(m["video_duration"]-episode["duration"]) > 1/30+.001
                or m["frames"] != math.ceil(episode["duration"]*30)
                or m["bytes"] != assets["video.mp4"].size or m["silence_seconds"]
                or not m["rms_db"] or max(m["rms_db"]) < -50 or not m["peak_db"] or max(m["peak_db"]) >= -.01):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise Held("media_measurements_invalid") from None


def player_evidence(snapshot, cache_dir):
    """Enrich only relevant names/eligibility from the trusted local Sleeper cache."""
    from sleeper_dynasty.cache import FileCache
    from app.services.generation.store import digest
    raw = FileCache(cache_dir).read("players.json")
    if not isinstance(raw, dict):
        return {"available": False}
    ids = {p for rows in snapshot.get("scores", {}).values() for row in rows for p in row.get("players", []) if p != "0"}
    players = {}
    for pid in sorted(ids):
        entry = raw.get(pid, {})
        if not isinstance(entry, dict):
            continue
        name = entry.get("full_name") or " ".join(p for p in (entry.get("first_name"), entry.get("last_name")) if isinstance(p, str) and p)
        positions = entry.get("fantasy_positions") or ([entry["position"]] if entry.get("position") else [])
        if name and isinstance(name, str) and isinstance(positions, list) and all(isinstance(p, str) for p in positions):
            players[pid] = {"name": name, "positions": sorted(set(positions))}
    return {"available": True, "source": "sleeper:players.json", "digest": digest(players), "players": players}


async def recent_premises(db, series_id, published_script_ids):
    """Server-owned selected artifact IDs, newest publication first; never client/provider input.

    Task 9 supplies actual publication selections, one current script per episode.
    No lifecycle/head inference: generated corrections are not published history.
    """
    import json
    from app.services.generation.models import ContentArtifact
    from app.services.generation.store import Held
    seen, result = set(), []
    for ident in published_script_ids:
        row = await db.get(ContentArtifact, ident)
        if row is None or row.series_id != series_id or row.feature != "recap_video":
            raise Held("recap_published_selection_invalid")
        data = json.loads(row.payload_json)
        episode = data.get("episode_id")
        if not episode:
            raise Held("recap_published_selection_invalid")
        if episode in seen:
            continue
        seen.add(episode)
        # Compact history only; durable artifact retains the entire script.
        values = [{"premise": p["premise"][:300], "punchline": p["punchline"][:300],
                   "owner_ids": p["owner_ids"]} for p in data["script"]["premises"][:24]]
        result.append({"episode_id": episode, "artifact_id": row.id, "premises": values})
        if len(result) == 6:
            break
    return result


async def _published_article(db, episode):
    import json
    from sqlalchemy import select
    from app.services.generation.models import ContentArtifact, ArtifactHead, GenerationOutbox
    from app.services.generation.store import Held, digest
    row = await db.scalar(select(ContentArtifact).where(ContentArtifact.series_id == episode.series_id,
        ContentArtifact.league_id == episode.league_id, ContentArtifact.feature == "analyst",
        ContentArtifact.digest == episode.article_digest))
    if not row:
        raise Held("recap_article_unpublished")
    data = json.loads(row.payload_json)
    head = await db.get(ArtifactHead, row.subject)
    if not head or head.hold or head.artifact_id != row.id or head.revision != row.revision:
        raise Held("recap_article_changed")
    projection = await db.scalar(select(GenerationOutbox).where(GenerationOutbox.key == "artifact:" + row.id))
    if (not projection or not projection.delivered or projection.error or projection.kind != "artifact"
            or json.loads(projection.payload_json).get("artifact_id") != row.id
            or data.get("edition_type") != "roast" or not data.get("markdown")
            or data.get("season") != episode.season or data.get("week") != episode.week
            or data.get("revision") != row.revision or digest(data) != row.digest):
        raise Held("recap_article_unpublished")
    if json.loads(row.facts_json).get("recap_facts_digest") != episode.facts_digest:
        raise Held("recap_article_facts_changed")
    return {"artifact_id": row.id, "digest": row.digest, "revision": row.revision,
            "markdown": data["markdown"], "correction_note": data.get("correction_note")}


async def prepare_script(db, episode_id, *, cache_dir, published_script_ids=()):
    """Build immutable candidate input from durable server evidence; no paid request."""
    import json
    from app.services.generation.recap_models import RecapEpisode, RecapObservation
    from app.services.generation.store import Held, lock_control
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    await lock_control(db)
    row = await db.get(RecapEpisode, episode_id)
    observation = await db.get(RecapObservation, row.latest_observation_id) if row else None
    if not row or not observation:
        raise Held("recap_readiness_missing")
    source = json.loads(observation.snapshot_json)
    metadata = player_evidence(source, cache_dir)
    claims = compile_claims({**source, "player_metadata": metadata})
    payload = {"episode_id": row.episode_id, "season": row.season, "week": row.week, "period_id": row.period_id,
        "edition": {"season": row.season, "week": row.week, "facts": {"period_id": row.period_id}},
        "recap_facts_digest": row.facts_digest, "source_digest": observation.snapshot_digest,
        "observation_id": observation.id, "source_snapshot": source, "player_evidence": metadata,
        "claims": claims, "published_article": await _published_article(db, row),
        "recent_premises": await recent_premises(db, row.series_id, published_script_ids), "event_at": row.admitted_at}
    await require_script_inputs(db, row.series_id, row.league_id, payload, cache_dir=cache_dir)
    return payload


async def require_script_inputs(db, series_id, league_id, payload, *, cache_dir=None, automatic=False, media_checkpoint=True):
    """Fence competitive changes, article corrections and relevant metadata changes.

    Observation timestamps may advance. Exact original snapshot remains bound for audit.
    """
    import json
    from app.config import get_settings
    from app.services.generation.recap_models import RecapObservation
    from app.services.generation.store import Held, digest
    from app.services.recap_video.readiness import require_readiness, competitive_digest
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    row = await require_readiness(db, series_id, payload, league_id=league_id, automatic=automatic, media_checkpoint=media_checkpoint)
    if not row or payload.get("episode_id") != row.episode_id:
        raise Held("recap_readiness_missing")
    original = await db.get(RecapObservation, payload.get("observation_id", ""))
    latest = await db.get(RecapObservation, row.latest_observation_id)
    if (not original or original.episode_id != row.episode_id or not latest
            or latest.episode_id != row.episode_id or original.snapshot_digest != payload.get("source_digest")
            or digest(payload.get("source_snapshot")) != original.snapshot_digest
            or digest(json.loads(original.snapshot_json)) != original.snapshot_digest
            or latest.snapshot_digest != row.source_digest
            or digest(json.loads(latest.snapshot_json)) != latest.snapshot_digest
            or competitive_digest(payload["source_snapshot"]) != row.facts_digest
            or competitive_digest(json.loads(latest.snapshot_json)) != row.facts_digest):
        raise Held("recap_source_changed")
    article = await _published_article(db, row)
    if article != payload.get("published_article"):
        raise Held("recap_article_changed")
    metadata = payload.get("player_evidence", {"available": False})
    if metadata.get("available") and metadata != player_evidence(payload["source_snapshot"], cache_dir or get_settings().cache_dir):
        raise Held("recap_player_evidence_changed")
    expected = compile_claims({**payload["source_snapshot"], "player_metadata": metadata})
    if (any(c["kind"] in ("substitution", "optimal") for c in expected["claims"])
            and payload["source_snapshot"].get("lineup_eligibility") != json.loads(latest.snapshot_json).get("lineup_eligibility")):
        raise Held("recap_lineup_eligibility_changed")
    if expected != payload.get("claims"):
        raise Held("recap_claims_changed")
    return row


def require_approved_script(payload, saved, attempts):
    """Tie approved structured output to the actual immutable receipt checkpoints."""
    import json
    from app.services.generation.store import Held
    from sleeper_dynasty.engine.recap_video_claims import validate_script
    from sleeper_dynasty.llm.recap_video_writer import Script, Review
    try:
        script = payload["script"]
        reviews = script["reviews"]
        normalized = Script.model_validate({k: v for k, v in script.items() if k != "reviews"}).model_dump()
        final = Review.model_validate(reviews[-1]).model_dump()
        if (len(attempts) not in (2, 4) or len(reviews) != len(attempts) // 2
                or not final["approved"] or final["issues"] or not all(final["checks"].values())
                or set(final["checked_segment_ids"]) != {"opening", "closing", *[s["id"] for s in normalized["segments"]]}
                or validate_script(normalized, saved["claims"], saved["published_article"])
                or any(payload.get(k) != saved[k] for k in ("claims", "episode_id", "source_digest", "recap_facts_digest"))
                or payload.get("article_digest") != saved["published_article"]["digest"]):
            raise ValueError()
        for attempt, name, expected, schema in ((attempts[-2], "submit_script", normalized, Script),
                                                (attempts[-1], "review_script", final, Review)):
            receipt = json.loads(json.loads(attempt.receipt_json)["body"])
            blocks = [b for b in receipt["content"] if b.get("type") == "tool_use"]
            if (receipt.get("stop_reason") != "tool_use" or len(blocks) != 1 or blocks[0]["name"] != name
                    or schema.model_validate(blocks[0]["input"]).model_dump() != expected):
                raise ValueError()
    except (ValueError, TypeError, KeyError, IndexError):
        raise Held("recap_script_unapproved") from None
