"""Pure fail-closed checks and immutable durable observations. No provider calls."""
from __future__ import annotations

import json
import logging

from sqlalchemy import func, select

from app.services.generation.models import LeagueSeason, LeagueSeries
from app.services.generation.recap_budget import episode_identity
from app.services.generation.recap_models import RecapEpisode, RecapObservation
from app.services.generation.store import Held, digest, dump, lock_control, resolve_policy
from app.services.recap_video.contracts import EpisodeKey, ReadinessDecision

log = logging.getLogger(__name__)
FACT_FIELDS = ("season", "week", "period_id", "nfl_weeks", "round", "phase", "round_type",
    "expected_games", "observed_games", "schedule_revision", "participants", "pairings", "scores",
    "starters", "bracket", "dispositions", "rules", "roster_positions", "scoring_settings", "player_metadata")


def competitive_digest(snapshot: dict) -> str:
    return digest({k: snapshot.get(k) for k in FACT_FIELDS})


def evaluate_readiness(snapshot: dict, previous: dict | None, now: int) -> ReadinessDecision:
    eligible = int(snapshot.get("eligible_at") or 0)
    fingerprint = competitive_digest(snapshot)
    def held(code):
        return ReadinessDecision(False, code, eligible, fingerprint)
    if snapshot.get("inventory_verified") is not True:
        return held("schedule_inventory_unqualified")
    expected, observed = snapshot.get("expected_games") or [], snapshot.get("observed_games") or []
    observed_ids = [g.get("event_id") for g in observed]
    if (not expected or len(expected) != len(set(expected)) or len(observed_ids) != len(set(observed_ids))
            or set(expected) != set(observed_ids)):
        return held("schedule_incomplete")
    if snapshot.get("source_errors"):
        return held("source_error")
    dispositions = snapshot.get("dispositions") or {}
    for game in observed:
        if game.get("completed") is True and game.get("status") in ("STATUS_FINAL", "STATUS_FINAL_OVERTIME"):
            continue
        decision = dispositions.get(game["event_id"], {})
        if (decision.get("authority") != "league" or not decision.get("source")
                or decision.get("decision") not in ("void", "counted")):
            return held("games_unresolved")
    if snapshot.get("bracket", {}).get("ok") is not True:
        return held("bracket_unavailable")
    if snapshot.get("participant_error"):
        return held(snapshot["participant_error"])
    participants, pairings = snapshot.get("participants") or [], snapshot.get("pairings") or []
    ids = [p.get("roster_id") for p in participants]
    covered = [rid for p in pairings for rid in p.get("rosters", [])]
    playing = {p.get("roster_id") for p in participants if p.get("status") in ("regular", "title", "placement", "consolation")}
    if (not ids or len(ids) != len(set(ids)) or any(not p.get("owner_id") for p in participants)
            or any(p.get("status") not in ("regular", "title", "placement", "consolation", "bye", "season_finished") for p in participants)
            or len(covered) != len(set(covered)) or set(covered) != playing
            or any(len(p.get("rosters", [])) != 2 for p in pairings)
            or not snapshot.get("scores") or not snapshot.get("starters")):
        return held("participant_incomplete")
    from app.services.recap_video.periods import build_participants
    verified = build_participants(participants, snapshot["scores"], snapshot["bracket"], snapshot)
    if verified["participant_error"]:
        return held(verified["participant_error"])
    if (verified["starters"] != snapshot["starters"]
            or {(p["roster_id"], p["status"]) for p in verified["participants"]}
            != {(p["roster_id"], p["status"]) for p in participants}
            or {tuple(sorted(p["rosters"])) for p in verified["pairings"]}
            != {tuple(sorted(p["rosters"])) for p in pairings}):
        return held("participant_evidence_conflict")
    if not eligible or not snapshot.get("schedule_revision"):
        return held("release_time_unknown")
    if (previous is None or competitive_digest(previous) != fingerprint
            or now - int(previous.get("observed_at", now)) < 3600):
        return held("facts_unstable")
    if now < eligible:
        return held("release_not_due")
    return ReadinessDecision(True, "ready", eligible, fingerprint)


async def workflow_enabled(db, series_id: str) -> bool:
    # Task 5 registers this policy feature. Absent is safely disabled.
    config = await resolve_policy(db, series_id)
    feature = config["policy"]["features"].get("recap_video", {})
    return bool(feature and feature.get("mode") != "disabled")


async def _authority_reason(db, key, league_id, *, automatic=False):
    """Admission never substitutes for current policy or membership authority."""
    from app.db.models import LeagueMembership
    policy = await resolve_policy(db, key.series_id)
    if policy["blocked_by"]:
        return policy["blocked_by"][0]
    features = policy["policy"]["features"]
    if not features.get("recap_video") or features["recap_video"].get("mode") == "disabled":
        return "recap_workflow_disabled"
    if any(not features.get(f) or features[f].get("paused") or features[f].get("mode") == "disabled"
           for f in ("analyst", "recap_video")):
        return "recap_feature_paused"
    season = await db.get(LeagueSeason, league_id)
    if (not season or not season.verified_at or season.series_id != key.series_id or season.season != key.season
            or not await db.scalar(select(LeagueMembership.id).where(LeagueMembership.league_id == league_id).limit(1))):
        return "recap_authority_missing"
    if automatic and any(features[f].get("mode") != "automatic" for f in ("analyst", "recap_video")):
        return "manual_approval_required"
    return ""


async def _admission_reason(db, key, snapshot, *, explicit_manual=False):
    if not await workflow_enabled(db, key.series_id):
        return "recap_workflow_disabled"
    reason = await _authority_reason(db, key, snapshot["league_id"], automatic=not explicit_manual)
    if reason:
        return reason
    series = await db.get(LeagueSeries, key.series_id)
    season = await db.get(LeagueSeason, snapshot["league_id"])
    latest_year = await db.scalar(select(func.max(LeagueSeason.season)).where(LeagueSeason.series_id == key.series_id))
    if (not series or not series.activated_at or not season or season.series_id != key.series_id
            or key.season != latest_year or season.season != key.season
            or snapshot.get("current_period_id", str(season.latest_week)) != key.period_id
            or snapshot["week"] < season.latest_week
            or snapshot["week"] <= series.activation_week
            or snapshot.get("eligible_at", 0) <= series.activated_at):
        return "historical_approval_required"
    return ""


async def observe_period(db, key: EpisodeKey, snapshot: dict, now: int) -> str:
    """Caller owns transaction. Every observation is append-only, even failures."""
    await lock_control(db)
    if snapshot.get("season") != key.season or snapshot.get("period_id") != key.period_id:
        raise ValueError("Episode snapshot identity mismatch")
    ident = episode_identity(key.series_id, key.season, key.period_id)
    row = await db.get(RecapEpisode, ident)
    if row is None:
        row = RecapEpisode(episode_id=ident, series_id=key.series_id, season=key.season,
            period_id=key.period_id, league_id=snapshot["league_id"], week=snapshot["week"],
            round=snapshot.get("round"), nfl_weeks_json=dump(snapshot.get("nfl_weeks", [])),
            admitted_at=0, stable_since=0, observed_at=0, latest_observation_id="")
        db.add(row)
    elif row.league_id != snapshot["league_id"] or row.week != snapshot["week"] or row.nfl_weeks_json != dump(snapshot.get("nfl_weeks", [])):
        raise ValueError("Episode period membership changed; review scoring rules")
    if now < row.observed_at:
        raise ValueError("Observation clock moved backwards")
    previous = None
    if row.latest_observation_id and row.stable_since:
        old = await db.get(RecapObservation, row.latest_observation_id)
        previous = {**json.loads(old.snapshot_json), "observed_at": row.stable_since}
    saved = {**snapshot, "observed_at": now}
    previous_lifecycle, previous_hold, previous_facts = row.lifecycle, row.hold, row.facts_digest
    decision = evaluate_readiness(saved, previous, now)
    admission = (await _authority_reason(db, key, snapshot["league_id"]) if row.admitted_at
                 else await _admission_reason(db, key, snapshot))
    if decision.ready and not admission and not row.admitted_at:
        row.admitted_at = now
    valid = decision.code in ("ready", "facts_unstable", "release_not_due")
    same = previous is not None and competitive_digest(previous) == decision.facts_digest
    row.stable_since = (row.stable_since if same else now) if valid else 0
    row.lifecycle = "ready" if decision.ready and not admission else "held"
    row.hold = (admission or ("" if decision.ready else decision.code)) if valid else decision.code
    progressed = {"waiting_for_article", "scripting", "narration", "speech_check", "rendering", "media_check", "review", "published", "withdrawn", "correction"}
    if previous_lifecycle in progressed and previous_facts == decision.facts_digest and decision.ready and not admission:
        row.lifecycle, row.hold = previous_lifecycle, previous_hold
    elif previous_facts and previous_facts != decision.facts_digest:
        # Invalidate selection immediately; retained receipts still settle money.
        from app.services.generation.recap_models import RecapStage, RecapProviderAttempt
        stages = (await db.scalars(select(RecapStage).where(RecapStage.episode_id == ident))).all()
        for stage in stages:
            stage.state, stage.reason, stage.lease_until = "held", "recap_facts_changed", 0
            stage.generation += 1
        if stages:
            row.lifecycle, row.hold = "held", "recap_facts_changed"
        for attempt in (await db.scalars(select(RecapProviderAttempt).where(
                RecapProviderAttempt.episode_id == ident, RecapProviderAttempt.state == "dispatching"))).all():
            attempt.state = "unknown"
    row.eligible_at, row.observed_at, row.facts_digest = decision.eligible_at, now, decision.facts_digest
    row.source_digest = digest(saved)
    row.next_observation_at = now + 900
    observation = RecapObservation(episode_id=ident, observed_at=now, snapshot_json=dump(saved),
        snapshot_digest=row.source_digest, facts_digest=decision.facts_digest,
        provider_timestamps_json=dump(saved.get("provider_timestamps", {})),
        source_pointers_json=dump(saved.get("source_pointers", {})), decision=row.hold or "ready")
    db.add(observation)
    await db.flush()
    row.latest_observation_id = observation.id
    log.info("Recap readiness episode=%s state=%s reason=%s due=%s", ident, row.lifecycle, row.hold, row.next_observation_at)
    return ident


def source_ready(row: RecapEpisode, snapshot: dict) -> bool:
    """Recheck two persisted observations; approval itself is not an observation."""
    return bool(row.stable_since and evaluate_readiness(snapshot,
        {**snapshot, "observed_at": row.stable_since}, row.observed_at).ready)


async def require_readiness(db, series_id: str, payload: dict, *, league_id=None,
                            allow_current_admission=False, automatic=False, media_checkpoint=False) -> RecapEpisode | None:
    """Current persisted evidence must match the immutable operation snapshot."""
    if not await workflow_enabled(db, series_id) and not payload.get("recap_facts_digest"):
        return None
    period = str(payload.get("period_id") or payload.get("week") or "")
    season = payload.get("season")
    ident = episode_identity(series_id, season, period) if type(season) is int and period else ""
    row = await db.get(RecapEpisode, ident) if ident else None
    if not row:
        raise Held("recap_readiness_missing")
    if ((league_id is not None and row.league_id != league_id) or row.week != payload.get("week")
            or payload.get("edition", {}).get("season", season) != season
            or payload.get("edition", {}).get("week", row.week) != row.week):
        raise Held("recap_episode_identity_conflict")
    key = EpisodeKey(series_id, row.season, row.period_id)
    authority = await _authority_reason(db, key, row.league_id, automatic=automatic)
    if authority:
        raise Held(authority)
    if allow_current_admission and not row.admitted_at:
        observation = await db.get(RecapObservation, row.latest_observation_id)
        snapshot = json.loads(observation.snapshot_json) if observation else {}
        if not source_ready(row, snapshot):
            raise Held(evaluate_readiness(snapshot, {**snapshot, "observed_at": row.stable_since}, row.observed_at).code)
        if payload.get("recap_facts_digest") != row.facts_digest:
            raise Held("recap_facts_changed")
        reason = await _admission_reason(db, key, snapshot, explicit_manual=True)
        if reason:
            raise Held(reason)
        # Read-only validation here. The command records admission only after
        # actor checks and all other authorization checks have succeeded.
        return row
    # Media progress does not revoke settled source facts for written recaps.
    # Media failures stay on RecapStage; row.hold is source/admission authority.
    allowed = {"ready", "waiting_for_article", "scripting", "narration", "speech_check", "rendering", "media_check", "review", "published"}
    if row.lifecycle not in allowed or row.hold:
        raise Held(row.hold or "recap_not_ready")
    if not row.admitted_at:
        raise Held("recap_readiness_missing")
    if payload.get("recap_facts_digest") != row.facts_digest:
        raise Held("recap_facts_changed")
    return row
