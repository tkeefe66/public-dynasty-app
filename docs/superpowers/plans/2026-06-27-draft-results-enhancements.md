# Draft Results Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a totals row, an All-Time view, a roster-status chip, and a games-started count to the "How past picks panned out" draft-results table on the Outlook tab.

**Architecture:** Two new pure engine fields (`games_started`, `roster_status`) flow engine → grader → cache → API model → `owner_view` → TS type → `PastPicksTable`. Games-started is a count-counterpart to the existing owner-gated `started_points_while_on_roster`. Roster status is derived from `current_holders` (current owner per player) plus a traded-away set mirrored from resolved trades. The frontend gains a status chip column, a GS column, a per-table totals row, and an "All-Time" entry in the year selector.

**Tech Stack:** Python (pure engine functions, pytest), FastAPI/Pydantic, Next.js 14 / React / TypeScript / Tailwind, vitest.

## Global Constraints

- **Never show "KTC" in the UI** — value columns are "Value" / "Trade Value". (No new value labels here, but keep it in mind.)
- **Five-metric vocabulary** stays: Total Points / Regular Season Points / Playoff Points / Toilet Bowl Points.
- **Engine functions are pure** — no I/O; callers thread data in. Unit-tested.
- **Cache schema:** any change to `drafted_picks` dict keys requires bumping `SCHEMA_VERSION` (currently 15) and running `next build` before deploy (stale-cache 500 gotcha).
- **Games started is ONE combined number** across all phases (regular + playoff + toilet).
- **Totals row sums every numeric column**, value columns included as-is.
- **All-Time is an extra year-selector entry** listing every pick (not a per-season summary); per-season tabs remain; it is NOT the default tab.
- Frontend interactive components need `"use client"` (already present in `PastPicksTable.tsx`).

---

### Task 1: Engine — `started_games_while_on_roster`

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_results.py` (add function after `started_points_while_on_roster`, ~line 56)
- Test: `tests/test_draft_results.py`

**Interfaces:**
- Produces: `started_games_while_on_roster(pid: str, uid: str, *, matchups: dict[tuple[str,int,int], dict], roster_to_user_by_league: dict[str, dict[int,str]]) -> int` — count of weeks `pid` was in the starting lineup while on `uid`'s roster, across all phases.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_draft_results.py` (uses existing `_matchups`, `_R2U` helpers in that file):

```python
def test_started_games_while_on_roster_counts_starts_owner_gated():
    from sleeper_dynasty.engine.draft_results import started_games_while_on_roster
    n = started_games_while_on_roster(
        "p1", "U", matchups=_matchups(), roster_to_user_by_league=_R2U)
    # weeks 1, 2, 15, 16 started for U; week 4 benched (not counted);
    # week 3 was on roster 2 / OTHER (not counted).
    assert n == 4


def test_started_games_zero_for_owner_who_never_started_him():
    from sleeper_dynasty.engine.draft_results import started_games_while_on_roster
    n = started_games_while_on_roster(
        "p1", "Z", matchups=_matchups(), roster_to_user_by_league=_R2U)
    assert n == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft_results.py::test_started_games_while_on_roster_counts_starts_owner_gated -v`
Expected: FAIL with `ImportError: cannot import name 'started_games_while_on_roster'`

- [ ] **Step 3: Write minimal implementation**

In `src/sleeper_dynasty/engine/draft_results.py`, add after `started_points_while_on_roster` (after line 55):

```python
def started_games_while_on_roster(
    pid: str,
    uid: str,
    *,
    matchups: dict[tuple[str, int, int], dict],
    roster_to_user_by_league: dict[str, dict[int, str]],
) -> int:
    """Count of weeks ``pid`` was in ``uid``'s starting lineup while on roster.

    One combined number across all phases (regular + playoff + toilet). Owner-gated
    by weekly roster membership, so weeks after the owner traded the player away
    don't count. Bench-only weeks (not in ``starters``) don't count.
    """
    count = 0
    for (lg, _wk, rid), entry in matchups.items():
        if roster_to_user_by_league.get(lg, {}).get(rid) != uid:
            continue
        if pid in (entry.get("starters") or []):
            count += 1
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_draft_results.py -k started_games -v`
Expected: PASS (both new tests)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_results.py tests/test_draft_results.py
git commit -m "feat(draft-results): count games started for owner (owner-gated)"
```

---

### Task 2: Engine — `derive_roster_status`

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_results.py` (add function after Task 1's addition)
- Test: `tests/test_draft_results.py`

**Interfaces:**
- Produces: `derive_roster_status(pid: str, uid: str, *, current_holders: dict[str,str], traded_away_set: set[tuple[str,str]]) -> str` — returns `"rostered"`, `"traded"`, or `"dropped"`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_draft_results.py`:

```python
def test_derive_roster_status():
    from sleeper_dynasty.engine.draft_results import derive_roster_status
    # still on the drafting owner's roster
    assert derive_roster_status(
        "p1", "U", current_holders={"p1": "U"}, traded_away_set=set()) == "rostered"
    # gone, and U traded him away
    assert derive_roster_status(
        "p1", "U", current_holders={"p1": "V"},
        traded_away_set={("U", "p1")}) == "traded"
    # gone, U did not trade him (dropped / waiver), now unowned
    assert derive_roster_status(
        "p1", "U", current_holders={}, traded_away_set=set()) == "dropped"
    # gone, U did not trade him, picked up by V -> dropped from U's view
    assert derive_roster_status(
        "p1", "U", current_holders={"p1": "V"}, traded_away_set=set()) == "dropped"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft_results.py::test_derive_roster_status -v`
Expected: FAIL with `ImportError: cannot import name 'derive_roster_status'`

- [ ] **Step 3: Write minimal implementation**

In `src/sleeper_dynasty/engine/draft_results.py`, add after `started_games_while_on_roster`:

```python
def derive_roster_status(
    pid: str,
    uid: str,
    *,
    current_holders: dict[str, str],
    traded_away_set: set[tuple[str, str]],
) -> str:
    """Current standing of ``pid`` relative to the drafting owner ``uid``.

    - "rostered": still on ``uid``'s roster right now.
    - "traded":   no longer on ``uid``'s roster, and ``uid`` traded him away.
    - "dropped":  no longer on ``uid``'s roster via any other path (waiver/drop).
    """
    if current_holders.get(pid) == uid:
        return "rostered"
    if (uid, pid) in traded_away_set:
        return "traded"
    return "dropped"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_draft_results.py::test_derive_roster_status -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_results.py tests/test_draft_results.py
git commit -m "feat(draft-results): derive current roster status (rostered/traded/dropped)"
```

---

### Task 3: Engine — extend `build_drafted_pick_results` with the two new fields

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_results.py` (`build_drafted_pick_results`, lines 58-113)
- Test: `tests/test_draft_results.py`

**Interfaces:**
- Consumes: `started_games_while_on_roster` and `derive_roster_status` (Tasks 1-2).
- Produces: `build_drafted_pick_results(..., games_fn: Callable[[str, str], int], current_holders: dict[str, str], traded_away_set: set[tuple[str, str]]) -> list[dict]` — each dict additionally carries `"games_started": int` and `"roster_status": str`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_draft_results.py`:

```python
def test_build_results_includes_games_started_and_roster_status():
    picks = [
        _pick("p1", "U", rnd=1, slot=1),
        _pick("p2", "V", rnd=1, slot=2),
    ]
    rows = build_drafted_pick_results(
        picks,
        ktc_floats={"p1": 5000.0, "p2": 3000.0},
        normalized_name_by_pid={"p1": "aida", "p2": "bo"},
        names={"p1": "Aida", "p2": "Bo"},
        positions={"p1": "WR", "p2": "RB"},
        extremes_by_name={},
        acquired_set=set(),
        points_fn=lambda pid, uid, phase: 0.0,
        games_fn=lambda pid, uid: {("p1", "U"): 7, ("p2", "V"): 0}.get((pid, uid), 0),
        current_holders={"p1": "U"},                 # p1 still rostered by U
        traded_away_set={("V", "p2")},               # V traded p2 away
    )
    by_pid = {r["player_id"]: r for r in rows}
    assert by_pid["p1"]["games_started"] == 7
    assert by_pid["p1"]["roster_status"] == "rostered"
    assert by_pid["p2"]["games_started"] == 0
    assert by_pid["p2"]["roster_status"] == "traded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft_results.py::test_build_results_includes_games_started_and_roster_status -v`
Expected: FAIL with `TypeError: build_drafted_pick_results() got an unexpected keyword argument 'games_fn'`

- [ ] **Step 3: Write minimal implementation**

In `src/sleeper_dynasty/engine/draft_results.py`, update the signature of `build_drafted_pick_results` (line 58-68) to add the three new keyword params at the end of the signature:

```python
def build_drafted_pick_results(
    picks: list[DraftedPick],
    *,
    ktc_floats: dict[str, float],
    normalized_name_by_pid: dict[str, str],
    names: dict[str, str],
    positions: dict[str, str],
    extremes_by_name: dict[str, tuple[float, float]],
    acquired_set: set[tuple[str, str]],
    points_fn: Callable[[str, str, str], float],
    games_fn: Callable[[str, str], int],
    current_holders: dict[str, str],
    traded_away_set: set[tuple[str, str]],
) -> list[dict]:
```

Then, inside the `for p in picks:` loop, add the two keys to the appended dict (insert after the `"production_toilet": ...` line, line 111):

```python
            "production_toilet": points_fn(p.player_id, p.drafter_id, "toilet"),
            "games_started": games_fn(p.player_id, p.drafter_id),
            "roster_status": derive_roster_status(
                p.player_id, p.drafter_id,
                current_holders=current_holders,
                traded_away_set=traded_away_set),
```

- [ ] **Step 4: Run the full draft-results suite to verify it passes**

Run: `pytest tests/test_draft_results.py -v`
Expected: PASS (all tests, including the pre-existing `test_build_results_career_arc_and_avg_slot` — it does not pass the new kwargs, so it will now FAIL; fix it in Step 5 before committing).

- [ ] **Step 5: Update the pre-existing build-results tests to pass the new required kwargs**

The two existing tests `test_build_results_career_arc_and_avg_slot` and `test_build_results_folds_current_into_extremes` call `build_drafted_pick_results` without the new kwargs. Add the three new kwargs to BOTH calls. For `test_build_results_career_arc_and_avg_slot` add after its `points_fn=...` argument:

```python
        games_fn=lambda pid, uid: 0,
        current_holders={},
        traded_away_set=set(),
```

For `test_build_results_folds_current_into_extremes` change its call's trailing args from:

```python
        acquired_set=set(), points_fn=lambda pid, uid, phase: 0.0)
```

to:

```python
        acquired_set=set(), points_fn=lambda pid, uid, phase: 0.0,
        games_fn=lambda pid, uid: 0, current_holders={}, traded_away_set=set())
```

Run: `pytest tests/test_draft_results.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_results.py tests/test_draft_results.py
git commit -m "feat(draft-results): add games_started + roster_status to pick rows"
```

---

### Task 4: Grader wiring — build traded-away set, games callback, pass new args

**Files:**
- Modify: `api/app/services/grader.py` (lines 736-785, the drafted-picks try-block)

**Interfaces:**
- Consumes: `started_games_while_on_roster` (Task 1), extended `build_drafted_pick_results` (Task 3), and the in-scope `current_holders: dict[str, str]` variable (already populated and passed to `ChainCacheEntry` at line 857).

- [ ] **Step 1: Add the games-started import**

In `api/app/services/grader.py`, change the import (lines 737-739) from:

```python
            from sleeper_dynasty.engine.draft_results import (
                build_drafted_pick_results, started_points_while_on_roster,
            )
```

to:

```python
            from sleeper_dynasty.engine.draft_results import (
                build_drafted_pick_results, started_points_while_on_roster,
                started_games_while_on_roster,
            )
```

- [ ] **Step 2: Build the traded-away set alongside the acquired set**

In `api/app/services/grader.py`, the existing `acquired_set` loop (lines 758-765) iterates `received`. Extend it to also collect `given` into a new `traded_away_set`. Replace lines 758-765:

```python
            acquired_set: set[tuple[str, str]] = set()
            for rt in resolved_dicts:
                for uid, side in (rt.get("sides") or {}).items():
                    for a in (side.get("received") or []):
                        if a.get("drafted_player_id"):
                            acquired_set.add((uid, a["drafted_player_id"]))
                        elif a.get("via_pick") and a.get("player_id"):
                            acquired_set.add((uid, a["player_id"]))
```

with:

```python
            acquired_set: set[tuple[str, str]] = set()
            traded_away_set: set[tuple[str, str]] = set()
            for rt in resolved_dicts:
                for uid, side in (rt.get("sides") or {}).items():
                    for a in (side.get("received") or []):
                        if a.get("drafted_player_id"):
                            acquired_set.add((uid, a["drafted_player_id"]))
                        elif a.get("via_pick") and a.get("player_id"):
                            acquired_set.add((uid, a["player_id"]))
                    for a in (side.get("given") or []):
                        if a.get("player_id"):
                            traded_away_set.add((uid, a["player_id"]))
                        if a.get("drafted_player_id"):
                            traded_away_set.add((uid, a["drafted_player_id"]))
```

- [ ] **Step 3: Add the games callback**

In `api/app/services/grader.py`, after the `_points` function (after line 774), add:

```python
            def _games(pid: str, uid: str) -> int:
                return started_games_while_on_roster(
                    pid, uid,
                    matchups=supporting["matchups"],
                    roster_to_user_by_league=supporting["roster_to_user_by_league"],
                )
```

- [ ] **Step 4: Pass the new args to `build_drafted_pick_results`**

In `api/app/services/grader.py`, change the call (lines 776-785) to add the three new kwargs. Replace the trailing `points_fn=_points,` line so the call ends:

```python
                acquired_set=acquired_set,
                points_fn=_points,
                games_fn=_games,
                current_holders=current_holders,
                traded_away_set=traded_away_set,
            )
```

- [ ] **Step 5: Verify the module imports and the engine suite still passes**

Run: `python -c "import app.services.grader"` from the `api/` directory (or `pip show`-confirmed env). If the project layout requires it, run instead: `python -c "import ast; ast.parse(open('api/app/services/grader.py').read())"` from repo root to confirm it parses.
Expected: no error.

Run: `pytest tests/test_draft_results.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/app/services/grader.py
git commit -m "feat(draft-results): wire games_started + traded-away set in grader"
```

---

### Task 5: API model + `owner_view` passthrough + cache schema bump

**Files:**
- Modify: `api/app/models/owner.py` (`DraftPickResult`, lines 98-114)
- Modify: `api/app/services/owner_view.py` (lines 223-236)
- Modify: `api/app/services/chain_cache.py` (line 11, `SCHEMA_VERSION`)

**Interfaces:**
- Consumes: the `drafted_picks` dicts now carrying `games_started` + `roster_status` (Task 4).
- Produces: `DraftPickResult` Pydantic model with `games_started: int` and `roster_status: str` fields, surfaced via `owner_view`.

- [ ] **Step 1: Add the two fields to the Pydantic model**

In `api/app/models/owner.py`, in `DraftPickResult` (after line 114, `production_toilet: float`), add:

```python
    production_toilet: float
    games_started: int = 0
    roster_status: str = "rostered"
```

- [ ] **Step 2: Pass the fields through in `owner_view`**

In `api/app/services/owner_view.py`, in the `DraftPickResult(...)` construction (lines 223-236), add after `production_toilet=...` (line 235):

```python
            production_toilet=float(p.get("production_toilet", 0.0)),
            games_started=int(p.get("games_started", 0) or 0),
            roster_status=str(p.get("roster_status", "rostered") or "rostered"),
```

- [ ] **Step 3: Bump the cache schema version**

In `api/app/services/chain_cache.py` line 11, change:

```python
SCHEMA_VERSION = 15  # bumped: lineup_signals (Franchise Rating redesign)
```

to:

```python
SCHEMA_VERSION = 16  # bumped: drafted_picks games_started + roster_status
```

- [ ] **Step 4: Verify the backend test suite passes**

Run: `make test` (backend portion) — or from `api/`: `pytest -q`
Expected: PASS (no schema/model errors). Pre-feature caches are invalidated by the version bump and recompute on next refresh.

- [ ] **Step 5: Commit**

```bash
git add api/app/models/owner.py api/app/services/owner_view.py api/app/services/chain_cache.py
git commit -m "feat(draft-results): expose games_started + roster_status; bump cache schema to 16"
```

---

### Task 6: Frontend — types + pure helpers (totals + All-Time flatten)

**Files:**
- Modify: `web/lib/types.ts` (`DraftPickResult`, lines 223-240)
- Create: `web/components/ownerdeepdive/pastPicks.ts` (pure helpers)
- Test: `web/components/ownerdeepdive/pastPicks.test.ts`

**Interfaces:**
- Produces:
  - `DraftPickResult` TS type gains `games_started: number` and `roster_status: "rostered" | "traded" | "dropped"`.
  - `ALL_TIME = "all"` sentinel constant.
  - `flattenAllTime(bySeason: Record<string, DraftPickResult[]>): DraftPickResult[]` — every pick, sorted by `current_value - avg_slot_value` descending.
  - `columnTotals(rows: DraftPickResult[]): ColumnTotals` where `ColumnTotals = { current_value, lowest_value, highest_value, deltaSum, production_total, production_regular, production_playoff, production_toilet, games_started }` (all numbers).

- [ ] **Step 1: Write the failing test**

Create `web/components/ownerdeepdive/pastPicks.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { flattenAllTime, columnTotals, ALL_TIME } from "./pastPicks";
import type { DraftPickResult } from "@/lib/types";

const mk = (over: Partial<DraftPickResult>): DraftPickResult => ({
  player_id: "x", full_name: "X", position: "WR", round: 1, slot: 1,
  picks_in_round: 12, draft_season: 2025, acquired_via_trade: false,
  current_value: 0, lowest_value: 0, highest_value: 0, avg_slot_value: 0,
  production_total: 0, production_regular: 0, production_playoff: 0,
  production_toilet: 0, games_started: 0, roster_status: "rostered", ...over,
});

describe("pastPicks helpers", () => {
  it("ALL_TIME sentinel", () => {
    expect(ALL_TIME).toBe("all");
  });

  it("flattenAllTime merges seasons and sorts by value delta desc", () => {
    const bySeason = {
      "2024": [mk({ player_id: "a", current_value: 100, avg_slot_value: 90 })], // +10
      "2025": [
        mk({ player_id: "b", current_value: 100, avg_slot_value: 50 }),  // +50
        mk({ player_id: "c", current_value: 100, avg_slot_value: 120 }), // -20
      ],
    };
    const out = flattenAllTime(bySeason);
    expect(out.map((r) => r.player_id)).toEqual(["b", "a", "c"]);
  });

  it("columnTotals sums numeric columns including delta", () => {
    const rows = [
      mk({ current_value: 100, lowest_value: 50, highest_value: 150,
           avg_slot_value: 60, production_total: 200, production_regular: 100,
           production_playoff: 30, production_toilet: 5, games_started: 10 }),
      mk({ current_value: 200, lowest_value: 80, highest_value: 260,
           avg_slot_value: 220, production_total: 50, production_regular: 40,
           production_playoff: 0, production_toilet: 2, games_started: 3 }),
    ];
    const t = columnTotals(rows);
    expect(t.current_value).toBe(300);
    expect(t.lowest_value).toBe(130);
    expect(t.highest_value).toBe(410);
    // deltaSum = (100-60) + (200-220) = 40 + (-20) = 20
    expect(t.deltaSum).toBe(20);
    expect(t.production_total).toBe(250);
    expect(t.production_regular).toBe(140);
    expect(t.production_playoff).toBe(30);
    expect(t.production_toilet).toBe(7);
    expect(t.games_started).toBe(13);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run components/ownerdeepdive/pastPicks.test.ts`
Expected: FAIL — cannot resolve `./pastPicks`.

- [ ] **Step 3: Add the new type fields**

In `web/lib/types.ts`, in `DraftPickResult` (after line 239, `production_toilet: number;`), add:

```typescript
  production_toilet: number;
  games_started: number;
  roster_status: "rostered" | "traded" | "dropped";
```

- [ ] **Step 4: Write the helper module**

Create `web/components/ownerdeepdive/pastPicks.ts`:

```typescript
import type { DraftPickResult } from "@/lib/types";

/** Sentinel value used in the year selector for the All-Time view. */
export const ALL_TIME = "all";

const delta = (r: DraftPickResult): number => r.current_value - r.avg_slot_value;

/** Every pick across all seasons, sorted by value-vs-slot delta (best first). */
export function flattenAllTime(
  bySeason: Record<string, DraftPickResult[]>,
): DraftPickResult[] {
  return Object.values(bySeason)
    .flat()
    .slice()
    .sort((a, b) => delta(b) - delta(a));
}

export interface ColumnTotals {
  current_value: number;
  lowest_value: number;
  highest_value: number;
  deltaSum: number;
  production_total: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
  games_started: number;
}

/** Sum every numeric column across the given rows. */
export function columnTotals(rows: DraftPickResult[]): ColumnTotals {
  return rows.reduce<ColumnTotals>(
    (t, r) => ({
      current_value: t.current_value + r.current_value,
      lowest_value: t.lowest_value + r.lowest_value,
      highest_value: t.highest_value + r.highest_value,
      deltaSum: t.deltaSum + delta(r),
      production_total: t.production_total + r.production_total,
      production_regular: t.production_regular + r.production_regular,
      production_playoff: t.production_playoff + r.production_playoff,
      production_toilet: t.production_toilet + r.production_toilet,
      games_started: t.games_started + r.games_started,
    }),
    {
      current_value: 0, lowest_value: 0, highest_value: 0, deltaSum: 0,
      production_total: 0, production_regular: 0, production_playoff: 0,
      production_toilet: 0, games_started: 0,
    },
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npx vitest run components/ownerdeepdive/pastPicks.test.ts`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/lib/types.ts web/components/ownerdeepdive/pastPicks.ts web/components/ownerdeepdive/pastPicks.test.ts
git commit -m "feat(draft-results): TS types + pure helpers for totals and all-time"
```

---

### Task 7: Frontend — render status chip, GS column, totals row, All-Time tab

**Files:**
- Modify: `web/components/ownerdeepdive/PastPicksTable.tsx`

**Interfaces:**
- Consumes: `flattenAllTime`, `columnTotals`, `ALL_TIME` (Task 6); `DraftPickResult.games_started` / `.roster_status` (Task 6).

- [ ] **Step 1: Import the helpers and add a status-chip component**

In `web/components/ownerdeepdive/PastPicksTable.tsx`, after the existing imports (line 5), add:

```typescript
import { flattenAllTime, columnTotals, ALL_TIME } from "./pastPicks";
```

After the `Delta` component (after line 18), add a status chip:

```typescript
const STATUS_META: Record<DraftPickResult["roster_status"], { label: string; cls: string }> = {
  rostered: { label: "Rostered", cls: "text-pos border-pos/40" },
  traded: { label: "Traded", cls: "text-dim border-divider" },
  dropped: { label: "Dropped", cls: "text-neg border-neg/40" },
};

function StatusChip({ status }: { status: DraftPickResult["roster_status"] }) {
  const m = STATUS_META[status] ?? STATUS_META.dropped;
  return (
    <span className={`inline-block font-mono text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${m.cls}`}>
      {m.label}
    </span>
  );
}
```

- [ ] **Step 2: Add the All-Time entry to the selector and resolve rows**

In `PastPicksTable.tsx`, replace the rows-resolution + selector setup. Change line 24-31 from:

```typescript
  const seasons = Object.keys(bySeason).sort().reverse(); // most recent first
  const [active, setActive] = useState<string>(seasons[0] ?? "");

  if (seasons.length === 0) {
    return <div className="text-dim text-[12px]">No completed rookie drafts yet.</div>;
  }

  const rows = bySeason[active] ?? [];
```

to:

```typescript
  const seasons = Object.keys(bySeason).sort().reverse(); // most recent first

  const [active, setActive] = useState<string>(seasons[0] ?? "");

  if (seasons.length === 0) {
    return <div className="text-dim text-[12px]">No completed rookie drafts yet.</div>;
  }

  const tabs = [...seasons, ALL_TIME];
  const rows = active === ALL_TIME ? flattenAllTime(bySeason) : (bySeason[active] ?? []);
  const totals = columnTotals(rows);
```

- [ ] **Step 3: Render the All-Time tab button**

In `PastPicksTable.tsx`, change the selector map (lines 36-44) to iterate `tabs` and label the sentinel. Replace `{seasons.map((s) => (` block with:

```typescript
        {tabs.map((s) => (
          <button key={s} type="button" onClick={() => setActive(s)}
            className={`font-mono text-[11px] px-2.5 py-1 rounded border transition-colors ${
              s === active
                ? "border-ink text-ink font-bold"
                : "border-divider text-dim hover:text-ink"}`}>
            {s === ALL_TIME ? "All-Time" : s}
          </button>
        ))}
```

- [ ] **Step 4: Add the Status and GS header cells**

In `PastPicksTable.tsx`, in the `<thead>` row, add a Status header after the `Acquired` `<th>` (after line 53) and a GS header after the `Toilet Pts` `<th>` (after line 77).

After the Acquired `<th>` (line 53):

```typescript
              <th className="text-left font-normal px-1 pb-1.5">Status</th>
```

After the Toilet Pts `<th>` (line 77):

```typescript
              <th className={numTh}>
                GS <InfoTooltip title="Games Started" body="Number of weeks you started this player while he was on your roster, across all phases." align="right" />
              </th>
```

- [ ] **Step 5: Add the Status and GS body cells**

In `PastPicksTable.tsx`, in the `<tbody>` row map, add a Status cell after the Acquired `<td>` (after line 90) and a GS cell after the Toilet Pts `<td>` (after line 98).

After the Acquired `<td>` (line 88-90):

```typescript
                <td className="text-left px-1 py-1.5">
                  <StatusChip status={r.roster_status} />
                </td>
```

After the Toilet Pts `<td>` (line 98):

```typescript
                <td className={numTd}>{r.games_started}</td>
```

- [ ] **Step 6: Add the totals row**

In `PastPicksTable.tsx`, add a `<tfoot>` after the closing `</tbody>` (after line 101). The column order must match the header: Player | Rnd | Acquired | Status | Current | Lowest | Highest | Avg Pick Value | Total | Reg | Playoff | Toilet | GS.

```typescript
          <tfoot>
            <tr className="border-t-2 border-ink font-semibold">
              <td className="text-left pr-1 py-1.5">Total</td>
              <td className="px-1 py-1.5" />
              <td className="px-1 py-1.5" />
              <td className="px-1 py-1.5" />
              <td className={numTd}>{val(totals.current_value)}</td>
              <td className={`${numTd} text-dim`}>{val(totals.lowest_value)}</td>
              <td className={`${numTd} text-dim`}>{val(totals.highest_value)}</td>
              <td className={numTd}><Delta n={totals.deltaSum} /></td>
              <td className={numTd}>{pts(totals.production_total)}</td>
              <td className={numTd}>{pts(totals.production_regular)}</td>
              <td className={numTd}>{pts(totals.production_playoff)}</td>
              <td className={numTd}>{pts(totals.production_toilet)}</td>
              <td className={numTd}>{totals.games_started}</td>
            </tr>
          </tfoot>
```

- [ ] **Step 7: Widen the table min-width**

In `PastPicksTable.tsx`, the `<table>` className has `min-w-[780px]` (line 48). Two columns were added; change it to `min-w-[920px]`.

- [ ] **Step 8: Verify the helper tests still pass and the app builds**

Run: `cd web && npx vitest run components/ownerdeepdive/pastPicks.test.ts`
Expected: PASS

Run: `cd web && npm run build`
Expected: build succeeds (catches missing `"use client"` / type errors). Note: do NOT run `next build` while `next dev` is live (corrupts `.next`).

- [ ] **Step 9: Commit**

```bash
git add web/components/ownerdeepdive/PastPicksTable.tsx
git commit -m "feat(draft-results): status chip, GS column, totals row, All-Time tab"
```

---

### Task 8: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the engine + backend suites**

Run: `pytest -q` (repo root) and the backend `make test` portion.
Expected: PASS.

- [ ] **Step 2: Run the frontend unit suite**

Run: `cd web && npx vitest run`
Expected: PASS.

- [ ] **Step 3: Grep for any stale references**

Run: `grep -rn "min-w-\[780px\]" web/components/ownerdeepdive/PastPicksTable.tsx`
Expected: no matches (confirms the width bump landed).

- [ ] **Step 4: Manual smoke (optional but recommended)**

Start `make dev-api` + `make dev-web`, refresh a league, open an owner page → Outlook tab → "How past picks panned out": confirm the status chips, GS column, totals row, and All-Time tab render and that totals add up. A real refresh is required for the new fields to populate (schema bump invalidates old caches).

---

## Self-Review

**Spec coverage:**
- Totals row (every numeric column) → Task 6 (`columnTotals`) + Task 7 Step 6. ✓
- All-Time view (extra tab, picks listed, sorted, own totals) → Task 6 (`flattenAllTime`, `ALL_TIME`) + Task 7 Steps 2-3. ✓
- Roster status chip → Tasks 2, 3, 4, 5, 7. ✓
- Games started (one combined number) → Tasks 1, 3, 4, 5, 7. ✓
- Cache schema bump → Task 5 Step 3. ✓
- Tests (engine pure + FE helpers) → Tasks 1-3, 6. ✓

**Type consistency:** `games_started: int`/`number` and `roster_status: str`/`"rostered"|"traded"|"dropped"` are consistent across engine dict, Pydantic model, TS type, and helpers. `columnTotals` returns `deltaSum` (sum of `current_value - avg_slot_value`), consumed by the `<Delta>` component in the totals row. `flattenAllTime`/`columnTotals`/`ALL_TIME` names match between Task 6 definitions and Task 7 consumption.

**Placeholder scan:** none — every code step shows full content.

**Note on roster_status edge:** a drafted player who was traded away and later re-acquired and is currently rostered resolves to `"rostered"` (current_holders wins), which is the desired "is he on the team now" semantic.
