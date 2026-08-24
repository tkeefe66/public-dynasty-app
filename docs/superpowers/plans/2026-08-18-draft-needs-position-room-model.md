# Draft Needs — Position-Room Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `engine/draft_needs.py`'s replacement-line demand so it is never inflated by FLEX
occupancy, add K as a scoreable position for "Holes going in" (DEF stays excluded), fix
`drafted_into`/`started` so a pick only credits an open hole instance once (not every pick at that
position), and disambiguate the "Going in" panel's rendering so a reader never has to parse prose
to tell a real hole from the no-holes fallback, or "no holes existed" from "holes existed and
nothing addressed them."

**Architecture:** Two independent surfaces, no shared interface change. (1) `engine/draft_needs.py`
gets a structural demand model (`_direct_demand`, keyed off `roster_positions` × owner count, never
off solved-lineup FLEX occupancy) plus a capacity-capped `drafted_into`/`started` computation. Its
public output shape (`OwnerNeeds`/`SlotStanding`) is unchanged, so nothing downstream of it —
`grader.py`'s dict-comprehension caching, `ChainCacheEntry.draft_needs`, `OwnerNeedsResp`/
`SlotStandingResp`, `draft_board_view.py` — needs to change at all. (2) `web/components/
DraftGoingIn.tsx` gets a `{ text, dim }` reading shape for all three cells (Holes / Drafted into /
Started), replacing today's plain-string renderers, so a real hole reads in full ink and a "nothing
to report" reading (no holes, softest-slot fallback, or holes-but-nothing-addressed) reads dim —
using `text-dim`, the same neutral tone `Meta`'s own `tone="dim"` already uses elsewhere on this
board, never a `-pos`/`-neg` tone.

**Tech Stack:** Python (engine, pytest), TypeScript/React (Next.js, vitest + testing-library).

**Spec:** `docs/superpowers/specs/2026-08-18-draft-needs-position-room-model.md` (depends on
`docs/superpowers/specs/2026-08-17-draft-needs-phase5-design.md`, both the original design and its
2026-08-17 revision).

## Global Constraints

- No colour on any verdict in `DraftGoingIn.tsx` — never a `-pos`/`-neg` tone class. `text-dim` (or
  `Meta`'s `tone="dim"`) is the only styling distinction allowed, matching the file's existing rule
  4 and the codebase-wide convention (`Meta`'s own docstring: "dim is a real tone, not the absence
  of one").
- `draft_needs` output is display-only and must never feed Franchise Rating — unaffected by this
  plan, restated because every task in this plan touches the module that computes it.
- No `ChainCacheEntry.draft_needs` schema change, no `SCHEMA_VERSION` bump — this plan changes
  values, not shapes. `OwnerNeeds`/`SlotStanding` (engine) and `OwnerNeedsResp`/`SlotStandingResp`
  (API) keep their existing fields.
- K gains a replacement line and can appear in `holes`, but is deliberately **not** given any
  special-case in the `drafted_into`/`started` computation — a rookie draft essentially never picks
  a kicker (measured: zero in the reference league's 2026 class), so it will read `—`/absent there
  by construction, not by a carve-out. Do not add K-specific branching to Task 3.
- DEF stays excluded. Widening it is out of scope for this plan (not decided in the spec).

---

## File Structure

- **Modify:** `src/sleeper_dynasty/engine/draft_needs.py` — demand computation, `EXCLUDED_SLOTS`,
  `drafted_into`/`started` computation, module + inline docstrings.
- **Modify:** `tests/test_draft_needs.py` — replace/add tests for the above.
- **Modify:** `web/components/DraftGoingIn.tsx` — `{ text, dim }` reading shape for all three
  cells, replacing `goingInText`/`PositionList`/`startedText`.
- **Modify:** `web/tests/DraftGoingIn.test.tsx` — replace/add tests for the above.

No new files. No API, Pydantic, TypeScript-type, or cache-layer changes — see Global Constraints.

---

### Task 1: Freeze replacement-line demand at direct-slot counts

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_needs.py`
- Test: `tests/test_draft_needs.py`

**Interfaces:**
- Consumes: `SLOT_ELIGIBILITY` (`engine/lineup.py`, unchanged) — a slot label is "FLEX-type" when
  `len(SLOT_ELIGIBILITY.get(label, set())) != 1`.
- Produces: `_direct_demand(starter_slots: list[str], num_owners: int) -> dict[str, int]`, called
  once per `build_draft_needs` invocation, replacing the old per-owner FLEX-inflated tally. Task 2
  and Task 3 both build on this function's presence but do not change its signature.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_draft_needs.py`, replacing the existing
`test_a_flex_start_counts_toward_its_own_positions_line_not_flexs` function (its fixture's expected
values were computed under the old FLEX-inflated demand model and are no longer correct — this new
test supersedes it, keeping the same underlying invariant: a FLEX occupant is checked against its
own real position's line):

```python
def test_demand_is_frozen_at_direct_slot_count_not_flex_inflated():
    """Position-room-model fix (2026-08-18): FLEX occupancy used to feed
    back into a position's demand tally (an RB started in FLEX counted as
    ANOTHER RB start leaguewide), diluting the replacement line for every
    owner who never put that position in FLEX at all -- the ChocGummyBear
    case from the spec (a real RB2 read as 'no hole' because other owners'
    FLEX choices inflated the RB line's depth). Demand is now the
    position's own direct starting-slot count x owner count, full stop --
    nobody drafts a FLEX.

    2 owners, roster = 1 direct RB slot + 1 FLEX (RB-only pool, so FLEX
    always resolves to an RB). Old model: demand['RB'] = 4 (2 owners x 2 RB
    starts each, FLEX included) -> line = 4th-best = 10.0 (rb2b's own
    value) -> u2's rb2b(10.0) sits exactly ON the line it helped define,
    no hole. New model: demand['RB'] = 2 (2 owners x 1 DIRECT RB slot) ->
    line = 2nd-best = 90.0 (rb1b's value) -> u2's whole roster (50.0, 10.0)
    sits well below it -- both a real hole. This also proves the FLEX
    occupant is still checked against its own real position's (RB) line,
    not a nonexistent 'FLEX' line -- u2's FLEX slot (rb2b) is flagged a
    hole exactly like its RB slot."""
    rosters = {"u1": {"rb1a", "rb1b"}, "u2": {"rb2a", "rb2b"}}
    points = {"rb1a": 100.0, "rb1b": 90.0, "rb2a": 50.0, "rb2b": 10.0}
    positions = {p: "RB" for p in points}
    needs = build_draft_needs(
        rosters, {}, positions, ["RB", "FLEX", "BN"], {}, {}, points=points
    )
    u1 = _by_owner(needs, "u1")
    u2 = _by_owner(needs, "u2")
    assert u1.starters_by_slot["RB"] == "rb1a"
    assert u1.starters_by_slot["FLEX"] == "rb1b"
    assert u1.holes == []
    assert u2.starters_by_slot["RB"] == "rb2a"
    assert u2.starters_by_slot["FLEX"] == "rb2b"
    assert u2.holes == ["RB"]
    for s in u2.slots:
        assert s.is_hole is True
        assert s.margin is not None and s.margin < 0
```

Delete `test_a_flex_start_counts_toward_its_own_positions_line_not_flexs` (the old test) in the same
edit — its fixture and assertions are specific to the FLEX-inflated demand model this task removes.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_draft_needs.py::test_demand_is_frozen_at_direct_slot_count_not_flex_inflated -v`
Expected: FAIL — `u2.holes` comes back `[]` under the current FLEX-inflated demand (line lands on
10.0, rb2b's own value, not below it).

- [ ] **Step 3: Implement `_direct_demand` and wire it in**

In `src/sleeper_dynasty/engine/draft_needs.py`, add the new function directly above
`_solve_owner` (after `_starter_slots`):

```python
def _direct_demand(starter_slots: list[str], num_owners: int) -> dict[str, int]:
    """Leaguewide replacement-line demand for each single-position slot
    label -- that label's own direct starting-slot count in
    ``roster_positions``, times the number of owners in the league. Frozen,
    never inflated by which real position happens to win a FLEX-type slot
    in a given season (position-room-model spec, 2026-08-18): "nobody
    drafts a FLEX." A slot label is FLEX-type when its ``SLOT_ELIGIBILITY``
    spans more than one position -- those labels contribute no demand of
    their own; whichever real position fills one still counts toward THAT
    position's own line (Pass 3 checks the occupant's real position, never
    the raw slot label -- unaffected by this function)."""
    per_owner: dict[str, int] = {}
    for slot in starter_slots:
        eligible = SLOT_ELIGIBILITY.get(slot, set())
        if len(eligible) != 1:
            continue
        per_owner[slot] = per_owner.get(slot, 0) + 1
    return {label: count * num_owners for label, count in per_owner.items()}
```

Replace the Pass 1 block inside `build_draft_needs`:

```python
    per_owner: dict[str, tuple[dict[str, str | None], list]] = {}
    demand: dict[str, int] = {}
    for uid, pids in rosters.items():
        starters_by_slot, slot_checks = _solve_owner(
            pids, positions, board, points, rank_points, starter_slots, keys
        )
        per_owner[uid] = (starters_by_slot, slot_checks)
        for _key, label, _unused_value, source in slot_checks:
            if source == "known":
                demand[label] = demand.get(label, 0) + 1
```

with:

```python
    demand = _direct_demand(starter_slots, len(rosters))

    per_owner: dict[str, tuple[dict[str, str | None], list]] = {}
    for uid, pids in rosters.items():
        starters_by_slot, slot_checks = _solve_owner(
            pids, positions, board, points, rank_points, starter_slots, keys
        )
        per_owner[uid] = (starters_by_slot, slot_checks)
```

Update the comment immediately above (currently "Pass 1: solve every owner's lineup ... FLEX
demand lands on whichever position empirically filled it, never on 'FLEX' itself...") to:

```python
    # Pass 1: demand is now structural -- see `_direct_demand`'s docstring
    # -- computed once, before any owner is solved. Solve every owner's
    # lineup (position-correct via SLOT_ELIGIBILITY, valued by points when
    # present -- rule 1) purely to get each owner's `starters_by_slot` /
    # `slot_checks` for Pass 3; the solve no longer feeds demand.
```

Update the module docstring's "Real per-player position, threaded through explicitly" paragraph
(the two sentences describing the old FLEX tally):

Replace:
```
FLEX-eligible slot has no line of its own: whichever real position actually
fills it (empirically, from each owner's own solved lineup, across the
whole league) has that start counted toward *that position's* demand and
compared against *that position's* line -- "a FLEX-eligible position counts
toward its own line, not FLEX's." Two passes follow from this: first solve
every owner's lineup and tally, per real position, how many league-wide
starts it actually filled (whether from a direct slot or a FLEX slot);
second, for each position, the line is the value of the Nth-best player
*at that position* across every reconstructed roster, N being that tally.
```

With:
```
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
```

- [ ] **Step 4: Run the full engine test file**

Run: `pytest tests/test_draft_needs.py -v`
Expected: PASS — all tests, including the new one and every pre-existing test whose fixtures never
routed a position through FLEX (verified during planning: none of the other fixtures depend on the
FLEX-tally behavior this task removes, since demand for a non-FLEX-eligible position, or a
FLEX-free roster shape, is numerically identical under both models).

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_needs.py tests/test_draft_needs.py
git commit -m "fix(engine): freeze draft-needs replacement-line demand at direct-slot counts"
```

---

### Task 2: Include K in "Holes going in" (DEF stays excluded)

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_needs.py`
- Test: `tests/test_draft_needs.py`

**Interfaces:**
- Consumes: `_direct_demand` (Task 1) — no change needed; K's demand falls out automatically once
  it's no longer stripped by `EXCLUDED_SLOTS` (`SLOT_ELIGIBILITY["K"] = {"K"}` is already a
  singleton in `engine/lineup.py`).
- Produces: no new public interface. `holes`/`slots` can now contain `"K"` entries.

- [ ] **Step 1: Write the failing tests**

Replace `test_k_and_def_slots_never_become_holes` in `tests/test_draft_needs.py` with two tests:

```python
def test_def_slot_never_becomes_a_hole():
    """DEF stays excluded post-K-inclusion (position-room-model spec,
    2026-08-18): dynasty-overall ECR doesn't meaningfully rank it, it's
    streamed weekly, and no rookie draft addresses it -- unchanged from
    the original K+DEF exclusion, now DEF-only. Not stripping it gives
    every owner a permanent phantom hole (empty slot, no players in the
    value map, always below any line)."""
    rosters = {"u1": {"qb1"}}
    positions = {"qb1": "QB"}
    needs = build_draft_needs(
        rosters, {"qb1": 1.0}, positions, ["QB", "DEF"], {}, {}
    )
    assert "DEF" not in needs[0].holes
    assert len(needs[0].slots) == 1, "DEF is stripped entirely, not just excluded from holes"


def test_k_slot_can_become_a_hole_under_the_league_line():
    """Position-room-model spec, 2026-08-18: K is no longer wholesale
    excluded -- kicker points are real (Sleeper scores K normally), and a
    thin K room is real diagnostic signal even though a rookie draft
    essentially never addresses it (see the spec's 'Decision: include K,
    scoped correctly'). `depth_k` is bench-only pool depth for u3 so the
    line isn't self-referential to the two owners actually being checked
    -- same discipline as every other demand-sensitive fixture in this
    file. direct demand for K = 1 slot/owner x 3 owners = 3; pool sorted
    descending [100(strong_k), 50(mid_k), 40(depth_k), 10(weak_k)] -> the
    3rd-best (line) = 40.0. weak_k (10.0) sits 30 below it -- a real hole.
    The ECR veto is a structural no-op here (deliberately no `board`
    entries -- dynasty-overall ECR doesn't rank kickers at all, so every K
    ties at the sentinel and nothing outranks anything)."""
    rosters = {
        "u1": {"qb1", "weak_k"},
        "u2": {"qb2", "strong_k"},
        "u3": {"qb3", "mid_k", "depth_k"},
    }
    points = {
        "qb1": 1.0, "qb2": 1.0, "qb3": 1.0,
        "weak_k": 10.0, "strong_k": 100.0, "mid_k": 50.0, "depth_k": 40.0,
    }
    positions = {
        "qb1": "QB", "qb2": "QB", "qb3": "QB",
        "weak_k": "K", "strong_k": "K", "mid_k": "K", "depth_k": "K",
    }
    needs = build_draft_needs(
        rosters, {}, positions, ["QB", "K", "BN"], {}, {}, points=points
    )
    u1 = _by_owner(needs, "u1")
    u2 = _by_owner(needs, "u2")
    u3 = _by_owner(needs, "u3")
    assert u1.holes == ["K"]
    k_slot = next(s for s in u1.slots if s.position == "K")
    assert k_slot.margin == -30.0
    assert k_slot.is_hole is True
    assert k_slot.vetoed is False
    assert u2.holes == []
    assert u3.starters_by_slot["K"] == "mid_k"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_draft_needs.py::test_def_slot_never_becomes_a_hole tests/test_draft_needs.py::test_k_slot_can_become_a_hole_under_the_league_line -v`
Expected: `test_def_slot_never_becomes_a_hole` PASSES already (DEF exclusion is pre-existing
behavior — this just confirms it survives the coming change before making it).
`test_k_slot_can_become_a_hole_under_the_league_line` FAILS: `u1.holes == []` today (K is stripped
by `EXCLUDED_SLOTS` before any solve happens, so `needs[0].slots` has no K entry and
`next(s for s in u1.slots if s.position == "K")` raises `StopIteration`).

- [ ] **Step 3: Remove K from `EXCLUDED_SLOTS`**

In `src/sleeper_dynasty/engine/draft_needs.py`, replace:

```python
# K/DEF are excluded from hole-hunting: dynasty-overall ECR does not
# meaningfully rank them, they're streamed off the wire week to week, and no
# rookie draft addresses them. Left in `roster_positions` unstripped before
# the solve, they'd come back permanently empty (no K/DEF players in the
# value map) -- and an empty slot is trivially below any replacement line,
# manufacturing two phantom holes for every owner every time.
EXCLUDED_SLOTS: set[str] = {"K", "DEF"}
```

with:

```python
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
# in the reference league's 2026 class), so those columns read empty for
# K by construction, not by a carve-out; see the gating discussion in the
# spec's "Decision: do not expect ... K ever populating 'Drafted into' /
# 'Started'".
EXCLUDED_SLOTS: set[str] = {"DEF"}
```

- [ ] **Step 4: Run the full engine test file**

Run: `pytest tests/test_draft_needs.py -v`
Expected: PASS — all tests, including both new ones.

- [ ] **Step 5: Run the broader engine + API suite for incidental breakage**

Run: `pytest tests/ -v` and `pytest api/tests/ -v` (per this repo's `pytest tests/` vs bare `pytest`
gotcha in `CLAUDE.md` — run them as two separate invocations, never bare `pytest` from root).
Expected: PASS. If any API-layer test (e.g. `api/tests/test_grader_service.py`'s draft-needs tests)
constructs a fixture whose expected `holes`/`slots` assumed K was always stripped, update that
fixture's expectations to match the new K-inclusive behavior — do not special-case K in production
code to make an old fixture pass unchanged; the fixture encoded the old (now-incorrect) exclusion.

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_needs.py tests/test_draft_needs.py
git commit -m "feat(engine): include K in draft-needs hole detection, DEF stays excluded"
```

(If Step 5 required fixture updates in `api/tests/`, add those files to this commit too.)

---

### Task 3: Cap `drafted_into`/`started` credit at the number of open hole instances

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_needs.py`
- Test: `tests/test_draft_needs.py`

**Interfaces:**
- Consumes: `hole_instances: list[tuple[str, float]]` — already built in Pass 3 (unchanged by this
  task), one `(position_label, margin)` entry per `is_hole=True` slot instance.
- Produces: no interface change — `OwnerNeeds.drafted_into`/`.started`/`.drafted_into_count` keep
  their existing types; only their computed values change for owners with more picks at a hole
  position than there were open hole instances at that position.

- [ ] **Step 1: Write the failing tests**

In `tests/test_draft_needs.py`, replace `test_started_counts_only_picks_with_a_recorded_start` with
two tests (the old test's fixture had exactly one hole instance but two picks crediting it, which is
precisely the over-counting bug this task fixes — its assertions, `drafted_into_count == 2` and
`started == 1`, encoded the bug and must change):

```python
def test_drafted_into_credit_is_capped_by_the_number_of_hole_instances():
    """Position-room-model fix (2026-08-18): a pick's position matching an
    open hole's LABEL used to credit unconditionally, so N picks at a
    position with exactly one hole slot all counted as 'drafted into' it --
    the waterboyboucher case from the spec (one -0.08 FLEX WR hole, four WR
    picks all credited), which reads as 'drafted four WRs, none of which
    ever helped' when the real gap is a single marginal slot.

    Two owners, one with a single RB hole (one starting RB slot, below the
    line) and two RB picks: the first pick credits and consumes the only
    hole slot; the second, identical-position pick has no capacity left
    and must NOT count."""
    rosters = {"u1": {"rb_bad"}, "u2": {"rb_good1", "rb_good2"}}
    points = {"rb_bad": 10.0, "rb_good1": 200.0, "rb_good2": 190.0}
    positions = {p: "RB" for p in points}
    picks_by_owner = {"u1": [("first_rb", "RB"), ("second_rb", "RB")]}
    needs = build_draft_needs(
        rosters, {}, positions, ["RB", "BN"], picks_by_owner, {}, points=points
    )
    u1 = _by_owner(needs, "u1")
    assert u1.holes == ["RB"]
    assert u1.drafted_into == ["RB"]
    assert u1.drafted_into_count == 1, (
        "only ONE RB starting slot was a hole -- only one pick can address it"
    )


def test_started_counts_only_the_credited_picks_with_a_recorded_start():
    """Started still gates on games_started > 0 -- verified under the
    capacity-capped model (two starting QB slots, both holes, so both of
    u1's two QB picks are legitimately credited; only one ever started)."""
    rosters = {
        "u1": {"qb_u1a", "qb_u1b"},
        "u2": {"qb_a", "qb_b", "qb_c", "qb_d"},
    }
    points = {
        "qb_u1a": 10.0, "qb_u1b": 9.0,
        "qb_a": 200.0, "qb_b": 190.0, "qb_c": 180.0, "qb_d": 170.0,
    }
    positions = {p: "QB" for p in points}
    picks_by_owner = {"u1": [("bench_qb", "QB"), ("started_qb", "QB")]}
    started_by_pick = {"bench_qb": 0, "started_qb": 5}
    needs = build_draft_needs(
        rosters, {}, positions, ["QB", "QB", "BN"], picks_by_owner,
        started_by_pick, points=points,
    )
    u1 = _by_owner(needs, "u1")
    assert u1.drafted_into_count == 2
    assert u1.started == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_draft_needs.py::test_drafted_into_credit_is_capped_by_the_number_of_hole_instances -v`
Expected: FAIL — `u1.drafted_into_count == 2` today (both RB picks credit the single RB hole label
unconditionally).

- [ ] **Step 3: Cap the credit in `build_draft_needs`**

In `src/sleeper_dynasty/engine/draft_needs.py`, replace the current tail of the per-owner loop:

```python
        picks = picks_by_owner.get(uid, [])
        drafted_into = [pos for _pid, pos in picks if pos in holes]
        started = sum(
            1 for pid, pos in picks
            if pos in holes and started_by_pick.get(pid, 0) > 0
        )
```

with:

```python
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
        for pid, pos in picks:
            if hole_capacity.get(pos, 0) <= 0:
                continue
            hole_capacity[pos] -= 1
            drafted_into.append(pos)
            if started_by_pick.get(pid, 0) > 0:
                started += 1
```

Update `build_draft_needs`'s own docstring paragraph describing Verdict 1 (currently: "the pick's
POSITION matches a position that was an open hole for this owner"). Replace:

```
Verdict 1 (``drafted_into``): the pick's POSITION matches a position that
was an open hole for this owner. Verdict 2 (``started``): of those, how
many ever recorded a start (``games_started > 0``). Both are display-only
and must never feed Franchise Rating -- needs is inferred, not measured.
```

with:

```
Verdict 1 (``drafted_into``): the pick's POSITION matches an open hole
INSTANCE for this owner, capacity-capped -- position-room-model fix,
2026-08-18. Picks are walked in draft order and each position's hole
count (from ``hole_instances``, one entry per ``is_hole=True`` slot) is
consumed as picks credit against it; a pick at a position whose hole
capacity is already exhausted earns no credit, so N picks can never
over-credit a single hole slot. Verdict 2 (``started``): of the CREDITED
picks, how many ever recorded a start (``games_started > 0``). Both are
display-only and must never feed Franchise Rating -- needs is inferred,
not measured.
```

- [ ] **Step 4: Run the full engine test file**

Run: `pytest tests/test_draft_needs.py -v`
Expected: PASS — all tests, including `test_drafted_into_matches_the_picks_position_to_an_open_hole`
(unaffected: its fixture has exactly one hole and one matching pick, which passes under both the old
membership check and the new capacity cap).

- [ ] **Step 5: Run the broader suite**

Run: `pytest tests/ -v` and `pytest api/tests/ -v`.
Expected: PASS. Fix any API-layer fixture whose `drafted_into`/`started` expectations assumed
uncapped crediting, same discipline as Task 2 Step 5.

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_needs.py tests/test_draft_needs.py
git commit -m "fix(engine): cap draft-needs drafted-into/started credit at open hole instances"
```

---

### Task 4: Frontend — dim the no-holes fallback so a real hole is visually distinct

**Files:**
- Modify: `web/components/DraftGoingIn.tsx`
- Test: `web/tests/DraftGoingIn.test.tsx`

**Interfaces:**
- Consumes: `OwnerNeedsResp`/`SlotStandingResp` (`web/lib/types.ts`, unchanged).
- Produces: `holesReading(n: OwnerNeedsResp): { text: string; dim: boolean }` and a generic
  `DotList({ text }: { text: string })` presentational helper, both consumed by Task 5 for the
  Drafted-into/Started cells.

- [ ] **Step 1: Write the failing tests**

Add to `web/tests/DraftGoingIn.test.tsx`:

```tsx
  it("renders a real hole in full ink and the no-holes softest reading dimmed", () => {
    // Q1 fix (position-room-model spec, 2026-08-18): the only prior signal
    // distinguishing "a real hole" from "no holes, here's the softest slot
    // anyway" was the word "softest" inside the string. `text-dim` (the
    // same neutral tone `Meta`'s own `tone="dim"` uses elsewhere on this
    // board) now marks the no-holes reading, never a `-pos`/`-neg` tone --
    // this stays within the file's existing no-colour rule.
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[
          {
            user_id: "u1", holes: ["QB"], drafted_into: [], started: 0, drafted_into_count: 0,
            slots: [{ slot: "QB", position: "QB", margin: -20, is_hole: true, vetoed: false }],
          },
          {
            user_id: "u3", holes: [], drafted_into: [], started: 0, drafted_into_count: 0,
            slots: [{ slot: "QB", position: "QB", margin: 42, is_hole: false, vetoed: false }],
          },
        ]}
      />,
    );
    expect(screen.getByTestId("going-in-holes-u1")).not.toHaveClass("text-dim");
    expect(screen.getByTestId("going-in-holes-u3")).toHaveClass("text-dim");
  });

  it("dims the em-dash and the mobile no-holes reading the same way as the desktop cell", () => {
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{ user_id: "u3", holes: [], drafted_into: [], started: 0, drafted_into_count: 0, slots: [] }]}
      />,
    );
    expect(screen.getByTestId("going-in-holes-u3")).toHaveClass("text-dim");
    expect(screen.getByTestId("going-in-holes-narrow-u3")).toHaveClass("text-dim");
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/DraftGoingIn.test.tsx -t "dim"`
Expected: FAIL — no cell currently carries a `text-dim` class at all (`goingInText` returns a bare
string, `HolesReading` applies no colour class).

- [ ] **Step 3: Refactor `DraftGoingIn.tsx` to a `{ text, dim }` reading**

In `web/components/DraftGoingIn.tsx`, replace the `goingInText` function with:

```tsx
type Reading = { text: string; dim: boolean };

/** The "Holes going in" cell's whole verdict (task 3, league-native-holes
 *  revision; `dim` added in the position-room-model revision, 2026-08-18)
 *  -- see this file's rules 2 and 3 above for why an owner with no holes
 *  still gets a real reading, and why `position` prints instead of `slot`.
 *
 *  `dim` is `false` only for one or more real `is_hole` entries or the
 *  legacy pre-revision degrade (bare position labels from `holes` when
 *  `slots` is empty but `holes` isn't -- those ARE real holes, just
 *  reported at coarser granularity). Every other case -- no reconstructable
 *  roster, or a clean lineup's softest slot -- is `dim: true`: "nothing
 *  wrong here," the same reading `text-dim` already carries for every
 *  em-dash on this board. */
function holesReading(n: OwnerNeedsResp): Reading {
  const { slots, holes } = n;
  if (slots.length === 0) {
    // M4 fix (2026-08-17): degrade to the pre-revision reading (position
    // labels, no margins) rather than the em-dash every owner would
    // otherwise show for up to a full refresh interval after deploy.
    return holes.length > 0
      ? { text: holes.join(" · "), dim: false }
      : { text: "—", dim: true };
  }
  const holeSlots = slots
    .filter((s) => s.is_hole)
    .slice()
    // `is_hole` is only ever set alongside a finite margin (never on a
    // `null`-margin empty/no-line slot) — see `engine/draft_needs.py`.
    .sort((a, b) => (a.margin as number) - (b.margin as number));
  if (holeSlots.length > 0) {
    return {
      text: holeSlots
        .map((s) => `${s.position}${formatMargin(s.margin as number)}`)
        .join(" · "),
      dim: false,
    };
  }
  const scored = slots.filter(
    (s): s is SlotStandingResp & { margin: number } => s.margin !== null
  );
  if (scored.length === 0) return { text: "—", dim: true };
  const softest = scored.reduce((worst, s) => (s.margin < worst.margin ? s : worst));
  const base = `softest ${softest.position} ${formatMargin(softest.margin)}`;
  return { text: softest.vetoed ? `${base} (market disagrees)` : base, dim: true };
}
```

Rename `HolesReading` to the generic `DotList` (Task 5 reuses it for Drafted-into, which is also a
middot-joined position list) and drop the `text` prop's implicit ownership of colouring — colour is
now applied by the caller, not this presentational helper:

```tsx
/** `text`'s reading, with each middot-separated entry kept ATOMIC — see the
 *  original docstring below for why. Purely presentational: colour (the
 *  `dim` distinction) is applied by the CALLER via a wrapping class, not
 *  here, since this helper is now shared across the Holes and Drafted-into
 *  cells (task 5). */
function DotList({ text }: { text: string }) {
  const parts = text.split(" · ");
  if (parts.length === 1) return <>{text}</>;
  return (
    <>
      {parts.map((p, i) => (
        <span key={`${p}-${i}`} className="whitespace-nowrap">
          {i > 0 ? " · " : null}
          {p}
        </span>
      ))}
    </>
  );
}
```

(Keep the rest of the original `HolesReading` docstring content above this — it still applies
verbatim to the atomic-wrap behavior; only the function name and the removed colouring
responsibility change.)

Update the two call sites that render the Holes cell. Desktop (inside the `ordered.map` in the
`return`):

```tsx
          {ordered.map((n) => {
            const holes = holesReading(n);
            return (
            <Row key={n.user_id} role="row" cols={GRID_GOING_IN}>
              <div
                role="cell"
                className="min-w-0 truncate font-display text-name font-bold tracking-[var(--track-name)] text-ink"
              >
                {nameOf.get(n.user_id) ?? n.user_id}
              </div>
              <div
                role="cell"
                className={holes.dim ? "text-dim" : undefined}
                data-testid={`going-in-holes-${n.user_id}`}
              >
                <DotList text={holes.text} />
              </div>
              <div role="cell" data-testid={`going-in-drafted-${n.user_id}`}>
                <PositionList items={n.drafted_into} />
              </div>
              <div role="cell" className="text-right" data-testid={`going-in-started-${n.user_id}`}>
                {startedText(n.started, n.drafted_into_count)}
              </div>
            </Row>
            );
          })}
```

(The Drafted-into and Started cells are left as-is here — Task 5 replaces them. Only the Holes cell
and the `const holes = holesReading(n)` / `return (...)` wrapping change in this task.)

Mobile (inside the second `ordered.map`):

```tsx
          {ordered.map((n) => {
            const holes = holesReading(n);
            return (
            <EntryCard key={n.user_id}>
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="min-w-0 flex-1 truncate font-display text-name font-bold tracking-[var(--track-name)] text-ink">
                  {nameOf.get(n.user_id) ?? n.user_id}
                </span>
              </div>
              <p className="mt-2.5 font-mono text-figure tabular text-dim">
                Holes going in{" "}
                <b
                  className={`font-medium ${holes.dim ? "text-dim" : "text-ink"}`}
                  data-testid={`going-in-holes-narrow-${n.user_id}`}
                >
                  <DotList text={holes.text} />
                </b>
              </p>
              <MetaLine className="mt-2.5">
                <Meta label="Drafted into">{n.drafted_into.length > 0 ? n.drafted_into.join(" · ") : "—"}</Meta>
                <Meta label="Started">{startedText(n.started, n.drafted_into_count)}</Meta>
              </MetaLine>
            </EntryCard>
            );
          })}
```

(Again, Drafted-into/Started stay as-is inside `MetaLine` here — Task 5 replaces them.)

Update rule 4 in the file's top docstring block (currently: "No colour on the verdicts. A hole is
not a failure, so nothing here ... takes a `-pos`/`-neg` tone.") to add:

```
 *  4. No colour on the verdicts. A hole is not a failure, so nothing here —
 *     not even the em-dash, not even a negative margin on a vetoed softest
 *     slot — takes a `-pos`/`-neg` tone. `text-dim` IS used, deliberately:
 *     it marks "nothing to report" (no roster, no holes, holes-but-
 *     nothing-addressed — task 5) as visually distinct from a real hole or
 *     a real credited pick, the same neutral tone `Meta`'s own
 *     `tone="dim"` already carries elsewhere on this board. A real hole,
 *     a real `drafted_into` list, and a real `started` fraction all stay
 *     full-ink; nothing here is ever `-pos`/`-neg`.
```

- [ ] **Step 4: Run the test file**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/DraftGoingIn.test.tsx`
Expected: PASS — every existing test (none asserted on classes except the "never colours" test,
which only checks for `.text-pos-strong`/`.text-neg-strong` and is unaffected by `text-dim`) plus the
two new ones.

- [ ] **Step 5: Commit**

```bash
git add web/components/DraftGoingIn.tsx web/tests/DraftGoingIn.test.tsx
git commit -m "feat(web): dim the no-holes fallback in the Going-in panel's Holes cell"
```

---

### Task 5: Frontend — disambiguate "—" between "no holes" and "holes, nothing addressed"

**Files:**
- Modify: `web/components/DraftGoingIn.tsx`
- Test: `web/tests/DraftGoingIn.test.tsx`

**Interfaces:**
- Consumes: `holesReading`, `DotList`, `Reading` type (Task 4).
- Produces: `draftedIntoReading(n: OwnerNeedsResp): Reading`, `startedReading(n: OwnerNeedsResp):
  Reading`. No further consumers — this is the last task.

- [ ] **Step 1: Write the failing tests**

In `web/tests/DraftGoingIn.test.tsx`, replace the existing test `"degrades Started to an em-dash
when the owner drafted into none of their holes"` (its fixture — holes present, nothing addressed —
is exactly the ambiguous case this task resolves; its old expectation of a bare `"—"` for both cells
is the defect):

```tsx
  it("reads 'not addressed' (not a bare em-dash) when holes existed but nothing was drafted into them", () => {
    // Q3 fix (position-room-model spec, 2026-08-18): "—" used to mean BOTH
    // "no holes existed" and "holes existed but nothing addressed them,"
    // rendered identically. A real hole (RB) existed here and nothing
    // filled it — that must read distinctly from the true no-holes case
    // below.
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u2", holes: ["RB"], drafted_into: [], started: 0, drafted_into_count: 0,
          slots: [{ slot: "RB", position: "RB", margin: -30, is_hole: true, vetoed: false }],
        }]}
      />,
    );
    expect(screen.getByTestId("going-in-holes-u2")).toHaveTextContent("RB-30");
    expect(screen.getByTestId("going-in-drafted-u2")).toHaveTextContent("not addressed");
    expect(screen.getByTestId("going-in-drafted-u2")).not.toHaveTextContent("—");
    expect(screen.getByTestId("going-in-started-u2")).toHaveTextContent("not addressed");
    expect(screen.getByTestId("going-in-drafted-u2")).toHaveClass("text-dim");
    expect(screen.getByTestId("going-in-started-u2")).toHaveClass("text-dim");
  });

  it("keeps the plain em-dash for a genuine no-holes owner, distinct from 'not addressed'", () => {
    render(
      <DraftGoingIn
        owners={OWNERS}
        needs={[{
          user_id: "u3", holes: [], drafted_into: [], started: 0, drafted_into_count: 0,
          slots: [{ slot: "QB", position: "QB", margin: 42, is_hole: false, vetoed: false }],
        }]}
      />,
    );
    expect(screen.getByTestId("going-in-drafted-u3")).toHaveTextContent("—");
    expect(screen.getByTestId("going-in-drafted-u3")).not.toHaveTextContent("not addressed");
    expect(screen.getByTestId("going-in-started-u3")).toHaveTextContent("—");
    expect(screen.getByTestId("going-in-started-u3")).not.toHaveTextContent("not addressed");
  });
```

Also update the existing test `"renders Started as a fraction over the picks that addressed a
hole"` — no assertion changes needed (its fixture has `drafted_into_count: 2 > 0`, so it stays on
the fraction path), but add one line confirming the fraction path is NOT dimmed, to lock in the
distinction:

```tsx
    expect(screen.getByTestId("going-in-started-u1")).not.toHaveClass("text-dim");
```

(Insert this line at the end of that existing test's body, right after the existing
`toHaveTextContent("1/2")` assertion.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/DraftGoingIn.test.tsx -t "not addressed"`
Expected: FAIL — both cells currently render a bare `"—"` for the holes-but-nothing-addressed case,
and neither cell carries a `text-dim` class today.

- [ ] **Step 3: Implement `draftedIntoReading`/`startedReading` and wire them in**

In `web/components/DraftGoingIn.tsx`, add below `holesReading`:

```tsx
/** The Drafted-into cell's reading (position-room-model spec, 2026-08-18,
 *  Q3): disambiguates the two things a bare "—" used to mean. `holes`
 *  empty -> genuinely nothing to draft into, the plain em-dash. `holes`
 *  non-empty but `drafted_into` empty -> a real hole existed and the draft
 *  did not address it, which reads as the words "not addressed" rather
 *  than the same em-dash a clean lineup gets — the two are not the same
 *  finding and must not render the same. */
function draftedIntoReading(n: OwnerNeedsResp): Reading {
  if (n.holes.length === 0) return { text: "—", dim: true };
  if (n.drafted_into.length === 0) return { text: "not addressed", dim: true };
  return { text: n.drafted_into.join(" · "), dim: false };
}

/** The Started cell's reading — same disambiguation as `draftedIntoReading`,
 *  applied to the fraction. A real, non-zero-denominator fraction
 *  (`drafted_into_count > 0`) is untouched by this fix and stays a plain
 *  `started/count` reading (rule 1 in this file's header docstring: a
 *  zero NUMERATOR with a real denominator, e.g. "0/2", is still a real
 *  fraction, not this function's "not addressed" case). */
function startedReading(n: OwnerNeedsResp): Reading {
  if (n.holes.length === 0) return { text: "—", dim: true };
  if (n.drafted_into_count === 0) return { text: "not addressed", dim: true };
  return { text: `${n.started}/${n.drafted_into_count}`, dim: false };
}
```

Delete the now-unused `PositionList` and `startedText` functions (both fully replaced by the
functions above — grep the file after this change to confirm no remaining callers).

Update the desktop cells (from Task 4's `ordered.map`):

```tsx
              <div
                role="cell"
                className={drafted.dim ? "text-dim" : undefined}
                data-testid={`going-in-drafted-${n.user_id}`}
              >
                <DotList text={drafted.text} />
              </div>
              <div
                role="cell"
                className={`text-right ${started.dim ? "text-dim" : ""}`.trim()}
                data-testid={`going-in-started-${n.user_id}`}
              >
                {started.text}
              </div>
```

with `const drafted = draftedIntoReading(n);` and `const started = startedReading(n);` added
alongside the existing `const holes = holesReading(n);` at the top of the desktop `ordered.map`
callback.

Update the mobile cells (from Task 4's second `ordered.map`), adding the same two `const`s at the
top of that callback:

```tsx
              <MetaLine className="mt-2.5">
                <Meta label="Drafted into" tone={drafted.dim ? "dim" : undefined}>
                  <DotList text={drafted.text} />
                </Meta>
                <Meta label="Started" tone={started.dim ? "dim" : undefined}>
                  {started.text}
                </Meta>
              </MetaLine>
```

(`Meta`'s `tone` prop already supports `"dim"` — `web/components/furniture/EntryCard.tsx` — so the
mobile cells use it directly rather than a wrapping `text-dim` span.)

- [ ] **Step 4: Run the test file**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/DraftGoingIn.test.tsx`
Expected: PASS — every test in the file, including the two new ones and the updated fraction test.

- [ ] **Step 5: Run the full frontend and backend suites**

Run: `cd web && npx vitest --config tests/vitest.config.ts run` (bare `npx vitest run` silently uses
no config and fails on JSX — use the flag every time, per `CLAUDE.md`), then `pytest tests/ -v` and
`pytest api/tests/ -v` from the repo root.
Expected: PASS across all three. This is the plan's final verification gate — do not consider the
plan complete until all three are green.

- [ ] **Step 6: Commit**

```bash
git add web/components/DraftGoingIn.tsx web/tests/DraftGoingIn.test.tsx
git commit -m "feat(web): disambiguate the Going-in panel's drafted-into/started em-dash"
```

---

## Self-Review Notes (for the plan author, not a task)

- **Spec coverage:** demand-freezing (Task 1) ✓, K inclusion with DEF excluded and no
  drafted_into/started carve-out (Task 2) ✓, drafted_into/started slot-instance-level (capacity-
  capped) matching (Task 3) ✓, hole-vs-softest visual distinction (Task 4) ✓, "—" disambiguation
  (Task 5) ✓. The spec's fourth open question (per-season persistence / an engine-logic
  invalidation signal) is explicitly out of scope — the spec itself says it "remain[s] open on
  their own track," unaffected by this spec, and no task above touches `ChainCacheEntry` at all.
- **No placeholders:** every step above contains literal code, exact fixture values worked by hand
  in each test's docstring, and exact run commands.
- **Type consistency:** `Reading` (`{ text: string; dim: boolean }`) is defined once in Task 4 and
  reused verbatim by Task 5's two new functions; `DotList` (renamed from `HolesReading` in Task 4)
  is defined once and reused by both the Holes cell (Task 4) and the Drafted-into cell (Task 5).
  `_direct_demand` (Task 1) is defined once and consumed unchanged by Task 2 (K) and Task 3
  (unaffected by the demand mechanism at all — it operates on `hole_instances`, a Pass 3 output).
