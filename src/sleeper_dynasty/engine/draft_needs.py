"""Draft-day needs: which starting slots were holes, and whether the draft
addressed them.

Reconstructs each owner's optimal starting lineup on draft day (by inverted
ECR, reusing ``engine/lineup.py::solve_optimal_lineup`` exactly as
``outlook.py``/``skill_signals.py`` do -- one call per owner, the full
``roster_positions``, real per-player positions, discard the returned
total), decides which of those slots were holes against a **per-position,
league-relative** replacement line, and answers two verdicts: did the draft
pick into an open hole, and did that pick ever start.

Pure. No I/O, no client, no import from ``api/``.

**Real per-player position, threaded through explicitly.** ``positions``
(player_id -> fantasy position, e.g. from the Sleeper player catalog
``api/app/services/grader_io.py`` already loads) is what lets
``solve_optimal_lineup``'s ``SLOT_ELIGIBILITY`` table do real work: a QB can
only ever fill a QB-eligible slot, never a WR slot, regardless of ECR. The
replacement line follows the same discipline -- it is computed **per
position**, not from one shared leaguewide pool. For a slot label with a
single eligible position (QB, RB, WR, TE) this is unambiguous. A
FLEX-eligible slot has no line of its own: whichever real position actually
fills it is compared against *that position's* line -- "a FLEX-eligible
position counts toward its own line, not FLEX's." Demand itself, however,
is FROZEN and structural (position-room-model spec, 2026-08-18):
``_direct_demand`` counts each position's own direct (non-FLEX) starting
slots in ``roster_positions``, times the number of owners in the league --
never inflated by which real position empirically wins a FLEX slot that
season. Two passes follow: first compute that fixed demand and solve every
owner's lineup (needed for Pass 3's per-slot checks, no longer for demand);
second, for each position, the line is the value of the Nth-best player *at
that position* across every reconstructed roster, N being that fixed
demand.

**Unmapped players get the same non-erasure treatment on both axes.** A
rostered player missing from the ECR ``board`` gets a value sentinel
(worse than every ranked player, but a real number, so he still competes
for and fills his slot rather than the slot going empty). A rostered player
missing from ``positions`` gets the analogous treatment on the other axis:
he cannot go through ``solve_optimal_lineup``'s real ``SLOT_ELIGIBILITY``
check (we don't know what he's eligible for), so he's excluded from the
primary solve, but if a starter slot comes back empty and one of these
players is still on the roster, he fills it directly -- better-value-first
-- rather than leaving a legitimate slot looking empty because of a data
gap rather than roster thinness. Since his true position is unknown he
can't inform any position's demand or be checked against a real
position's line; he's compared (if at all) against whatever line already
exists for the raw slot label he landed in, which is only ever non-trivial
for a single-position slot (a FLEX-label fallback is never flagged as a
hole, since there is no "FLEX line" to compare against -- honest silence
over a fabricated verdict). The same "nothing to attribute it to" reasoning
applies to an empty FLEX-type slot: it stays visible in ``starters_by_slot``
(``None``) but is excluded from ``holes``, since no Sleeper draft pick's
position is ever literally "FLEX" and a hole a pick can't be credited
against is worse than no verdict.

**A line can land on the sentinel itself.** If a position's own demand N
reaches past its ranked depth into board-unranked players (all sharing
``UNRANKED_ECR_SENTINEL``), that position's replacement line becomes the
sentinel value exactly. Every unranked player at that position then sits AT
the line, not below it -- mutually safe against each other, since this
module has no way to distinguish tied-worst players. Not a bug: it falls
out of the same strict-``<`` rule that makes the Nth-best ranked player safe
elsewhere, just visible here because "worst" is a real, finite number
instead of an unbounded rank.

**Not to be confused with the other ``draft_needs``.**
``engine/dynasty.py::assess_draft_needs`` is a different, pre-existing
concept (bye-week and roster-composition needs, surfaced as
``outlook["draft_needs"]`` and rendered by ``owner_view.py:177``'s
``DraftNeedView``). This module's ``build_draft_needs`` is unrelated and
newer -- wired separately onto ``ChainCacheEntry.draft_needs`` by
``grader.py``. Same name, two different things; check the import path.

**Revision -- the replacement line becomes league-native (2026-08-17).**
The line was originally drawn on ``dynasty-overall`` ECR alone -- a national
consensus calibrated for roughly-standard scoring. Measured against a real
league playing 6-point passing touchdowns, the ECR-drawn QB line landed 92
points below a points-drawn one, and the binary above/below verdict threw
away everything the engine already knew about *how far* a slot was from
replacement. See the spec's "Revision" section
(``docs/superpowers/specs/2026-08-17-draft-needs-phase5-design.md``) for the
full measurement.

``build_draft_needs`` now takes an optional ``points`` map (player_id ->
prior-season points, in this league's own scoring). When supplied, the
replacement line is drawn on **points**, not ECR -- points is already a
"higher is better" number and, unlike ECR, must never be inverted (see
``_value``'s docstring and ``test_points_are_not_inverted``, the test that
guards exactly this). ECR keeps two narrower jobs: a **fallback** value for a
player with no prior-season points (an offseason pickup nobody on this
roster has produced for yet), and a **veto** -- a slot below the points line
is a hole only if ECR does not rate that player above its own, separately
computed, ECR line (``test_a_young_player_below_replacement_on_points_is_vetoed_by_ecr``).
One sentence for the docstring: *last year's production says replaceable,
and the market does not disagree.* ``points=None`` (the default) falls back
entirely to the pre-revision ECR-only behaviour, unchanged -- every existing
call site and test keeps working
(``test_omitting_points_preserves_the_existing_ecr_behaviour``).

Severity replaces the binary: ``OwnerNeeds.slots`` carries one
``SlotStanding`` per starting slot INSTANCE (in ``roster_positions`` order),
each with its own ``margin`` (points below the line, negative), an
``is_hole`` verdict, and a ``vetoed`` flag distinguishing "below the line and
a real hole" from "below the line but the ECR veto rescued it". This
replaced two earlier, differently-keyed fields (``hole_margins``, keyed by
bare position label, and ``softest_slot``, whose first element was a
slot-INSTANCE key like ``"RB_2"``) that disagreed with each other and with
``holes`` the moment a position had more than one starting slot -- see the
2026-08-17 keyspace-fix revision. ``slots`` is the one keyspace: everything
else is derived from it. ``holes`` (bare position labels, most-severe first)
is a dedupe of the ``is_hole`` entries; "the softest slot" is
``min(slots, key=lambda s: s.margin)``; a vetoed slot is any entry with
``vetoed=True``.

**The last six-figure-margin path (2026-08-18 fix).** A starter with a
KNOWN position but neither prior-season points nor an ECR rank at all was
the one case the I2 rank-match couldn't reach -- that match requires a
``board`` (ECR) entry to key off of, and this player has neither axis. He
fell through ``_value`` to the raw ``-UNRANKED_ECR_SENTINEL`` (an
ECR-scale number, ~1e6) compared directly against a points-drawn line,
producing a measured ``-1,000,050.0`` margin on a thin bench -- the same
scale-mixing defect I2 fixed, just on the one path I2's own docstring had
declared "untouched ... unchanged and correct." ``_rank_matched_points``
now gives him a points-space FLOOR (below the worst real points-haver at
his position) instead -- see that function's docstring for the mechanism.
He still counts as a hole (the ECR veto can't rescue a player whose ECR
value is the same sentinel), which is a deliberate reading, not an
arithmetic accident: a total unknown -- no production, no market opinion
-- is conservatively treated as below replacement, same verdict as
pre-fix, now on a sane scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sleeper_dynasty.engine.lineup import (
    BENCH_SLOTS,
    SLOT_ELIGIBILITY,
    solve_optimal_lineup,
)

# DEF is excluded from hole-hunting: dynasty-overall ECR does not
# meaningfully rank it, it's streamed off the wire week to week, and no
# rookie draft addresses it. Left in `roster_positions` unstripped before
# the solve, it would come back permanently empty (no DEF players in the
# value map) -- and an empty slot is trivially below any replacement line,
# manufacturing a phantom hole for every owner every time.
#
# K was excluded for the same reasons through 2026-08-17, but kicker
# points are real (Sleeper scores K normally, `points` already carries
# them from the league's own scoring) and a thin K room is real
# diagnostic signal -- see the position-room-model spec, 2026-08-18,
# "Decision: include K, scoped correctly". K is no longer stripped here.
# It gets a real demand (`_direct_demand`) and a real line like any other
# single-position slot; the ECR veto degrades to a structural no-op for it
# (dynasty-overall ECR does not rank kickers at all, so every K ties at
# `UNRANKED_ECR_SENTINEL` and none can outrank another). K is
# deliberately NOT given any special handling in `drafted_into`/`started`
# below -- a rookie draft essentially never picks a kicker (measured: zero
# in the reference league's 2026 class), so a K-only hole genuinely never
# gets addressed. That's a real, honest reading, not an empty one: the web
# layer's Drafted-into cell (`draftedIntoReading`, `DraftGoingIn.tsx`)
# renders it as the words "not addressed", distinct from the plain "--" a
# zero-holes owner gets there. The Started cell reads plain "--" instead
# (nothing to compute a start-rate over -- same reading a zero-holes owner
# gets there); see the gating discussion in the spec's "Decision: do not
# expect ... K ever populating 'Drafted into' / 'Started'".
EXCLUDED_SLOTS: set[str] = {"DEF"}

# A rostered player absent from the ECR board needs a value that ranks worse
# than every real ECR rank (so he never looks like a stud) but is still a
# finite, comparable number (so he fills his slot rather than the slot
# manufacturing the same phantom hole an empty K/DEF slot would). No real
# ECR board rank reaches six digits.
UNRANKED_ECR_SENTINEL = 1_000_000.0


def _value(
    pid: str,
    board: dict[str, float],
    points: dict[str, float] | None = None,
    rank_points: dict[str, float] | None = None,
) -> float:
    """The one scalar every downstream comparison sorts on -- and the exact
    seam where two OPPOSITE value conventions meet, which is the defect most
    likely to slip through a change to this module.

    ``points`` (prior-season points, this league's own scoring) is already
    "higher is better" and must NEVER be inverted -- ``test_points_are_not_
    inverted`` is the named test that guards this. Inverting it would start
    the WORST player on every roster, and every other assertion in the
    suite would still pass, because the ordering is merely reversed, not
    broken.

    ``board`` (ECR: rank, lower = better) is the opposite convention and
    MUST be inverted before it can be compared or sorted the same way --
    ``test_ecr_rank_is_inverted_so_the_best_player_starts`` guards that
    direction. Raw ECR in means the worst players would be picked first.

    Priority: a player's own ``points`` value when present (rule 1);
    ``rank_points`` -- a rank-matched points-space stand-in for a player
    with an ECR but no points (I2 fix, 2026-08-17) -- next; raw inverted
    ECR as the LAST-resort fallback when neither exists (rule 5, unchanged);
    the unranked sentinel when there's no ECR either, so a slot never reads
    empty.

    ``rank_points`` (built once per league by ``_rank_matched_points``) is
    itself always in points space -- it is looked up, never inverted, same
    as ``points``. Mixing raw ``-ecr`` (always negative) directly against a
    points-drawn replacement line (never negative) manufactured a false
    hole for every no-points starter -- see this module's "Revision"
    docstring section and ``test_a_genuine_no_points_starter_is_not_
    automatically_a_hole``."""
    if points is not None and pid in points:
        return points[pid]
    if rank_points is not None and pid in rank_points:
        return rank_points[pid]
    ecr = board.get(pid, UNRANKED_ECR_SENTINEL)
    return -ecr


def _ecr_value(pid: str, board: dict[str, float]) -> float:
    """Pure ECR value (inverted, same convention as ``_value``'s ECR branch)
    -- used ONLY to draw the veto's ECR line (rule 3). Deliberately never
    consults ``points``: the veto's whole job is to ask what the market
    thinks independently of what points already disqualified."""
    ecr = board.get(pid, UNRANKED_ECR_SENTINEL)
    return -ecr


def _rank_matched_points(
    rosters: dict[str, set[str]],
    board: dict[str, float],
    positions: dict[str, str],
    points: dict[str, float] | None,
) -> dict[str, float]:
    """I2 fix (2026-08-17): a points-space stand-in for a rostered player
    who has an ECR but no prior-season points -- the offseason-pickup case
    the raw ``-ecr`` fallback exists for, but computed so it never mixes
    scales with the points-drawn replacement line.

    ``-ecr`` is always negative; a points line is never negative (points
    are >= 0). Comparing the two directly means a no-points starter is
    *always* below a points line, regardless of how good he actually is --
    manufacturing exactly the hole this module exists to detect honestly.
    Worse, when the replacement line itself lands ON such a player (he's
    the Nth-best in his position's pool), every OTHER player at that
    position inherits a margin inflated by the ``-ecr`` vs points gap (the
    measured case: a six-figure ``WR margin``).

    Rank-match instead: find the player's rank among every rostered,
    ECR-ranked player at his position (rank 1 = best ECR), then use the
    POINTS value of the player at that same rank among that position's
    rostered players who do have points. Both rankings are "1 = best", so
    this maps an elite-but-unproven ECR rank onto an elite points value
    from a real, comparable player, and a mediocre ECR rank onto a
    mediocre one -- a real points-scale number instead of a borrowed
    ECR-scale one. When his rank falls past the points-having pool's own
    depth, it clamps to that pool's worst (still real, still points-scale)
    entry rather than going out of bounds.

    Returns ``{}`` immediately when ``points`` is ``None`` -- the
    pre-revision ECR-only path never draws a points line in the first
    place, so there's nothing for this to reconcile scales against
    (``test_omitting_points_preserves_the_existing_ecr_behaviour``).

    **A player with NEITHER points NOR ECR gets a points-space FLOOR
    (2026-08-18 fix).** He is never a candidate for the rank-match above --
    that requires a ``board`` (ECR) entry, which he doesn't have either --
    so pre-fix he fell all the way through ``_value`` to the raw
    ``-UNRANKED_ECR_SENTINEL``: an ECR-scale number, compared directly
    against a points-drawn replacement line. Measured live: a six-figure
    margin (``-1,000,050.0``) on a thin bench, the same scale-mixing defect
    the rank-match above exists to prevent for the ECR-having case. He now
    gets the SAME points-space treatment: a floor strictly below the WORST
    real points-haver at his position (``min(points at that position) -
    1.0``) -- a real, finite, points-scale number, so he still ranks below
    every real player at his position (never displaces a genuine starter)
    without dragging the position's margins onto a six-figure scale. Only
    positions with at least one real points-haver get a floor; with none,
    every player at that position (this one included) already falls back
    to raw ``-ecr`` uniformly (the loop above's own comment) -- internally
    consistent without this, so nothing to fix there. Whether an
    unscored, unranked bench arm should count as a HOLE at all is a
    genuine product question this module declines to answer by
    arithmetic accident -- the ECR veto can't rescue him either way (his
    ECR value is the same sentinel it always was, always far below any
    real ECR line), so he stays a hole, same as before the fix: a
    below-replacement starter is the conservative default for a total
    unknown, just reported with a sane number now instead of a fabricated
    one. See ``test_a_pure_sentinel_starter_gets_a_points_scale_floor_not_
    a_six_figure_margin``.
    """
    if points is None:
        return {}

    all_pids: set[str] = set()
    for pids in rosters.values():
        all_pids.update(pids)

    ecr_ranked: dict[str, list[str]] = {}
    points_ranked: dict[str, list[str]] = {}
    for pid in all_pids:
        pos = positions.get(pid)
        if pos is None:
            continue
        if pid in board:
            ecr_ranked.setdefault(pos, []).append(pid)
        if pid in points:
            points_ranked.setdefault(pos, []).append(pid)

    # Sort keys are fully determinate (value, then pid) -- deterministic
    # regardless of `all_pids`' (a set's) build order, same discipline as
    # every other sort in this module.
    for pos, pids in ecr_ranked.items():
        pids.sort(key=lambda pid: (board[pid], pid))
    for pos, pids in points_ranked.items():
        pids.sort(key=lambda pid: (-points[pid], pid))

    result: dict[str, float] = {}
    for pos, ranked in ecr_ranked.items():
        pool = points_ranked.get(pos)
        if not pool:
            # Nobody at this position has points at all -- `_value` will
            # fall back to raw `-ecr` for EVERY player here, including the
            # one(s) that build this position's own replacement line, so
            # the scale stays uniform within the position. Nothing to
            # rank-match against.
            continue
        for idx, pid in enumerate(ranked):
            if pid in points:
                continue  # has his own real points value; not a fallback case
            match_idx = min(idx, len(pool) - 1)
            result[pid] = points[pool[match_idx]]

    # 2026-08-18 fix: a rostered, known-position player with NEITHER points
    # NOR an ECR rank at all (so never a candidate for the rank-match above,
    # which requires a `board` entry) gets a points-space FLOOR instead of
    # falling through to `_value`'s raw ECR-scale sentinel -- see this
    # function's docstring addendum for the full defect and reasoning.
    floor_by_pos = {
        pos: min(points[pid] for pid in pool) - 1.0
        for pos, pool in points_ranked.items()
    }
    for pid in all_pids:
        if pid in result or pid in points or pid in board:
            continue
        pos = positions.get(pid)
        if pos in floor_by_pos:
            result[pid] = floor_by_pos[pos]

    return result


@dataclass
class SlotStanding:
    """One starting slot INSTANCE's standing against the replacement line --
    the ONE keyspace both ``holes`` and "the softest slot" are derived from
    (2026-08-17 keyspace-fix revision; see module docstring)."""

    slot: str        # the slot-instance key, e.g. "RB_2" -- from `_slot_keys`
    position: str     # the occupant's real position, e.g. "RB" -- for display
    # Points vs that position's replacement line; negative = below. `None`
    # -- never a non-finite float -- when there's nothing to compare: no
    # occupant in the slot, or the occupant's slot label has no
    # replacement line at all (a raw FLEX-type label a fallback filler
    # landed in). C1 fix, 2026-08-17: `float("-inf")`/`float("inf")` here
    # used to reach the HTTP response and 500 the whole draft board --
    # Starlette's `JSONResponse.render` uses `allow_nan=False`.
    margin: float | None
    is_hole: bool     # below the line AND not vetoed
    vetoed: bool      # below the line but ECR rates the player above it


@dataclass
class OwnerNeeds:
    """One owner's draft-day picture. Plain dataclass -- the API's wire model
    is the deliberately differently-named ``OwnerNeedsResp`` (Pydantic, Task
    6), which does NOT carry ``starters_by_slot``."""

    user_id: str
    holes: list[str]
    starters_by_slot: dict[str, str | None]
    drafted_into: list[str]
    started: int
    drafted_into_count: int
    slots: list[SlotStanding]
    production: float


def _slot_keys(starter_slots: list[str]) -> list[str]:
    """One dict key per slot OCCURRENCE, preserving ``roster_positions``'
    declared order: the first ``"RB"`` keeps its bare label, the second
    becomes ``"RB_2"``, the third ``"RB_3"``, etc. Needed because a real
    league's ``roster_positions`` repeats slot labels (two RBs, two FLEXes)
    and a plain dict can't hold two values under one key."""
    seen: dict[str, int] = {}
    keys: list[str] = []
    for slot in starter_slots:
        seen[slot] = seen.get(slot, 0) + 1
        keys.append(slot if seen[slot] == 1 else f"{slot}_{seen[slot]}")
    return keys


def _starter_slots(roster_positions: list[str]) -> list[str]:
    """``roster_positions`` with bench slots and K/DEF stripped -- the only
    slots this module ever asks ``solve_optimal_lineup`` to fill."""
    return [
        s for s in roster_positions
        if s not in BENCH_SLOTS and s not in EXCLUDED_SLOTS
    ]


def _direct_demand(starter_slots: list[str], num_owners: int) -> dict[str, int]:
    """Leaguewide replacement-line demand for each single-position slot
    label -- that label's own direct starting-slot count in
    ``roster_positions``, times the number of owners in the league. Frozen,
    never inflated by which real position happens to win a FLEX-type slot
    in a given season (position-room-model spec, 2026-08-18): "nobody
    drafts a FLEX." A slot label is FLEX-type when its ``SLOT_ELIGIBILITY``
    spans more than one position -- those labels contribute no demand of
    their own; whichever real position fills one still counts toward THAT
    position's own line, PROVIDED that position has a direct slot at all
    (Pass 3 checks the occupant's real position, never the raw slot label
    -- unaffected by this function).

    EDGE CASE (final-review Finding 4, 2026-08-18, docstring-only --
    deliberate, not a bug): if ``roster_positions`` has NO direct
    single-position slot for some FLEX-eligible position whatsoever (e.g. a
    league whose only path to TE is a FLEX slot, no bare ``"TE"`` slot
    anywhere), that position gets NO entry here at all -- not a zero, an
    absence. It then gets no entry in ``lines``/``ecr_lines`` either
    (``_nth_best`` only iterates ``demand.items()``), so every occupant of
    that position -- via FLEX or the position-unmapped fallback, however he
    got a starting slot -- reads ``margin=None``/``is_hole=False`` in Pass
    3, regardless of how strong or weak he is. No line, no verdict: this is
    the module's deliberate safe-failure direction (silence over a false
    verdict, the same principle the empty-slot handling above already
    follows), not a gap to close by inventing a line. See
    ``test_flex_only_position_with_no_direct_slot_gets_no_line_at_all`` in
    ``tests/test_draft_needs.py`` for the pinned regression."""
    per_owner: dict[str, int] = {}
    for slot in starter_slots:
        eligible = SLOT_ELIGIBILITY.get(slot, set())
        if len(eligible) != 1:
            continue
        per_owner[slot] = per_owner.get(slot, 0) + 1
    return {label: count * num_owners for label, count in per_owner.items()}


def _solve_owner(
    pids: set[str],
    positions: dict[str, str],
    board: dict[str, float],
    points: dict[str, float] | None,
    rank_points: dict[str, float],
    starter_slots: list[str],
    keys: list[str],
) -> tuple[dict[str, str | None], list[tuple[str, str, float | None, str]]]:
    """This owner's slot-by-slot starters, using real per-player positions.

    Returns ``(starters_by_slot, slot_checks)``. ``slot_checks`` is one
    entry per starting-slot INSTANCE (same granularity as ``keys`` /
    ``starters_by_slot``): ``(key, label, value, source)`` where

    - ``source == "known"``: a starter whose real position is known --
      ``label`` is that real position. These are the only entries that
      count toward a position's demand and get checked against that
      position's own line.
    - ``source == "fallback"``: a slot filled by a position-unmapped player
      (see module docstring) -- ``label`` is the raw slot label, checked
      (if at all) against whatever line already exists for it.
    - ``source == "empty"``: nobody -- known or unmapped -- was left to
      fill this slot. ``value`` is ``None``. ``label`` is the raw slot
      label; a hole (infinite severity) only when it names a single real
      position -- see the ``build_draft_needs`` caller for why a FLEX-type
      empty slot is excluded from ``holes``.
    """
    starters_by_slot: dict[str, str | None] = {k: None for k in keys}
    if not starter_slots:
        return starters_by_slot, []

    # `pids` is a set -- iteration order is hash-seed-dependent, and ties on
    # value are the COMMON case here (every board-unranked player shares
    # UNRANKED_ECR_SENTINEL), so building this from raw set order would make
    # solve_optimal_lineup's stable tie-break arbitrary across processes.
    # sorted(pids) fixes the input order the dict (and everything derived
    # from it below) sees.
    known_map = {
        pid: (positions[pid], _value(pid, board, points, rank_points))
        for pid in sorted(pids) if pid in positions
    }
    # trap 2: discard the returned total, matching outlook.py:124. One call
    # over the whole owner roster with real positions -- SLOT_ELIGIBILITY
    # does genuine cross-position exclusion here.
    starters, _ = solve_optimal_lineup(starter_slots, known_map)

    # solve_optimal_lineup returns only the flat winning SET -- no per-slot
    # detail. Relabel: identical restrictiveness order, greedy
    # best-value-first, but the candidate pool is now exactly `starters`
    # (who solve_optimal_lineup already chose), so this can never fail to
    # place someone it already picked -- it's relabeling, not re-deciding.
    order = sorted(
        range(len(starter_slots)),
        key=lambda i: len(SLOT_ELIGIBILITY.get(starter_slots[i], set())),
    )
    pool = set(starters)
    slot_checks: list[tuple[str, str, float | None, str]] = []
    unfilled_idx: list[int] = []
    for i in order:
        slot = starter_slots[i]
        eligible = SLOT_ELIGIBILITY.get(slot, set())
        candidates = sorted(
            (pid for pid in pool if known_map[pid][0] in eligible),
            key=lambda pid: (-known_map[pid][1], pid),
        )
        if candidates:
            pid = candidates[0]
            starters_by_slot[keys[i]] = pid
            pool.discard(pid)
            pos, value = known_map[pid]
            slot_checks.append((keys[i], pos, value, "known"))
        else:
            unfilled_idx.append(i)

    # Fallback for a position-unmapped rostered player (module docstring):
    # not run through SLOT_ELIGIBILITY (we don't know his true position),
    # so he only ever claims a slot no known-position player could fill.
    unmapped_pool = sorted(
        (pid for pid in pids if pid not in positions),
        key=lambda pid: (-_value(pid, board, points, rank_points), pid),
    )
    for i in unfilled_idx:
        slot = starter_slots[i]
        if unmapped_pool:
            pid = unmapped_pool.pop(0)
            starters_by_slot[keys[i]] = pid
            value = _value(pid, board, points, rank_points)
            slot_checks.append((keys[i], slot, value, "fallback"))
        else:
            slot_checks.append((keys[i], slot, None, "empty"))

    return starters_by_slot, slot_checks


def _dedupe_holes(hole_instances: list[tuple[str, float]]) -> list[str]:
    """One entry per distinct slot LABEL (a second hole RB slot doesn't
    print "RB" twice), sorted most-severe first using the WORST (most
    negative) margin seen for that label. ``hole_instances`` carries
    margins (points below the line, negative) rather than the old positive
    "severity" -- ascending-by-margin
    sorts identically to the old descending-by-severity, since severity
    was always ``-margin``."""
    worst: dict[str, float] = {}
    for label, margin in hole_instances:
        if label not in worst or margin < worst[label]:
            worst[label] = margin
    return [label for label, _ in sorted(worst.items(), key=lambda kv: kv[1])]


def build_draft_needs(
    rosters: dict[str, set[str]],
    board: dict[str, float],
    positions: dict[str, str],
    roster_positions: list[str],
    picks_by_owner: dict[str, list[tuple[str, str]]],
    started_by_pick: dict[str, int],
    *,
    points: dict[str, float] | None = None,
    production_by_pick: dict[str, float] | None = None,
) -> list[OwnerNeeds]:
    """One ``OwnerNeeds`` per owner in ``rosters``.

    ``positions``: player_id -> fantasy position (e.g. "QB", "RB"), sourced
    from the Sleeper player catalog. ``picks_by_owner``: owner_user_id ->
    [(player_id, position), ...] for that owner's picks in the draft class
    being graded. ``started_by_pick``: player_id -> games started
    (``draft_results.py::started_games_while_on_roster``), owner-gated and
    already correct about a player traded away mid-season. ``points``:
    player_id -> prior-season points in this league's own scoring --
    optional, defaults to ``None``, which falls back entirely to the
    pre-revision ECR-only line (module docstring's "Revision" section).

    Verdict 1 (``drafted_into``): the pick's POSITION matches an open hole
    INSTANCE for this owner, capacity-capped -- position-room-model fix,
    2026-08-18. Picks are walked in draft order and each position's hole
    count (from ``hole_instances``, one entry per ``is_hole=True`` slot) is
    consumed as picks credit against it; a pick at a position whose hole
    capacity is already exhausted earns no credit, so N picks can never
    over-credit a single hole slot. Verdict 2 (``started``): of the CREDITED
    picks, how many ever recorded a start (``games_started > 0``).
    Verdict 3 (``production``): the combined production of the CREDITED picks
    (the same set Verdict 2 checks), regardless of whether they ever started --
    a real number, including a real ``0.0``, summed from ``production_by_pick``
    (already computed once per pick by the caller; this function does no new
    computation). All three are display-only and must never feed Franchise
    Rating -- needs is inferred, not measured.
    """
    starter_slots = _starter_slots(roster_positions)
    keys = _slot_keys(starter_slots)
    _production_by_pick = production_by_pick or {}

    # I2 fix (2026-08-17): computed once for the whole league, before either
    # pass below -- both the per-owner solve and the position-line tally
    # must value a no-points-but-ECR'd player identically, or the line and
    # the players checked against it would silently disagree on his worth.
    # See `_rank_matched_points`'s own docstring for the full mechanism.
    rank_points = _rank_matched_points(rosters, board, positions, points)

    # Pass 1: demand is now structural -- see `_direct_demand`'s docstring
    # -- computed once, before any owner is solved. Solve every owner's
    # lineup (position-correct via SLOT_ELIGIBILITY, valued by points when
    # present -- rule 1) purely to get each owner's `starters_by_slot` /
    # `slot_checks` for Pass 3; the solve no longer feeds demand.
    demand = _direct_demand(starter_slots, len(rosters))

    per_owner: dict[str, tuple[dict[str, str | None], list]] = {}
    for uid, pids in rosters.items():
        starters_by_slot, slot_checks = _solve_owner(
            pids, positions, board, points, rank_points, starter_slots, keys
        )
        per_owner[uid] = (starters_by_slot, slot_checks)

    # Pass 2: per-position replacement line, from the league's own
    # reconstructed rosters -- the Nth-best player AT THAT POSITION, N being
    # the position's own leaguewide demand from pass 1. Two parallel lines,
    # same Nth-best mechanism, two different value spaces:
    # `lines` (points-priority via `_value`, rule 2) decides who's below
    # replacement; `ecr_lines` (pure ECR via `_ecr_value`, rule 3) is
    # consulted ONLY by the veto below. When `points` is None both value
    # functions degenerate to the same ECR-inverted number, so `ecr_lines`
    # can never rescue a player the (then-identical) `lines` already
    # flagged -- the veto is a mathematical no-op on the pre-revision path.
    all_by_position: dict[str, list[float]] = {}
    all_ecr_by_position: dict[str, list[float]] = {}
    for pids in rosters.values():
        for pid in pids:
            pos = positions.get(pid)
            if pos is None:
                continue
            all_by_position.setdefault(pos, []).append(
                _value(pid, board, points, rank_points)
            )
            all_ecr_by_position.setdefault(pos, []).append(
                _ecr_value(pid, board)
            )

    def _nth_best(pool_by_position: dict[str, list[float]]) -> dict[str, float]:
        result: dict[str, float] = {}
        for pos, n in demand.items():
            pool_sorted = sorted(pool_by_position.get(pos, []), reverse=True)
            if n <= 0 or not pool_sorted:
                result[pos] = float("-inf")
            else:
                idx = min(n, len(pool_sorted)) - 1
                result[pos] = pool_sorted[idx]
        return result

    lines = _nth_best(all_by_position)
    ecr_lines = _nth_best(all_ecr_by_position)

    # Pass 3: check each owner's actual starters (known-position, fallback,
    # and empty) against the lines just computed, building one `SlotStanding`
    # per starting-slot INSTANCE -- the one keyspace `holes` and "the softest
    # slot" both derive from (keyspace-fix revision, module docstring). A
    # hole is subject to the ECR veto (rule 3); an empty slot can never be
    # vetoed (there's no player to check ECR against).
    needs: list[OwnerNeeds] = []
    for uid in rosters:
        starters_by_slot, slot_checks = per_owner[uid]
        standings_by_key: dict[str, SlotStanding] = {}
        hole_instances: list[tuple[str, float]] = []

        for key, label, value, source in slot_checks:
            if source == "empty":
                # No occupant in the slot: there is nobody to compare
                # against a replacement line, so this is NOT "infinitely
                # below replacement" -- it's a real value's absence.
                # `margin=None` renders as an empty slot; `is_hole=False`
                # because whether an unfillable slot should count as a hole
                # is a product question this arithmetic must not decide by
                # accident. C1 fix, 2026-08-17: the prior `float("-inf")`
                # sentinel reached `SlotStandingResp.margin` on the wire and
                # 500'd the whole draft board (Starlette's
                # `JSONResponse.render` uses `allow_nan=False`) -- and, since
                # `-inf` always wins a `min(slots, key=lambda s: s.margin)`
                # read, it also always "won" the softest-slot display.
                standings_by_key[key] = SlotStanding(
                    slot=key, position=label, margin=None,
                    is_hole=False, vetoed=False,
                )
                continue

            line = lines.get(label)
            assert value is not None  # filled slot: known or fallback
            if line is None or not math.isfinite(line):
                # No replacement line exists for this label -- a raw
                # FLEX-type slot label a fallback filler landed in (never
                # counted into `demand`, so never in `lines`), or
                # (defensively) a real position with no rostered pool at
                # all. Nothing to compare `value` against: computing
                # `value - float("-inf")` here is the SECOND non-finite-
                # margin path C1 closed (it renders as `+inf`, not `-inf`).
                standings_by_key[key] = SlotStanding(
                    slot=key, position=label, margin=None,
                    is_hole=False, vetoed=False,
                )
                continue

            margin = value - line
            is_hole = False
            vetoed = False
            if value < line:
                # Points-hole candidate (rule 3's veto, ECR axis only --
                # see `_ecr_value`'s docstring for why it never reads
                # `points`): not a hole if the market rates this player
                # above ITS OWN, separately-computed, ECR line.
                pid = starters_by_slot[key]
                assert pid is not None
                ecr_val = _ecr_value(pid, board)
                ecr_line = ecr_lines.get(label, float("-inf"))
                if ecr_val > ecr_line:
                    vetoed = True
                else:
                    is_hole = True
                    hole_instances.append((label, margin))
            standings_by_key[key] = SlotStanding(
                slot=key, position=label, margin=margin,
                is_hole=is_hole, vetoed=vetoed,
            )

        # `keys` preserves `roster_positions`' declared order (from
        # `_slot_keys` at the top of this function) -- `slots` follows it so
        # the panel can render row-for-row without re-sorting, and two
        # owners' rows line up.
        slots = [standings_by_key[k] for k in keys]
        holes = _dedupe_holes(hole_instances)

        # Capacity-capped, not membership-checked (position-room-model
        # fix, 2026-08-18): `pos in holes` used to credit EVERY pick at a
        # hole position, so N picks at a position with exactly one hole
        # SLOT all counted as "drafted into" it -- the waterboyboucher case
        # (one marginal FLEX hole, four unrelated WR picks all credited).
        # `hole_instances` (built above, one entry per is_hole=True SLOT
        # instance) gives each position label its true capacity; picks are
        # walked in DRAFT order (the order the owner actually made them)
        # and each position's capacity decrements as picks consume it --
        # once a position's holes are all credited, a further pick at that
        # position earns no credit, same as a real hole that's already
        # been filled.
        picks = picks_by_owner.get(uid, [])
        hole_capacity: dict[str, int] = {}
        for label, _margin in hole_instances:
            hole_capacity[label] = hole_capacity.get(label, 0) + 1

        drafted_into: list[str] = []
        started = 0
        production = 0.0
        for pid, pos in picks:
            if hole_capacity.get(pos, 0) <= 0:
                continue
            hole_capacity[pos] -= 1
            drafted_into.append(pos)
            if started_by_pick.get(pid, 0) > 0:
                started += 1
            production += _production_by_pick.get(pid, 0.0)

        needs.append(OwnerNeeds(
            user_id=uid,
            holes=holes,
            starters_by_slot=starters_by_slot,
            drafted_into=drafted_into,
            started=started,
            drafted_into_count=len(drafted_into),
            slots=slots,
            production=production,
        ))
    return needs
