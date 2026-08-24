"""Dynasty rookie consensus boards, resolved to each draft's own date.

Sleeper publishes no usable rookie ADP: ``adp_rookie`` is unpopulated, and the
overall-NFL ADP that IS published would grade a 1.01 rookie against ~30th
overall and print a 29-pick reach. That is why ``grader.py`` skipped the ADP
block for dynasty entirely, leaving two permanently blank columns.

FantasyPros publishes a dynasty ROOKIE consensus ranking, mirrored by
DynastyProcess with a ``scrape_date``, weekly, back to 2020. Unlike KTC and
FantasyCalc it has dated history, so it grades past classes as well as future
ones.

Resolution picks the board dated on the draft's own day, else the nearest
EARLIER day, never later — a draft is graded against the market as it stood
going in.

Pure. No I/O — callers thread in the parsed boards.
"""

from __future__ import annotations

from datetime import date

# FantasyPros' dynasty ROOKIE consensus. Not "do" (dynasty-overall) and not
# "dsf" (superflex) — those rank the whole player pool.
ROOKIE_ECR_TYPE = "drk"


def _numeric(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_boards(raw: dict) -> dict[str, dict[str, float]]:
    """``{date: {player_id: ecr}}``, non-numeric entries dropped.

    A date whose entries are all unusable is dropped rather than stored empty:
    an empty board is indistinguishable from a failed fetch downstream, and the
    store refuses empties for exactly that reason.
    """
    out: dict[str, dict[str, float]] = {}
    for day, entries in (raw or {}).items():
        if not isinstance(entries, dict):
            continue
        board: dict[str, float] = {}
        for pid, ecr in entries.items():
            val = _numeric(ecr)
            if val is None:
                continue
            board[str(pid)] = val
        if board:
            out[str(day)] = board
    return out


def parse_latest_board(
    rows: list[dict],
    crosswalk: dict[str, str],
    ecr_type: str = ROOKIE_ECR_TYPE,
) -> tuple[str, dict[str, float]] | None:
    """CSV rows -> (scrape_date_str, {sleeper_id: ecr}), or None.

    `crosswalk` is {fantasypros_id: sleeper_id}. An unmapped player is DROPPED,
    never zero-ranked. Returns None when no usable `ecr_type` row is present —
    an empty board is indistinguishable from a failed fetch downstream.

    `ecr_type` selects which FantasyPros consensus to pull out of the mixed
    feed (`drk` dynasty rookie, `do` dynasty overall, `dsf` dynasty superflex,
    ...); it defaults to `ROOKIE_ECR_TYPE` so the rookie-board call sites are
    unaffected.

    Takes the newest `scrape_date` present among matching rows and builds the
    board from that date's rows only (the file should hold one date, but this
    does not assume it).
    """
    by_date: dict[str, dict[str, float]] = {}
    for row in rows or []:
        if row.get("ecr_type") != ecr_type:
            continue
        val = _numeric(row.get("ecr"))
        if val is None:
            continue
        day = str(row.get("scrape_date") or "").strip()
        if not day:
            continue
        fp_id = str(row.get("id") or "").strip()
        sleeper_id = crosswalk.get(fp_id)
        if not sleeper_id:
            continue
        by_date.setdefault(day, {})[sleeper_id] = val
    if not by_date:
        return None
    newest = max(by_date)
    return newest, by_date[newest]


# Boards publish roughly weekly year-round (median gap 7 days across 309
# boards, 2020-2026); the largest legitimate gap observed is 39 days. 60 days
# clears that with headroom while still rejecting a board from a DIFFERENT
# rookie class, which is ~9 months away. Beyond this, "no baseline" is the
# honest answer: grading a 2027 class against a 2026 board is not a stale
# number, it is a number about different players.
MAX_BOARD_AGE_DAYS = 60

# `do`/`dsf` (dynasty overall / superflex) come off the same weekly scrape as
# `drk`, so the same publishing cadence applies: median 7-day gap, largest
# legitimate gap 39 days. But the 60-day figure above is NOT just cadence
# headroom — most of its slack exists to avoid mistaking a board from the
# NEXT rookie class (~9 months later) for a stale one. Dynasty-overall and
# superflex rank the whole player pool, not one draft class, so that
# confusion cannot happen: there is no "wrong class" a later board could
# belong to instead. Without that concern to push the number out, the bound
# only needs to cover a missed scrape or two — 45 days (39-day worst
# legitimate gap plus about a week of buffer) separates "the feed hiccuped"
# from "this market read is too old to trust," instead of borrowing the
# rookie path's 60 by inertia.
DYNASTY_OVERALL_MAX_BOARD_AGE_DAYS = 45


def resolve_board(
    boards: dict[str, dict[str, float]],
    drafted_on: date,
    max_age_days: int = MAX_BOARD_AGE_DAYS,
) -> tuple[str, dict[str, float]] | None:
    """The board dated on-or-before ``drafted_on``, newest first.

    Returns ``(date_string, board)``, or None when no board predates the draft:
    that class is older than our history and has no baseline, permanently.
    Handing back a later board would be exactly the hindsight grading this
    resolver exists to prevent.

    Also None when the best on-or-before board is older than ``max_age_days``:
    once committed history runs dry, the newest board still on-or-before a
    future draft is a board about an entirely different rookie class, not a
    stale number for this one.
    """
    target = drafted_on.isoformat()
    candidates = sorted((d for d in boards if d <= target), reverse=True)
    for day in candidates:
        board = boards.get(day)
        if not board:
            continue
        age = (drafted_on - date.fromisoformat(day)).days
        if age > max_age_days:
            return None
        return day, board
    return None


def board_delta(*, pick_no: int, ecr: float | None) -> float | None:
    """How far past his consensus rank a player was taken.

    Positive = still there later than the market ranked him (value).
    Negative = a reach. None when the player is unranked — the pick is
    ungraded on this baseline, which is not the same as scoring zero.
    """
    if ecr is None:
        return None
    return float(pick_no) - float(ecr)
