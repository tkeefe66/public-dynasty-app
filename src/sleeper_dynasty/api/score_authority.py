"""Separate Sleeper's settled results from its recalculated player statistics.

REST matchup totals can change before (or without) the stored matchup result
used by Sleeper's UI and roster standings. Never invent a weekly score from a
season-total residual. A retained score must have been observed previously and
the entire regular-season ledger must still reconcile with official records.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from decimal import Decimal
import json
import logging
from pathlib import Path
import re
import time

from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)


class ScoreConflict(ValueError):
    """Provider result and statistical feeds disagree; retry free collection."""


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError("missing score")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite score")
    return result


def points(row):
    return number(row["custom_points"] if row.get("custom_points") is not None else row["points"])


def completed_regular(league):
    settings = league.get("settings") or {}
    return min(int(settings.get("last_scored_leg") or 0), int(settings.get("playoff_week_start") or 15) - 1)


def reconciles(league, rosters, weeks):
    try:
        expected = {r["roster_id"]: r["settings"] for r in rosters}
        if not expected or len(expected) != len(rosters):
            return False
        totals = {rid: [Decimal(0), Decimal(0), 0, 0, 0] for rid in expected}
        count = completed_regular(league)
        if count < 1 or set(weeks) != {str(w) for w in range(1, count + 1)}:
            return False
        for rows in weeks.values():
            if len(rows) != len(expected) or {r["roster_id"] for r in rows} != set(expected):
                return False
            for row in rows:
                opponents = [r for r in rows if r.get("matchup_id") == row.get("matchup_id")
                             and r["roster_id"] != row["roster_id"]]
                if row.get("matchup_id") is None or len(opponents) != 1:
                    return False
                own, other = points(row), points(opponents[0])
                tally = totals[row["roster_id"]]
                tally[0] += own
                tally[1] += other
                tally[2 if own > other else 3 if own < other else 4] += 1
            if (league.get("settings") or {}).get("league_average_match"):
                ordered = sorted(points(r) for r in rows)
                mid = len(ordered) // 2
                median = (ordered[mid - 1] + ordered[mid]) / 2 if len(ordered) % 2 == 0 else ordered[mid]
                for row in rows:
                    own = points(row)
                    totals[row["roster_id"]][2 if own > median else 3 if own < median else 4] += 1
        for rid, (pf, pa, wins, losses, ties) in totals.items():
            s = expected[rid]
            if (pf != number(s["fpts"]) + number(s.get("fpts_decimal", 0)) / 100
                    or pa != number(s["fpts_against"]) + number(s.get("fpts_against_decimal", 0)) / 100
                    or (wins, losses, ties) != (s["wins"], s["losses"], s.get("ties", 0))):
                return False
        return True
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False


def reconcile_scores(league, rosters, current, previous):
    if reconciles(league, rosters, current):
        return deepcopy(current)
    retained = deepcopy(current)
    # A settled correction and an unsettled statistical change can coexist,
    # even for the same roster in different weeks. Select only a UNIQUE ledger
    # made from observed scores. Never manufacture scores from a residual.
    for roster in rosters:
        rid, settings = roster["roster_id"], roster["settings"]
        target = number(settings["fpts"]) + number(settings.get("fpts_decimal", 0)) / 100
        candidates = {Decimal(0): (1, [])}
        for week, rows in retained.items():
            row = next((r for r in rows if r["roster_id"] == rid), None)
            if row is None:
                raise ScoreConflict("score_source_conflict: incomplete roster-week inventory")
            old_rows = previous.get(week, [])
            saved = next((r for r in old_rows if r["roster_id"] == rid), None)
            options = [(points(row), None)]
            same_pair = {r["roster_id"] for r in rows if r.get("matchup_id") == row.get("matchup_id")} == {
                r["roster_id"] for r in old_rows if r.get("matchup_id") == row.get("matchup_id")}
            if (saved and same_pair and all(row.get(k) == saved.get(k) for k in
                    ("starters", "matchup_id", "custom_points")) and points(row) != points(saved)):
                options.append((points(saved), saved["points"]))
            next_candidates = {}
            for total, (ways, choices) in candidates.items():
                for value, saved_value in options:
                    updated = total + value
                    old_ways = next_candidates.get(updated, (0, []))[0]
                    next_candidates[updated] = (min(2, old_ways + ways), choices + [(week, saved_value)])
            candidates = next_candidates
        ways, choices = candidates.get(target, (0, []))
        if ways != 1:
            raise ScoreConflict("score_source_conflict: no unique previously observed score ledger matches official totals")
        for week, saved_value in choices:
            if saved_value is not None:
                row = next(r for r in retained[week] if r["roster_id"] == rid)
                row["score_authority"] = {"kind": "retained_result_reconciled_to_official_standings",
                                          "api_points": str(row["points"])}
                row["points"] = saved_value
    if reconciles(league, rosters, retained):
        return retained
    raise ScoreConflict("score_source_conflict: matchup totals disagree with official season points and records; "
                        "no previously observed result reconciles. Retry free collection; do not regenerate prose.")


class ScoreAuthority:
    def __init__(self, cache_dir: Path):
        self.directory = Path(cache_dir) / "sleeper-results"
        self._tasks = {}
        self._league_tasks = {}
        self._observed_at = {}
        self.evidence = {}

    async def rows(self, http, league_id, week):
        if not re.fullmatch(r"[0-9]+", league_id):
            raise ScoreConflict("score_source_conflict: invalid league identity")
        if time.monotonic() - self._observed_at.get(league_id, 0) > 60:
            self._tasks.pop(league_id, None)
            self._league_tasks.pop(league_id, None)
            self._observed_at[league_id] = time.monotonic()
        if league_id not in self._league_tasks:
            self._league_tasks[league_id] = asyncio.create_task(self._get(http, f"/league/{league_id}"))
        league = await self._league_tasks[league_id]
        # A regular-season conflict must not prevent reading upcoming or
        # postseason matchups, which have different result authorities.
        if league.get("status") != "in_season" or not 1 <= week <= completed_regular(league):
            return None
        if league_id not in self._tasks:
            self._tasks[league_id] = asyncio.create_task(self._load(http, league_id, league))
        try:
            return deepcopy((await self._tasks[league_id]).get(str(week)))
        except Exception:
            self._tasks.pop(league_id, None)
            raise

    async def _get(self, http, path):
        log.info("Fetching free score authority source=%s", path)
        response = await http.get(path)
        response.raise_for_status()
        return json.loads(response.text, parse_float=str)

    async def _load(self, http, league_id, league):
        base = f"/league/{league_id}"
        rosters = await self._get(http, base + "/rosters")
        current = {}
        for week in range(1, completed_regular(league) + 1):
            current[str(week)] = await self._get(http, base + f"/matchups/{week}")
        path = self.directory / f"{league_id}.json"
        try:
            previous = json.loads(path.read_text())
            previous = previous.get("weeks", {}) if previous.get("season") == league.get("season") else {}
        except (OSError, ValueError, AttributeError):
            previous = {}
        resolved = reconcile_scores(league, rosters, current, previous)
        self.evidence[league_id] = {
            "kind": "official_regular_season_reconciliation", "season": league["season"],
            "through_week": completed_regular(league),
            "rosters": [{"roster_id": r["roster_id"], "settings": r["settings"]} for r in rosters],
            "results": {w: [{"roster_id": r["roster_id"], "matchup_id": r["matchup_id"],
                             "points": str(points(r))} for r in rows] for w, rows in resolved.items()},
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, {"season": league["season"], "weeks": resolved,
                                 "verification": self.evidence[league_id]})
        if resolved != current:
            log.warning("Sleeper result/stat divergence league=%s: retained observed results verified against official standings", league_id)
        return resolved
