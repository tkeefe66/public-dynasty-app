# Methodology Page Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `/methodology` ("How it works") into a top-down, trust-building reference — "How the grade is built" — that descends from the Franchise letter through pillars, signals, raw metrics, and the math, threaded with one coherent worked example.

**Architecture:** A single static server-component page (`web/app/methodology/page.tsx`) wrapping `Shell` + `TopBar` around a provider-free, testable `MethodologyContent`. The descent reuses the live "Why this grade" diverging-bar visual (extracted into a shared `RatingBars` module so the page and the owner page render the same idiom). One hardcoded sample owner ("Marcus") with internally-coherent numbers is the worked example. A small `'use client'` sticky TOC adds scroll-spy.

**Tech Stack:** Next.js 14 App Router, React, TypeScript, Tailwind (CSS custom-property tokens), vitest + @testing-library/react.

## Global Constraints

- **Engine-accurate values (verbatim):** pillar weights **Results 0.43 / Skill 0.43 / Outlook 0.14**; signal weights — Results: championships 0.35, playoff_depth 0.25, made_playoffs 0.15, final_seed 0.15, points_for_rank 0.10; Skill: trade_value 0.25, trade_production 0.20, draft_skill 0.30, lineup_skill 0.25; Outlook: roster_value 0.45, draft_capital 0.30, youth 0.25. Scale: `rating = clamp(1500 + 275·Σ(weight·z), 800, 2200)`. Letter bands (delta from 1500): A+≥340, A≥270, A−≥210, B+≥150, B≥100, B−≥60, C+≥20, C≥−20, C−≥−60, D+≥−100, D≥−150, D−≥−210, else F.
- **Never render "KTC"** as a user-facing string — it is "Trade Value" / "Value" / "dynasty market value".
- **Five-metric labels** exact: Trade Value / Total Points / Regular Season Points / Playoff Points / Toilet Bowl Points.
- **Sample owner "Marcus" — source-of-truth numbers:** B+ at **1,664**; pillar contributions **Results +93, Skill +59, Outlook +12** (1500+93+59+12=1664). Pillar z's: Results +0.79, Skill +0.50, Outlook +0.30. Signal contribution = `round(275·w_pillar·w_signal·z_signal)`; a pillar's signal contributions sum (to rounding) to its pillar contribution.
- **Authoritative content source:** the committed spec `docs/superpowers/specs/2026-06-27-methodology-page-overhaul-design.md` (sections 1–8) holds the exact prose/definitions for each section — use it as the copy source; this plan pins the structure, numbers, and tests.
- **Don't break the live "Why this grade":** `web/components/ownerdeepdive/OverviewTab.tsx` must keep rendering identically after the bar extraction.
- **Build hygiene:** `cd web && npm run build` before done; never build against a running `next dev` tree.
- **Out of scope:** live personalization, backend changes, nav-label change, new routes.

---

## File Structure

- `web/components/RatingBars.tsx` — **create.** Shared presentational `fmtPts`, `Bar`, `ContributionRow` (the diverging bar + label/weight/points row), extracted from OverviewTab. Pure, no hooks → usable in both client and server components.
- `web/components/ownerdeepdive/OverviewTab.tsx` — **modify.** Import the shared pieces instead of its local copies (behavior unchanged).
- `web/components/methodology/sample.ts` — **create.** The "Marcus" worked-example data (pillars → signals → contributions), typed; plus the page's section/signal definition data.
- `web/components/methodology/MethodologyContent.tsx` — **create.** The provider-free page body: the 8 sections built from `sample.ts` + `RatingBars`. Exported for testing.
- `web/components/methodology/MethodologyToc.tsx` — **create, `'use client'`.** Sticky in-page TOC + scroll-spy.
- `web/app/methodology/page.tsx` — **rewrite.** Compose `Shell` + `TopBar` + `MethodologyToc` + `MethodologyContent`.
- `web/tests/Methodology.test.tsx` — **create.** Renders `MethodologyContent`; asserts structure/numbers/no-KTC.
- `web/tests/RatingBars.test.tsx` — **create.** Bar renders positive (green) and negative (red).

---

### Task 1: Extract the shared rating-bar component

**Files:**
- Create: `web/components/RatingBars.tsx`
- Modify: `web/components/ownerdeepdive/OverviewTab.tsx`
- Test: `web/tests/RatingBars.test.tsx`

**Interfaces:**
- Produces: `fmtPts(n: number): string`; `Bar(props: { points: number; scale: number })`; `ContributionRow(props: { label: string; weight?: number; points: number; scale: number; signal?: boolean })` — all from `web/components/RatingBars.tsx`. `ContributionRow` is the current `DriverRow` renamed.

- [ ] **Step 1: Write the failing test**

Create `web/tests/RatingBars.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ContributionRow, fmtPts } from "../components/RatingBars";

describe("RatingBars", () => {
  it("formats points with a sign", () => {
    expect(fmtPts(12)).toBe("+12");
    expect(fmtPts(-5)).toBe("-5");
    expect(fmtPts(0)).toBe("0");
  });

  it("renders a labeled contribution row with its points", () => {
    render(<ContributionRow label="Skill" weight={0.43} points={59} scale={100} />);
    expect(screen.getByText("Skill")).toBeInTheDocument();
    expect(screen.getByText("+59")).toBeInTheDocument();
    expect(screen.getByText("43%")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run --config tests/vitest.config.ts tests/RatingBars.test.tsx`
Expected: FAIL — `Cannot find module '../components/RatingBars'`.

- [ ] **Step 3: Create the shared module**

Create `web/components/RatingBars.tsx` by moving the three helpers out of OverviewTab (rename `DriverRow` → `ContributionRow`):

```tsx
export function fmtPts(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

/** Diverging bar on a shared scale: positive extends right (green), negative
 *  left (red), from a center zero axis. */
export function Bar({ points, scale }: { points: number; scale: number }) {
  const mag = Math.min(50, (Math.abs(points) / scale) * 50);
  const pos = points >= 0;
  return (
    <div className="relative h-[7px] rounded-full bg-divider" aria-hidden="true">
      <span className="absolute top-0 bottom-0 left-1/2 w-px bg-dim/50" />
      {points !== 0 && (
        <span
          className={`absolute inset-y-0 rounded-full ${pos ? "bg-pos" : "bg-neg"}`}
          style={pos ? { left: "50%", width: `${mag}%` } : { right: "50%", width: `${mag}%` }}
        />
      )}
    </div>
  );
}

export function ContributionRow({
  label, weight, points, scale, signal,
}: {
  label: string; weight?: number; points: number; scale: number; signal?: boolean;
}) {
  return (
    <div className="grid grid-cols-[104px_1fr_46px] sm:grid-cols-[150px_1fr_52px] items-center gap-2.5">
      <span className={`flex items-baseline gap-1.5 min-w-0 ${signal ? "pl-3 text-dim text-[12px]" : "text-ink font-semibold text-[13px]"}`}>
        <span className="truncate">{label}</span>
        {weight != null && <span className="font-mono text-[9px] text-dim shrink-0">{Math.round(weight * 100)}%</span>}
      </span>
      <Bar points={points} scale={scale} />
      <span className={`text-right font-mono text-[11px] tabular ${points > 0 ? "text-pos" : points < 0 ? "text-neg" : "text-dim"}`}>
        {fmtPts(points)}
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Rewire OverviewTab to import them**

In `web/components/ownerdeepdive/OverviewTab.tsx`: delete the local `fmtPts`, `Bar`, and `DriverRow` definitions; add `import { Bar, ContributionRow, fmtPts } from "@/components/RatingBars";` near the top imports; replace the two `DriverRow` usages (lines ~109 and ~116) with `ContributionRow`. Leave everything else (RatingDrivers, OverviewTab) unchanged.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npx vitest run --config tests/vitest.config.ts tests/RatingBars.test.tsx tests/OwnerDeepDive.test.tsx`
Expected: PASS — new bar tests green AND the existing OwnerDeepDive tests still green (proves the extraction didn't change live behavior).

- [ ] **Step 6: Commit**

```bash
git add web/components/RatingBars.tsx web/components/ownerdeepdive/OverviewTab.tsx web/tests/RatingBars.test.tsx
git commit -m "refactor(web): extract shared rating contribution-bar (RatingBars)"
```

---

### Task 2: The worked-example sample data + section definitions

**Files:**
- Create: `web/components/methodology/sample.ts`
- Test: `web/tests/Methodology.test.tsx` (create here; extended in Task 3)

**Interfaces:**
- Produces:
  - `SAMPLE` — `{ name: "Marcus"; letter: "B+"; rating: 1664; pillars: PillarRow[] }` where `PillarRow = { key: "results"|"skill"|"outlook"; label: string; weight: number; contribution: number; signals: SignalRow[] }` and `SignalRow = { key: string; label: string; weight: number; raw: string; contribution: number }`.
  - `SECTIONS` — `{ id: string; title: string }[]` (the 8 TOC entries, in order).
- The pillar contributions are **+93 / +59 / +12** (sum 164 → rating 1664). Signal contributions within each pillar sum (to rounding) to the pillar contribution.

- [ ] **Step 1: Write the failing test (coherence of the worked example)**

Create `web/tests/Methodology.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { SAMPLE, SECTIONS } from "../components/methodology/sample";

describe("methodology sample data (coherence)", () => {
  it("pillar contributions sum to the rating delta from 1500", () => {
    const sum = SAMPLE.pillars.reduce((a, p) => a + p.contribution, 0);
    expect(1500 + sum).toBe(SAMPLE.rating); // 1500 + 93 + 59 + 12 = 1664
    expect(SAMPLE.rating).toBe(1664);
    expect(SAMPLE.letter).toBe("B+"); // delta 164 >= 150
  });

  it("each pillar's signal contributions sum (within rounding) to the pillar", () => {
    for (const p of SAMPLE.pillars) {
      const s = p.signals.reduce((a, x) => a + x.contribution, 0);
      expect(Math.abs(s - p.contribution)).toBeLessThanOrEqual(2);
    }
  });

  it("uses the live pillar weights", () => {
    const w = Object.fromEntries(SAMPLE.pillars.map((p) => [p.key, p.weight]));
    expect(w).toEqual({ results: 0.43, skill: 0.43, outlook: 0.14 });
  });

  it("has the eight ordered TOC sections", () => {
    expect(SECTIONS).toHaveLength(8);
    expect(SECTIONS[0].title).toMatch(/verdict/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run --config tests/vitest.config.ts tests/Methodology.test.tsx`
Expected: FAIL — `Cannot find module '../components/methodology/sample'`.

- [ ] **Step 3: Create the sample-data module**

Create `web/components/methodology/sample.ts`. Choose signal z-values so each pillar's signal contributions sum to its pillar contribution (formula `round(275·w_pillar·w_signal·z)`). The values below satisfy that (Results signals → +93, Skill → +59, Outlook → +12):

```ts
export type SignalRow = {
  key: string; label: string; weight: number; raw: string; contribution: number;
};
export type PillarRow = {
  key: "results" | "skill" | "outlook";
  label: string; weight: number; contribution: number; signals: SignalRow[];
};

export const SAMPLE = {
  name: "Marcus",
  letter: "B+",
  rating: 1664,
  pillars: [
    {
      key: "results", label: "Results", weight: 0.43, contribution: 93,
      signals: [
        { key: "championships", label: "Championships", weight: 0.35, raw: "1 title", contribution: 41 },
        { key: "playoff_depth", label: "Playoff Depth", weight: 0.25, raw: "4 rounds won", contribution: 24 },
        { key: "made_playoffs", label: "Made Playoffs", weight: 0.15, raw: "80% of seasons", contribution: 14 },
        { key: "final_seed", label: "Final Seed", weight: 0.15, raw: "avg 3rd", contribution: 10 },
        { key: "points_for_rank", label: "Points-For Rank", weight: 0.10, raw: "2nd in scoring", contribution: 4 },
      ],
    },
    {
      key: "skill", label: "Skill", weight: 0.43, contribution: 59,
      signals: [
        { key: "trade_value", label: "Trade Value", weight: 0.25, raw: "+0.6σ per deal", contribution: 16 },
        { key: "trade_production", label: "Trade Production", weight: 0.20, raw: "+0.4σ per deal", contribution: 9 },
        { key: "draft_skill", label: "Draft Skill", weight: 0.30, raw: "picks beat slot", contribution: 19 },
        { key: "lineup_skill", label: "Lineup Skill", weight: 0.25, raw: "96% efficient", contribution: 15 },
      ],
    },
    {
      key: "outlook", label: "Outlook", weight: 0.14, contribution: 12,
      signals: [
        { key: "roster_value", label: "Roster Value", weight: 0.45, raw: "3rd in league", contribution: 6 },
        { key: "draft_capital", label: "Draft Capital", weight: 0.30, raw: "avg holdings", contribution: 3 },
        { key: "youth", label: "Youth", weight: 0.25, raw: "young core", contribution: 3 },
      ],
    },
  ] as PillarRow[],
};

export const SECTIONS: { id: string; title: string }[] = [
  { id: "verdict", title: "The verdict" },
  { id: "pillars", title: "The three pillars" },
  { id: "signals", title: "Inside each pillar" },
  { id: "metrics", title: "The five trade metrics" },
  { id: "math", title: "The math" },
  { id: "columns", title: "Supporting columns" },
  { id: "words", title: "How the words are written" },
  { id: "sources", title: "Sources & limits" },
];
```

> Verify the sums before moving on: Results 41+24+14+10+4 = 93 ✓; Skill 16+9+19+15 = 59 ✓; Outlook 6+3+3 = 12 ✓.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run --config tests/vitest.config.ts tests/Methodology.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/methodology/sample.ts web/tests/Methodology.test.tsx
git commit -m "feat(web): methodology worked-example sample data + section list"
```

---

### Task 3: Build the page body (MethodologyContent + 8 sections)

**Files:**
- Create: `web/components/methodology/MethodologyContent.tsx`
- Modify: `web/tests/Methodology.test.tsx` (add render assertions)

**Interfaces:**
- Consumes: `SAMPLE`, `SECTIONS` (Task 2); `Bar`, `ContributionRow`, `fmtPts` (Task 1).
- Produces: `MethodologyContent()` — a provider-free React component (no Shell/TopBar, no next/navigation), exporting the full descent. Each of the 8 sections is wrapped in `<section id={SECTIONS[i].id}>` with an `<h2>` whose text matches the section title; section bodies use the exact prose from spec sections 1–8.

- [ ] **Step 1: Write the failing render test**

Add to `web/tests/Methodology.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MethodologyContent } from "../components/methodology/MethodologyContent";

describe("MethodologyContent", () => {
  it("renders all eight section headings", () => {
    render(<MethodologyContent />);
    for (const s of ["The verdict", "The three pillars", "Inside each pillar",
      "The five trade metrics", "The math", "Supporting columns",
      "How the words are written", "Sources & limits"]) {
      expect(screen.getByRole("heading", { name: new RegExp(s, "i") })).toBeInTheDocument();
    }
  });

  it("shows the worked example and the live pillar weights", () => {
    render(<MethodologyContent />);
    expect(screen.getAllByText(/Marcus/).length).toBeGreaterThan(0);
    expect(screen.getByText("B+")).toBeInTheDocument();
    expect(screen.getByText(/1,?664/)).toBeInTheDocument();
    expect(screen.getByText("43%")).toBeInTheDocument(); // a pillar weight chip
  });

  it("explains lineup skill with the bench mini-example", () => {
    render(<MethodologyContent />);
    expect(screen.getByText(/Lineup Skill/i)).toBeInTheDocument();
    expect(screen.getByText(/bench/i)).toBeInTheDocument();
  });

  it("never shows the term KTC", () => {
    const { container } = render(<MethodologyContent />);
    expect(container.textContent).not.toMatch(/KTC/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run --config tests/vitest.config.ts tests/Methodology.test.tsx`
Expected: FAIL — `Cannot find module '../components/methodology/MethodologyContent'`.

- [ ] **Step 3: Build MethodologyContent**

Create `web/components/methodology/MethodologyContent.tsx`. Requirements (use the committed spec sections 1–8 as the prose source; pin every number from Global Constraints):

- A hero block: `<h1>How the grade is built</h1>` + the line "Every number on this page traces back to the box scores."
- A recurring **sample card** (small component in this file) showing `Marcus · B+ · 1,664` and the three pillar contributions (`Results +93 · Skill +59 · Outlook +12`); render it at the top of sections 1–5.
- **Section 1 "The verdict"** (`<section id="verdict">`): the letter meaning, 1500 center / C=average / 800–2200 clamp / all-time / league-relative, and the full **letter bands** list from Global Constraints. Introduce Marcus.
- **Section 2 "The three pillars"** (`id="pillars"`): the three `ContributionRow`s for Marcus (label, weight, contribution, shared `scale = max(|93|,|59|,|12|)=93`), plus the one-line "why two equal axes" rationale.
- **Section 3 "Inside each pillar"** (`id="signals"`): for each pillar, its signal `ContributionRow`s (signal rows use `signal` flag, the per-signal `weight`, `contribution`, same scale) + each signal's plain definition + Marcus's `raw`. Give **lineup_skill** the most room and include the worked mini-example: "optimal lineup scored 142, Marcus started 128 → 14 points left on the bench; rolled across the season → 96% efficient." Reuse `SAMPLE.pillars[*].signals` for the rows.
- **Section 4 "The five trade metrics"** (`id="metrics"`): the five metrics with formulas (from Global Constraints / spec §4) + the tight "how a trade's real outcome is traced" block (asset journey, became-grade, pan-out timeline, injury context).
- **Section 5 "The math"** (`id="math"`): z-scoring → weighting → `rating = clamp(1500 + 275·Σ(weight·z), 800, 2200)`, Marcus's final assembly `1500 + 93 + 59 + 12 = 1,664 → B+`, and the Total-Points-stays-out note + ▲▼ note.
- **Section 6 "Supporting columns"** (`id="columns"`): Window, Draft Capital, and **Trade Grade** (explicitly *not* the Franchise letter; the z-bucket bands), record/finishes & standings — per spec §6.
- **Section 7 "How the words are written"** (`id="words"`): the grounded-LLM trust paragraph (spec §7).
- **Section 8 "Sources & limits"** (`id="sources"`): data sources + limitations + the existing GitHub / back-home footer (spec §8).
- Styling: existing Tailwind tokens (`bg-surface`, `border-divider`, `text-dim`, `text-ink`, `font-mono`, etc.), light + dark; mono formula chips as in the current page. A thin left "spine" (e.g. a `border-l border-divider` rail on the content column) connecting sections 1–3.
- **Do not** render "KTC" anywhere.

Keep the file focused: section bodies may be local subcomponents (`Verdict()`, `Pillars()`, …) driven by `SAMPLE`/`SECTIONS`. This is presentational; no hooks, no client directive.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run --config tests/vitest.config.ts tests/Methodology.test.tsx`
Expected: PASS (all coherence + render assertions).

- [ ] **Step 5: Commit**

```bash
git add web/components/methodology/MethodologyContent.tsx web/tests/Methodology.test.tsx
git commit -m "feat(web): methodology page body — top-down descent with worked example"
```

---

### Task 4: Page assembly + sticky TOC + full verification

**Files:**
- Create: `web/components/methodology/MethodologyToc.tsx`
- Modify: `web/app/methodology/page.tsx`

**Interfaces:**
- Consumes: `SECTIONS` (Task 2), `MethodologyContent` (Task 3), existing `Shell`, `TopBar`.
- Produces: the rewritten `/methodology` page.

- [ ] **Step 1: Create the sticky TOC (client component)**

Create `web/components/methodology/MethodologyToc.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { SECTIONS } from "./sample";

export function MethodologyToc() {
  const [active, setActive] = useState(SECTIONS[0].id);
  useEffect(() => {
    const obs = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(e.target.id);
      },
      { rootMargin: "-30% 0px -60% 0px" },
    );
    for (const s of SECTIONS) {
      const el = document.getElementById(s.id);
      if (el) obs.observe(el);
    }
    return () => obs.disconnect();
  }, []);
  return (
    <nav className="hidden lg:block sticky top-20 self-start text-[12px] space-y-1.5">
      {SECTIONS.map((s) => (
        <a
          key={s.id}
          href={`#${s.id}`}
          className={`block transition-colors ${active === s.id ? "text-ink font-semibold" : "text-dim hover:text-ink"}`}
        >
          {s.title}
        </a>
      ))}
    </nav>
  );
}
```

- [ ] **Step 2: Rewrite the page to compose everything**

Replace `web/app/methodology/page.tsx` with:

```tsx
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { MethodologyContent } from "@/components/methodology/MethodologyContent";
import { MethodologyToc } from "@/components/methodology/MethodologyToc";

export default function MethodologyPage() {
  return (
    <Shell>
      <TopBar activeNav="methodology" />
      <div className="lg:grid lg:grid-cols-[180px_1fr] lg:gap-12">
        <MethodologyToc />
        <div className="min-w-0">
          <MethodologyContent />
        </div>
      </div>
    </Shell>
  );
}
```

- [ ] **Step 3: Build to verify (no dev server running)**

Confirm no dev server first: `pgrep -fl "next dev"` (must be empty; if not, stop it before building).
Run: `cd web && npm run build`
Expected: build succeeds — catches a missing `'use client'` (the TOC needs it) or any type error.

- [ ] **Step 4: Run the full web suite**

Run: `cd web && npx vitest run --config tests/vitest.config.ts`
Expected: all green (Methodology + RatingBars + the pre-existing suite — proves the RatingBars extraction didn't regress OverviewTab/Leaderboard tests).

- [ ] **Step 5: Commit**

```bash
git add web/components/methodology/MethodologyToc.tsx web/app/methodology/page.tsx
git commit -m "feat(web): assemble methodology page with sticky scroll-spy TOC"
```

---

## Self-Review

**Spec coverage:**
- 8-section top-down structure → Task 2 (`SECTIONS`) + Task 3 (the section components). ✓
- Worked example "Marcus" (coherent numbers) → Task 2 (`SAMPLE` + coherence tests) + Task 3 (rendered, incl. recurring card). ✓
- Reuse the live "Why this grade" bar idiom → Task 1 (shared `RatingBars`, used by both OverviewTab and the page). ✓
- Lineup-skill showcase + bench mini-example → Task 3 (§3, tested). ✓
- Five metrics, became-grade/lineage/timeline/injury → Task 3 (§4). ✓
- The math + Trade Grade distinct from Franchise letter + supporting columns + grounded-LLM + sources/limits → Task 3 (§5–8). ✓
- Sticky scroll-spy TOC, spine, tokens, hero copy → Task 3 (spine/hero) + Task 4 (TOC). ✓
- Accuracy (weights/bands) + no "KTC" → Global Constraints + tests (weights 43/43/14, `container.textContent` no /KTC/). ✓
- `next build` + full vitest → Task 4. ✓

**Placeholder scan:** Task 3 Step 3 points to the committed spec for the long descriptive prose rather than transcribing every sentence — the spec is a concrete, committed source (not a "TODO"), and every numeric/structural fact and the testable invariants are pinned in the plan. No "add error handling"-style gaps.

**Type consistency:** `ContributionRow` (renamed from `DriverRow`) named identically in Task 1's module and Task 3's usage. `SAMPLE`/`SECTIONS` shapes match between Task 2 (definition + tests) and Task 3 (consumption). `MethodologyContent` (no props, provider-free) consistent between Task 3 (definition/test) and Task 4 (page import). Section `id`s (`verdict`/`pillars`/`signals`/`metrics`/`math`/`columns`/`words`/`sources`) match between `SECTIONS` (Task 2), the `<section id>` wrappers (Task 3), and the TOC anchors (Task 4).
