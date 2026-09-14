"""Automatic weekly Analyst generation. Saved editions are never regenerated."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.services.analyst_store import AnalystStore
from app.services.name_override_store import NameOverrideStore
from app.services.profile_store import ProfileStore
from app.services.analyst_outlook import upcoming_outlook
from sleeper_dynasty.engine.recap import build_recap_facts
from sleeper_dynasty.api.projections import normalize_projection
from sleeper_dynasty.llm.cost_store import LlmCostStore
from sleeper_dynasty.llm.recap_writer import RecapWriter
from sleeper_dynasty.models.player import build_players

log = logging.getLogger(__name__)


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


async def generate_analyst(client, entry, cache_dir: Path, *, skip_llm=False, writer=None):
    """Catch up missing regular-season editions in order; retry on next refresh.

No historic-season bulk generation. The first current-season refresh catches up
completed weeks. Budget checks run per edition; page reads never invoke an LLM.
"""
    league_id = entry.league_id
    if skip_llm or (writer is None and not os.environ.get("ANTHROPIC_API_KEY")):
        log.warning("Analyst deferred for %s: LLM budget reached or API key absent; retry on refresh", league_id)
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
            existing = {(d["season"], d["week"]) for d in store.editions(league_id)}
            if not any((league.season, w) not in existing for w in range(1, last_week + 1)):
                return
            rosters = await client.get_rosters(league_id)
            overrides = NameOverrideStore(cache_dir=cache_dir).read(league_id)
            current_rosters = [replace(r, owner_name=overrides.get(r.owner_id, r.owner_name)) for r in rosters]
            rosters = [replace(r, owner_name=overrides.get(r.owner_id, r.owner_name),
                               wins=0, losses=0, ties=0, points_for=0, points_against=0) for r in rosters]
            players = build_players(await client.get_players())
            profiles = ProfileStore(cache_dir).read(league_id)
            lore = json.dumps({r.owner_name: profiles[r.owner_id] for r in rosters if r.owner_id in profiles}) if profiles else None
            active_writer = writer or RecapWriter(cost_store=LlmCostStore(cache_dir), league_id=league_id)
            for week in range(1, last_week + 1):
                results = await client.get_matchup_results(league_id, week)
                if not complete_results(results, rosters, week):
                    raise ValueError(f"Week {week} results are incomplete; retry after Sleeper scores every matchup")
                rosters = advance_standings(rosters, results)
                if (league.season, week) in existing:
                    continue
                if writer is None:
                    from app.services.refresh_service import _llm_over_budget
                    if await _llm_over_budget(cache_dir):
                        return
                projections = {}
                try:
                    raw = await client.get_projections(league.season, week)
                    projections = {pid: normalize_projection(stats, league.scoring_settings)
                                   for pid, stats in raw.items() if isinstance(stats, dict)}
                except Exception:
                    log.warning("Analyst week %s: projections unavailable; omitting busts", week, exc_info=True)
                facts = build_recap_facts(
                    week, league.name, results, rosters,
                    {r.roster_id: r.owner_name for r in rosters}, players,
                    league.roster_positions, projections,
                )
                log.info("Generating Analyst league=%s season=%s week=%s", league_id, league.season, week)
                # Missed weeks get a retrospective only. A current forecast
                # cannot be presented as what we knew several weeks ago.
                outlook = None
                if week + 1 == int(state.get("week", 0)):
                    outlook = await upcoming_outlook(client, league, week + 1, current_rosters, players)
                markdown = await asyncio.to_thread(active_writer.write, facts, lore=lore, outlook=outlook)
                if not isinstance(markdown, str) or not markdown.strip():
                    raise ValueError("Analyst returned empty text; retry on next refresh")
                store.save(league_id, {
                    "season": league.season, "week": week, "league_name": league.name,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "model": active_writer.model, "markdown": markdown.strip(),
                    "facts": facts.to_dict(),
                    "outlook": outlook.to_dict() if outlook else None,
                    "lore": lore,
                })
                log.info("Saved Analyst league=%s season=%s week=%s", league_id, league.season, week)
    except Exception:
        log.exception("Analyst generation failed for %s; saved editions preserved; retry on next refresh", league_id)
