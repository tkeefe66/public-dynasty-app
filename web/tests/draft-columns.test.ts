import { describe, it, expect } from "vitest";
import {
  pickGroups, ownerGroups, ownerGrid, PICK_GRIDS, OWNER_GRIDS, GRID_GOING_IN,
  OWNER_GRID_MIN, OWNER_GRID_ADP_ONLY, OWNER_GRID_GRADED_ONLY,
  OWNER_GRID_GRADED_VERDICT, OWNER_GRID_GRADED_ADP,
} from "@/lib/draft-columns";

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

/** Both ledgers' templates, in one record, so the three rules below apply
 *  identically to Picks and Owners rather than being duplicated per section
 *  (controller ruling: "the arithmetic test loops over both records"). */
const ALL_GRIDS: Record<
  string,
  { cls: string; args: { hasBaseline?: boolean; hasProjections?: boolean; graded: boolean; hasVerdicts?: boolean; hasAdpColumns?: boolean } }
> = { ...PICK_GRIDS, ...OWNER_GRIDS };

/** Splits a raw `grid-template-columns` string into its individual tracks,
 *  keeping a `minmax(a,b)` intact as one token (same depth-tracking idea as
 *  `tracks()` above, but collecting tokens instead of just counting them). */
function trackList(cols: string): string[] {
  const result: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of cols) {
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    if (ch === " " && depth === 0) {
      if (cur) result.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  if (cur) result.push(cur);
  return result;
}

/** The desktop header re-cut's own gate arithmetic (see `draft-columns.ts`'s
 *  docstrings above `GRID_P_PLAIN`/`OWNER_GRID_MIN`): a template's minimum
 *  rendered width is every fixed `px` track plus the flex track's OWN
 *  `minmax(min,...)` floor (170px on Picks' Player column, 140px on Owners'
 *  Owner column — read directly off the track string, not hardcoded here, so
 *  a future change to either floor can't silently drift out of step with
 *  this test) plus a 10px gap between every pair of tracks
 *  (`n` tracks → `n - 1` gaps) plus the 28px of horizontal cell padding
 *  (`px-3.5` = 14px * 2, applied by `Row`/`GroupedHead` on every row). This
 *  is the required PANEL CONTENT width — it must fit under `WIDTH_GATE_BUDGET_PX`
 *  (see below), not under the raw `min-[910px]:block` viewport gate both
 *  ledgers render behind (`DraftBoard.tsx`) — the viewport gives up 48px to
 *  `Shell`'s padding and 2px to `Panel`'s border before the grid ever sees it,
 *  so checking against the bare viewport number was the bug this suite used
 *  to have (see `WIDTH_GATE_BUDGET_PX`'s own comment). If the panel content
 *  doesn't fit that real budget, the desktop table never appears at the
 *  width it claims to fit. */
/** The width gate's REAL budget, not the raw breakpoint. Both ledgers' desktop
 *  tables render behind `min-[WIDTH_GATE_PX]px:block` (910, literal at every
 *  use site in `DraftBoard.tsx` — Tailwind's JIT scanner needs the class as
 *  literal source text). But the grid never sees the full viewport: `Shell.tsx`
 *  applies `px-3 sm:px-6 lg:px-8` (48px at this width — `sm` applies, `lg`
 *  does not, and `tailwind.config.ts` carries no `screens` override to move
 *  that boundary), and `Panel.tsx` adds a 1px border on each side (2px). A
 *  template's `minWidthPx()` must fit `WIDTH_GATE_PX − 48 − 2`, not
 *  `WIDTH_GATE_PX` itself — comparing against the raw gate is exactly how two
 *  templates (`GRID_PB_VERDICT` at 854px, `OWNER_GRID_GRADED_ADP` at 858px)
 *  shipped overflowing a `< 870` check while the real budget at that gate was
 *  only 820: both needed the gate raised, not the check loosened. */
const WIDTH_GATE_PX = 910;
const SHELL_HORIZONTAL_PADDING_PX = 48;
const PANEL_BORDER_PX = 2;
const WIDTH_GATE_BUDGET_PX = WIDTH_GATE_PX - SHELL_HORIZONTAL_PADDING_PX - PANEL_BORDER_PX; // 860
function minWidthPx(cols: string): number {
  const list = trackList(cols);
  const fixedAndFlexSum = list.reduce((sum, t) => {
    const flex = /^minmax\((\d+)px,\s*\d+px\)$/.exec(t);
    if (flex) return sum + Number(flex[1]);
    const fixed = /^(\d+)px$/.exec(t);
    if (fixed) return sum + Number(fixed[1]);
    throw new Error(`minWidthPx: unrecognized grid track "${t}" in "${cols}"`);
  }, 0);
  const gaps = 10 * (list.length - 1);
  const cellPadding = 28;
  return fixedAndFlexSum + gaps + cellPadding;
}

function groupsFor(name: string, args: (typeof ALL_GRIDS)[string]["args"]) {
  return name in PICK_GRIDS
    ? pickGroups(args as Parameters<typeof pickGroups>[0])
    : ownerGroups(args as Parameters<typeof ownerGroups>[0]);
}

describe("pickGroups / ownerGroups", () => {
  it("covers every template's tracks exactly", () => {
    // The whole contract. A short sum slides every later cap one column left.
    for (const [name, { cls, args }] of Object.entries(ALL_GRIDS)) {
      const groups = groupsFor(name, args);
      if (!groups) continue; // narrow templates keep the plain head
      const sum = groups.reduce((n, g) => n + g.span, 0);
      expect(sum, `${name} spans must cover its tracks`).toBe(tracks(cls));
    }
  });

  it("returns null below the eight-column floor", () => {
    for (const [name, { cls, args }] of Object.entries(ALL_GRIDS)) {
      if (tracks(cls) < 8) {
        expect(groupsFor(name, args), `${name} is under the floor`).toBeNull();
      }
    }
  });

  it("caps the Production family, and leaves identity uncapped, on the Picks ledger", () => {
    const groups = pickGroups({ hasBaseline: true, graded: true, hasVerdicts: true, hasProjections: false })!;
    expect(groups[0].label).toBeUndefined(); // identity run is capless
    expect(groups.map((g) => g.label).filter(Boolean)).toContain("Production");
  });

  it("caps the Production family, and leaves identity uncapped, on the Owners ledger", () => {
    const groups = ownerGroups({ graded: true, hasAdpColumns: true, hasVerdicts: false })!;
    expect(groups[0].label).toBeUndefined(); // identity run (# · Owner) is capless
    expect(groups.map((g) => g.label).filter(Boolean)).toContain("Production");
  });

  /* ---- fix round 1: "Points" was wrong (only Total is a points figure on
   * either grouped shape; Start %/GS/Regular/Playoff/Toilet are not) — pin
   * the intended label set exactly, so a silent relabel back to "Points"
   * (or a reintroduced single-column cap on Verdict/Now) fails here rather
   * than only failing a human reading the header. */
  it("labels every grouped template's caps exactly, and never re-introduces a single-column cap", () => {
    const verdictGroups = pickGroups({ hasBaseline: true, graded: true, hasVerdicts: true, hasProjections: false })!;
    // identity(3, capless) | Baseline(2) | Verdict(1, capless) | Production(3) | Now(1, capless)
    expect(verdictGroups.map((g) => g.label)).toEqual([undefined, "Baseline", undefined, "Production", undefined]);

    const gradedGroups = pickGroups({ hasBaseline: true, graded: true, hasVerdicts: false, hasProjections: false })!;
    // identity(3, capless) | Baseline(2) | Production(3) | Now(1, capless)
    expect(gradedGroups.map((g) => g.label)).toEqual([undefined, "Baseline", "Production", undefined]);

    const ownerAdpGroups = ownerGroups({ graded: true, hasAdpColumns: true, hasVerdicts: true })!;
    // identity(2, capless) | PAR(1, capless) | Production(5) | ADP(1, capless) | Coverage(1, capless)
    expect(ownerAdpGroups.map((g) => g.label)).toEqual([undefined, undefined, "Production", undefined, undefined]);

    const ownerGradedGroups = ownerGroups({ graded: true, hasAdpColumns: false, hasVerdicts: false })!;
    // identity(2, capless) | PAR(1, capless) | Production(5)
    expect(ownerGradedGroups.map((g) => g.label)).toEqual([undefined, undefined, "Production"]);

    // identity(2, capless) | PAR(1, capless) | Production(5) | Hit/Bust(1, capless).
    // Hit/Bust must NOT join the Production cap: it counts verdicts, it is not
    // a points figure, and a cap that swallowed it would put a "Production"
    // header over a column of counts.
    const ownerVerdictGroups = ownerGroups({ graded: true, hasAdpColumns: false, hasVerdicts: true })!;
    expect(ownerVerdictGroups.map((g) => g.label)).toEqual([undefined, undefined, "Production", undefined]);

    // Nowhere does "Points" survive as a cap label.
    for (const groups of [verdictGroups, gradedGroups, ownerAdpGroups, ownerGradedGroups]) {
      expect(groups.map((g) => g.label)).not.toContain("Points");
    }
  });
});

describe("ownerGrid template selection", () => {
  it("gives a graded class with verdicts the Hit/Bust template", () => {
    // Mutation this catches: `hasVerdicts` never reaching `ownerGrid`, so a
    // class with verdicts silently falls through to GRADED_ONLY and the
    // header renders a Hit/Bust cell into a template with no track for it —
    // which does not throw, it just slides every later cell one column left.
    expect(ownerGrid({ graded: true, hasAdpColumns: false, hasVerdicts: true }))
      .toBe(OWNER_GRID_GRADED_VERDICT);
    expect(ownerGrid({ graded: true, hasAdpColumns: false, hasVerdicts: false }))
      .toBe(OWNER_GRID_GRADED_ONLY);
  });

  it("keeps ADP when a class carries BOTH, rather than growing an 11th column", () => {
    // Mutation this catches: reordering `ownerGrid`'s two graded branches so
    // verdicts win. The args here are the ONLY combination that discriminates
    // between them — with just one of the two flags set, either order returns
    // the same template and the test cannot fail.
    //
    // ADP wins because OWNER_GRID_GRADED_ADP is already 858px against an
    // 860px budget: there is no room for Hit/Bust beside it, and the
    // alternative (dropping ADP +/- and Coverage from a class that HAS them)
    // trades a populated column for a rollup still readable per-pick on the
    // ledger below. See OWNER_GRID_GRADED_VERDICT's docstring.
    expect(ownerGrid({ graded: true, hasAdpColumns: true, hasVerdicts: true }))
      .toBe(OWNER_GRID_GRADED_ADP);
  });

  it("ignores verdicts entirely on an ungraded class", () => {
    // A class that has not played has nothing to roll up, so `hasVerdicts`
    // must not pull it off the narrow templates.
    expect(ownerGrid({ graded: false, hasAdpColumns: false, hasVerdicts: true }))
      .toBe(OWNER_GRID_MIN);
    expect(ownerGrid({ graded: false, hasAdpColumns: true, hasVerdicts: true }))
      .toBe(OWNER_GRID_ADP_ONLY);
  });
});

describe("desktop header width gate (Treatment C re-cut)", () => {
  // Both ledgers render their desktop table behind `min-[910px]:block`
  // (`DraftBoard.tsx`) — but the grid only ever sees `WIDTH_GATE_BUDGET_PX`
  // (860 = 910 − 48px Shell padding − 2px Panel border), not the raw 910.
  // A template whose own minimum width (see `minWidthPx` above) reaches that
  // real budget never actually fits the viewport width it claims to, so a
  // future column addition that pushes a template over the line must fail
  // here rather than silently wrapping (or clipping with no scroll
  // affordance) in a real browser.
  it("every template's computed minimum width fits under the real (post Shell/Panel) budget", () => {
    for (const [name, { cls }] of Object.entries(ALL_GRIDS)) {
      const width = minWidthPx(cls);
      expect(
        width,
        `${name} minimum width is ${width}px, over the ${WIDTH_GATE_BUDGET_PX}px real budget at the ${WIDTH_GATE_PX}px gate: "${cls}"`,
      ).toBeLessThanOrEqual(WIDTH_GATE_BUDGET_PX);
    }
  });

  it("the widest template on each ledger is the one measured in the docstrings", () => {
    // Pins the actual numbers so a silent per-track shrink (which would
    // still pass the <= budget check above) can't erode the documented slack
    // without this test catching the drift. These are unchanged by the gate
    // move (910 raised the BUDGET the templates are checked against; it did
    // not re-cut any track), so the pinned values from before the gate fix
    // still hold.
    expect(minWidthPx(PICK_GRIDS.GRID_PB_VERDICT.cls)).toBe(854);
    expect(minWidthPx(OWNER_GRIDS.OWNER_GRID_GRADED_ADP.cls)).toBe(858);
  });
});

/* ---- Task 7: the "Going in" panel's own template joins the same gate ----
 * Not folded into `ALL_GRIDS` above — that record feeds the grouped-header
 * suites (`pickGroups`/`ownerGroups`), which take `PickGridArgs`/
 * `OwnerGridArgs` shapes `GRID_GOING_IN` doesn't have (and, at four tracks,
 * doesn't need — it sits well under the eight-column floor those suites
 * gate on). This is the one assertion this brand-new template actually
 * needs: the same `minWidthPx` arithmetic, checked against the same real
 * (post Shell/Panel) budget every other template on this board answers to. */
describe("Going in panel width gate", () => {
  it("the Going in template's minimum width fits under the real (post Shell/Panel) budget", () => {
    const width = minWidthPx(GRID_GOING_IN);
    expect(
      width,
      `GRID_GOING_IN minimum width is ${width}px, over the ${WIDTH_GATE_BUDGET_PX}px real budget: "${GRID_GOING_IN}"`,
    ).toBeLessThanOrEqual(WIDTH_GATE_BUDGET_PX);
  });
});
