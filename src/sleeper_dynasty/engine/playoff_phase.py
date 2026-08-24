"""Interpret Sleeper winners/losers brackets into a per-week phase map.

Pure + fully unit-testable: no I/O, no Sleeper types -- raw bracket dicts in,
``(week, roster_id) -> phase`` out. "phase" is "playoff" (live title-path
winners game) or "toilet" (any losers-bracket game). Anything absent is a
dropped week (bye, winners placement game) or regular season (handled by the
caller via week < playoff_week_start).
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)


def weeks_for_round(r, playoff_week_start, playoff_round_type, total_rounds=None):
    """NFL week(s) a bracket round occupies."""
    if playoff_round_type == 2:
        first = playoff_week_start + 2 * (r - 1)
        return [first, first + 1]
    if playoff_round_type == 1 and total_rounds is not None and r == total_rounds:
        first = playoff_week_start + (r - 1)
        return [first, first + 1]
    return [playoff_week_start + (r - 1)]


def _is_title_path(entry):
    p = entry.get("p")
    return p is None or p == 1


def _rosters(entry):
    out = []
    for k in ("t1", "t2"):
        v = entry.get(k)
        if isinstance(v, int):
            out.append(v)
    return out


def classify_playoff_phases(winners_bracket, losers_bracket, playoff_week_start, playoff_round_type):
    """(week, roster_id) -> "playoff" | "toilet". See module docstring."""
    out = {}
    w_rounds = [e.get("r") for e in winners_bracket if isinstance(e.get("r"), int)]
    total_w = max(w_rounds) if w_rounds else 0
    for e in winners_bracket:
        if not _is_title_path(e):
            continue
        r = e.get("r")
        if not isinstance(r, int):
            continue
        for wk in weeks_for_round(r, playoff_week_start, playoff_round_type, total_w):
            for rid in _rosters(e):
                out[(wk, rid)] = "playoff"
    l_rounds = [e.get("r") for e in losers_bracket if isinstance(e.get("r"), int)]
    total_l = max(l_rounds) if l_rounds else 0
    for e in losers_bracket:
        r = e.get("r")
        if not isinstance(r, int):
            continue
        for wk in weeks_for_round(r, playoff_week_start, playoff_round_type, total_l):
            for rid in _rosters(e):
                out.setdefault((wk, rid), "toilet")
    return out


def build_bracket_watch(winners_bracket, roster_to_user, *, seed_by_user=None):
    """Who is still alive on the title path, for the postseason dashboard lead.

    Pure, and deliberately conservative — the lead must never claim a team is
    alive or out on anything but a played result:

    * **Entrants come from every round, not round one.** In a 6-team bracket
      the top two seeds have byes and first appear in round 2, so a round-1
      scan reports a 4-team field and treats the 1 seed as eliminated.
    * **Only a played title-path loss eliminates.** ``w``/``l`` are null until
      a game finishes, so a pending final knocks nobody out.
    * **Placement games are not the title path.** Losing a third-place game
      does not eliminate (you were already out), and winning one must never
      read as still alive for the championship. Same ``p`` rule the phase
      classifier uses.

    ``seed_by_user`` is regular-season rank (1 = best). Omitted or incomplete,
    ``top_seed`` comes back None rather than guessed — an unnamed cell beats a
    wrong one.

    Returns None when there is no bracket at all.
    """
    if not winners_bracket:
        return None

    entrants: list[int] = []
    eliminated_rids: list[int] = []
    for e in winners_bracket:
        for rid in _rosters(e):
            if rid not in entrants:
                entrants.append(rid)
        # A loss only counts on the title path, and only once played.
        if _is_title_path(e) and isinstance(e.get("l"), int):
            if e["l"] not in eliminated_rids:
                eliminated_rids.append(e["l"])

    def uid_of(rid):
        return (roster_to_user or {}).get(rid)

    # A roster the owner map doesn't cover is skipped rather than surfaced as
    # a bare id — the lead prints names, and a number there reads as a bug.
    entered_uids = [u for u in (uid_of(r) for r in entrants) if u]
    eliminated = [u for u in (uid_of(r) for r in eliminated_rids) if u]
    alive = [u for u in entered_uids if u not in eliminated]

    seeds = seed_by_user or {}
    seeded = [(seeds[u], u) for u in alive if u in seeds]
    top_seed, top_uid = min(seeded) if seeded else (None, None)

    return {
        "entered": len(entered_uids),
        "alive": alive,
        "alive_count": len(alive),
        "eliminated": eliminated,
        "top_seed_user_id": top_uid,
        "top_seed": top_seed,
    }
