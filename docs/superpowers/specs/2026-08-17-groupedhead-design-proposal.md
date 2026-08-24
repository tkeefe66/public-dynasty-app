# GroupedHead — a design-system proposal

**Date:** 2026-08-17
**Status:** **APPROVED 2026-08-17** — landed in `3f1e973`. Resolutions to the four open
questions are recorded in that commit message and summarised at the bottom of this file.
**Blocks:** phase 4 of `docs/superpowers/specs/2026-08-17-draft-board-redesign-design.md`
**Destination:** the **Dynasty Analyzer Design System** project (`5c2c2210-71e4-42ac-b2ae-305b36558750`), which generates `.design/`

## Why this is a proposal and not a patch

`.design/` is **generated** and is the source of truth for every design value. `DESIGN_SYSTEM.md` is
explicit that a `.design/` change merged without design-project review is itself drift. So a new
primitive cannot be hand-written into `.design/components/` — it would be overwritten by the next
sync, and it would carry no review.

The alternative that must **not** happen: building it as a local dialect in
`web/components/furniture/` and adding an entry to `web/tests/furniture-rules.test.ts`'s exception
list. That is how a design system stops meaning anything. The guard's job is to notice exactly this
kind of addition; silencing it defeats the purpose of having noticed.

## The problem

The draft board's picks ledger reached **twelve columns** and, with phase 4's sort and tooltip
affordances, thirteen. At `--text-label` (8.5px) with `--track-label` (0.11em) letterspacing, a
single-tier `Row variant="head"` at twelve columns produces a run of abbreviations with no
grouping: *ECR · Slot +/- · Verdict · Total · Start % · Regular · Playoff · Toilet · GS · Now*.

Reviewed live, the failure is not that labels truncate — widths can be tuned — it is that **nothing
tells the reader which columns belong together**. Four of those ten are the same metric family
measured in different phases, and the header gives no signal of it.

The prototype that resolved it is at
`https://claude.ai/code/artifact/1a871e97-5127-44ab-9ff7-8060e4577530` (toggle **Grouped**). Its
insight is small and specific: a **Points** cap over four columns lets them read *Total · Regular
Season · Playoff · Toilet Bowl* instead of printing "Points" four times across one header. The cap
factors out a genuinely shared word.

## What is proposed

A second `Row` head variant — a naming tier above the label tier.

```jsx
<GroupedHead
  cols="66px 84px minmax(140px,420px) 60px 72px 66px 72px 74px 56px 60px"
  groups={[
    { span: 3 },                    // identity: pick · owner · player
    { span: 2, label: "Baseline" }, // ECR · Slot +/-
    { span: 1, label: "Verdict" },
    { span: 3, label: "Points" },   // Total · Start % · GS
    { span: 1, label: "Now" },
  ]}
>
  <SortButton sort="none">Pick</SortButton>
  …one child per column, exactly as a `Row variant="head"` takes them
</GroupedHead>
```

### Geometry

| Property | Value | Why |
|---|---|---|
| Total height | **68px** | 18px naming tier + `SortButton`'s mandated 44px target + 6px top padding |
| Naming tier | 18px | Cap type at `--text-label`, `--dim`, letterspacing `0.16em` |
| Cap rule | `1px solid var(--rule-strong)` | Spans **exactly** its group's tracks, drawn under the cap |
| Label tier | 44px | Unchanged from `Row variant="head"` — this is not negotiable |

**The 44px is the whole reason this is a new shape rather than a variation.** `Row`'s head is 44px
*specifically* so a `SortButton` fits (`SortButton.jsx`: "The 44px target lives on the BUTTON, not
the row"). Stacking a naming tier on top means the head is no longer 44px, and `Row`'s grammar —
`cols` repeated verbatim on the head and every body row — cannot express a spanning cap.

### Rules

1. **Eight or more columns only.** Below that a single-tier head is not crowded and the extra 24px
   buys nothing. A seven-column `GroupedHead` is a misuse.
2. **A cap must factor out a genuinely shared word or a real structural family.** *Points* over
   Total/Regular/Playoff/Toilet earns its place. *Details* over four unrelated columns does not —
   that is decoration, and the system's own rule is that structural devices encode something true
   about the content.
3. **Every column belongs to exactly one group**, and spans must sum to the track count. An
   ungrouped run takes a capless group (`{ span: 3 }`) rather than being omitted — the arithmetic
   is what keeps the caps aligned to their columns.
4. **`cols` is still repeated verbatim** on the body rows, exactly as `Row` requires. `GroupedHead`
   changes the head only.
5. **Caps are never interactive.** Sorting lives on the label tier, where `SortButton` already is.
   A clickable cap would imply sorting a group, which is not a thing.

### What it does not change

The mobile answer is unchanged: below the breakpoint an entry is a **card**, not a row, so
`GroupedHead` has no phone rendering and needs none. `EntryCard`'s `MetaLine`/`Meta` already carry
labels per figure, which is the grouping problem solved a different way.

## Evidence it is needed

- **Measured**: the picks table needs 988px before the Player column gets anything once sort and
  tooltip affordances land. That crowding is what forced the column budget decision; the header
  legibility problem is the same pressure at the label tier.
- **Prototyped**: the artifact above renders both treatments against real league data with the real
  tokens and faces. The single-tier variant is still there to compare against.
- **Chosen**: reviewed 2026-08-17, grouped was preferred over the one-row treatment.

## Open questions for review

1. **Is 68px acceptable, or should the naming tier be 16px** for a 66px total? 18px was chosen so
   the cap's underline clears the label tier's ascenders; 16px may be enough.
2. **Should the cap rule be `--rule-strong` or `--rule`?** `--rule-strong` reads as a deliberate
   division; `--rule` would recede and might be enough given the type is already `--dim`.
3. **Does the eight-column floor belong in the component** (refuse to render, fall back to a plain
   head) **or in the prompt as guidance?** Enforcing it in code is unusual for this package, whose
   primitives generally trust their caller.
4. **Is there a second consumer?** A primitive with one call site is a component-shaped constant.
   `StandingsTable` and `Leaderboard` are the candidates — both are wide, and if either would use
   it, that materially strengthens the case. If neither would, this proposal should probably be
   rejected in favour of trimming the draft board further.

Question 4 is the one that should decide it.

## How it lands, if approved

1. Authored in the **Dynasty Analyzer Design System** project — `GroupedHead.jsx`, `.d.ts`, and a
   `.prompt.md` carrying the rules above and the one gotcha (the 44px label tier).
2. `.design/` re-synced into the repo. **REQUIRED BACKGROUND:** `design-system-sync` — in
   particular the post-sync dangling-token diff, which is the only thing that catches a renamed
   token, since `var(--gone)` resolves to nothing and renders unstyled rather than erroring.
3. `web/components/furniture/GroupedHead.tsx` implements it against the synced contract, the way
   every other primitive in that directory mirrors its `.design/` counterpart.
4. Phase 4's header work unblocks.

Until step 1 completes, **phase 4 does not ship its header**. The rest of phase 4 — per-column
sorting, definition tooltips, and the nav entry — depends on none of this and can proceed.

## Resolved — 2026-08-17

Steps 1–3 are done (`3f1e973`); phase 4's header is unblocked.

1. **18px naming tier, 68px total.** 16px was compared side by side against the shipped column
   set and 18 was kept — the cap rule wants the clearance.
2. **`--rule-strong`.** The cap type is already `--dim`; a `--rule` hairline under dim type
   reads as a smudge rather than a division.
3. **The eight-column floor is guidance**, stated in `GroupedHead.prompt.md`, not enforced in
   code. Every primitive in this package trusts its caller, and a floor is a taste judgement.
   The **span-sum invariant is different and IS checked** (dev-mode warning, web mirror only) —
   that one is arithmetic, it fails by sliding every later cap one column left, and the drift
   guard cannot see it.
4. **Yes, there is a second consumer** — this was the question that decided it. Measured against
   the real components rather than guessed:

   | Table | Widest track count | Candidate |
   |---|---|---|
   | `DraftBoard` | 10 | the proposer |
   | `PastPicksTable` | up to 17 | yes |
   | `StandingsTable` | 9 | plausible — its Outlook columns (Window / s+t / Draft cap) are a real family that already drop together for redraft |
   | `Leaderboard` | 7 | no — under the floor |

   Two callers today and a third that is a genuinely different feature, so the
   component-shaped-constant objection does not hold.

## Correction — 2026-08-17, found in phase 4

**This document's own worked example was wrong, and the first consumer faithfully implemented
it.** The `{ span: 3, label: "Points" }` over *Total · Start % · GS* above was written when the
picks rows still carried four true points columns. **The column budget then trimmed Regular /
Playoff / Toilet off those rows**, and the label was carried forward without rechecking that it
still factored out a shared word. Of the three columns left, only Total is a points figure — a
percentage and a game count are not. The cap satisfied neither branch of the rule it was the
headline illustration of.

The picks and owners caps are **"Production"** now — CLAUDE.md's own word for this family
(`production_total`, `production_regular`, …), which the rule's *real structural family* branch
covers honestly. Start % was **not** pulled out into its own group: it sits physically between
Total and Regular, so a contiguous four-column "Points" cap would need a column reorder, which
is not worth it — and the rendered headers already read *Total Points / Regular / Playoff /
Toilet*, so nothing was printing the word four times anyway.

Two changes landed upstream in `.design/` as a result:

- **A fifth rule: a cap spans two or more columns.** The example also used
  `{ span: 1, label: "Verdict" }` and `{ span: 1, label: "Now" }`, which name a column 24px above
  the name it already carries. `GroupedHead.d.ts`'s own JSDoc already said "omit for an ungrouped
  run", so the example and the type contradicted each other; the JSDoc wins.
- **Re-check a cap whenever its columns change**, with this drift named as the cautionary case.

The lesson generalises past this component: a rule about *content* — as opposed to arithmetic —
cannot be enforced by a test or a guard, so it survives only as long as someone re-reads it when
the content moves. The span-sum invariant caught nothing here because the spans were always
correct; what rotted was the word.

**One thing the proposal did not anticipate.** The consumers render inside `role="table"`, so
the naming tier had to become a real `role="row"` of `role="columnheader"` cells carrying
`aria-colspan` — decorative divs would have broken the table's semantics outright. That markup
lives in the **web mirror only**: `.design/` primitives are style-only and take their roles
through `...rest`, so keeping ARIA out of the upstream component is what keeps the two in step.
The upshot is that the capless group is load-bearing twice over — it is the same rule serving
the cap alignment and the accessible column arithmetic.
