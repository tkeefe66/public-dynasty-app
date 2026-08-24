"""Audit script: validates the playoff-phase bracket classifier against real Sleeper data.

Fetches live data from Sleeper's public API (no auth, stdlib urllib only) for the
league chain starting at league 9000000000000000001, walks back to origin via
previous_league_id, and for each season:

  - Prints the winners + losers bracket game-by-game in human-readable form
  - Shows the derived phase map (which weeks are "playoff" or "toilet" per roster)
  - Maps roster_id -> owner display name for readability
  - Runs structural assertions and prints PASS/REVIEW for each

How to run:
    PYTHONPATH=src python scripts/audit_playoff_phases.py

Imports classify_playoff_phases and weeks_for_round from
sleeper_dynasty.engine.playoff_phase (pure, no I/O). Requires PYTHONPATH=src so
the engine is importable without an editable install.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from typing import Any

# ---------------------------------------------------------------------------
# Classifier import (pure engine, no I/O)
# ---------------------------------------------------------------------------
try:
    from sleeper_dynasty.engine.playoff_phase import classify_playoff_phases, weeks_for_round
except ImportError as exc:
    sys.exit(
        f"Cannot import playoff_phase: {exc}\n"
        "Run with:  PYTHONPATH=src python scripts/audit_playoff_phases.py"
    )

BASE_URL = "https://api.sleeper.app/v1"
ENTRY_LEAGUE_ID = "9000000000000000001"


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def _get(path: str) -> Any:
    url = BASE_URL + path
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fetch_league(league_id: str) -> dict:
    return _get(f"/league/{league_id}")


def fetch_winners_bracket(league_id: str) -> list[dict]:
    try:
        data = _get(f"/league/{league_id}/winners_bracket")
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  [warn] winners_bracket fetch failed: {e}")
        return []


def fetch_losers_bracket(league_id: str) -> list[dict]:
    try:
        data = _get(f"/league/{league_id}/losers_bracket")
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  [warn] losers_bracket fetch failed: {e}")
        return []


def fetch_rosters(league_id: str) -> list[dict]:
    data = _get(f"/league/{league_id}/rosters")
    return data if isinstance(data, list) else []


def fetch_users(league_id: str) -> list[dict]:
    data = _get(f"/league/{league_id}/users")
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# League chain walk
# ---------------------------------------------------------------------------

def walk_league_chain(entry_id: str) -> list[dict]:
    """Walk previous_league_id back to origin. Returns newest->oldest.

    Sleeper marks the origin season with the sentinel string "0" rather
    than a JSON null, so that value is treated as absent too.
    """
    chain: list[dict] = []
    current_id: str | None = entry_id
    while current_id:
        raw = fetch_league(current_id)
        chain.append(raw)
        prev_id = raw.get("previous_league_id")
        current_id = prev_id if prev_id and prev_id != "0" else None
    return chain


# ---------------------------------------------------------------------------
# Name mapping helpers
# ---------------------------------------------------------------------------

def build_name_map(league_id: str) -> dict[int, str]:
    """roster_id -> owner display name."""
    users = fetch_users(league_id)
    rosters = fetch_rosters(league_id)

    user_display: dict[str, str] = {}
    for u in users:
        uid = u.get("user_id", "")
        name = (u.get("metadata") or {}).get("team_name") or u.get("display_name") or uid
        user_display[uid] = str(name)

    out: dict[int, str] = {}
    for r in rosters:
        rid = r.get("roster_id")
        uid = r.get("owner_id") or ""
        if rid is not None:
            out[int(rid)] = user_display.get(uid, uid or f"roster_{rid}")
    return out


# ---------------------------------------------------------------------------
# Bracket display helpers
# ---------------------------------------------------------------------------

def _placement_label(p: int | None) -> str:
    if p is None or p == 1:
        return ""
    labels = {3: "p:3", 5: "p:5", 7: "p:7"}
    return f" [{labels.get(p, f'p:{p}')}]"


def _roster_name(rid: int | None, names: dict[int, str]) -> str:
    if rid is None:
        return "BYE"
    return f"{names.get(rid, str(rid))} (r{rid})"


def print_bracket_side(entries: list[dict], label: str, names: dict[int, str],
                        playoff_week_start: int, playoff_round_type: int) -> None:
    """Print one bracket (winners or losers) game by game, grouped by round."""
    if not entries:
        print(f"  {label}: (empty)")
        return

    rounds: dict[int, list[dict]] = defaultdict(list)
    for e in entries:
        r = e.get("r")
        if isinstance(r, int):
            rounds[r].append(e)

    total_rounds = max(rounds) if rounds else 0

    # Identify which rosters got first-round byes (in winners bracket):
    # a roster has a bye if it appears as t1/t2 in round 2 but not in round 1
    r1_rosters: set[int] = set()
    r2_rosters: set[int] = set()
    for e in rounds.get(1, []):
        for k in ("t1", "t2"):
            v = e.get(k)
            if isinstance(v, int):
                r1_rosters.add(v)
    for e in rounds.get(2, []):
        for k in ("t1", "t2"):
            v = e.get(k)
            if isinstance(v, int):
                r2_rosters.add(v)
    bye_rosters = r2_rosters - r1_rosters if label == "WINNERS" else set()

    print(f"\n  {label} BRACKET:")
    if bye_rosters:
        bye_names = ", ".join(f"{names.get(r, str(r))} (r{r})" for r in sorted(bye_rosters))
        print(f"    First-round byes: {bye_names}")

    for r in sorted(rounds):
        wks = weeks_for_round(r, playoff_week_start, playoff_round_type, total_rounds)
        wk_str = "/".join(f"wk{w}" for w in wks)
        print(f"    Round {r} ({wk_str}):")
        for e in rounds[r]:
            t1 = e.get("t1")
            t2 = e.get("t2")
            winner = e.get("w")
            p = e.get("p")
            placement = _placement_label(p)
            t1_name = _roster_name(t1 if isinstance(t1, int) else None, names)
            t2_name = _roster_name(t2 if isinstance(t2, int) else None, names)
            if winner is not None:
                winner_name = names.get(winner, str(winner))
                result = f"-> {winner_name} wins"
            else:
                result = "-> (not played)"
            print(f"      {t1_name} vs {t2_name}  {result}{placement}")


def print_phase_map(phase_map: dict[tuple[int, int], str], names: dict[int, str],
                    playoff_week_start: int) -> None:
    """Print per-roster week assignments from classify_playoff_phases."""
    # Group by roster
    roster_weeks: dict[int, dict[str, list[int]]] = defaultdict(lambda: {"playoff": [], "toilet": []})
    for (wk, rid), phase in phase_map.items():
        roster_weeks[rid][phase].append(wk)

    print("\n  PHASE MAP (bracket-aware assignments):")
    for rid in sorted(roster_weeks):
        playoff_wks = sorted(roster_weeks[rid]["playoff"])
        toilet_wks = sorted(roster_weeks[rid]["toilet"])
        name = names.get(rid, f"r{rid}")
        playoff_str = f"playoff: wks {playoff_wks}" if playoff_wks else "playoff: []"
        toilet_str = f"toilet: wks {toilet_wks}" if toilet_wks else "toilet: []"
        print(f"    r{rid} {name:<20} {playoff_str}  |  {toilet_str}")


# ---------------------------------------------------------------------------
# Structural assertions
# ---------------------------------------------------------------------------

def run_assertions(
    season: int,
    status: str,
    winners: list[dict],
    losers: list[dict],
    phase_map: dict[tuple[int, int], str],
    total_rosters: int,
    playoff_teams: int,
    playoff_week_start: int,
    playoff_round_type: int,
    names: dict[int, str],
) -> list[tuple[str, str, str]]:
    """Run structural assertions. Returns list of (label, result, detail)."""
    results: list[tuple[str, str, str]] = []

    # Collect all rosters that appear in any bracket
    winners_rosters: set[int] = set()
    losers_rosters: set[int] = set()
    for e in winners:
        for k in ("t1", "t2"):
            v = e.get(k)
            if isinstance(v, int):
                winners_rosters.add(v)
    for e in losers:
        for k in ("t1", "t2"):
            v = e.get(k)
            if isinstance(v, int):
                losers_rosters.add(v)

    # 1. Every roster in exactly one bracket (for completed seasons with brackets)
    is_completed = status == "complete"
    if is_completed and winners_rosters:
        both = winners_rosters & losers_rosters
        neither = set(range(1, total_rosters + 1)) - winners_rosters - losers_rosters
        # Note: it's valid for some rosters to be in neither if they're excluded from
        # both brackets (depends on league size vs playoff_teams), but every playoff
        # roster should be in exactly one bracket
        playoff_all = winners_rosters | losers_rosters
        if both:
            both_names = ", ".join(f"r{r}({names.get(r,'?')})" for r in sorted(both))
            results.append(("Rosters in exactly one bracket", "REVIEW",
                            f"rosters in BOTH brackets: {both_names}"))
        else:
            results.append(("Rosters in exactly one bracket", "PASS",
                            f"{len(playoff_all)} rosters split winners={len(winners_rosters)} losers={len(losers_rosters)}"))
    else:
        results.append(("Rosters in exactly one bracket", "SKIP",
                        f"season status={status}, brackets={'present' if winners_rosters else 'empty'}"))

    # 2. Championship game (p:1) exists and has a winner
    if is_completed and winners:
        champ_games = [e for e in winners if e.get("p") == 1 or e.get("p") is None]
        # p=None entries in winners bracket are title-path games (p=1 is the championship)
        champ = [e for e in winners if e.get("p") == 1]
        if not champ:
            # fallback: highest round with no placement tag
            all_rounds = [e.get("r") for e in winners if isinstance(e.get("r"), int) and e.get("p") is None]
            if all_rounds:
                max_r = max(all_rounds)
                champ = [e for e in winners if e.get("r") == max_r and e.get("p") is None]
        if champ:
            c = champ[0]
            winner = c.get("w")
            if winner is not None:
                results.append(("Championship game exists with winner", "PASS",
                                f"champion: {names.get(winner, str(winner))} (r{winner})"))
            else:
                results.append(("Championship game exists with winner", "REVIEW",
                                "championship game found but no winner recorded"))
        else:
            results.append(("Championship game exists with winner", "REVIEW",
                            "no championship game (p:1) found in winners bracket"))
    else:
        results.append(("Championship game exists with winner", "SKIP",
                        f"season status={status}"))

    # 3. First-round bye rosters have no phase entry in opening playoff week
    if is_completed and winners:
        rounds: dict[int, list[dict]] = defaultdict(list)
        for e in winners:
            r = e.get("r")
            if isinstance(r, int):
                rounds[r].append(e)
        total_w = max(rounds) if rounds else 0

        r1_rosters_w: set[int] = set()
        for e in rounds.get(1, []):
            for k in ("t1", "t2"):
                v = e.get(k)
                if isinstance(v, int):
                    r1_rosters_w.add(v)

        r2_rosters_w: set[int] = set()
        for e in rounds.get(2, []):
            for k in ("t1", "t2"):
                v = e.get(k)
                if isinstance(v, int):
                    r2_rosters_w.add(v)

        bye_rosters_w = r2_rosters_w - r1_rosters_w
        opening_wk = weeks_for_round(1, playoff_week_start, playoff_round_type, total_w)[0]

        bye_with_phase = [r for r in bye_rosters_w if (opening_wk, r) in phase_map]
        if bye_rosters_w and not bye_with_phase:
            results.append(("Bye rosters absent from opening playoff week", "PASS",
                            f"{len(bye_rosters_w)} bye rosters correctly absent from wk{opening_wk}"))
        elif not bye_rosters_w:
            results.append(("Bye rosters absent from opening playoff week", "PASS",
                            "no first-round byes detected"))
        else:
            bad = ", ".join(f"r{r}({names.get(r,'?')})" for r in bye_with_phase)
            results.append(("Bye rosters absent from opening playoff week", "REVIEW",
                            f"bye rosters have phase entry in wk{opening_wk}: {bad}"))
    else:
        results.append(("Bye rosters absent from opening playoff week", "SKIP",
                        f"season status={status}"))

    # 4. No roster has both playoff and toilet in the same week
    week_roster: dict[tuple[int, int], list[str]] = defaultdict(list)
    for (wk, rid), phase in phase_map.items():
        week_roster[(wk, rid)].append(phase)

    conflicts = [(wk, rid, phases) for (wk, rid), phases in week_roster.items()
                 if len(set(phases)) > 1]
    if not conflicts:
        results.append(("No roster in both playoff+toilet same week", "PASS",
                        "no conflicts found"))
    else:
        details = "; ".join(f"wk{wk} r{rid}:{phases}" for wk, rid, phases in conflicts[:5])
        results.append(("No roster in both playoff+toilet same week", "REVIEW",
                        f"{len(conflicts)} conflict(s): {details}"))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("PLAYOFF PHASE AUDIT")
    print(f"Entry league: {ENTRY_LEAGUE_ID}")
    print("=" * 70)

    print("\nFetching league chain...")
    chain = walk_league_chain(ENTRY_LEAGUE_ID)
    print(f"Chain length: {len(chain)} seasons")

    all_assertion_results: list[tuple[int, str, str, str]] = []  # (season, label, result, detail)
    overall_reviews = 0

    for raw in reversed(chain):  # oldest -> newest
        league_id = raw["league_id"]
        season = int(raw["season"])
        status = raw.get("status", "unknown")
        settings = raw.get("settings") or {}
        playoff_week_start = settings.get("playoff_week_start", 15)
        playoff_round_type = settings.get("playoff_round_type", 0)
        total_rosters = raw.get("total_rosters", 0)
        playoff_teams = settings.get("num_playoff_teams", 6)

        print("\n" + "=" * 70)
        print(f"SEASON {season}  [{league_id}]")
        print(f"  status={status}  playoff_week_start={playoff_week_start}"
              f"  playoff_round_type={playoff_round_type}"
              f"  total_rosters={total_rosters}  playoff_teams={playoff_teams}")

        # Fetch data
        names = build_name_map(league_id)
        winners = fetch_winners_bracket(league_id)
        losers = fetch_losers_bracket(league_id)

        if not winners:
            print("  (no bracket data — season may be in progress or pre-playoff)")
        else:
            print_bracket_side(winners, "WINNERS", names, playoff_week_start, playoff_round_type)
            print_bracket_side(losers, "LOSERS", names, playoff_week_start, playoff_round_type)

        # Derive phase map
        phase_map = classify_playoff_phases(winners, losers, playoff_week_start, playoff_round_type)
        print_phase_map(phase_map, names, playoff_week_start)

        # Assertions
        assertion_results = run_assertions(
            season=season,
            status=status,
            winners=winners,
            losers=losers,
            phase_map=phase_map,
            total_rosters=total_rosters,
            playoff_teams=playoff_teams,
            playoff_week_start=playoff_week_start,
            playoff_round_type=playoff_round_type,
            names=names,
        )

        print(f"\n  ASSERTIONS (season {season}):")
        for label, result, detail in assertion_results:
            marker = "PASS" if result == "PASS" else ("SKIP" if result == "SKIP" else "REVIEW ***")
            print(f"    [{marker}] {label}")
            print(f"           {detail}")
            all_assertion_results.append((season, label, result, detail))
            if result == "REVIEW":
                overall_reviews += 1

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for season, label, result, detail in all_assertion_results:
        if result in ("PASS", "SKIP"):
            tag = "PASS" if result == "PASS" else "SKIP"
        else:
            tag = "REVIEW ***"
        print(f"  {season}  [{tag}]  {label}")
        if result == "REVIEW":
            print(f"         -> {detail}")

    print()
    if overall_reviews == 0:
        print("OVERALL: ALL ASSERTIONS PASSED (or skipped for in-progress seasons)")
    else:
        print(f"OVERALL: {overall_reviews} REVIEW(s) — see details above")


if __name__ == "__main__":
    main()
