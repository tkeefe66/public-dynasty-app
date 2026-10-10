"""Prepare durable weekly facts; only reviewed AI roasts reach readers."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.services.analyst_store import AnalystStore
from app.services.name_override_store import NameOverrideStore
from app.services.profile_store import ProfileStore
from app.services.analyst_outlook import upcoming_outlook
from app.services.analyst_bets import load_bets_snapshot
from app.services.player_context import load_player_context
from sleeper_dynasty.engine.recap_race import build_race_context
from sleeper_dynasty.engine.recap import build_recap_facts
from sleeper_dynasty.engine.recap_results import render_results_recap
from sleeper_dynasty.api.projections import normalize_projection
from sleeper_dynasty.models.scoring import has_threshold_bonuses
from sleeper_dynasty.llm.cost_store import LlmCostStore
from sleeper_dynasty.llm.recap_packet import ArchivedPacket
from sleeper_dynasty.llm.recap_writer import RecapWriter
from sleeper_dynasty.models.player import build_players

log = logging.getLogger(__name__)


@asynccontextmanager
async def _no_fence():
    yield None


def complete_results(results, rosters, week: int) -> bool:
    """Fail closed on partial upstream data before permanently publishing."""
    if len(results) != len(rosters) or {r.roster_id for r in results} != {r.roster_id for r in rosters}:
        return False
    groups = Counter(r.matchup_id for r in results)
    if None in groups or any(n != 2 for n in groups.values()):
        return False
    return all(
        r.week == week and r.points is not None and math.isfinite(r.points)
        and r.players_points and any(p != "0" for p in r.starters)
        and all(p in r.players_points for p in r.starters if p != "0")
        for r in results
    ) and any(r.points != 0 for r in results)


def advance_standings(rosters, results):
    """Use historical weekly scores, never today's cumulative Sleeper record."""
    by_id = {r.roster_id: r for r in rosters}
    for result in results:
        opponent = next(r for r in results if r.matchup_id == result.matchup_id and r.roster_id != result.roster_id)
        roster = by_id[result.roster_id]
        a, b = result.points, opponent.points
        by_id[result.roster_id] = replace(
            roster, players=result.players, wins=roster.wins + (a > b),
            losses=roster.losses + (a < b), ties=roster.ties + (a == b),
            points_for=roster.points_for + a, points_against=roster.points_against + b,
        )
    return list(by_id.values())


async def generate_analyst(client, entry, cache_dir: Path, *, skip_llm=False, writer=None,
                           correction_week: int | None = None, correction_reason: str | None = None,
                           now: datetime | None = None, publication_fence=None):
    """Catch up missing regular-season editions in order; retry on next refresh.

No historic-season bulk generation. The first current-season refresh catches up
completed weeks. Budget checks run per edition; page reads never invoke an LLM.
"""
    league_id = entry.league_id
    # Production refreshes prepare private facts for managed AI generation.
    # Explicitly injected writers remain usable for pure tests.
    skip_llm = skip_llm or writer is None
    # Analyst archives currently support Sleeper leagues only.
    if ".l." in league_id:
        return
    from app.services.recap_video.collector import collect_recap
    # Enabled workflow has its own complete scoring-period collector. Its
    # failures must reach the free job, not the legacy best-effort logger.
    if await collect_recap(client, league_id, cache_dir, publication_fence,
            int((now or datetime.now(timezone.utc)).timestamp())):
        return
    try:
        store = AnalystStore(cache_dir)
        with store.claim(league_id) as claimed:
            if not claimed:
                return
            state = await client.get_nfl_state()
            league, _ = await client.get_league(league_id)
            if (state.get("season_type") != "regular"
                    or int(state.get("season", 0)) != league.season):
                return
            last_week = min(int(state.get("week", 0)) - 1, (league.playoff_week_start or 15) - 1, 18)
            saved_editions = store.editions(league_id)
            existing = {(d["season"], d["week"]): d for d in saved_editions}
            if correction_week is not None:
                if not correction_reason or not correction_reason.strip():
                    raise ValueError("Explicit correction requires a reader-visible reason")
                if not 1 <= correction_week <= last_week or (league.season, correction_week) not in existing:
                    raise ValueError("Only an already published completed week can be corrected")
            elif not any((league.season, w) not in existing
                         or existing[(league.season, w)]["edition_type"] == "results"
                         for w in range(1, last_week + 1)):
                return
            active_writer = writer
            if correction_week is None and not skip_llm:
                for week in range(1, last_week + 1):
                    previous = existing.get((league.season, week))
                    if previous is None or previous["edition_type"] != "results":
                        continue
                    if writer is None:
                        from app.services.refresh_service import _llm_over_budget
                        if not os.environ.get("ANTHROPIC_API_KEY") or await _llm_over_budget(cache_dir):
                            break
                    if not store.start_attempt(league_id, league.season, week,
                            (now or datetime.now(timezone.utc)).timestamp()):
                        continue
                    try:
                        # A later retry must preserve the original scores, bets,
                        # profiles, news chronology and next-week forecast.
                        facts = ArchivedPacket(previous["facts"])
                        outlook = ArchivedPacket(previous["outlook"]) if previous.get("outlook") else None
                        markdown = await asyncio.to_thread(active_writer.write, facts,
                            lore=previous.get("lore"), outlook=outlook)
                        if not isinstance(markdown, str) or not markdown.strip():
                            raise ValueError("Analyst returned empty text")
                        context = previous["facts"].get("player_context", {})
                        edition = {**previous, "markdown": markdown.strip(), "edition_type": "roast",
                            "model": active_writer.model, "generated_at": datetime.now(timezone.utc).isoformat(),
                            "sources": context.get("sources", []), "context_note": context.get("note")}
                        store.save_correction(league_id, edition,
                            "Full Analyst roast added after the results edition; original results preserved.", claimed=True)
                        log.info("Saved Analyst roast revision league=%s season=%s week=%s", league_id, league.season, week)
                    except Exception:
                        log.warning("Analyst roast upgrade failed league=%s season=%s week=%s; results retained for retry",
                                    league_id, league.season, week, exc_info=True)
            if correction_week is None and all((league.season, w) in existing for w in range(1, last_week + 1)):
                return
            rosters = await client.get_rosters(league_id)
            overrides = NameOverrideStore(cache_dir=cache_dir).read(league_id)
            current_rosters = [replace(r, owner_name=overrides.get(r.owner_id, r.owner_name)) for r in rosters]
            rosters = [replace(r, owner_name=overrides.get(r.owner_id, r.owner_name),
                               wins=0, losses=0, ties=0, points_for=0, points_against=0) for r in rosters]
            players = build_players(await client.get_players())
            profiles = ProfileStore(cache_dir).read(league_id)
            lore = json.dumps({r.owner_name: profiles[r.owner_id] for r in rosters if r.owner_id in profiles}) if profiles else None
            for week in range(1, last_week + 1):
                results = await client.get_matchup_results(league_id, week)
                if not complete_results(results, rosters, week):
                    raise ValueError(f"Week {week} results are incomplete; retry after Sleeper scores every matchup")
                before = rosters
                rosters = advance_standings(rosters, results)
                if correction_week is not None and week != correction_week:
                    continue
                previous = existing.get((league.season, week))
                if correction_week is None and previous is not None:
                    continue
                use_ai = not skip_llm and (writer is not None or bool(os.environ.get("ANTHROPIC_API_KEY")))
                if use_ai and writer is None:
                    from app.services.refresh_service import _llm_over_budget
                    if await _llm_over_budget(cache_dir):
                        use_ai = False
                if use_ai and correction_week is None and not store.start_attempt(
                    league_id, league.season, week,
                    (now or datetime.now(timezone.utc)).timestamp(),
                ):
                    log.info("Analyst AI retry cooling down; using results edition league=%s season=%s week=%s",
                             league_id, league.season, week)
                    use_ai = False
                if correction_week is not None and not use_ai:
                    raise ValueError("AI unavailable for requested correction; preserving published edition")
                projections = {}
                try:
                    # Weekly projected averages do not give the probability
                    # of crossing a bonus threshold. Base-only expectations
                    # cannot fairly label bonus-inclusive actuals as busts.
                    if not has_threshold_bonuses(league.scoring_settings, getattr(league, "scoring_bonuses", ())):
                        raw = await client.get_projections(league.season, week)
                        projections = {pid: normalize_projection(stats, league.scoring_settings)
                                       for pid, stats in raw.items() if isinstance(stats, dict)}
                    else:
                        log.info("Analyst week %s: threshold bonus projections unavailable; omitting busts", week)
                except Exception:
                    log.warning("Analyst week %s: projections unavailable; omitting busts", week, exc_info=True)
                facts = build_recap_facts(
                    week, league.name, results, rosters,
                    {r.roster_id: r.owner_name for r in rosters}, players,
                    league.roster_positions, projections,
                )
                if len(facts.matchups) * 2 != len(results):
                    raise ValueError(f"Week {week} recap is missing matchup scores; retry after complete results")
                if use_ai or week == last_week:
                    try:
                        facts.player_context = await load_player_context(
                            cache_dir, league.season, week, results, players)
                    except Exception:
                        log.warning("Analyst player context unavailable; using verified scores only", exc_info=True)
                        facts.player_context = {"players": [], "sources": [],
                            "note": "Player news and snap context were unavailable for this edition. No explanation for low scores is assumed."}
                log.info("Generating Analyst league=%s season=%s week=%s", league_id, league.season, week)
                # Missed weeks get a retrospective only. A current forecast
                # cannot be presented as what we knew several weeks ago.
                outlook = None
                if week + 1 == int(state.get("week", 0)):
                    outlook = await upcoming_outlook(client, league, week + 1, current_rosters, players)
                upcoming = []
                try:
                    if week < league.playoff_week_start - 1:
                        upcoming = await client.get_matchup_results(league_id, week + 1)
                        upcoming = [r for r in upcoming if r.week == week + 1]
                except Exception:
                    log.warning("Analyst next-week pairings unavailable; omitting matchup stakes", exc_info=True)
                # Compare the latest complete reconstruction with Sleeper's
                # authoritative record; do not present unsupported league rules
                # as an official playoff race.
                current_by_id = {r.roster_id: r for r in current_rosters}
                verified = week != last_week or all(
                    (r.wins, r.losses, r.ties) == (current_by_id[r.roster_id].wins,
                        current_by_id[r.roster_id].losses, current_by_id[r.roster_id].ties)
                    and math.isclose(r.points_for, current_by_id[r.roster_id].points_for, abs_tol=0.011)
                    for r in rosters
                )
                facts.standings_race = build_race_context(before, rosters, league, week,
                                                         verified=verified, upcoming=upcoming)
                if not facts.standings_race["available"]:
                    log.warning("Analyst standings claims omitted for league=%s week=%s: %s",
                                league_id, week, facts.standings_race["reason"])
                prior = next((e for e in saved_editions if e["season"] == league.season and e["week"] < week
                              and e["facts"].get("bets", {}).get("available")), None)
                if week == last_week:
                    facts.bets = await load_bets_snapshot(league_id, league.season, current_rosters,
                        datetime.now(timezone.utc), prior["facts"]["bets"] if prior else None)
                else:
                    facts.bets = {"available": False, "reason": "Historical bet states are unavailable; do not backdate today's ledger."}
                edition_type = "results"
                model = "verified-results-v1"
                if use_ai:
                    try:
                        markdown = await asyncio.to_thread(active_writer.write, facts, lore=lore, outlook=outlook)
                        if not isinstance(markdown, str) or not markdown.strip():
                            raise ValueError("Analyst returned empty text")
                        edition_type = "roast"
                        model = active_writer.model
                    except Exception:
                        if correction_week is not None:
                            raise
                        log.warning("Analyst roast failed league=%s season=%s week=%s; staging private facts for retry",
                                    league_id, league.season, week, exc_info=True)
                if edition_type == "results":
                    markdown = render_results_recap(facts.to_dict(), outlook.to_dict() if outlook else None)
                edition = {
                    "season": league.season, "week": week, "league_name": league.name,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "model": model, "edition_type": edition_type, "markdown": markdown.strip(),
                    "facts": facts.to_dict(),
                    "outlook": outlook.to_dict() if outlook else None,
                    "lore": lore,
                    "sources": facts.player_context.get("sources", []) if edition_type == "roast" else [],
                    "context_note": facts.player_context.get("note") if edition_type == "roast" else None,
                }
                async with (publication_fence or _no_fence)():
                    if correction_week is not None:
                        store.save_correction(league_id, edition, correction_reason, claimed=True)
                    else:
                        store.save(league_id, edition)
                log.info("%s Analyst league=%s season=%s week=%s type=%s",
                         "Published" if edition_type == "roast" else "Staged private facts for",
                         league_id, league.season, week, edition_type)
    except Exception:
        log.exception("Analyst generation failed for %s; saved editions preserved; retry on next refresh", league_id)
