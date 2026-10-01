"""Observe free snapshots. Only semantic events can authorize managed work."""
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.services.generation.artifacts import import_artifact, overlay, subject_key
from app.services.generation.models import (
    ArtifactHead,
    GenerationCandidate,
    GenerationOperation,
    LeagueSeries,
    stamp,
)
from app.services.generation.policy import supports_feature
from app.services.generation.registry import register_entry
from app.services.generation.store import digest, dump, lock_control


async def observe(db, *, series_id, league_id, feature, subject, event, payload):
    await lock_control(db)
    series = await db.get(LeagueSeries, series_id)
    # Summaries keep the newest desired snapshot. Started jobs retain their own immutable copy.
    key = subject_key("candidate", subject, "latest" if feature.endswith("blurb") else event)
    row = await db.get(GenerationCandidate, key)
    if row and row.event > event:
        return row
    if row and row.event == event:
        payload = {**payload, "event_at": json.loads(row.payload_json).get("event_at", 0)}
    if row is None:
        row = GenerationCandidate(key=key, series_id=series_id, league_id=league_id,
            feature=feature, subject=subject, event=event)
        db.add(row)
    snapshot_digest = digest(payload)
    if row.digest and row.digest != snapshot_digest:
        row.revision += 1
    row.event, row.payload_json, row.digest = event, dump(payload), snapshot_digest
    row.hold = ""
    event_at = int(payload.get("event_at") or 0)
    week = int(payload.get("week") or 0)
    if (not series.activated_at or event_at <= series.activated_at
            or (feature != "trade_story" and week <= series.activation_week)):
        row.hold = "historical_approval_required"
    head = await db.get(ArtifactHead, subject)
    if head and head.hold:
        row.hold = head.hold
    pending = await db.scalar(select(GenerationOperation).where(
        GenerationOperation.subject == subject,
        GenerationOperation.state.in_(("needs_attention", "held"))).limit(1))
    if pending:
        row.hold = "subject_needs_attention"
    if not row.hold:
        row.eligible_at = stamp()
    await db.flush()
    return row


def automatic_reason(season, feature, payload, now):
    if feature == "trade_story":
        if int(payload.get("event_at") or 0) < now - 7 * 86400:
            return "historical_approval_required"
    elif not season.latest_week or payload.get("week") != season.latest_week:
        return "missed_event_approval_required"
    return ""


def _origin(raw, tx, fallback):
    for resolved in raw.get("resolved_trades", []):
        trade = resolved.get("trade", {})
        if str(trade.get("transaction_id")) == str(tx):
            return str(trade.get("league_id") or fallback)
    return fallback


async def import_chain(db, raw, series_id):
    lid = raw["league_id"]
    provider = "yahoo" if ".l." in lid else "sleeper"
    season = (raw.get("league_season_by_id") or {}).get(lid, 0)
    for tx, content in (raw.get("trade_stories") or {}).items():
        await import_artifact(db, series_id=series_id, league_id=lid, feature="trade_story",
            subject=subject_key("trade_story", provider, _origin(raw, tx, lid), tx),
            payload=content, target={"slot": "trade_stories", "key": tx})
    for scope, owners in (raw.get("owner_rating_blurbs") or {}).items():
        for uid, content in owners.items():
            await import_artifact(db, series_id=series_id, league_id=lid, feature="gm_rating_blurb",
                subject=subject_key("gm_rating_blurb", series_id, season, scope, uid),
                payload=content, target={"slot": "owner_rating_blurbs", "scope": scope, "key": uid})
    for uid, content in (raw.get("franchise_blurbs") or {}).items():
        await import_artifact(db, series_id=series_id, league_id=lid, feature="franchise_blurb",
            subject=subject_key("franchise_blurb", series_id, season, uid),
            payload=content, target={"slot": "franchise_blurbs", "key": uid})


async def collect(db, entry, cache_dir):
    season = await register_entry(db, entry, verified=True)
    sid = season.series_id
    # Read prose even when the disposable chain schema is obsolete.
    path = Path(cache_dir) / f"chain_{entry.league_id}.json"
    if path.exists():
        raw = json.loads(path.read_text())
        if raw.get("league_id") != entry.league_id:
            raise ValueError("Legacy chain identity mismatch; refusing prose import")
        await import_chain(db, raw, sid)
    for candidate in entry.generation_inputs:
        feature, payload = candidate["feature"], candidate["payload"]
        subject = subject_key(feature, *(
            candidate["identity"] if feature == "trade_story" else [sid, *candidate["identity"]]))
        row = await observe(db, series_id=sid, league_id=entry.league_id, feature=feature,
            subject=subject, event=candidate["event"], payload=payload)
        if not supports_feature(entry.capabilities, season.provider, feature):
            row.hold = "feature_unsupported"
    await collect_analyst(db, entry.league_id, sid, cache_dir)
    await overlay(db, entry, sid)
    return sid


async def collect_analyst(db, league_id, series_id, cache_dir):
    from app.services.analyst_store import AnalystEdition, AnalystStore
    store = AnalystStore(cache_dir)
    root = store.league_dir(league_id)
    if not root.exists():
        return
    # Originals and every revision remain separately addressable.
    paths = [*root.glob("*.json"), *root.glob("revisions/*/*.json")]
    editions = []
    for path in sorted(paths):
        raw = json.loads(path.read_text())
        if not {"season", "week", "markdown"}.issubset(raw):
            continue
        edition = AnalystEdition.model_validate(raw).model_dump()
        editions.append(edition)
        subject = subject_key("analyst", series_id, edition["season"], edition["week"])
        await import_artifact(db, series_id=series_id, league_id=league_id, feature="analyst",
            subject=subject, payload=edition, target={}, revision=edition["revision"], facts=edition["facts"])
    latest = {}
    for edition in editions:
        key = (edition["season"], edition["week"])
        if key not in latest or edition["revision"] > latest[key]["revision"]:
            latest[key] = edition
    for edition in latest.values():
        if edition["edition_type"] != "results":
            continue
        await observe(db, series_id=series_id, league_id=league_id, feature="analyst",
            subject=subject_key("analyst", series_id, edition["season"], edition["week"]),
            event=f'{edition["season"]}:week:{edition["week"]:02d}',
            payload={"facts": edition["facts"], "edition": edition, "week": edition["week"],
                "season": edition["season"], "event_at": int(datetime.fromisoformat(
                    edition["generated_at"]).timestamp())})
