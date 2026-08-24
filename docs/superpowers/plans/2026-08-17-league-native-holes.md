# League-Native Replacement Lines — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw the draft-needs replacement line on the prior season's points in the league's own scoring, report severity in points rather than a binary, and surface it so no row is blank.

**Architecture:** Three seams. The engine's hole definition changes shape (points primary, ECR as fallback + veto, margins returned). The grader supplies a prior-season points map it already has in `supporting["matchups"]`. The panel renders margins and a softest-slot line, and moves above Picks.

**Spec:** `docs/superpowers/specs/2026-08-17-draft-needs-phase5-design.md` § "Revision — the replacement line becomes league-native" (at the end; it supersedes § Defining a hole).

## Global Constraints

- **Branch `new-draft-board`. Never commit to `main`** (it auto-deploys). **Do NOT push.**
- **Never render "KTC"** in UI. It is "Trade Value" / "Value".
- **Display-only. Never feeds Franchise Rating.**
- **No `SCHEMA_VERSION` bump** — `draft_needs` is already a value-layer field, always recomputed. Adding fields inside its rows changes no cache contract (a stale row simply lacks them and the read-time model supplies defaults).
- **Prior season only.** For a May 2026 draft the points come from 2025. Using the draft's own season would be hindsight and must never happen — there is a test for it.
- Reuse `.design/` primitives; never add a `web/tests/furniture-rules.test.ts` exception entry.
- Verify: `pytest tests/ -q` (root), `cd api && pytest tests/ -q`, `cd web && npx vitest --config tests/vitest.config.ts run`, `npx tsc --noEmit`, `npm run build`. A bare `pytest` from the root breaks; a bare `npx vitest run` silently uses NO config.
- **Run every suite in the FOREGROUND.** Agents in this project have stalled waiting on background jobs.
- **State in a comment which mutation each test catches**, then confirm the data would catch it. **Falsify every test**: mutate, confirm red, restore, confirm byte-identical. Six tests in this project have failed to distinguish what they were named for.

---

### Task 1: Points-based lines, severity, and the ECR veto

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_needs.py`
- Test: `tests/test_draft_needs.py`

**Interfaces:**
- Produces: `build_draft_needs(rosters, board, positions, roster_positions, picks_by_owner, started_by_pick, *, points: dict[str, float] | None = None) -> list[OwnerNeeds]`, with `OwnerNeeds` gaining `hole_margins: dict[str, float]` and `softest_slot: tuple[str, float] | None`.

`points` is player_id → prior-season points in this league's scoring. **Optional with a `None` default** so every existing call site and test keeps working and falls back to today's ECR-only behaviour — that is what keeps this task reviewable on its own.

**The rules, in the order they apply:**

1. **Value each rostered player by `points`** when present. Fill the optimal lineup on that value (it is already a "higher is better" number, so unlike ECR it needs **no inversion** — do not invert it, and say so in a comment, because the ECR path right next to it does).
2. **The line per position** is the Nth-best *by points* among all rostered players at that position, N being the same empirically-counted demand as today.
3. **A hole is below the line on points AND not vetoed by ECR.** The veto: if the player's ECR is better than the ECR line at that position, it is not a hole. One sentence for the docstring: *last year's production says replaceable, and the market does not disagree.*
4. **Margins.** `hole_margins[slot]` is points below the line (negative). `softest_slot` is the starting slot with the smallest margin — including when it is positive, which is the whole point: an owner with no holes still has a softest slot.
5. **No `points` at all for a player** → fall back to that player's ECR standing. A player with neither points nor ECR keeps the existing sentinel (worse than everyone, better than nobody) so a slot never reads empty.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_line_is_drawn_on_points_not_ecr_when_points_are_present():
    """Mutation this catches: ranking the pool by ECR while `points` is supplied.

    The fixture is built so the two disagree — the ECR-best QB is the
    points-worst — so a test whose data let them coincide would pass against
    either implementation. This is the whole revision in one assertion.
    """
    rosters = {f"u{i}": {f"qb{i}"} for i in range(1, 4)}
    board  = {"qb1": 1.0, "qb2": 2.0, "qb3": 3.0}      # ECR says qb1 best
    points = {"qb1": 10.0, "qb2": 200.0, "qb3": 300.0}  # points say qb1 worst
    out = build_draft_needs(rosters, board, {p: "QB" for p in board},
                            ["QB", "BN"], {}, {}, points=points)
    holes = {n.user_id: n.holes for n in out}
    assert holes["u1"] == ["QB"], "qb1 is last by points and must be the hole"
    assert holes["u3"] == []

def test_points_are_not_inverted():
    """Mutation this catches: applying the ECR inversion to `points` too.

    Inverting a higher-is-better number starts the WORST player, and every
    other assertion here would still pass because the ordering is merely
    reversed, not broken.
    """
    rosters = {"u1": {"good", "bad"}}
    out = build_draft_needs(rosters, {}, {"good": "QB", "bad": "QB"},
                            ["QB", "BN"], {}, {},
                            points={"good": 300.0, "bad": 5.0})
    assert out[0].starters_by_slot["QB"] == "good"

def test_a_young_player_below_replacement_on_points_is_vetoed_by_ecr():
    """Mutation this catches: dropping the ECR veto.

    Without it a second-year breakout who barely played reads as a hole in a
    dynasty league, which is the false positive the veto exists to prevent.
    """
    rosters = {"u1": {"rookie"}, "u2": {"vet2"}, "u3": {"vet3"}}
    board  = {"rookie": 5.0, "vet2": 90.0, "vet3": 95.0}   # market loves the rookie
    points = {"rookie": 12.0, "vet2": 200.0, "vet3": 210.0}
    out = {n.user_id: n.holes for n in build_draft_needs(
        rosters, board, {p: "QB" for p in board}, ["QB", "BN"], {}, {}, points=points)}
    assert out["u1"] == [], "ECR rates him above the line, so not a hole"

def test_every_owner_gets_a_softest_slot_even_with_no_holes():
    """Mutation this catches: only populating softest_slot when holes exist —
    which would leave exactly the blank rows this revision is fixing."""
    rosters = {f"u{i}": {f"qb{i}"} for i in range(1, 4)}
    out = build_draft_needs(rosters, {}, {f"qb{i}": "QB" for i in range(1, 4)},
                            ["QB", "BN"], {}, {},
                            points={f"qb{i}": 100.0 * i for i in range(1, 4)})
    for n in out:
        assert n.softest_slot is not None
        assert n.softest_slot[0] == "QB"

def test_a_hole_carries_its_margin_in_points():
    """Mutation this catches: reporting the margin as a rank delta or as an
    absolute value — a hole's margin must be NEGATIVE points below the line."""
    rosters = {f"u{i}": {f"qb{i}"} for i in range(1, 4)}
    points = {"qb1": 100.0, "qb2": 200.0, "qb3": 300.0}
    out = {n.user_id: n for n in build_draft_needs(
        rosters, {}, {p: "QB" for p in points}, ["QB", "BN"], {}, {}, points=points)}
    assert out["u1"].hole_margins["QB"] < 0

def test_omitting_points_preserves_the_existing_ecr_behaviour():
    """Mutation this catches: making `points` required, or defaulting it to {}
    in a way that zeroes every player. Every pre-revision call site relies on
    this path."""
    rosters = {"u1": {"a"}, "u2": {"b"}}
    board = {"a": 1.0, "b": 200.0}
    out = {n.user_id: n.holes for n in build_draft_needs(
        rosters, board, {"a": "QB", "b": "QB"}, ["QB", "BN"], {}, {})}
    assert out["u1"] == []
```

- [ ] **Step 2: Run them and watch them fail.** `pytest tests/test_draft_needs.py -q`
- [ ] **Step 3: Implement.** Keep every existing guarantee: determinism (`sorted(pids)` and total-order tie-breaks), K/DEF stripped before the solve, bench slots never holes, the unranked sentinel, `starters_by_slot`.
- [ ] **Step 4: Verify the whole engine suite.** `pytest tests/ -q`
- [ ] **Step 5: Commit** — `feat(engine): league-native replacement lines with severity`

---

### Task 2: Supply prior-season points, and widen the wire model

**Files:**
- Modify: `api/app/services/grader.py`, `api/app/models/league.py`, `api/app/services/draft_board_view.py`
- Test: `api/tests/test_grader_service.py`, `api/tests/test_draft_board_view.py`

**Interfaces:**
- Consumes Task 1's `points=` keyword.
- Produces: `OwnerNeedsResp` gaining `hole_margins: dict[str, float]` and `softest_slot: tuple[str, float] | None` (serialise as an object or a 2-tuple — pick one and keep the frontend type in step).

**Building the points map — the season is the thing to get right.** Sum `players_points` (`grader_io.py:125`) across every matchup entry whose league id is the **prior** season's, i.e. the same `_prior_league_id` the seed already uses. **Not the draft's own season** — for a May 2026 draft, 2026 has not been played, and using it later in the year would silently become hindsight. There is a test for this; make it bite.

Note `players_points` covers only players rostered *in this league* that season, which is exactly why Task 1 keeps an ECR fallback. Do not try to widen the source.

- [ ] **Step 1: Write the failing tests**, including one asserting the points map is built from the prior league id and NOT the draft's own season (mutate the league id and watch it fail), and one asserting `OwnerNeedsResp` round-trips the new fields.
- [ ] **Step 2–4: fail → implement → verify.** `cd api && pytest tests/ -q`
- [ ] **Step 5: Commit** — `feat(api): supply prior-season league-scoring points to draft needs`

---

### Task 3: Render severity, and move the panel above Picks

**Files:**
- Modify: `web/components/DraftGoingIn.tsx`, `web/components/DraftBoard.tsx`, `web/lib/types.ts`, `web/lib/draft-columns.ts`
- Test: `web/tests/DraftGoingIn.test.tsx`, `web/tests/draft-columns.test.ts`

**Two changes:**

1. **Move `<DraftGoingIn>` above `<PicksSection>`.** It is pre-draft context and currently renders *after* 36 picks, which is why it could not be found at all. It belongs directly after Owners.
2. **Render margins, and never render an all-blank row.**
   - holes: `TE −60 · RB −24`
   - no holes: `softest: QB +8`
   - `—` survives only when there is no reconstructable roster.

**Width:** the grid is cut against **802px** of real track budget (`910 − 48px Shell − 2px Panel − 30px gaps − 28px cell padding`), not against 910. Add the revised template to the same `WIDTH_GATE_BUDGET_PX` assertion. Getting this wrong cost a full round in phase 4.

**No colour on the margins** beyond the sanctioned tone tokens — a hole is not a failure, and `-pos`/`-neg` on a data figure is drift the guard will catch.

- [ ] **Step 1: Write the failing tests** — margins render with sign; an owner with no holes shows a softest slot rather than three dashes; the panel appears before the picks table in DOM order; the new grid fits the budget.
- [ ] **Step 2–4: fail → implement → verify.** `npx vitest --config tests/vitest.config.ts run`, `npx tsc --noEmit`, `npm run build`
- [ ] **Step 5: Commit** — `feat(web): the Going in panel reports severity, above the picks`

---

## Notes for the controller

- Tasks are strictly ordered: 1 → 2 → 3. Each is independently reviewable and shippable.
- Task 1's `points=None` default is what makes it so: with the engine landed and nothing supplying points, behaviour is unchanged in production until Task 2.
- The live evidence behind this revision is in the spec revision's tables. If an implementer's numbers contradict them, that is worth surfacing, not working around.
