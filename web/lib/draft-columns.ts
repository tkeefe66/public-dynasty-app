import type { HeadGroup } from "@/components/furniture/GroupedHead";

/* ---------------------------------------------------------------------------
 * The draft board's eleven grid templates, plus the header content that goes
 * with them (grouped-head spans and per-column tooltip definitions).
 *
 * Moved out of `DraftBoard.tsx` so the head and every body `Row` share ONE
 * constant, and so `pickGroups`/`ownerGroups` are keyed on exactly the same
 * argument shape `pickGrid`/`ownerGrid` pick the column template from — a
 * short span sum silently slides every later cap one column left, which is
 * an arithmetic bug wearing a styling-bug costume, so the two selectors take
 * the identical object rather than two argument lists that could drift out
 * of step with each other.
 *
 * Raw `grid-template-columns` STRINGS, not Tailwind `grid-cols-[...]`
 * classes — applied via `style` on both `Row` and `GroupedHead` (see
 * `Row.tsx`'s `cols` prop). A head positioned by a class and a body
 * positioned by `style` is exactly how the two silently drift out of
 * column; sharing one string retires that hazard for this table outright.
 * ------------------------------------------------------------------------ */

/* ---- Picks ledger: seven templates, hasBaseline × (graded | hasProjected |
 * neither), plus one verdict variant. `graded` implies no Projected — a
 * preseason estimate is superseded by what actually happened — so the two
 * never coexist. A verdict requires production to judge (implies `graded`)
 * AND a rookie-ECR baseline to judge it against (implies `hasBaseline`), so
 * there is no no-baseline-with-verdict or unplayed-with-verdict template.
 *
 * The Player track is capped the same way the Owners table's Owner track is
 * (see that constant's own comment) — `minmax(0,1fr)` was absorbing every
 * px of row slack, stranding the baseline/verdict/production columns ~600px
 * from the name at a wide viewport. Capped, slack collects at the row's
 * right edge instead. The fixed tracks were re-budgeted for the `now` column
 * at the (then) 870px gate, not just appended — measured against the live
 * 2025 rookie class: `owner` (120px) had ~60px of dead margin over every real
 * drafter name (longest 88px) and drops to 100px; `now` drops to 60px
 * against its real measured max ("Rostered", 48px at this font); `pick`
 * stays 40px, an exact fit for the round·slot code (`1.01`), with no slack
 * to give. That reclaims 40px for Player, whose floor rises from 140 to
 * 170 — 6px above the same live class's longest name+position ("TreVeyon
 * HendersonRB", 164px). The gate has since moved to 910px (see
 * `DraftBoard.tsx`'s width-budget docstring above `PicksSection`) because
 * Treatment C's header re-cut below pushed the widest template past the real
 * budget at 870 — the Player floor and the re-budgeted tracks here are
 * unchanged, only the breakpoint moved.
 *
 * TREATMENT C (header re-cut): Phase 4 added a sort mark + a definition
 * trigger to every non-identity header cell — 33px of chrome (5px gap + 12px
 * mark + 4px gap + 12px trigger) — into tracks sized for plain text, and 6 of
 * these 7 non-identity cells wrapped to 2-3 lines at the widest template.
 * Every non-identity track below is now `ceil(label width in Geist Mono at
 * --text-label with tracking-[0.12em]) + 33px chrome`, plus a few px of
 * slack, per the measurements in `draft-columns.test.ts`'s own header-width
 * test. `now` (18px label) and `ecr`/the dynamic ADP baseline label (18px)
 * both land on 54px; `slot` (24px, "Slot" — shortened from "Slot +/-", the
 * definition tooltip already carries the full name) on 60px; `verdict` (43px,
 * kept — it's the app's own term) on 78px; `total`/`start` (Picks ledger
 * abbreviates "Start %" to "Start", 31px each) on 66px; `gs` (12px) on 48px.
 * The widest template (`GRID_PB_VERDICT`) comes to 854px fixed+flex+gaps+
 * padding. That is 16px under the raw 870px this used to be checked against,
 * but the REAL budget at a 870px gate is only 820px (viewport minus `Shell`'s
 * 48px horizontal padding minus `Panel`'s 2px border — see
 * `draft-columns.test.ts`'s `WIDTH_GATE_BUDGET_PX`) — so at 870 this template
 * actually overflowed by 34px. The gate moved to 910px (real budget 860px)
 * to clear it instead of trimming further; 854px now sits 6px under that
 * real budget. */
export const GRID_P_PLAIN = "40px 100px minmax(170px,420px) 54px";
export const GRID_P_PROJ = "40px 100px minmax(170px,420px) 60px 54px";
export const GRID_P_GRADED = "40px 100px minmax(170px,420px) 66px 66px 48px 54px";
export const GRID_PB_PLAIN = "40px 100px minmax(170px,420px) 54px 60px 54px";
export const GRID_PB_PROJ = "40px 100px minmax(170px,420px) 54px 60px 60px 54px";
export const GRID_PB_GRADED = "40px 100px minmax(170px,420px) 54px 60px 66px 66px 48px 54px";
export const GRID_PB_VERDICT = "40px 100px minmax(170px,420px) 54px 60px 78px 66px 66px 48px 54px";

/* ---- Owners ledger: four templates, graded × hasAdpColumns. The Owner
 * track is capped, not `minmax(0,1fr)` — an uncapped `fr` track absorbs
 * every px of slack in the row, which at a wide viewport (1405px+) put
 * ~600px of dead air between a short owner name and its figures. Capped, the
 * track sizes to its content and the leftover space collects at the row's
 * right edge instead. 420px is generous headroom for any real owner display
 * name; 140px keeps the column from collapsing on a narrow one.
 *
 * TREATMENT C (header re-cut): same `label + 33px chrome` re-cut as the
 * Picks ledger above — 7 of these 8 non-identity cells wrapped at the
 * widest template. `par` ("PAR", shortened from "Points Above Round", 24px)
 * and `adp` ("ADP", shortened from "ADP +/-", 18px) land on 60px/54px;
 * `coverage` ("Cov", shortened from "Coverage", 24px) on 60px; `total`
 * keeps the full five-metric word "Total Points" (73px — the widest label
 * on either ledger) at 108px; `start` (Owners ledger also shortens "Start %"
 * to "Start", 31px) at 66px; `regular`/`playoff` (43px each, kept — five-
 * metric vocabulary) at 78px; `toilet` (37px, kept) at 72px. The widest
 * template (`OWNER_GRID_GRADED_ADP`) comes to 858px fixed+flex+gaps+padding.
 * That is 12px under the raw 870px this used to be checked against, but the
 * REAL budget at a 870px gate is only 820px (see the note above
 * `GRID_PB_VERDICT`) — so at 870 this template also overflowed, by 38px, the
 * tighter of the two ledgers. At the current 910px gate (real budget 860px)
 * it sits 2px under budget. */
export const OWNER_GRID_MIN = "24px minmax(140px,420px)";
export const OWNER_GRID_ADP_ONLY = "24px minmax(140px,420px) 54px 60px";
export const OWNER_GRID_GRADED_ONLY = "24px minmax(140px,420px) 60px 108px 66px 78px 78px 72px";
export const OWNER_GRID_GRADED_ADP = "24px minmax(140px,420px) 60px 108px 66px 78px 78px 72px 54px 60px";
/** GRADED_ONLY plus Hit/Bust. 88px on the same `label + 33px chrome` re-cut as
 *  its neighbours ("Hit/Bust" is the widest label in the graded run after
 *  "Total Points"), landing the template at 822px — 38px under the 860px real
 *  budget at the 910px gate.
 *
 *  WHY THERE IS NO `..._GRADED_ADP_VERDICT`. `OWNER_GRID_GRADED_ADP` is
 *  already 858px against that 860px budget: two pixels. Hit/Bust cannot be
 *  added to it without either trimming a column that template exists to carry
 *  or raising the gate past the 1024px viewports (iPad landscape) that would
 *  then fall back to cards — so the ADP template deliberately does NOT get the
 *  column, and `ownerGrid` checks ADP first. That costs nothing today: ADP is
 *  captured going-forward-only from dated daily snapshots, so no draft that
 *  predates the first snapshot can ever resolve one, and no league currently
 *  reaches this template at all. When one does, it renders every column it has
 *  today and loses only the rollup, which is still per-pick on the ledger
 *  below. Deferring that is the decision; re-opening the breakpoint
 *  negotiation to pre-empt it is not. */
export const OWNER_GRID_GRADED_VERDICT = "24px minmax(140px,420px) 60px 108px 66px 78px 78px 72px 88px";

export interface PickGridArgs {
  hasBaseline: boolean;
  hasProjections: boolean;
  graded: boolean;
  hasVerdicts: boolean;
}

export function pickGrid({ hasBaseline, hasProjections, graded, hasVerdicts }: PickGridArgs): string {
  // A verdict needs production to judge AND a rookie-ECR baseline to judge it
  // against, so it can only ever coexist with both.
  if (hasBaseline && graded && hasVerdicts) return GRID_PB_VERDICT;
  if (hasBaseline && graded) return GRID_PB_GRADED;
  if (hasBaseline && hasProjections) return GRID_PB_PROJ;
  if (hasBaseline) return GRID_PB_PLAIN;
  if (graded) return GRID_P_GRADED;
  if (hasProjections) return GRID_P_PROJ;
  return GRID_P_PLAIN;
}

/**
 * The grouped-head spans for whichever pick template `pickGrid` would pick
 * for the same args. `null` below the eight-column floor — five of the seven
 * pick templates never reach it, and a seven-column `GroupedHead` is a
 * misuse (`GroupedHead.prompt.md`'s own rule): the head isn't crowded and the
 * naming tier costs 24px above the data for nothing.
 *
 * The two grouped shapes (`GRID_PB_GRADED`, 9 tracks; `GRID_PB_VERDICT`, 10)
 * share the same two caps — identity is capless because the columns' own
 * names are the whole explanation, and Baseline factors out the shared word
 * over the class's board rank and its delta. Total/Start %/GS are capped
 * "Production" — NOT a shared word (only Total is a points figure; Start %
 * and GS are both owner-gated measures of that same production, which is
 * the real structural family `GroupedHead.prompt.md`'s rule asks for). An
 * earlier pass labelled this cap "Points", copied from a worked example
 * written before the column budget trimmed Regular/Playoff/Toilet off the
 * pick rows — it read as a shared word only because that example predated
 * the trim. Verdict and Now are each a single column, so per `GroupedHead`'s
 * own JSDoc ("Omit for an ungrouped run") they stay capless (`{ span: 1 }`)
 * rather than carrying a redundant one-column label 24px above a column that
 * already carries that label.
 */
export function pickGroups({ hasBaseline, graded, hasVerdicts }: PickGridArgs): HeadGroup[] | null {
  if (hasBaseline && graded && hasVerdicts) {
    // GRID_PB_VERDICT — 10 tracks: pick·owner·player | ECR·Slot+/- | Verdict | Total·Start%·GS | Now
    return [
      { span: 3 },
      { span: 2, label: "Baseline" },
      { span: 1 },
      { span: 3, label: "Production" },
      { span: 1 },
    ];
  }
  if (hasBaseline && graded) {
    // GRID_PB_GRADED — 9 tracks: pick·owner·player | ECR·Slot+/- | Total·Start%·GS | Now
    return [
      { span: 3 },
      { span: 2, label: "Baseline" },
      { span: 3, label: "Production" },
      { span: 1 },
    ];
  }
  return null; // every other pick template sits under the eight-column floor
}

export interface OwnerGridArgs {
  graded: boolean;
  hasAdpColumns: boolean;
  hasVerdicts: boolean;
}

/** ADP is tested BEFORE verdicts on purpose — see `OWNER_GRID_GRADED_VERDICT`
 *  for why the two cannot share a template. A class carrying both renders the
 *  ADP one. */
export function ownerGrid({ graded, hasAdpColumns, hasVerdicts }: OwnerGridArgs): string {
  if (graded && hasAdpColumns) return OWNER_GRID_GRADED_ADP;
  if (graded && hasVerdicts) return OWNER_GRID_GRADED_VERDICT;
  if (graded) return OWNER_GRID_GRADED_ONLY;
  if (hasAdpColumns) return OWNER_GRID_ADP_ONLY;
  return OWNER_GRID_MIN;
}

/**
 * The grouped-head spans for whichever owner template `ownerGrid` would pick
 * for the same args. `null` below the floor — `OWNER_GRID_MIN` (2 tracks)
 * and `OWNER_GRID_ADP_ONLY` (4) both keep the plain head.
 *
 * Points Above Round and ADP +/- each stay their own capless single-column
 * group (per `GroupedHead`'s own JSDoc — "Omit for an ungrouped run" — a
 * one-column cap groups nothing) rather than joining Production: PAR is a
 * different figure from the received-only run (a round-relative margin, not
 * a received-only tally), and ADP +/- measures the class's draft-night
 * market, not production at all. "Production" caps exactly the Total/
 * Start %/Regular/Playoff/Toilet run — NOT a shared word (only "Total
 * Points" says "Points"; Regular/Playoff/Toilet don't), but a real
 * structural family: CLAUDE.md's own vocabulary for this run is
 * `production_total`/`production_regular`/…, and Start % is an owner-gated
 * measure of that same production. The same cap and the same reasoning
 * apply on the Picks ledger's own grouped templates (`pickGroups`).
 */
export function ownerGroups({ graded, hasAdpColumns, hasVerdicts }: OwnerGridArgs): HeadGroup[] | null {
  if (graded && hasAdpColumns) {
    // OWNER_GRID_GRADED_ADP — 10 tracks: #·Owner | PAR | Total·Start%·Regular·Playoff·Toilet | ADP+/- | Coverage
    return [
      { span: 2 },
      { span: 1 },
      { span: 5, label: "Production" },
      { span: 1 },
      { span: 1 },
    ];
  }
  if (graded && hasVerdicts) {
    // OWNER_GRID_GRADED_VERDICT — 9 tracks: #·Owner | PAR | Total·Start%·Regular·Playoff·Toilet | Hit/Bust
    // Hit/Bust stays its own capless single-column group: it is a count of
    // verdicts, not a points figure, so it joins neither "Production" nor PAR.
    return [
      { span: 2 },
      { span: 1 },
      { span: 5, label: "Production" },
      { span: 1 },
    ];
  }
  if (graded) {
    // OWNER_GRID_GRADED_ONLY — 8 tracks: #·Owner | PAR | Total·Start%·Regular·Playoff·Toilet
    return [
      { span: 2 },
      { span: 1 },
      { span: 5, label: "Production" },
    ];
  }
  return null; // OWNER_GRID_MIN / OWNER_GRID_ADP_ONLY sit under the eight-column floor
}

/** Every template's literal class string plus the exact args that select it —
 *  the arithmetic tests (`draft-columns.test.ts`) read both off this record
 *  so the templates the test measures can never drift from what `DraftBoard`
 *  actually renders. */
export const PICK_GRIDS: Record<string, { cls: string; args: PickGridArgs }> = {
  GRID_P_PLAIN: { cls: GRID_P_PLAIN, args: { hasBaseline: false, hasProjections: false, graded: false, hasVerdicts: false } },
  GRID_P_PROJ: { cls: GRID_P_PROJ, args: { hasBaseline: false, hasProjections: true, graded: false, hasVerdicts: false } },
  GRID_P_GRADED: { cls: GRID_P_GRADED, args: { hasBaseline: false, hasProjections: false, graded: true, hasVerdicts: false } },
  GRID_PB_PLAIN: { cls: GRID_PB_PLAIN, args: { hasBaseline: true, hasProjections: false, graded: false, hasVerdicts: false } },
  GRID_PB_PROJ: { cls: GRID_PB_PROJ, args: { hasBaseline: true, hasProjections: true, graded: false, hasVerdicts: false } },
  GRID_PB_GRADED: { cls: GRID_PB_GRADED, args: { hasBaseline: true, hasProjections: false, graded: true, hasVerdicts: false } },
  GRID_PB_VERDICT: { cls: GRID_PB_VERDICT, args: { hasBaseline: true, hasProjections: false, graded: true, hasVerdicts: true } },
};

export const OWNER_GRIDS: Record<string, { cls: string; args: OwnerGridArgs }> = {
  OWNER_GRID_MIN: { cls: OWNER_GRID_MIN, args: { graded: false, hasAdpColumns: false, hasVerdicts: false } },
  OWNER_GRID_ADP_ONLY: { cls: OWNER_GRID_ADP_ONLY, args: { graded: false, hasAdpColumns: true, hasVerdicts: false } },
  OWNER_GRID_GRADED_ONLY: { cls: OWNER_GRID_GRADED_ONLY, args: { graded: true, hasAdpColumns: false, hasVerdicts: false } },
  OWNER_GRID_GRADED_VERDICT: { cls: OWNER_GRID_GRADED_VERDICT, args: { graded: true, hasAdpColumns: false, hasVerdicts: true } },
  OWNER_GRID_GRADED_ADP: { cls: OWNER_GRID_GRADED_ADP, args: { graded: true, hasAdpColumns: true, hasVerdicts: true } },
};

/* ---- Going in panel: one fixed template, four tracks. See
 * `DraftGoingIn.tsx`. Biggest Needs redesign (2026-08-19): full sentences replaced short
 * "POS±NN" chips, so the flexible column moves from Owner to Biggest
 * Needs. Owner narrows (names are short; the room was never the
 * constraint) to free width for sentences that need real growing room.
 * Positions Drafted widens for its new total-picks line; Points Produced
 * widens slightly for "45.8 pts" plus its mobile label.
 * minWidthPx: 110 + 280 + 170 + 100 (fixed/flex-floor sum) + 30 (3 gaps
 * × 10px) + 28 (cell padding) = 718px, against the 860px WIDTH_GATE_BUDGET_PX
 * — verified by the dedicated "Going in panel width gate" test below, not
 * asserted from this comment alone. */
export const GRID_GOING_IN = "minmax(110px,160px) minmax(280px,640px) 170px 100px";

/* ---------------------------------------------------------------------------
 * Column definitions — every non-identity column on either ledger, fed to
 * `InfoTooltip`. Identity columns (Round·Pick, Owner, Player, `#`) carry no
 * entry here on purpose: their names are the whole explanation, and a
 * tooltip trigger with no definition is worse than no trigger, so the
 * inverse holds too — a definition with no column to attach it to is dead
 * weight. Every key below is a real sort key from `draft-sort.ts`'s
 * consumers except `proj`, which has no sort key but is a real, reachable
 * header on an ungraded class with projections.
 *
 * No `label` field — an earlier pass added one to hold the column's
 * canonical short name, but nothing ever read it: the on-screen header text
 * stays the literal string (or dynamic `baseline_label`) already written at
 * each call site in `DraftBoard.tsx`. A field a future header-string change
 * would never touch is drift bait, not documentation, so it was removed
 * rather than left to silently go stale. `title` is what `InfoTooltip`
 * renders as the popover's kicker.
 * ------------------------------------------------------------------------ */
export interface ColumnDef {
  title: string;
  body: string;
  formula?: string;
}

export const COLUMN_DEFS: Record<string, ColumnDef> = {
  ecr: {
    title: "Draft Baseline",
    body:
      "The board rank this pick is measured against on draft night — rookie " +
      "consensus ECR for a dynasty class, Sleeper ADP for redraft or keeper — " +
      "pinned to the draft's own date, never today's.",
  },
  slot_delta: {
    title: "Slot +/-",
    body:
      "Draft position minus the baseline rank. Positive means the player was " +
      "taken later than the board had him.",
    formula: "Pick − Baseline",
  },
  verdict: {
    title: "Verdict",
    body:
      "Hit, Average, or Bust — graded against the cohort of picks in the same " +
      "baseline band held the same number of seasons, by percentile. Not a " +
      "fixed threshold.",
  },
  hit_bust: {
    title: "Hit / Bust",
    body:
      "How many of this owner's picks landed as Hits and how many as Busts, " +
      "counted from the verdicts on their pick rows below. Picks that cannot " +
      "be judged — an unplayed class, a keeper, a band with too few comparable " +
      "players — count toward neither.",
  },
  total: {
    title: "Total Points",
    body:
      "Received-only: points scored by this pick while on the owner's roster, " +
      "bench included, across all weeks.",
  },
  start_pct: {
    title: "Start %",
    body: "The share of this pick's Total Points that came from a started lineup.",
    formula: "Started ÷ Total",
  },
  gs: {
    title: "Games Started",
    body: "Games started for the drafting owner, across all phases of the season.",
  },
  now: {
    title: "Now",
    body:
      "This pick's current standing with the drafting owner — Rostered, " +
      "Traded, Dropped, or no reading at all.",
  },
  par: {
    title: "Points Above Round",
    body:
      "Production against the average pick in the same round of this draft — " +
      "zero-sum within the class, so it rewards drafting well from a bad slot " +
      "rather than just picking early.",
    formula: "Total − Round Average",
  },
  regular: {
    title: "Regular Season Points",
    body: "Received-only started points, weeks before the playoff cutoff.",
  },
  playoff: {
    title: "Playoff Points",
    body:
      "Received-only started points in live title-path winners-bracket games " +
      "only. Byes, eliminated weeks, and placement games count zero.",
  },
  toilet: {
    title: "Toilet Bowl Points",
    body: "Received-only started points in any losers-bracket game.",
  },
  adp: {
    title: "ADP +/-",
    body:
      "This owner's picks against Sleeper ADP, pinned to the draft's own " +
      "date, never today's. A draft predating the first daily snapshot has no " +
      "ADP baseline, permanently.",
  },
  coverage: {
    title: "Coverage",
    body:
      "How many of this owner's picks had an ADP baseline at all — why this " +
      "figure can be blank rather than zero.",
  },
  proj: {
    title: "Projected Points",
    body:
      "Preseason projected points — the only forward-looking figure available " +
      "before a class has played. Superseded once the class is graded.",
  },
};
