"""Scoring periods and full roster/bracket coverage; no guessed pairings."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sleeper_dynasty.engine.playoff_phase import weeks_for_round
from sleeper_dynasty.engine.lineup import BENCH_SLOTS, SLOT_ELIGIBILITY


def next_reconciliation(eligible_at: int, now: int) -> int:
    release = datetime.fromtimestamp(eligible_at or now, ZoneInfo("America/Denver"))
    friday = release.date() + timedelta(days=(4 - release.weekday()) % 7)
    cutoff = datetime.combine(friday + timedelta(days=1), time(), ZoneInfo("America/Denver"))
    return now + (900 if now < cutoff.timestamp() else 86400)


def eligible_release(last_game_day: str) -> int:
    day = date.fromisoformat(last_game_day)
    # Thursday through Monday belongs to the following Tuesday release.
    days = (1 - day.weekday()) % 7
    tuesday = day + timedelta(days=days)
    return int(datetime.combine(tuesday, time(8), ZoneInfo("America/Denver")).timestamp())


def period_release(games: list[dict], weeks: list[int]) -> int:
    """Anchor each NFL week at its first scheduled game; delayed games still
    block completion, but do not push an already-reached Tuesday another week.
    """
    return max(eligible_release(min(g["gameday"] for g in games if g["week"] == w)) for w in weeks)


def scoring_period(week: int, settings: dict, bracket: dict) -> dict:
    start = settings.get("playoff_week_start")
    if type(start) is not int or start not in range(1, 19):
        raise ValueError("playoff_rules_unknown")
    if week < start:
        return {"period_id": str(week), "week": week, "round": None, "phase": "regular", "nfl_weeks": [week]}
    kind = settings.get("playoff_round_type")
    if type(kind) is not int or kind not in (0, 1, 2) or not bracket.get("ok"):
        raise ValueError("playoff_rules_unknown")
    if settings.get("playoff_teams", settings.get("num_playoff_teams")) not in (4, 6, 8):
        raise ValueError("playoff_format_unsupported")
    rounds = [max((e.get("r", 0) for e in bracket.get(name, [])), default=0) for name in ("winners", "losers")]
    total = max(rounds)
    if not total or (kind == 1 and len({r for r in rounds if r}) > 1):
        raise ValueError("playoff_round_timing_unsupported")
    for r in range(1, total + 1):
        weeks = weeks_for_round(r, start, kind, total)
        if week in weeks:
            if max(weeks) > 18:
                raise ValueError("playoff_round_timing_unsupported")
            return {"period_id": f"playoff:{r}", "week": max(weeks), "round": r,
                    "phase": "post", "nfl_weeks": weeks, "round_type": kind}
    raise ValueError("season_finished")


def _number(value):
    if not isinstance(value, str):
        raise ValueError("score_precision_unavailable")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("score_invalid")
    return result


def build_participants(rosters: list, scores: dict, bracket: dict, period: dict) -> dict:
    """Keep full source rows, including overrides/bench/ordered starter slots.

    Bracket match IDs are namespaced. Unresolved reference slots never become
    invented opponents. Non-playing roster status requires positive evidence.
    """
    out = {"participants": [], "pairings": [], "scores": deepcopy(scores), "starters": {},
           "bracket": deepcopy(bracket), "participant_error": ""}
    try:
        ids = [r["roster_id"] for r in rosters]
        if not ids or len(set(ids)) != len(ids) or any(not r.get("owner_id") for r in rosters):
            raise ValueError("participant_incomplete")
        weeks = period["nfl_weeks"]
        if any(str(w) not in scores for w in weeks):
            raise ValueError("round_incomplete")
        by_week = {}
        for w in weeks:
            rows = scores[str(w)]
            indexed = {r["roster_id"]: r for r in rows}
            if set(indexed) != set(ids) or len(rows) != len(ids):
                raise ValueError("participant_incomplete")
            by_week[w] = indexed
            out["starters"][str(w)] = {str(rid): deepcopy(row.get("starters")) for rid, row in indexed.items()}
        positions = period.get("roster_positions")
        if (not isinstance(positions, list) or not positions
                or any(not isinstance(p, str) or p not in SLOT_ELIGIBILITY and p not in BENCH_SLOTS for p in positions)
                or not any(p in SLOT_ELIGIBILITY for p in positions)):
            raise ValueError("roster_positions_unsupported")
        starter_count = sum(p not in BENCH_SLOTS for p in positions)
        phase = period["phase"]
        statuses, pairs = {}, []
        if phase == "regular":
            groups = defaultdict(list)
            for row in by_week[weeks[0]].values():
                groups[row.get("matchup_id")].append(row["roster_id"])
            if None in groups or any(len(g) != 2 for g in groups.values()):
                raise ValueError("participant_incomplete")
            pairs = [{"rosters": group, "status": "regular", "source_id": str(mid)} for mid, group in groups.items()]
            statuses = dict.fromkeys(ids, "regular")
        else:
            if not bracket.get("ok"):
                raise ValueError("bracket_unavailable")
            if period.get("round_type") not in (0, 1, 2):
                raise ValueError("playoff_rules_unknown")
            round_no = period["round"]
            finished, future = set(), set()
            for name in ("winners", "losers"):
                entries = bracket.get(name)
                if not isinstance(entries, list):
                    raise ValueError("bracket_unavailable")
                index = {e["m"]: e for e in entries}
                if len(index) != len(entries):
                    raise ValueError("bracket_conflict")
                def resolve(value):
                    if type(value) is int:
                        return value
                    if isinstance(value, dict) and len(value) == 1:
                        side, match = next(iter(value.items()))
                        if side in ("w", "l"):
                            return index.get(match, {}).get(side)
                    return None
                for entry in entries:
                    r = entry.get("r")
                    if type(r) is not int or r < 1:
                        raise ValueError("bracket_conflict")
                    slots = [resolve(entry.get(side)) for side in ("t1", "t2")]
                    # Also validate explicit t*_from provenance when supplied.
                    for slot, side in zip(slots, ("t1", "t2")):
                        reference = entry.get(side + "_from")
                        if reference and resolve(reference) not in (None, slot):
                            raise ValueError("bracket_conflict")
                    if any(s is not None and s not in ids for s in slots):
                        raise ValueError("bracket_conflict")
                    if r < round_no:
                        # A completed semifinal does not prove that its loser
                        # has no placement game. Only an explicit placement
                        # result fixes both participants' final bracket ranks.
                        if (type(entry.get("p")) is int and entry["p"] > 0
                                and entry.get("w") in slots and entry.get("l") in slots
                                and entry.get("w") != entry.get("l") and None not in slots):
                            finished.update(slots)
                    elif r > round_no:
                        future.update(s for s in slots if s is not None)
                    else:
                        if None in slots or len(set(slots)) != 2:
                            raise ValueError("round_unresolved")
                        if any(s in statuses for s in slots):
                            raise ValueError("bracket_conflict")
                        state = "consolation" if name == "losers" else "title" if entry.get("p") in (None, 1) else "placement"
                        statuses.update(dict.fromkeys(slots, state))
                        pairs.append({"rosters": slots, "status": state, "source_id": f"{name}:{entry['m']}",
                            "winner": entry.get("w"), "loser": entry.get("l")})
            for rid in ids:
                if rid not in statuses:
                    statuses[rid] = "bye" if rid in future else "season_finished" if rid in finished else "unknown"
            if "unknown" in statuses.values():
                raise ValueError("participant_status_unknown")
            for rid, status in statuses.items():
                if status in ("bye", "season_finished") and any(by_week[w][rid].get("matchup_id") is not None for w in weeks):
                    raise ValueError("pairing_conflict")
        # Every raw competitive pairing must be exactly one supported pair;
        # matching IDs within a pair alone misses IDs shared by extra owners.
        for w in weeks:
            groups = defaultdict(set)
            for row in by_week[w].values():
                if row.get("matchup_id") is not None:
                    groups[row["matchup_id"]].add(row["roster_id"])
            if {frozenset(g) for g in groups.values()} != {frozenset(p["rosters"]) for p in pairs}:
                raise ValueError("pairing_conflict")
        for pair in pairs:
            totals = []
            for rid in pair["rosters"]:
                total = Decimal(0)
                for w in weeks:
                    row = by_week[w][rid]
                    other = next(i for i in pair["rosters"] if i != rid)
                    if row.get("matchup_id") is None or row.get("matchup_id") != by_week[w][other].get("matchup_id"):
                        raise ValueError("pairing_conflict")
                    starters, points = row.get("starters"), row.get("players_points")
                    if not isinstance(starters, list) or not starters or not isinstance(points, dict):
                        raise ValueError("starter_evidence_incomplete")
                    if len(starters) != starter_count:
                        raise ValueError("starter_evidence_incomplete")
                    active = [pid for pid in starters if pid != "0"]
                    if len(active) != len(set(active)) or any(pid not in (row.get("players") or []) for pid in active):
                        raise ValueError("starter_evidence_incomplete")
                    for pid in starters:
                        if pid != "0":
                            _number(points[pid])
                    original = _number(row["points"])
                    total += _number(row["custom_points"]) if row.get("custom_points") is not None else original
                totals.append(total)
            pair.update(scope="round" if phase == "post" else "week", scores=[str(n) for n in totals],
                        result="tie" if totals[0] == totals[1] else "win")
            if phase == "post":
                if pair.get("winner") not in pair["rosters"] or pair.get("loser") not in pair["rosters"] or pair["winner"] == pair["loser"]:
                    raise ValueError("round_unresolved")
                if totals[0] != totals[1] and pair["winner"] != pair["rosters"][0 if totals[0] > totals[1] else 1]:
                    raise ValueError("round_result_conflict")
                if totals[0] == totals[1]:
                    pair["result"] = "tiebreak_win"
            else:
                pair["winner"] = None if totals[0] == totals[1] else pair["rosters"][0 if totals[0] > totals[1] else 1]
        out["participants"] = [{**deepcopy(r), "status": statuses[r["roster_id"]]} for r in rosters]
        out["pairings"] = pairs
    except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
        out["participant_error"] = str(exc) if isinstance(exc, ValueError) else "participant_incomplete"
    return out
