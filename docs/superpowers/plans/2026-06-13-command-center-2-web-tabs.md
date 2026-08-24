# Command Center · Plan 2 — Web Tabbed Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the owner page (`OwnerDeepDive`) into a tabbed franchise cockpit — a persistent hero band (identity + vitals + optional blurb) over four tabs (Overview / Roster & Health / Future & Draft / Trades) — consuming the outlook data Plan 1 added to `OwnerDetailResp`.

**Architecture:** Decompose the 283-line `OwnerDeepDive.tsx` into a thin shell plus focused child components under `web/components/ownerdeepdive/`. The existing trade content moves *verbatim* into a `TradesTab`. New tabs render Plan 1's `outlook` / `roster_rank` / `draft_skill`. When `outlook` is null (pre-feature cache), the outlook tabs and vitals hide and the page falls back to Trades — no regressions.

**Tech Stack:** Next.js 14 (App Router, RSC + client islands), React, Tailwind (CSS-token classes), Vitest + Testing Library, Playwright.

**Prerequisite:** Plan 1 merged (the `outlook`, `roster_rank`, `draft_skill` fields exist on
`OwnerDetailResp` and in `web/lib/types.ts`).

This is **Plan 2 of 3** (spec: `docs/superpowers/specs/2026-06-13-franchise-command-center-design.md`).

> **Carry-over note from the Plan 1 final review — different rank denominators.** `roster_rank`
> (`#3 / 12`, hero band) ranks **current-roster owners only**, while `draft_skill.rank` (`#2 of 14`,
> Future & Draft tab) ranks **all owners who ever drafted in the chain**. The `of` counts can differ.
> Render each with its own `of` exactly as the API returns it — do NOT assume they share a
> denominator or reuse one count for the other.

---

## File Structure

- **Create** `web/components/ownerdeepdive/util.tsx` — shared `signed`, `tone`, `whenLabel`, `gradePillClass` (moved from `OwnerDeepDive.tsx`).
- **Create** `web/components/ownerdeepdive/TradesTab.tsx` — the current 5 tiles + `CareerArc` + best/worst + receipts table + `DealCard` (moved verbatim).
- **Create** `web/components/ownerdeepdive/HeroBand.tsx` — identity + vitals + optional franchise blurb.
- **Create** `web/components/ownerdeepdive/OverviewTab.tsx` — four teaser cards that switch tabs.
- **Create** `web/components/ownerdeepdive/RosterHealthTab.tsx` — age-by-position, young core, aging risks.
- **Create** `web/components/ownerdeepdive/FutureDraftTab.tsx` — draft capital, needs, draft skill.
- **Modify** `web/components/OwnerDeepDive.tsx` — becomes the shell (hero + tab nav + tab switch + profile editor passthrough).
- **Tests:** `web/tests/OwnerDeepDive.test.tsx` (extend), `web/tests/ownerdeepdive/RosterHealthTab.test.tsx`, `web/tests/ownerdeepdive/FutureDraftTab.test.tsx`, `web/e2e/owner.spec.ts`.

---

## Task 1: Extract shared utils + TradesTab (no behavior change)

Pure refactor first — move existing code out so the shell can grow. The page must look
identical after this task.

**Files:**
- Create: `web/components/ownerdeepdive/util.tsx`
- Create: `web/components/ownerdeepdive/TradesTab.tsx`
- Modify: `web/components/OwnerDeepDive.tsx`

- [ ] **Step 1: Create the shared utils**

```tsx
// web/components/ownerdeepdive/util.tsx
import { OwnerTradeRow } from "@/lib/types";

export function gradePillClass(grade: string): "a" | "b" | "c" {
  const head = grade.charAt(0).toUpperCase();
  if (head === "A") return "a";
  if (head === "B") return "b";
  return "c";
}

export function signed(n: number, digits = 0): string {
  const v = digits ? n.toFixed(digits) : Math.round(n).toLocaleString();
  return n > 0 ? `+${v}` : v;
}

export function tone(n: number): string {
  return n > 0
    ? "text-pos font-semibold"
    : n < 0 ? "text-neg font-semibold" : "text-dim";
}

export function whenLabel(t: OwnerTradeRow): string {
  const yr = `'${String(t.season).slice(2)}`;
  return t.week ? `${yr} W${t.week}` : yr;
}
```

- [ ] **Step 2: Create TradesTab with the moved content**

Move the JSX currently in `OwnerDeepDive.tsx` for sections **2 (five metrics)**, **3 (CareerArc)**,
**4 (best/worst)**, **5 (every trade)**, and the `DealCard` function into this new file. It takes
the data it needs as props and imports helpers from `util.tsx`.

```tsx
// web/components/ownerdeepdive/TradesTab.tsx
"use client";

import { Fragment, useState } from "react";
import Link from "next/link";
import { OwnerDetailResp, OwnerTradeRow } from "@/lib/types";
import { OwnerLabel } from "../OwnerLabel";
import { CareerArc } from "../CareerArc";
import { signed, tone, whenLabel } from "./util";

export function TradesTab({
  leagueId, detail,
}: { leagueId: string; detail: OwnerDetailResp }) {
  const [yearFilter, setYearFilter] = useState<number | "all">("all");

  const byId = new Map(detail.trades.map((t) => [t.trade_id, t]));
  const best = detail.best_trade_id ? byId.get(detail.best_trade_id) : undefined;
  const worst = detail.worst_trade_id ? byId.get(detail.worst_trade_id) : undefined;
  const showWorst = worst && worst.trade_id !== best?.trade_id;

  const seasons = Array.from(new Set(detail.trades.map((t) => t.season)))
    .sort((a, b) => b - a);
  const shownTrades = yearFilter === "all"
    ? detail.trades
    : detail.trades.filter((t) => t.season === yearFilter);

  return (
    <div className="space-y-6">
      {/* five metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {[
          { k: "Trade Value", v: signed(detail.totals_by_lens.ktc), n: detail.totals_by_lens.ktc },
          { k: "Total Points", v: signed(detail.totals_by_lens.production, 1), n: detail.totals_by_lens.production },
          { k: "Regular Season Points", v: signed(detail.totals_by_lens.regular, 1), n: detail.totals_by_lens.regular },
          { k: "Playoff Points", v: signed(detail.totals_by_lens.playoff, 1), n: detail.totals_by_lens.playoff },
          { k: "Toilet Bowl Points", v: signed(detail.totals_by_lens.toilet, 1), n: detail.totals_by_lens.toilet },
        ].map((it) => (
          <div key={it.k} className="bg-surface border border-divider rounded-card p-4">
            <div className="font-mono text-[9px] uppercase tracking-widest text-dim">{it.k}</div>
            <div className={`tabular text-[24px] font-extrabold tracking-tight mt-1.5 ${tone(it.n)}`}>{it.v}</div>
          </div>
        ))}
      </div>

      <CareerArc arc={detail.career_arc} />

      {(best || showWorst) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {best && <DealCard leagueId={leagueId} row={best} kind="best" />}
          {showWorst && <DealCard leagueId={leagueId} row={worst!} kind="worst" />}
        </div>
      )}

      <section className="bg-surface border border-divider rounded-card p-4 px-5">
        <div className="flex justify-between items-baseline gap-3 mb-3.5">
          <div className="flex items-baseline gap-3 min-w-0">
            <div className="text-[14px] font-bold tracking-tight">Every trade</div>
            {seasons.length > 1 && (
              <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter trades by year">
                {[{ key: "all" as const, label: "All" }, ...seasons.map((s) => ({ key: s, label: `'${String(s).slice(2)}` }))].map((it) => {
                  const active = yearFilter === it.key;
                  return (
                    <button key={it.key} type="button" aria-pressed={active}
                      onClick={() => setYearFilter(it.key)}
                      className={`font-mono text-[10px] px-2 py-0.5 rounded border transition-colors ${active ? "border-ink text-ink font-bold" : "border-divider text-dim hover:text-ink hover:border-ink"}`}>
                      {it.label}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          <div className="font-mono text-[10px] text-dim shrink-0">{shownTrades.length} deals</div>
        </div>
        {detail.trades.length === 0 ? (
          <div className="text-dim text-[12px] py-6 text-center">No trades on record.</div>
        ) : (
          <div className="font-mono text-[11px] tabular">
            <div className="grid grid-cols-[58px_1fr_64px_60px_60px_60px_60px] gap-2 pb-2 border-b border-divider text-[10px] uppercase tracking-widest text-dim">
              <div>When</div>
              <div className="font-sans normal-case tracking-normal text-[11px] font-semibold">With · received</div>
              <div className="text-right">Value</div><div className="text-right">Total</div>
              <div className="text-right">Reg</div><div className="text-right">Playoff</div><div className="text-right">Toilet</div>
            </div>
            {shownTrades.map((t) => (
              <Link key={t.trade_id} href={`/league/${leagueId}/trade/${t.trade_id}`}
                className="grid grid-cols-[58px_1fr_64px_60px_60px_60px_60px] gap-2 py-2.5 border-b border-divider last:border-b-0 hover:bg-bg items-center">
                <div className="text-dim">{whenLabel(t)}</div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    {t.counterparties.length === 0 ? <span className="text-dim">—</span> : t.counterparties.map((p, i) => (
                      <Fragment key={p.user_id}>{i > 0 && <span className="text-dim">·</span>}<OwnerLabel owner={p} variant="compact" /></Fragment>
                    ))}
                  </div>
                  <div className="text-dim text-[10px] truncate mt-0.5">{t.assets_short}</div>
                </div>
                <div className={`text-right ${tone(t.swing_ktc)}`}>{signed(t.swing_ktc)}</div>
                <div className={`text-right ${tone(t.swing_prod)}`}>{signed(t.swing_prod, 1)}</div>
                <div className={`text-right ${tone(t.swing_regular)}`}>{signed(t.swing_regular, 1)}</div>
                <div className={`text-right ${tone(t.swing_playoff)}`}>{signed(t.swing_playoff, 1)}</div>
                <div className={`text-right ${tone(t.swing_toilet)}`}>{signed(t.swing_toilet, 1)}</div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function DealCard({ leagueId, row, kind }: { leagueId: string; row: OwnerTradeRow; kind: "best" | "worst" }) {
  const best = kind === "best";
  return (
    <Link href={`/league/${leagueId}/trade/${row.trade_id}`}
      className="block bg-surface border border-divider rounded-card p-4 hover:border-ink transition-colors">
      <div className={`font-mono text-[10px] uppercase tracking-widest ${best ? "text-pos" : "text-neg"}`}>{best ? "▲ Best heist" : "▼ Worst beat"}</div>
      <div className={`tabular text-[22px] font-extrabold tracking-tight mt-1 ${tone(row.swing_ktc)}`}>{signed(row.swing_ktc)}</div>
      <div className="mt-2 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[12px]">
        <span className="font-mono text-[10px] text-dim">{whenLabel(row)}</span>
        {row.counterparties.map((p) => <OwnerLabel key={p.user_id} owner={p} variant="compact" />)}
      </div>
      <div className="text-dim text-[11px] mt-1 truncate">{row.assets_short}</div>
    </Link>
  );
}
```

- [ ] **Step 3: Slim `OwnerDeepDive.tsx` to render the header + `<TradesTab/>`**

Replace sections 2–5 and the `DealCard`/helper functions in `OwnerDeepDive.tsx` with an import
and a single `<TradesTab leagueId={leagueId} detail={detail} />` after the identity header. Remove
the now-duplicated `signed`/`tone`/`whenLabel`/`gradePillClass` and import them from `./ownerdeepdive/util`.

- [ ] **Step 4: Run the existing component test**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx`
Expected: PASS — the existing "renders all five sections" test still passes (content unchanged, just relocated).

- [ ] **Step 5: Commit**

```bash
git add web/components/ownerdeepdive/util.tsx web/components/ownerdeepdive/TradesTab.tsx web/components/OwnerDeepDive.tsx
git commit -m "refactor(web): extract TradesTab + shared utils from OwnerDeepDive"
```

---

## Task 2: Tab scaffold + Overview/Trades switch

**Files:**
- Modify: `web/components/OwnerDeepDive.tsx`
- Create: `web/components/ownerdeepdive/OverviewTab.tsx`
- Test: `web/tests/OwnerDeepDive.test.tsx`

- [ ] **Step 1: Write the failing test (tab switching)**

Append to `web/tests/OwnerDeepDive.test.tsx`:

```tsx
it("defaults to Overview and switches to Trades", async () => {
  const user = userEvent.setup();
  render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
  // Overview tab is active by default
  expect(screen.getByRole("tab", { name: /overview/i })).toHaveAttribute("aria-selected", "true");
  // The receipts table lives in the Trades tab — not visible yet
  expect(screen.queryByText("Every trade")).not.toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: /trades/i }));
  expect(screen.getByText("Every trade")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx`
Expected: FAIL — no `tab` roles yet.

- [ ] **Step 3: Add a minimal Overview placeholder**

```tsx
// web/components/ownerdeepdive/OverviewTab.tsx
"use client";

import { OwnerDetailResp } from "@/lib/types";

export type TabKey = "overview" | "roster" | "future" | "trades";

export function OverviewTab({
  detail, onNavigate,
}: { detail: OwnerDetailResp; onNavigate: (t: TabKey) => void }) {
  // Teaser cards land in Task 5; for now a single jump-to-trades affordance so
  // the tab is functional and testable.
  return (
    <div className="space-y-3">
      <button type="button" onClick={() => onNavigate("trades")}
        className="text-[12px] text-dim hover:text-ink underline">
        View all {detail.trades.length} trades →
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Add the tab nav + switch to `OwnerDeepDive.tsx`**

Add `import { OverviewTab, TabKey } from "./ownerdeepdive/TabKey or OverviewTab"` (export `TabKey`
from `OverviewTab.tsx`), `import { TradesTab } from "./ownerdeepdive/TradesTab"`, and tab state:

```tsx
  const [tab, setTab] = useState<TabKey>("overview");
  const TABS: { key: TabKey; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "roster", label: "Roster & Health" },
    { key: "future", label: "Future & Draft" },
    { key: "trades", label: "Trades" },
  ];
```

Render below the identity `<header>`:

```tsx
  <div role="tablist" aria-label="Franchise sections" className="flex flex-wrap gap-1 border-b border-divider">
    {TABS.map((t) => (
      <button key={t.key} role="tab" aria-selected={tab === t.key}
        onClick={() => setTab(t.key)}
        className={`font-mono text-[11px] px-3 py-2 -mb-px border-b-2 transition-colors ${
          tab === t.key ? "border-ink text-ink font-bold" : "border-transparent text-dim hover:text-ink"}`}>
        {t.label}
      </button>
    ))}
  </div>
  <div className="mt-5">
    {tab === "overview" && <OverviewTab detail={detail} onNavigate={setTab} />}
    {tab === "roster" && <div className="text-dim text-[12px]">Roster & Health — Task 3.</div>}
    {tab === "future" && <div className="text-dim text-[12px]">Future & Draft — Task 4.</div>}
    {tab === "trades" && <TradesTab leagueId={leagueId} detail={detail} />}
  </div>
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx`
Expected: PASS (both the existing test — now navigate to Trades first — and the new tab test).

> If the existing "renders all five sections" test asserts trade content directly, update it to
> click the Trades tab first (`await user.click(screen.getByRole("tab", { name: /trades/i }))`)
> before asserting the receipts/tiles.

- [ ] **Step 6: Commit**

```bash
git add web/components/OwnerDeepDive.tsx web/components/ownerdeepdive/OverviewTab.tsx web/tests/OwnerDeepDive.test.tsx
git commit -m "feat(web): tabbed shell for the owner command center"
```

---

## Task 3: Roster & Health tab

**Files:**
- Create: `web/components/ownerdeepdive/RosterHealthTab.tsx`
- Modify: `web/components/OwnerDeepDive.tsx`
- Test: `web/tests/ownerdeepdive/RosterHealthTab.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/ownerdeepdive/RosterHealthTab.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RosterHealthTab } from "../../components/ownerdeepdive/RosterHealthTab";
import { OutlookView } from "../../lib/types";

const OUTLOOK: OutlookView = {
  window: "Ascending", trajectory: "young + pick-rich",
  age_profile: {
    avg_age_by_position: { RB: 23.5, WR: 24.0 }, overall_avg_age: 24.0,
    aging_risks: [{ player_id: "rb_old", full_name: "Old Back", position: "RB", age: 29 }],
    core_young: [{ player_id: "wr_young", full_name: "Young Gun", position: "WR", age: 22 }],
  },
  draft_capital: { picks_by_season: {}, picks_by_season_round: {}, net_vs_average: 0, status: "neutral", total_value: 0 },
  draft_needs: [],
};

describe("RosterHealthTab", () => {
  it("renders age by position, young core, and aging risks", () => {
    render(<RosterHealthTab outlook={OUTLOOK} />);
    expect(screen.getByText("Young Gun")).toBeInTheDocument();
    expect(screen.getByText("Old Back")).toBeInTheDocument();
    expect(screen.getByText(/RB/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/ownerdeepdive/RosterHealthTab.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the component**

```tsx
// web/components/ownerdeepdive/RosterHealthTab.tsx
"use client";

import { OutlookView } from "@/lib/types";

function PlayerChip({ name, position, age }: { name: string; position: string; age: number | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 bg-bg border border-divider rounded-full px-2.5 py-1 text-[12px]">
      <span className="font-semibold">{name}</span>
      <span className="font-mono text-[10px] text-dim">{position}{age != null ? ` · ${age}` : ""}</span>
    </span>
  );
}

export function RosterHealthTab({ outlook }: { outlook: OutlookView }) {
  const ap = outlook.age_profile;
  const positions = Object.entries(ap.avg_age_by_position).sort((a, b) => a[0].localeCompare(b[0]));
  const maxAge = Math.max(30, ...positions.map(([, v]) => v));
  return (
    <div className="space-y-6">
      <section className="bg-surface border border-divider rounded-card p-5">
        <div className="text-[14px] font-bold tracking-tight mb-1">Roster age</div>
        <div className="font-mono text-[11px] text-dim mb-4">overall avg {ap.overall_avg_age.toFixed(1)}</div>
        <div className="space-y-2">
          {positions.map(([pos, age]) => (
            <div key={pos} className="flex items-center gap-3">
              <div className="w-10 font-mono text-[11px] text-dim">{pos}</div>
              <div className="flex-1 h-3 rounded bg-bg overflow-hidden">
                <div className="h-full bg-ink/60 rounded" style={{ width: `${Math.min(100, (age / maxAge) * 100)}%` }} />
              </div>
              <div className="w-10 text-right font-mono text-[11px] tabular">{age.toFixed(1)}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-surface border border-divider rounded-card p-5">
        <div className="text-[14px] font-bold tracking-tight mb-3">Young core <span className="font-mono text-[10px] text-dim">≤ 25</span></div>
        {ap.core_young.length === 0 ? <div className="text-dim text-[12px]">None.</div> : (
          <div className="flex flex-wrap gap-2">
            {ap.core_young.map((p) => <PlayerChip key={p.player_id} name={p.full_name} position={p.position} age={p.age} />)}
          </div>
        )}
      </section>

      <section className="bg-surface border border-divider rounded-card p-5">
        <div className="text-[14px] font-bold tracking-tight mb-3">Aging risks</div>
        {ap.aging_risks.length === 0 ? <div className="text-dim text-[12px]">None.</div> : (
          <div className="flex flex-wrap gap-2">
            {ap.aging_risks.map((p) => <PlayerChip key={p.player_id} name={p.full_name} position={p.position} age={p.age} />)}
          </div>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Wire it into the shell**

In `OwnerDeepDive.tsx`, replace the `roster` placeholder:

```tsx
    {tab === "roster" && (detail.outlook
      ? <RosterHealthTab outlook={detail.outlook} />
      : <div className="text-dim text-[12px]">Outlook not available — refresh the league.</div>)}
```

Add `import { RosterHealthTab } from "./ownerdeepdive/RosterHealthTab";`.

- [ ] **Step 5: Run to verify it passes**

Run: `cd web && npx vitest run tests/ownerdeepdive/RosterHealthTab.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/components/ownerdeepdive/RosterHealthTab.tsx web/components/OwnerDeepDive.tsx web/tests/ownerdeepdive/RosterHealthTab.test.tsx
git commit -m "feat(web): roster & health tab"
```

---

## Task 4: Future & Draft tab

**Files:**
- Create: `web/components/ownerdeepdive/FutureDraftTab.tsx`
- Modify: `web/components/OwnerDeepDive.tsx`
- Test: `web/tests/ownerdeepdive/FutureDraftTab.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/ownerdeepdive/FutureDraftTab.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FutureDraftTab } from "../../components/ownerdeepdive/FutureDraftTab";
import { OutlookView, DraftSkillView } from "../../lib/types";

const OUTLOOK: OutlookView = {
  window: "Rebuilding", trajectory: "stockpiling",
  age_profile: { avg_age_by_position: {}, overall_avg_age: 0, aging_risks: [], core_young: [] },
  draft_capital: {
    picks_by_season: { "2027": 5, "2028": 4 },
    picks_by_season_round: { "2027-1": 2, "2027-2": 1 },
    net_vs_average: 3, status: "pick-rich", total_value: 1800,
  },
  draft_needs: [{ position: "TE", urgency: "immediate", reason: "no startable TE" }],
};
const SKILL: DraftSkillView = { score: 0.42, rank: 1, of: 12 };

describe("FutureDraftTab", () => {
  it("renders capital, needs, and draft skill", () => {
    render(<FutureDraftTab outlook={OUTLOOK} draftSkill={SKILL} />);
    expect(screen.getByText(/pick-rich/i)).toBeInTheDocument();
    expect(screen.getByText("2027")).toBeInTheDocument();
    expect(screen.getByText(/no startable TE/)).toBeInTheDocument();
    expect(screen.getByText(/#1/)).toBeInTheDocument(); // draft skill rank
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/ownerdeepdive/FutureDraftTab.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the component**

```tsx
// web/components/ownerdeepdive/FutureDraftTab.tsx
"use client";

import { DraftSkillView, OutlookView } from "@/lib/types";

const URGENCY_TONE: Record<string, string> = {
  immediate: "text-neg", developing: "text-dim",
};

export function FutureDraftTab({
  outlook, draftSkill,
}: { outlook: OutlookView; draftSkill?: DraftSkillView | null }) {
  const dc = outlook.draft_capital;
  const seasons = Object.keys(dc.picks_by_season).sort();
  return (
    <div className="space-y-6">
      <section className="bg-surface border border-divider rounded-card p-5">
        <div className="flex items-baseline justify-between mb-4">
          <div className="text-[14px] font-bold tracking-tight">Draft capital</div>
          <span className="font-mono text-[11px] text-dim">
            {dc.status} · {dc.net_vs_average >= 0 ? `+${dc.net_vs_average}` : dc.net_vs_average} vs avg · {Math.round(dc.total_value).toLocaleString()} value
          </span>
        </div>
        <div className="flex flex-wrap gap-3">
          {seasons.map((s) => (
            <div key={s} className="bg-bg border border-divider rounded-card px-4 py-3 text-center">
              <div className="font-mono text-[10px] text-dim">{s}</div>
              <div className="tabular text-[22px] font-extrabold">{dc.picks_by_season[s]}</div>
              <div className="font-mono text-[9px] text-dim">picks</div>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-surface border border-divider rounded-card p-5">
        <div className="text-[14px] font-bold tracking-tight mb-3">Draft needs</div>
        {outlook.draft_needs.length === 0 ? <div className="text-dim text-[12px]">No pressing needs.</div> : (
          <ul className="space-y-2">
            {outlook.draft_needs.map((n, i) => (
              <li key={`${n.position}-${i}`} className="flex items-baseline gap-2 text-[13px]">
                <span className="font-bold">{n.position}</span>
                <span className={`font-mono text-[10px] uppercase ${URGENCY_TONE[n.urgency] ?? "text-dim"}`}>{n.urgency}</span>
                <span className="text-dim">— {n.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {draftSkill && (
        <section className="bg-surface border border-divider rounded-card p-5">
          <div className="text-[14px] font-bold tracking-tight mb-1">Past draft skill</div>
          <div className="font-mono text-[11px] text-dim">
            #{draftSkill.rank} of {draftSkill.of} · score {draftSkill.score >= 0 ? "+" : ""}{draftSkill.score.toFixed(2)}
          </div>
          <div className="text-dim text-[11px] mt-1">How past rookie picks panned out vs their draft-slot tier.</div>
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wire it into the shell**

```tsx
    {tab === "future" && (detail.outlook
      ? <FutureDraftTab outlook={detail.outlook} draftSkill={detail.draft_skill} />
      : <div className="text-dim text-[12px]">Outlook not available — refresh the league.</div>)}
```

Add `import { FutureDraftTab } from "./ownerdeepdive/FutureDraftTab";`.

- [ ] **Step 5: Run to verify it passes**

Run: `cd web && npx vitest run tests/ownerdeepdive/FutureDraftTab.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/components/ownerdeepdive/FutureDraftTab.tsx web/components/OwnerDeepDive.tsx web/tests/ownerdeepdive/FutureDraftTab.test.tsx
git commit -m "feat(web): future & draft tab"
```

---

## Task 5: Hero band vitals + Overview teasers

**Files:**
- Create: `web/components/ownerdeepdive/HeroBand.tsx`
- Modify: `web/components/ownerdeepdive/OverviewTab.tsx`
- Modify: `web/components/OwnerDeepDive.tsx`
- Test: `web/tests/OwnerDeepDive.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `web/tests/OwnerDeepDive.test.tsx` a `DETAIL_WITH_OUTLOOK` built from `DETAIL` plus:

```tsx
const DETAIL_WITH_OUTLOOK = {
  ...DETAIL,
  outlook: {
    window: "Ascending", trajectory: "young + pick-rich",
    age_profile: { avg_age_by_position: { RB: 23.5 }, overall_avg_age: 24.2, aging_risks: [], core_young: [] },
    draft_capital: { picks_by_season: { "2027": 5 }, picks_by_season_round: {}, net_vs_average: 3, status: "pick-rich", total_value: 1800 },
    draft_needs: [],
  },
  roster_rank: { rank: 3, of: 12 },
  draft_skill: { score: 0.4, rank: 2, of: 12 },
};

it("shows hero vitals when outlook present", () => {
  render(<OwnerDeepDive leagueId="L" detail={DETAIL_WITH_OUTLOOK} />);
  expect(screen.getByText("Ascending")).toBeInTheDocument();
  expect(screen.getByText("#3 / 12")).toBeInTheDocument();
  expect(screen.getByText("24.2")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx`
Expected: FAIL — vitals not rendered.

- [ ] **Step 3: Implement HeroBand**

```tsx
// web/components/ownerdeepdive/HeroBand.tsx
"use client";

import { OwnerDetailResp, StandingRow } from "@/lib/types";
import { OwnerLabel } from "../OwnerLabel";
import { gradePillClass } from "./util";

function Vital({ k, v }: { k: string; v: string }) {
  return (
    <div className="bg-bg border border-divider rounded-card px-3 py-2 text-center">
      <div className="tabular text-[15px] font-bold">{v}</div>
      <div className="font-mono text-[9px] uppercase tracking-widest text-dim">{k}</div>
    </div>
  );
}

export function HeroBand({
  detail, standing, totalOwners, archetype, rivalNames, roast, editAffordance,
}: {
  detail: OwnerDetailResp;
  standing?: StandingRow;
  totalOwners?: number;
  archetype?: string;
  rivalNames: string[];
  roast?: string;
  editAffordance?: React.ReactNode;
}) {
  const grade = standing?.grade;
  const ol = detail.outlook;
  const rank = detail.roster_rank;
  return (
    <header className="bg-surface border border-divider rounded-card p-5">
      <div className="flex items-start justify-between gap-3">
        <OwnerLabel owner={detail.owner} variant="full" size="lg" />
        <div className="flex items-center gap-2 shrink-0">
          {grade && (
            <span className="px-2 py-0.5 rounded font-bold text-[13px] font-sans"
              style={{ background: `var(--pill-${gradePillClass(grade)}-bg)`, borderColor: `var(--pill-${gradePillClass(grade)}-border)`, color: `var(--pill-${gradePillClass(grade)}-text)`, border: "1px solid" }}>
              {grade}
            </span>
          )}
          {editAffordance}
        </div>
      </div>

      {(standing || archetype || rivalNames.length > 0) && (
        <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-dim">
          {standing && <span className="font-mono">#{standing.rank}{totalOwners ? ` of ${totalOwners}` : ""}</span>}
          {archetype && (<><span aria-hidden="true">·</span><span className="font-semibold text-ink">{archetype}</span></>)}
          {rivalNames.length > 0 && (<><span aria-hidden="true">·</span><span>rivals: {rivalNames.join(", ")}</span></>)}
        </div>
      )}
      {roast && <div className="mt-1.5 text-[12px] italic text-dim leading-snug">"{roast}"</div>}

      {ol && (
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Vital k="Window" v={ol.window} />
          <Vital k="Roster rank" v={rank ? `#${rank.rank} / ${rank.of}` : "—"} />
          <Vital k="Avg age" v={ol.age_profile.overall_avg_age.toFixed(1)} />
          <Vital k="Draft capital" v={ol.draft_capital.status} />
        </div>
      )}

      {detail.franchise_blurb && (
        <div className="mt-3 text-[13px] italic text-ink/80 leading-snug">{detail.franchise_blurb}</div>
      )}
    </header>
  );
}
```

> NOTE: `detail.franchise_blurb` is populated by **Plan 3**; until then it is `undefined` and the
> block simply doesn't render. Add `franchise_blurb?: string | null;` to `OwnerDetailResp` in
> `web/lib/types.ts` now so this compiles (Plan 3 fills the backend).

- [ ] **Step 4: Replace the identity header in `OwnerDeepDive.tsx` with `<HeroBand/>`**

Move the rivalNames computation and the edit button JSX into the `editAffordance` prop, and render
`<HeroBand detail={detail} standing={standing} totalOwners={totalOwners} archetype={profile?.archetype}
rivalNames={rivalNames} roast={profile?.roast} editAffordance={editable ? <EditButton/> : null} />`.

- [ ] **Step 5: Build the real Overview teasers**

Replace `OverviewTab.tsx` body with four teaser cards (Roster / Future / Track record / Signature deals).
Cards that map to outlook tabs only render when `detail.outlook` exists:

```tsx
// web/components/ownerdeepdive/OverviewTab.tsx
"use client";

import { OwnerDetailResp } from "@/lib/types";
import { CareerArc } from "../CareerArc";
import { signed } from "./util";

export type TabKey = "overview" | "roster" | "future" | "trades";

function Teaser({ title, onClick, link, children }: { title: string; onClick?: () => void; link?: string; children: React.ReactNode }) {
  return (
    <div className="bg-surface border border-divider rounded-card p-4">
      <div className="flex items-baseline justify-between mb-2">
        <div className="font-mono text-[10px] uppercase tracking-widest text-dim">{title}</div>
        {onClick && <button type="button" onClick={onClick} className="text-[11px] text-pos hover:underline">full →</button>}
      </div>
      {children}
    </div>
  );
}

export function OverviewTab({ detail, onNavigate }: { detail: OwnerDetailResp; onNavigate: (t: TabKey) => void }) {
  const ol = detail.outlook;
  const byId = new Map(detail.trades.map((t) => [t.trade_id, t]));
  const best = detail.best_trade_id ? byId.get(detail.best_trade_id) : undefined;
  const worst = detail.worst_trade_id ? byId.get(detail.worst_trade_id) : undefined;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {ol && (
        <Teaser title="Roster & Health" onClick={() => onNavigate("roster")}>
          <div className="text-[12px]">avg age {ol.age_profile.overall_avg_age.toFixed(1)}</div>
          <div className="text-[12px] text-dim mt-1">{ol.age_profile.core_young.length} young · {ol.age_profile.aging_risks.length} aging</div>
        </Teaser>
      )}
      {ol && (
        <Teaser title="Future & Draft" onClick={() => onNavigate("future")}>
          <div className="text-[12px]">{ol.draft_capital.status}</div>
          <div className="text-[12px] text-dim mt-1">{ol.draft_needs.map((n) => n.position).join(", ") || "no pressing needs"}</div>
        </Teaser>
      )}
      <Teaser title="Track record" onClick={() => onNavigate("trades")}>
        <CareerArc arc={detail.career_arc} />
      </Teaser>
      <Teaser title="Signature deals" onClick={() => onNavigate("trades")}>
        {best && <div className="text-[12px] text-pos">▲ {signed(best.swing_ktc)} · {best.assets_short}</div>}
        {worst && worst.trade_id !== best?.trade_id && <div className="text-[12px] text-neg mt-1">▼ {signed(worst.swing_ktc)} · {worst.assets_short}</div>}
      </Teaser>
    </div>
  );
}
```

(Update `OwnerDeepDive.tsx`'s `import { TabKey } from ...` to import from `OverviewTab`.)

- [ ] **Step 6: Run to verify it passes**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx`
Expected: PASS (vitals test + earlier tests).

- [ ] **Step 7: Commit**

```bash
git add web/components/ownerdeepdive/HeroBand.tsx web/components/ownerdeepdive/OverviewTab.tsx web/components/OwnerDeepDive.tsx web/lib/types.ts web/tests/OwnerDeepDive.test.tsx
git commit -m "feat(web): hero vitals + overview teasers"
```

---

## Task 6: Graceful degradation + dynamic tab list

When `outlook` is null (pre-feature cache), hide the outlook tabs and default to Overview (which
itself shows only the Track-record + Signature-deals teasers). The page must never show empty
outlook tabs.

**Files:**
- Modify: `web/components/OwnerDeepDive.tsx`
- Test: `web/tests/OwnerDeepDive.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
it("hides outlook tabs when outlook is absent", () => {
  render(<OwnerDeepDive leagueId="L" detail={DETAIL} />); // DETAIL has no outlook
  expect(screen.queryByRole("tab", { name: /roster & health/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: /future & draft/i })).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /overview/i })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /trades/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx`
Expected: FAIL — the outlook tabs render unconditionally.

- [ ] **Step 3: Make the tab list dynamic**

```tsx
  const TABS: { key: TabKey; label: string }[] = [
    { key: "overview", label: "Overview" },
    ...(detail.outlook ? [
      { key: "roster" as TabKey, label: "Roster & Health" },
      { key: "future" as TabKey, label: "Future & Draft" },
    ] : []),
    { key: "trades", label: "Trades" },
  ];
```

(The `tab === "roster"/"future"` render branches already guard on `detail.outlook`, so the
"refresh the league" fallback strings from Tasks 3/4 become dead code — remove them and render the
components directly, since the tabs only exist when `outlook` is present.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx`
Expected: PASS — all owner tests green.

- [ ] **Step 5: Typecheck + full web unit suite**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: no type errors; all tests pass.

- [ ] **Step 6: Commit**

```bash
git add web/components/OwnerDeepDive.tsx web/tests/OwnerDeepDive.test.tsx
git commit -m "feat(web): hide outlook tabs on pre-feature caches"
```

---

## Task 7: E2E smoke + visual pass

**Files:**
- Create: `web/e2e/owner.spec.ts`

- [ ] **Step 1: Write the e2e test**

```ts
// web/e2e/owner.spec.ts
import { test, expect } from "@playwright/test";

// Assumes a seeded/cached league is reachable at this id in the dev environment.
// Replace LEAGUE_ID / OWNER_ID with the smoke-test fixtures used by other e2e specs.
const LEAGUE_ID = process.env.E2E_LEAGUE_ID ?? "demo";
const OWNER_ID = process.env.E2E_OWNER_ID ?? "demo-owner";

test("owner command center renders and switches tabs", async ({ page }) => {
  await page.goto(`/league/${LEAGUE_ID}/owner/${OWNER_ID}`);
  await expect(page.getByRole("tablist", { name: /franchise sections/i })).toBeVisible();
  await page.getByRole("tab", { name: /trades/i }).click();
  await expect(page.getByText("Every trade")).toBeVisible();
});
```

- [ ] **Step 2: Run e2e (if the dev environment has a cached league)**

Run: `cd web && npm run test:e2e -- owner.spec.ts`
Expected: PASS against a warmed league. If no fixture exists, mark it `test.skip` with a comment and rely on unit coverage — do not invent a fixture.

- [ ] **Step 3: Manual visual check**

Run `make dev-api` + `make dev-web`, open an owner page, confirm: hero vitals, all four tabs,
Overview teasers jump to the right tab, Roster/Future render real data, Trades identical to before.

- [ ] **Step 4: Commit**

```bash
git add web/e2e/owner.spec.ts
git commit -m "test(web): e2e smoke for owner command center"
```

---

## Self-Review

**Spec coverage:**
- Tabbed cockpit (Overview / Roster & Health / Future & Draft / Trades) → Tasks 2–6. ✓
- Hero band: identity + Window/Roster-rank/Avg-age/Draft-capital vitals → Task 5. ✓
- Overview = teaser of every domain, links into tabs → Task 5. ✓
- Trades tab = current content verbatim → Task 1. ✓
- Roster & Health (age by position, young core, aging risks) → Task 3. ✓
- Future & Draft (capital, needs, draft skill) → Task 4. ✓
- Franchise blurb render slot (data from Plan 3) → Task 5 (conditional, graceful). ✓
- Graceful degradation when outlook null → Task 6. ✓
- Editable profile stays Owners-tab-only → preserved via `editAffordance` passthrough (Task 5). ✓

**Placeholder scan:** none. Task 2 ships an intentionally minimal Overview that Task 5 replaces —
both fully specified, not a placeholder. The e2e fixture ids are env-driven with a documented skip
fallback (Task 7).

**Type consistency:** `TabKey` is defined once in `OverviewTab.tsx` and imported everywhere.
`OutlookView`/`DraftSkillView`/`RankView` field names match Plan 1's `web/lib/types.ts` exactly.
`detail.franchise_blurb` typed in Task 5, populated in Plan 3. Helper names (`signed`/`tone`/
`whenLabel`/`gradePillClass`) live once in `util.tsx`.
