"""Free source collection outside transactions, then fenced immutable persistence."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.services.analyst_store import AnalystStore
from app.services.generation.models import LeagueSeason
from app.services.generation.recap_models import RecapEpisode, RecapObservation, RecapScheduleInventory
from app.services.generation.store import dump, lock_control
from app.services.name_override_store import NameOverrideStore
from app.services.recap_video.contracts import EpisodeKey
from app.services.recap_video.periods import build_participants, period_release, scoring_period
from app.services.recap_video import readiness
from sleeper_dynasty.api.nfl_inventory import fetch_inventory
from sleeper_dynasty.api.nfl_schedule import fetch_week_evidence

log = logging.getLogger(__name__)


def _scores(rows):
    for row in rows:
        for key in ("points", "custom_points"):
            if type(row.get(key)) is int:
                row[key] = str(row[key])
        for pid, value in (row.get("players_points") or {}).items():
            if type(value) is int:
                row["players_points"][pid] = str(value)
    return rows


def source_facts(snapshot):
    """Full competitive data for later claims, separate from any trimmed prose."""
    return {k: snapshot.get(k) for k in readiness.FACT_FIELDS}


def edition_from_snapshot(snapshot, *, generated_at):
    names = {p["roster_id"]: p.get("owner_name") or p["owner_id"] for p in snapshot["participants"]}
    matchups = []
    for pair in snapshot["pairings"]:
        ids, values = pair["rosters"], pair["scores"]
        winner = pair.get("winner")
        index = ids.index(winner) if winner in ids else 0
        other = 1 - index
        margin = abs(Decimal(values[0]) - Decimal(values[1]))
        matchups.append({"winner": names[ids[index]], "loser": names[ids[other]],
            "winner_points": values[index], "loser_points": values[other], "margin": str(margin),
            "tied": winner is None, "score_tied": margin == 0, "blowout": margin >= 30,
            "nailbiter": margin <= 5, "scope": pair["scope"], "status": pair["status"],
            "result_source": pair["source_id"], "result": pair["result"]})
    facts = {"week": snapshot["week"], "period_id": snapshot["period_id"],
        "league_name": snapshot.get("league_name", "League"), "matchups": matchups,
        "standings": [], "high_scorer": None, "low_scorer": None,
        "bench_regret": [], "lucky": [], "unlucky": [], "heroes": [], "goats": [], "busts": [],
        "lineups": [], "standings_race": {"available": False}, "bets": {"available": False},
        "player_context": {}, "participant_coverage": snapshot["participants"],
        "source_snapshot": source_facts(snapshot), "recap_facts_digest": readiness.competitive_digest(snapshot),
        "result_scope": "Complete scoring round" if snapshot["phase"] == "post" else "Completed week"}
    return {"season": snapshot["season"], "week": snapshot["week"], "league_name": facts["league_name"],
        "generated_at": datetime.fromtimestamp(generated_at, timezone.utc).isoformat(),
        "model": "verified-period-v1", "edition_type": "results",
        "markdown": "Private verified scoring-period evidence. Awaiting reviewed Analyst publication.",
        "facts": facts, "outlook": None, "lore": None}


async def _persist_inventory(db, inventory, now):
    await lock_control(db)
    previous = await db.scalar(select(RecapScheduleInventory).where(
        RecapScheduleInventory.season == inventory["season"]).order_by(RecapScheduleInventory.qualified_at).limit(1))
    if previous:
        old = json.loads(previous.inventory_json)
        if {g["event_id"] for g in old["games"]} != {g["event_id"] for g in inventory["games"]}:
            raise ValueError("schedule_inventory_unqualified: event identities changed; review crosswalk")
    same = await db.scalar(select(RecapScheduleInventory).where(
        RecapScheduleInventory.season == inventory["season"], RecapScheduleInventory.revision == inventory["revision"]))
    if same:
        return same.version
    db.add(RecapScheduleInventory(version=inventory["version"], season=inventory["season"],
        revision=inventory["revision"], qualified_at=now, inventory_json=dump(inventory)))
    await db.flush()
    return inventory["version"]


async def collect_recap(client, league_id, cache_dir, fence, now: int) -> bool:
    """Invalidation also covers malformed source shapes and unexpected errors."""
    try:
        return await _collect_recap(client, league_id, cache_dir, fence, now)
    except Exception as exc:
        if fence is not None:
            async with fence() as db:
                rows = list((await db.scalars(select(RecapEpisode).where(
                    RecapEpisode.league_id == league_id, RecapEpisode.observed_at < now,
                    RecapEpisode.lifecycle != "complete"))).all())
                for row in rows:
                    old = await db.get(RecapObservation, row.latest_observation_id)
                    if old:
                        failed = {**json.loads(old.snapshot_json), "source_errors": ["collector_exception:" + type(exc).__name__]}
                        await readiness.observe_period(db, EpisodeKey(row.series_id, row.season, row.period_id), failed, now)
        log.exception("Recap collection failed league=%s; review source error and retry", league_id)
        raise RuntimeError("recap_collection_failed: " + str(exc)) from exc


async def _collect_recap(client, league_id, cache_dir, fence, now: int) -> bool:
    """True means workflow handled this league, including held/no-due periods.

    Source failures commit an invalidating observation before raising to the
    owning free job. No transaction stays open across external HTTP calls.
    """
    if fence is None or ".l." in league_id:
        return False
    async with fence() as db:
        season = await db.get(LeagueSeason, league_id)
        if not season or not await readiness.workflow_enabled(db, season.series_id):
            return False
        series_id = season.series_id
        existing = list((await db.scalars(select(RecapEpisode).where(
            RecapEpisode.league_id == league_id, RecapEpisode.lifecycle != "complete"))).all())
        due = [r for r in existing if r.next_observation_at <= now]
        if existing and not due:
            return True
    sources = {}
    async def fetch(name, path):
        try:
            result = await client.get_recap_source(path)
        except Exception:
            log.exception("Recap source collection failed source=%s", path)
            result = {"ok": False, "source": path, "error": "source_exception"}
        expected_type = dict if name in ("state", "league") else list
        if result.get("ok") and not isinstance(result.get("data"), expected_type):
            result = {**result, "ok": False, "error": "invalid_shape"}
        sources[name] = result
        return result.get("data") if result.get("ok") else None
    state = await fetch("state", "/state/nfl")
    league = await fetch("league", f"/league/{league_id}")
    rosters = await fetch("rosters", f"/league/{league_id}/rosters")
    users = await fetch("users", f"/league/{league_id}/users")
    winners = await fetch("winners", f"/league/{league_id}/winners_bracket")
    losers = await fetch("losers", f"/league/{league_id}/losers_bracket")
    bracket = {"ok": isinstance(winners, list) and isinstance(losers, list),
               "winners": winners, "losers": losers}
    periods = {r.period_id: {"period_id": r.period_id, "week": r.week, "round": r.round,
        "nfl_weeks": json.loads(r.nfl_weeks_json), "phase": "post" if r.round else "regular"} for r in due}
    settings = (league or {}).get("settings") or {}
    errors = [f"{name}:{s.get('error', 'invalid_shape')}" for name, s in sources.items() if not s.get("ok")]
    if league and str(league.get("season")) != str(season.season):
        errors.append("league_season_identity_conflict")
    current_period_id = ""
    if state and league and int(state.get("season", 0)) == int(league.get("season", 0)):
        week = min(18, int(state.get("week", 0)) - 1)
        if week > 0:
            try:
                current = scoring_period(week, settings, bracket)
                current_period_id = current["period_id"]
                periods[current["period_id"]] = current
            except ValueError as exc:
                if str(exc) != "season_finished":
                    errors.append(str(exc))
    if not isinstance(rosters, list) or not isinstance(users, list):
        errors.append("participant_inventory_unavailable")
    inventory = None
    try:
        inventory = await fetch_inventory(season.season)
        async with fence() as db:
            inventory_version = await _persist_inventory(db, inventory, now)
    except Exception as exc:
        errors.append("schedule_inventory_unqualified:" + type(exc).__name__)
        log.exception("Recap schedule qualification failed league=%s; retry source collection", league_id)
        inventory = None
    if not periods:
        if errors:
            raise RuntimeError("recap_collection_failed: " + "; ".join(errors))
        return True
    aliases = NameOverrideStore(cache_dir=cache_dir).read(league_id)
    names = {u["user_id"]: (u.get("metadata") or {}).get("team_name") or u.get("display_name") or u["user_id"] for u in users or []}
    roster_data = [{**r, "owner_name": aliases.get(r.get("owner_id"), names.get(r.get("owner_id"), r.get("owner_id")))} for r in rosters or []]
    failure = list(errors)
    for period in periods.values():
        period.setdefault("round_type", settings.get("playoff_round_type"))
        period["roster_positions"] = (league or {}).get("roster_positions")
        scores, observed, period_errors = {}, [], list(errors)
        period_sources = dict(sources)
        expected = [g for g in (inventory or {}).get("games", []) if g["week"] in period["nfl_weeks"]]
        for week in period["nfl_weeks"]:
            raw = await fetch(f"matchups:{week}", f"/league/{league_id}/matchups/{week}")
            period_sources[f"matchups:{week}"] = sources[f"matchups:{week}"]
            if isinstance(raw, list):
                scores[str(week)] = _scores(raw)
            else:
                period_errors.append(f"matchups:{week}:unavailable")
            try:
                evidence = await fetch_week_evidence(season.season, week)
                period_sources[f"scoreboard:{week}"] = evidence
                by_id = {g["event_id"]: g for g in expected if g["week"] == week}
                for game in evidence["games"]:
                    original = by_id.get(game["event_id"])
                    if original and any(game.get(k) != original.get(k) for k in ("home", "away", "kickoff")):
                        period_errors.append("schedule_identity_conflict")
                    observed.append({k: game.get(k) for k in ("event_id", "home", "away", "kickoff", "status", "completed", "state")})
            except Exception:
                period_errors.append(f"scoreboard:{week}:unavailable")
                log.exception("Recap scoreboard failed league=%s week=%s", league_id, week)
        built = build_participants(roster_data, scores, bracket, period)
        snapshot = {**period, **built, "league_id": league_id, "league_name": (league or {}).get("name", "League"),
            "current_period_id": current_period_id,
            "scoring_settings": (league or {}).get("scoring_settings"),
            "player_metadata": {"available": False, "reason": "Player names and eligible positions require source enrichment before player/counterfactual claims."},
            "season": season.season, "rules": settings, "dispositions": {},
            "inventory_verified": inventory is not None, "expected_games": sorted(g["event_id"] for g in expected),
            "observed_games": sorted(observed, key=lambda g: g["event_id"]),
            "schedule_revision": (inventory or {}).get("revision", ""), "source_errors": period_errors,
            "eligible_at": period_release(expected, period["nfl_weeks"]) if expected and all(any(g["week"] == w for g in expected) for w in period["nfl_weeks"]) else 0,
            "sources": period_sources, "source_pointers": {"inventory_version": inventory_version if inventory else None},
            "provider_timestamps": {name: s.get("provider_timestamp", "") for name, s in period_sources.items()}}
        async with fence() as db:
            ident = await readiness.observe_period(db, EpisodeKey(series_id, season.season, period["period_id"]), snapshot, now)
            row = await db.get(RecapEpisode, ident)
            if row.lifecycle == "ready" or (row.hold == "manual_approval_required" and readiness.source_ready(row, snapshot)):
                store = AnalystStore(cache_dir)
                with store.claim(league_id) as claimed:
                    if not claimed:
                        raise RuntimeError("recap_collection_failed: archive busy; retry")
                    if not store.edition_path(league_id, row.season, row.week).exists():
                        store.save(league_id, edition_from_snapshot(snapshot, generated_at=row.admitted_at or row.observed_at))
        failure.extend(period_errors)
    if failure:
        raise RuntimeError("recap_collection_failed: " + "; ".join(dict.fromkeys(failure)))
    return True
