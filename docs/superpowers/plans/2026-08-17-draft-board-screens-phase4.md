# Draft Board Phase 4 — Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the draft board's screen layer — a grouped sortable header, per-column sorting that reorders desktop rows and phone cards together, definition tooltips on every non-identity column, and a Draft entry in both navs.

**Architecture:** Four independent seams. `SortButton` is mirrored from `.design/` into `web/components/furniture/` (the last unmirrored primitive this phase needs; `GroupedHead` landed in `3f1e973` and `InfoTooltip.tsx` already exists and is the app's sanctioned tooltip — do NOT mirror `.design/`'s `Tooltip`). `DraftBoard.tsx` gains one sorted array feeding both bodies. The header becomes a `GroupedHead` whose `groups` are computed per grid template. A new `/league/[id]/draft` route redirects to the newest season, which needs a small backend seasons endpoint.

**Tech Stack:** Next.js 14 App Router (RSC + client components), Tailwind against `.design/` tokens, vitest + @testing-library/react, FastAPI backend.

**Spec:** `docs/superpowers/specs/2026-08-17-draft-board-redesign-design.md` (§ Screens, § The column budget, § GroupedHead). Approved GroupedHead resolutions: `docs/superpowers/specs/2026-08-17-groupedhead-design-proposal.md`.

## Global Constraints

- **Branch is `new-draft-board`. Never commit to `main`. Do NOT push** — the controller handles pushes.
- **Never render "KTC"** anywhere in the UI. It is "Trade Value" / "Value".
- **Tailwind grid templates must be complete literal strings.** The JIT scanner reads source as text; an interpolated or concatenated `grid-cols-[...]` silently loses columns in a production build while jsdom tests still pass. Every template is a full `const` string, and `min-[870px]` is written out at each use site.
- **Reuse, don't invent.** `.design/` primitives only; adding an entry to `web/tests/furniture-rules.test.ts`'s exception list is never the answer. If a screen resists the vocabulary, stop and report it.
- **No colour on data.** Figures reconcile with the rows beneath them.
- **Sorting must reorder BOTH bodies** — desktop rows and phone `EntryCard`s — from the same array. Reordering only the desktop rows desynchronises them: invisible on desktop, wrong on a phone.
- **The 44px label tier in `GroupedHead` is not negotiable** (it is a `SortButton`'s tap target). The `InfoTooltip` trigger's 26px target is equally deliberate and must NOT be raised to 44px.
- Run before claiming done: `cd web && npx vitest --config tests/vitest.config.ts run` (bare `npx vitest run` silently uses NO config and fails on JSX) and `npx tsc --noEmit`. For backend work also `cd api && pytest tests/`.
- `npx tsc --noEmit` currently emits two PRE-EXISTING errors about `.next/types/app/preview/page.ts` referencing a deleted `app/preview/page`. Those are stale generated artifacts, not your regression. Any OTHER error is yours.

---

### Task 1: Mirror `SortButton` into furniture

**Files:**
- Create: `web/components/furniture/SortButton.tsx`
- Test: `web/tests/SortButton.test.tsx`

**Interfaces:**
- Consumes: `web/components/furniture/Mark.tsx` (`Mark`), `web/components/furniture/merge.ts` (`mergeClasses`).
- Produces: `export type SortDir = "none" | "ascending" | "descending"` and `export function SortButton(props: { children?: ReactNode; sort?: SortDir; onClick?: () => void; align?: "left" | "right"; className?: string })`. Tasks 2 and 3 import both.

**Background:** read `.design/components/controls/SortButton.jsx` and its `.prompt.md` first — that is the contract. Mirror it the way `web/components/furniture/Row.tsx` mirrors `Row.jsx`: Tailwind utilities against tokens instead of inline styles, `mergeClasses` for the caller override, and the `.design/` docstring's reasoning preserved.

`StandingsTable.tsx` has its OWN inline sort header (`aria-sort` around line 417, `toggleSort` around 528). **Do not refactor it** — that is a separate, tested surface and is out of scope. It is a known second dialect; the controller has recorded it as a follow-up.

Two things the mirror must get right, both already learned in `Row.tsx`:

- Tailwind's preflight sets `text-transform: none` on `<button>`, so the header row's `uppercase` does NOT reach inside. The button must repeat `uppercase` on itself or a sortable column renders in a different case from a fixed one. (This exact bug split the standings header in two.)
- Font, letterspacing and colour otherwise inherit, so a sortable column is typographically identical to a fixed one.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/SortButton.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SortButton } from "@/components/furniture/SortButton";

describe("SortButton", () => {
  it("carries direction on aria-sort", () => {
    render(<SortButton sort="descending">Total</SortButton>);
    expect(screen.getByRole("button").getAttribute("aria-sort")).toBe("descending");
  });

  it("defaults to none", () => {
    render(<SortButton>Total</SortButton>);
    expect(screen.getByRole("button").getAttribute("aria-sort")).toBe("none");
  });

  it("repeats uppercase on the button itself", () => {
    // Tailwind preflight sets text-transform:none on <button>, so inheriting
    // the head row's `uppercase` is NOT enough — this is the bug that split
    // the standings header in two.
    render(<SortButton>Total</SortButton>);
    expect(screen.getByRole("button").className).toMatch(/\buppercase\b/);
  });

  it("keeps the 44px target on the button, not the row", () => {
    render(<SortButton>Total</SortButton>);
    expect(screen.getByRole("button").className).toMatch(/\bmin-h-tap\b/);
  });

  it("fires onClick", async () => {
    const onClick = vi.fn();
    const { default: userEvent } = await import("@testing-library/user-event");
    render(<SortButton onClick={onClick}>Total</SortButton>);
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("right-aligns a numeric column across the full cell", () => {
    render(<SortButton align="right">Total</SortButton>);
    const cn = screen.getByRole("button").className;
    expect(cn).toMatch(/\bjustify-end\b/);
    expect(cn).toMatch(/\bw-full\b/);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/SortButton.test.tsx`
Expected: FAIL — cannot resolve `@/components/furniture/SortButton`.

- [ ] **Step 3: Write `web/components/furniture/SortButton.tsx`**

Mirror `.design/components/controls/SortButton.jsx`. The mark is `sort-asc` when ascending and `sort-desc` otherwise, at `size={12}`, dimmed to 30% opacity when `sort === "none"`. Active state (`sort !== "none"`) takes `text-ink`; inactive inherits. Confirm `sort-asc` and `sort-desc` exist in `web/components/furniture/fx-icon-paths.ts` before wiring them (they do).

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/SortButton.test.tsx tests/furniture-rules.test.ts`
Expected: PASS, including the drift guard.

- [ ] **Step 5: Commit**

```bash
git add web/components/furniture/SortButton.tsx web/tests/SortButton.test.tsx
git commit -m "feat(web): mirror SortButton into furniture"
```

---

### Task 2: Sort the picks and owners ledgers from one array

**Files:**
- Modify: `web/components/DraftBoard.tsx`
- Create: `web/lib/draft-sort.ts`
- Test: `web/tests/draft-sort.test.ts`, extend `web/tests/draft-board.test.tsx`

**Interfaces:**
- Consumes: `SortButton`, `SortDir` from Task 1.
- Produces: `web/lib/draft-sort.ts` exporting

```ts
// SortDir is DEFINED IN Task 1's SortButton.tsx and imported here — do not
// declare a second copy. (Controller ruling, pre-flight scan.)
import type { SortDir } from "@/components/furniture/SortButton";
export interface SortState { key: string; dir: "ascending" | "descending" }
/** Pure. Returns a NEW array; never mutates. Nulls sort last in both
 *  directions — an absent figure is not a small one. */
export function sortRows<T>(rows: T[], state: SortState | null, get: (row: T, key: string) => string | number | null | undefined): T[];
/** The next state for a click on `key`. First click on a numeric column opens
 *  descending (the interesting end); on a text column, ascending. Clicking the
 *  active column flips it. */
export function nextSort(current: SortState | null, key: string, numeric: boolean): SortState;
```

Task 3 renders the header that drives this; keep the exported names stable.

**Why a separate lib file:** the ordering rules are pure and deserve their own unit tests, and `DraftBoard.tsx` is already 576 lines.

- [ ] **Step 1: Write the failing pure tests**

```ts
// web/tests/draft-sort.test.ts
import { describe, it, expect } from "vitest";
import { sortRows, nextSort } from "@/lib/draft-sort";

const get = (r: Record<string, unknown>, k: string) => r[k] as number | string | null;

describe("sortRows", () => {
  const rows = [{ n: 3 }, { n: 1 }, { n: 2 }];

  it("does not mutate its input", () => {
    const copy = [...rows];
    sortRows(rows, { key: "n", dir: "ascending" }, get);
    expect(rows).toEqual(copy);
  });

  it("returns the original order when there is no sort", () => {
    expect(sortRows(rows, null, get)).toEqual(rows);
  });

  it("sorts numbers, both ways", () => {
    expect(sortRows(rows, { key: "n", dir: "ascending" }, get).map((r) => r.n)).toEqual([1, 2, 3]);
    expect(sortRows(rows, { key: "n", dir: "descending" }, get).map((r) => r.n)).toEqual([3, 2, 1]);
  });

  it("sorts strings case-insensitively", () => {
    const s = [{ v: "beta" }, { v: "Alpha" }, { v: "gamma" }];
    expect(sortRows(s, { key: "v", dir: "ascending" }, get).map((r) => r.v)).toEqual(["Alpha", "beta", "gamma"]);
  });

  it("puts nulls last in BOTH directions", () => {
    // An absent figure is not a small one. A null that sorts to the top
    // descending would read as the best pick in the class.
    const n = [{ v: 5 }, { v: null }, { v: 9 }];
    expect(sortRows(n, { key: "v", dir: "descending" }, get).map((r) => r.v)).toEqual([9, 5, null]);
    expect(sortRows(n, { key: "v", dir: "ascending" }, get).map((r) => r.v)).toEqual([5, 9, null]);
  });

  it("is stable for equal keys", () => {
    const t = [{ v: 1, id: "a" }, { v: 1, id: "b" }, { v: 0, id: "c" }];
    expect(sortRows(t, { key: "v", dir: "descending" }, get).map((r) => r.id)).toEqual(["a", "b", "c"]);
  });
});

describe("nextSort", () => {
  it("opens a numeric column descending", () => {
    expect(nextSort(null, "total", true)).toEqual({ key: "total", dir: "descending" });
  });

  it("opens a text column ascending", () => {
    expect(nextSort(null, "player", false)).toEqual({ key: "player", dir: "ascending" });
  });

  it("flips the active column", () => {
    expect(nextSort({ key: "total", dir: "descending" }, "total", true)).toEqual({ key: "total", dir: "ascending" });
    expect(nextSort({ key: "total", dir: "ascending" }, "total", true)).toEqual({ key: "total", dir: "descending" });
  });

  it("switching columns opens the new one at its own default", () => {
    expect(nextSort({ key: "total", dir: "ascending" }, "player", false)).toEqual({ key: "player", dir: "ascending" });
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/draft-sort.test.ts`
Expected: FAIL — cannot resolve `@/lib/draft-sort`.

- [ ] **Step 3: Write `web/lib/draft-sort.ts`**

Use a decorated stable sort (map to `{row, i}`, compare, fall back to `i`) so equal keys keep their incoming order. `Array.prototype.sort` is spec-stable in modern V8, but the fallback makes the intent explicit and testable.

- [ ] **Step 4: Verify it passes**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/draft-sort.test.ts`
Expected: PASS.

- [ ] **Step 5: Wire it into `DraftBoard.tsx`**

`PicksSection` and `OwnersSection` each hold one `SortState | null` in `useState` and derive **one** sorted array with `useMemo`. **That same array feeds the desktop rows and the phone `EntryCard` list.** Do not sort in two places.

Accessor maps — a `key` per sortable column pointing at the row field:

- Picks: `pick` (use the flat draft order, not the label), `owner` (owner name), `player`, `ecr`, `slot_delta`, `verdict`, `total`, `start_pct`, `gs`, `now`.
- Owners: `rank`, `owner`, `par`, `total`, `start_pct`, `regular`, `playoff`, `toilet`, `hit_bust`, `picks`.

Two orderings that are not the obvious ones:

- **`verdict` is ordinal, not alphabetical.** Rank it Hit → Average → Bust → unlabelled so descending reads best-first. Alphabetical would put Average above Bust above Hit, which is meaningless.
- **`now` is ordinal too**: Rostered → Traded → Dropped → Inactive.

Default sort for picks stays the natural draft order (`null` state). Do not open the table pre-sorted on a metric.

- [ ] **Step 6: Extend `web/tests/draft-board.test.tsx`**

Add tests that:
1. Clicking a picks column header reorders the desktop rows.
2. **The phone cards reorder identically** — assert on `[data-testid="draft-picks-mobile"]`'s rendered order, matching the desktop order. This is the test that catches the desync the spec calls out; without it the whole sorting feature can ship half-broken and look fine.
3. `aria-sort` moves to the clicked column and the previously-sorted column returns to `none`.
4. Unlabelled/null verdict rows sort last, not first, when sorting Verdict descending.

- [ ] **Step 7: Run the frontend suite**

Run: `cd web && npx vitest --config tests/vitest.config.ts run && npx tsc --noEmit`
Expected: PASS (ignoring the two pre-existing `app/preview` type errors).

- [ ] **Step 8: Commit**

```bash
git add web/lib/draft-sort.ts web/tests/draft-sort.test.ts web/components/DraftBoard.tsx web/tests/draft-board.test.tsx
git commit -m "feat(web): sort the draft ledgers, desktop rows and phone cards from one array"
```

---

### Task 3: Grouped header and definition tooltips

**Files:**
- Modify: `web/components/DraftBoard.tsx`
- Create: `web/lib/draft-columns.ts`
- Test: `web/tests/draft-columns.test.ts`, extend `web/tests/draft-board.test.tsx`

**Interfaces:**
- Consumes: `GroupedHead` + `HeadGroup` from `@/components/furniture/GroupedHead`, `SortButton` from Task 1, `SortState`/`nextSort` from Task 2, `InfoTooltip` from `@/components/InfoTooltip`.
- Produces: `web/lib/draft-columns.ts` exporting `pickGroups(...)` and `COLUMN_DEFS`.

**CONTROLLER RULING (pre-flight scan) — this task covers BOTH sections, not just Picks.** The spec's "Header is grouped" sits under the Picks description, but `OwnersSection`'s widest template (`OWNER_GRID_GRADED_ADP`) is 10 tracks and carries the same Total · Start % · Regular · Playoff · Toilet family. That is the strongest case for the primitive anywhere in the app — factoring out the shared word so four columns stop printing "Points" is the exact justification `GroupedHead` was approved on. Applying it to Picks and leaving Owners as a flat run would put two header dialects in one panel.

So: `pickGroups` gets a sibling `ownerGroups`, the four `OWNER_GRID_*` templates move to `draft-columns.ts` and convert to raw strings alongside the pick ones, and `OWNER_GRIDS` joins `PICK_GRIDS` in the arithmetic test (the "covers every template's tracks" and "null below the floor" tests should loop over both records). The eight-column floor applies independently to each: `OWNER_GRID_MIN` is 2 tracks and keeps the plain head.

**The hard part.** `DraftBoard.tsx` has **seven** pick-grid templates (`GRID_P_PLAIN` … `GRID_PB_VERDICT`, lines ~434-440) with track counts from 4 to 10, chosen by `pickGrid(hasBaseline, graded, hasVerdicts, hasProjections)`. `GroupedHead`'s spans must sum to the track count **of whichever template is active**, so the groups are computed by a parallel function keyed on exactly the same arguments.

`GroupedHead` warns in dev when the spans do not cover the tracks — that warning is your fastest signal that a template and its groups have drifted. It is a `console.warn`, so it will not fail a test on its own; the tests below assert the arithmetic directly.

**`GroupedHead` is for 8+ columns only.** Four of the seven templates are below that floor. **Narrow templates keep the plain `Row variant="head"`** — do not force a naming tier onto a five-column table. Decide per template and test both paths.

- [ ] **Step 1: Write the failing arithmetic tests**

```ts
// web/tests/draft-columns.test.ts
import { describe, it, expect } from "vitest";
import { pickGroups, PICK_GRIDS } from "@/lib/draft-columns";

/** Count grid tracks in a raw `grid-template-columns` string, ignoring any
 *  spaces inside a function like `minmax(0, 1fr)`. */
function tracks(cols: string): number {
  let depth = 0, flat = "";
  for (const ch of cols) {
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    else if (depth === 0) flat += ch;
  }
  return flat.trim().split(/\s+/).filter(Boolean).length;
}

describe("pickGroups", () => {
  it("covers every template's tracks exactly", () => {
    // The whole contract. A short sum slides every later cap one column left.
    for (const [name, { cls, args }] of Object.entries(PICK_GRIDS)) {
      const groups = pickGroups(args);
      if (!groups) continue; // narrow templates keep the plain head
      const sum = groups.reduce((n, g) => n + g.span, 0);
      expect(sum, `${name} spans must cover its tracks`).toBe(tracks(cls));
    }
  });

  it("returns null below the eight-column floor", () => {
    for (const [name, { cls, args }] of Object.entries(PICK_GRIDS)) {
      if (tracks(cls) < 8) {
        expect(pickGroups(args), `${name} is under the floor`).toBeNull();
      }
    }
  });

  it("caps the Points family, and leaves identity uncapped", () => {
    const groups = pickGroups({ hasBaseline: true, graded: true, hasVerdicts: true, hasProjections: false })!;
    expect(groups[0].label).toBeUndefined();     // identity run is capless
    expect(groups.map((g) => g.label).filter(Boolean)).toContain("Points");
  });
});
```

`PICK_GRIDS` is a record mapping each template name to `{ cls, args }` — the literal class string and the exact `pickGrid` arguments that select it. Export it from `draft-columns.ts` and have `DraftBoard.tsx` use those same constants, so the templates cannot drift from what the test measures.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/draft-columns.test.ts`
Expected: FAIL — cannot resolve `@/lib/draft-columns`.

- [ ] **Step 3: Write `web/lib/draft-columns.ts`**

Move the seven `GRID_*` literals here as complete literal strings (they must stay complete — see Global Constraints), add `PICK_GRIDS`, `pickGroups`, and `COLUMN_DEFS`.

`COLUMN_DEFS` is a record from column key to `{ label: string; title: string; body: string; formula?: string }`. Write real definitions — a trigger with no definition is worse than no trigger.

**CONTROLLER CORRECTION — use these exact keys, verified against `DraftBoard.tsx` after Task 2.** Two earlier briefs in this phase named things that did not exist because I wrote them from the spec's target state instead of the code; do not repeat it. The sort keys Task 2 actually established are:

```
pick  owner  player  rank            <- IDENTITY: no tooltip trigger, ever
ecr  slot_delta  verdict  total  start_pct  gs  now  par  regular  playoff  toilet  adp  coverage
```

`adp` and `coverage` are real columns and **need definitions** — my original list omitted them. There is no `hit_bust` and no `picks` column; the Owners table's 9th/10th are ADP +/- and Coverage. A `Proj` column also exists on ungraded classes and needs a definition, though it has no sort key — check whether it is reachable before adding a trigger to it.

`InfoTooltip`'s props are exactly `{ title: string; body: string; formula?: string; align?: "left" | "right" }` — use `align="right"` on right-aligned numeric columns so the panel does not run off the edge.

Definitions to write, at minimum:

- `ecr` — the rookie consensus board rank on draft night, and that it is pinned to the draft's own date, not today's.
- `slot_delta` — draft position minus that consensus rank; positive means taken later than the board had him.
- `verdict` — Hit / Average / Bust against the **cohort of picks in the same ECR band held the same number of seasons**, by percentile. Not a fixed threshold.
- `total` — Total Points, received-only, bench included, all weeks.
- `start_pct` — Start %: the share of this player's points that were in a started lineup for this owner.
- `gs` — games started for the drafting owner, all phases.
- `now` — the pick's current standing for the drafting owner: Rostered / Traded / Dropped / Inactive.
- `par` — Points Above Round (owners table): production against the average pick in the same round of this draft, zero-sum within the class.
- Owners-table `regular` / `playoff` / `toilet` — the five-metric vocabulary, verbatim from CLAUDE.md.
- `adp` — the pick's position against Sleeper ADP **pinned to that draft's own date**, never today's; a draft predating the first daily snapshot has no ADP baseline, permanently.
- `coverage` — how many of the owner's picks had an ADP baseline at all, which is why the figure can be blank rather than zero.
- `proj` (ungraded classes only) — preseason projected points, the only forward-looking figure available before a class has played; it is superseded once the class is graded.

Keep the five metric labels exactly as the vocabulary fixes them: **Trade Value · Total Points · Regular Season Points · Playoff Points · Toilet Bowl Points**.

- [ ] **Step 4: Verify the arithmetic tests pass**

Run: `cd web && npx vitest --config tests/vitest.config.ts run tests/draft-columns.test.ts`
Expected: PASS.

- [ ] **Step 5: Render the grouped header in `DraftBoard.tsx`**

For a template at 8+ tracks, render `GroupedHead` with `cols` = the active template's track string and `groups` = `pickGroups(args)`; below the floor keep `Row variant="head"`. Each header cell holds a `SortButton` (Task 2's `nextSort` on click, `aria-sort` from the current state) and, for **non-identity** columns only, an `InfoTooltip` from `COLUMN_DEFS`.

**Identity columns carry no tooltip trigger** — Round·Pick, Owner, Player and `#`. Their names are the whole explanation, and the user asked for this explicitly.

**CONTROLLER RULING (pre-flight scan) — convert this table to the `cols` string prop.** `GroupedHead` takes `cols` as a raw `grid-template-columns` **string** (applied via `style`), while `DraftBoard` currently threads Tailwind `grid-cols-[...]` **classes** through `className`. Mixing them — a header positioned by inline style over body rows positioned by a class — is exactly how the two silently drift out of column.

So in `draft-columns.ts` the seven templates become raw strings:

```ts
// was: "grid-cols-[40px_100px_minmax(170px,420px)_60px]"
export const GRID_P_PLAIN = "40px 100px minmax(170px,420px) 60px";
```

and both the head and every body `Row` take `cols={grid}` instead of `className={grid}`. `Row` already supports the `cols` prop and applies it via `style` (see `Row.tsx`), so head and body share one constant by construction.

This also **retires the Tailwind JIT hazard for this table outright**: with no `grid-cols-[...]` class left, there is nothing for the scanner to miss, and the "literal complete string" rule in Global Constraints stops being load-bearing here. `min-[870px]` is a normal utility and stays a written-out literal at both use sites — that part is unchanged.

Keep the `PICK_GRIDS` test helper in step with this: it should split the raw string on **whitespace**, not on `_`.

- [ ] **Step 6: Extend `web/tests/draft-board.test.tsx`**

1. A graded class with verdicts renders the naming tier, with a **Points** cap whose `aria-colspan` matches the number of point columns.
2. A narrow class (no baseline, ungraded) renders NO naming tier.
3. Identity columns render no tooltip trigger; each non-identity column renders exactly one.
4. Every rendered tooltip trigger has a non-empty definition body (guards the "trigger with no definition" failure).

- [ ] **Step 7: Full frontend run**

Run: `cd web && npx vitest --config tests/vitest.config.ts run && npx tsc --noEmit`
Expected: PASS. The drift guard must stay green — if it goes red, fix the code, never the guard's exception list.

- [ ] **Step 8: Commit**

```bash
git add web/lib/draft-columns.ts web/tests/draft-columns.test.ts web/components/DraftBoard.tsx web/tests/draft-board.test.tsx
git commit -m "feat(web): grouped draft-board header with definition tooltips"
```

---

### Task 4: Draft in both navs, and a `/draft` redirect route

**Files:**
- Modify: `web/components/TopBar.tsx` (NAV array ~line 40), `web/components/DashboardTabs.tsx` (TABS array ~line 30)
- Create: `web/app/league/[id]/draft/page.tsx`
- Modify: `api/app/routes/draft.py`, `web/lib/api.ts`
- Test: `web/tests/draft-nav.test.tsx`, extend `api/tests/test_draft_routes.py`

**Interfaces:**
- Consumes: `available_seasons(entry)` from `api/app/services/draft_board_view.py` (already exists, already used by the 404 detail).
- Produces: `GET /api/league/{league_id}/draft/seasons` → `{"seasons": [int, ...]}` newest first; `draftSeasons(leagueId)` in `web/lib/api.ts`.

**Why a new endpoint:** the nav cannot link to a season it does not know, and `TopBar` has no dashboard data. `DraftBoardResp` carries `seasons`, but fetching it requires already knowing a season — the chicken-and-egg the redirect route exists to break.

- [ ] **Step 1: Write the failing backend test**

```python
# api/tests/test_draft_routes.py — add
def test_draft_seasons_lists_newest_first(client, warm_league):
    r = client.get(f"/league/{warm_league}/draft/seasons")
    assert r.status_code == 200
    seasons = r.json()["seasons"]
    assert seasons == sorted(seasons, reverse=True)


def test_draft_seasons_409s_on_a_cold_cache(client, cold_league):
    # Same cold-start contract as every other dashboard endpoint.
    assert client.get(f"/league/{cold_league}/draft/seasons").status_code == 409
```

Match the fixtures already used in that file rather than inventing new ones — read it first and follow its existing shape.

- [ ] **Step 2: Run and watch it fail**

Run: `cd api && pytest tests/test_draft_routes.py -v`
Expected: FAIL — 404, route does not exist.

- [ ] **Step 3: Add the route**

In `api/app/routes/draft.py`, beside the existing season route. It sits under the same `league_guard` as its neighbours and follows the same cold-cache 409 contract. **Register it so `/draft/seasons` cannot be captured by the `/draft/{season}` int path param** — declare it before, and note that `season` is typed `int` so `"seasons"` would 422 rather than match, but explicit ordering is clearer than relying on that.

- [ ] **Step 4: Verify backend green**

Run: `cd api && pytest tests/ -q`
Expected: PASS.

- [ ] **Step 5: Add `draftSeasons` to `web/lib/api.ts`**

Mirror the `draftBoard` docstring style, noting the 409 cold-cache behaviour.

- [ ] **Step 6: Write `web/app/league/[id]/draft/page.tsx`**

A server component that fetches the seasons and `redirect()`s to `/league/{id}/draft/{newest}`.

**On any failure — 409 cold cache, network, or an empty list — redirect to the current NFL season's board instead of erroring.** That page already owns the cold-start and 404 experiences (`DraftBoardErrorState` names the seasons that DO exist and links them), so falling through to it is strictly better than a second error surface. Do not duplicate that error UI here.

`redirect()` throws a Next control-flow error — call it OUTSIDE any `try` block, or the `catch` swallows the redirect and the route hangs.

- [ ] **Step 7: Add Draft to both navs**

- `TopBar.tsx`: append to `NAV` — `{ key: "draft", label: "Draft", href: (id) => \`/league/${id}/draft\` }`. **No icon.** Nothing in the nineteen marks reads as "draft", and Bets already sets the precedent of an unmarked item; drawing a twentieth is how a drawn set stops being a set. Note the existing entries use `tab`, not `href` — Draft is a real route, not a dashboard tab, so follow whatever shape `TopBar` already uses for a route-style link, and if none exists, add the minimum branch rather than reshaping the array.
- `DashboardTabs.tsx`: append `{ key: "draft", label: "Draft", href: (id) => \`/league/${id}/draft\` }` — four full-width cells become five (78px each at 390px; the 44px height is untouched).

- [ ] **Step 8: Write `web/tests/draft-nav.test.tsx`**

1. `TopBar` renders a Draft link pointing at `/league/{id}/draft`.
2. `DashboardTabs` renders five cells, the fifth being Draft.
3. The Draft nav item renders **no icon/mark** (assert no `svg` inside that link, matching how the Bets item is treated).

- [ ] **Step 9: Full run, both suites**

Run: `cd web && npx vitest --config tests/vitest.config.ts run && npx tsc --noEmit` and `cd api && pytest tests/ -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add web/components/TopBar.tsx web/components/DashboardTabs.tsx "web/app/league/[id]/draft/page.tsx" web/lib/api.ts web/tests/draft-nav.test.tsx api/app/routes/draft.py api/tests/test_draft_routes.py
git commit -m "feat(web,api): Draft in both navs, with a newest-season redirect"
```

---

## Notes for the controller

- **Task 1 must land before Tasks 2 and 3.** Tasks 2 and 3 both touch `DraftBoard.tsx`; run them in order, never in parallel. Task 4 is independent of all three and touches no shared file.
- **The spec's "Reconciliation, unresolved" risk (§ Risks, ~line 434) is CLOSED and the spec is stale.** The ~6% gap was an artefact of the independent recomputation, not the app: `_assemble_played_matchups` drops unpaired roster-weeks, so the app's figures were right. Update that section when convenient; it is not part of this phase's tasks.
- `StandingsTable.tsx`'s inline sort header is now a second dialect alongside `SortButton`. Deliberately out of scope — record it, do not fix it here.
