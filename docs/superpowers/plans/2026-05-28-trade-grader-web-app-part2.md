> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Trade Grader Web App Implementation Plan — Part 2

> **For agentic workers:** Continue from `2026-05-28-trade-grader-web-app.md`. This file picks up at Phase 5, Task 23. Use superpowers:subagent-driven-development.

Phases covered here: hero stats, standings table, sidebar, owner detail, trade detail, methodology, Railway deployment + polish.

---

## Conventions (repeated for executors reading this file in isolation)

- Backend tests: `pytest` from `api/`; frontend unit: `npm run test --` from `web/`; e2e: `npm run test:e2e` from `web/`.
- TDD loop: failing test → confirm fail → implement → confirm pass → commit. Each commit references one logical change.
- Frontend uses Tailwind classes against CSS-custom-property tokens declared in `web/app/globals.css` (`--bg`, `--ink`, `--pos`, etc.).
- All commits include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

---

# Phase 5 — Hero stats + standings table + sidebar

### Task 23: Hero stat cards with lens-aware labels and tooltips

**Files:**
- Create: `web/components/HeroStatCard.tsx`
- Create: `web/components/HeroStatsRow.tsx`
- Modify: `web/components/DashboardClient.tsx`
- Create: `web/tests/HeroStatCard.test.tsx`

- [ ] **Step 1: Write failing test**

Create `web/tests/HeroStatCard.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HeroStatCard } from "../components/HeroStatCard";

describe("HeroStatCard", () => {
  it("shows title, sublabel, value, context", () => {
    render(
      <HeroStatCard
        title="Biggest Win"
        sublabel="value swing · KTC"
        value="+2,755"
        valueColor="pos"
        context="Tom · Bijan deal"
        tooltip={{
          title: "Snapshot KTC swing",
          body: "Today's market value differential.",
          formula: "Σ(received) − Σ(given)",
        }}
      />,
    );
    expect(screen.getByText("Biggest Win")).toBeInTheDocument();
    expect(screen.getByText("value swing · KTC")).toBeInTheDocument();
    expect(screen.getByText("+2,755")).toBeInTheDocument();
    expect(screen.getByText("Tom · Bijan deal")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Confirm fail**

```bash
cd web && npm run test -- --run HeroStatCard
```

- [ ] **Step 3: Create `web/components/HeroStatCard.tsx`**

```tsx
import { InfoTooltip } from "./InfoTooltip";

interface Props {
  title: string;
  sublabel: string;
  value: string;
  valueColor?: "ink" | "pos" | "neg";
  context: string;
  unit?: string;
  tooltip: { title: string; body: string; formula?: string };
}

export function HeroStatCard({
  title, sublabel, value, valueColor = "ink", context, unit, tooltip,
}: Props) {
  const color = valueColor === "pos"
    ? "text-pos"
    : valueColor === "neg"
      ? "text-neg" : "text-ink";
  return (
    <div className="bg-surface border border-divider rounded-card p-4">
      <div className="flex justify-between items-start">
        <div>
          <div className="text-[13px] font-bold tracking-tight leading-tight">
            {title}
          </div>
          <div className="font-mono text-[9px] uppercase tracking-widest text-dim mt-0.5">
            {sublabel}
          </div>
        </div>
        <InfoTooltip {...tooltip} />
      </div>
      <div className={`tabular text-[28px] font-extrabold tracking-tight leading-none mt-2 ${color}`}>
        {value}
      </div>
      <div className="font-mono text-[10px] text-dim mt-1.5 tracking-wide">
        {context}
      </div>
      {unit && (
        <div className="font-mono text-[9px] text-dim mt-0.5 uppercase tracking-widest">
          {unit}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create `web/components/HeroStatsRow.tsx`**

```tsx
import { HeroStatCard } from "./HeroStatCard";
import { DashboardResp, Lens } from "@/lib/types";

const LENS_SUBLABEL: Record<Lens, string> = {
  ktc: "value swing · KTC",
  production: "points scored · since trade",
  impact: "decisive + playoff starts",
};

const TOOLTIPS = {
  activity: {
    title: "Trade Activity",
    body: "Total trades graded in the selected window.",
  },
  biggest_win: {
    ktc: {
      title: "Snapshot KTC value swing",
      body: "Difference between today's KTC value of assets received and given. Updates as KTC updates.",
      formula: "Σ(value received) − Σ(value given) · today's prices",
    },
    production: {
      title: "Hindsight production swing",
      body: "Sum of points the received players have actually scored for the receiving team since the trade, minus points the given players scored anywhere they ended up.",
      formula: "Σ(received pts) − Σ(given phantom pts)",
    },
    impact: {
      title: "Realized impact total",
      body: "Decisive starts (player score > margin of victory) + playoff starts attributed to the received players.",
      formula: "DS + PS",
    },
  },
  most_active: {
    title: "Most Active",
    body: "Owner who participated in the most trades in the selected window.",
  },
};

export function HeroStatsRow({ data }: { data: DashboardResp }) {
  const lens = data.selected_lens;
  const sub = LENS_SUBLABEL[lens];
  const win = data.hero_stats.biggest_win;
  const loss = data.hero_stats.biggest_loss;
  return (
    <div className="grid grid-cols-4 gap-3.5 mb-7">
      <HeroStatCard
        title="Trade Activity"
        sublabel="total trades · window"
        value={data.hero_stats.activity.value}
        context={data.hero_stats.activity.context}
        tooltip={TOOLTIPS.activity}
      />
      <HeroStatCard
        title="Biggest Win"
        sublabel={sub}
        value={win.value}
        valueColor="pos"
        context={win.context}
        unit={win.date && win.counterparty ? `${win.date} · vs ${win.counterparty}` : undefined}
        tooltip={TOOLTIPS.biggest_win[lens]}
      />
      <HeroStatCard
        title="Biggest Loss"
        sublabel={sub}
        value={loss.value}
        valueColor="neg"
        context={loss.context}
        unit={loss.date && loss.counterparty ? `${loss.date} · vs ${loss.counterparty}` : undefined}
        tooltip={TOOLTIPS.biggest_win[lens]}
      />
      <HeroStatCard
        title="Most Active"
        sublabel="trade count · window"
        value={data.hero_stats.most_active.value}
        context={data.hero_stats.most_active.context}
        tooltip={TOOLTIPS.most_active}
      />
    </div>
  );
}
```

- [ ] **Step 5: Modify `web/components/DashboardClient.tsx`** to render `HeroStatsRow`

Replace the placeholder `<pre>` and the placeholder `totalTrades` value with real values. The new render block (replacing the bottom JSX in DashboardClient):

```tsx
import { HeroStatsRow } from "./HeroStatsRow";

// ... inside the component, replace the lower JSX:
const activityCount = Number(data.hero_stats.activity.value);
return (
  <>
    <ProgressModal open={refreshing} events={events} />
    <LeagueHeader league={data.league} totalTrades={activityCount} />
    <YearTabs
      seasons={seasons}
      current={data.selected_year}
      leagueId={leagueId}
      lens={data.selected_lens}
    />
    <div className="flex justify-between items-end mb-3">
      <div>
        <div className="text-[13px] font-semibold tracking-tight">
          Trade highlights {data.selected_year === "all"
            ? "(all years)"
            : `for ${data.selected_year}`}
        </div>
        <div className="text-[11px] text-dim">
          Switch lens: "by KTC" = today&apos;s market · "by Production" = points
          scored · "by Impact" = decisive + playoff starts
        </div>
      </div>
      <LensSwitcher
        current={data.selected_lens}
        leagueId={leagueId}
        year={String(data.selected_year)}
      />
    </div>
    <HeroStatsRow data={data} />
  </>
);
```

- [ ] **Step 6: Confirm tests pass + build**

```bash
cd web && npm run test -- --run HeroStatCard && npm run build
```

Expected: PASS + build succeeds.

- [ ] **Step 7: Commit**

```bash
git add web/components/HeroStatCard.tsx web/components/HeroStatsRow.tsx web/components/DashboardClient.tsx web/tests/HeroStatCard.test.tsx
git commit -m "$(cat <<'EOF'
Add hero stat cards with lens-aware labels + tooltips

HeroStatCard: title, mono sublabel naming the lens, big value, context
line, optional unit. HeroStatsRow swaps the sublabel + tooltip
copy when the lens changes so the meaning of "biggest win" is never
ambiguous.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 24: First-visit explainer banner

**Files:**
- Create: `web/components/ExplainerBanner.tsx`
- Modify: `web/components/DashboardClient.tsx`

- [ ] **Step 1: Create `web/components/ExplainerBanner.tsx`**

```tsx
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const STORAGE_KEY = "tg-explainer-dismissed";

export function ExplainerBanner() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    setShow(localStorage.getItem(STORAGE_KEY) !== "1");
  }, []);

  if (!show) return null;
  return (
    <div className="relative border border-[#fef08a] rounded-card p-4 mb-5 bg-[#fffbeb] text-[#0e0e0e]">
      <button
        onClick={() => {
          localStorage.setItem(STORAGE_KEY, "1");
          setShow(false);
        }}
        className="absolute top-3 right-3 text-dim text-[14px]"
        aria-label="dismiss"
      >
        ×
      </button>
      <div className="font-mono text-[9px] uppercase tracking-widest text-[#92400e]">
        First time here?
      </div>
      <div className="mt-1 text-[13px] font-bold tracking-tight">
        What you&apos;re looking at
      </div>
      <p className="mt-1.5 text-[12px] leading-relaxed text-[#555]">
        Every trade in your league is graded three ways:{" "}
        <strong className="text-ink">Value Today</strong> (what each side is worth
        right now on KTC),{" "}
        <strong className="text-ink">Points Scored</strong> (how the received
        players have actually performed since the trade), and{" "}
        <strong className="text-ink">Impact</strong> (whether those players
        started, contributed in wins, and made the playoffs). Numbers in green
        favor that owner; red against. Hover any "i" for the precise definition.
      </p>
      <Link href="/methodology" className="mt-2.5 inline-block font-mono text-[10px] underline">
        Read the full methodology →
      </Link>
    </div>
  );
}
```

- [ ] **Step 2: Modify `web/components/DashboardClient.tsx`** to render the banner above the YearTabs:

```tsx
import { ExplainerBanner } from "./ExplainerBanner";

// In the JSX, just above <YearTabs ... />:
<ExplainerBanner />
```

- [ ] **Step 3: Verify build**

```bash
cd web && npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/components/ExplainerBanner.tsx web/components/DashboardClient.tsx
git commit -m "$(cat <<'EOF'
Add first-visit explainer banner

Sits above the year tabs. Names the three lenses in plain English,
links to /methodology, dismissable to localStorage so power users
aren't nagged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 25: Standings table — sortable headers + filter row + rows

**Files:**
- Create: `web/components/StandingsTable.tsx`
- Create: `web/lib/standings-filter.ts`
- Create: `web/tests/standings-filter.test.ts`
- Modify: `web/components/DashboardClient.tsx`

Client-side sort + filter over the data the API returns. URL holds the state.

- [ ] **Step 1: Write failing test**

Create `web/tests/standings-filter.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { applyStandingsState } from "../lib/standings-filter";
import { StandingRow } from "../lib/types";

const ROWS: StandingRow[] = [
  { rank: 1, user_id: "u1", display_name: "Tom",  net_ktc: 2755, net_production: 406.8, trades: 5, ps_plus: 2,  grade: "A" },
  { rank: 2, user_id: "u2", display_name: "Mike", net_ktc: 1120, net_production: 220.1, trades: 5, ps_plus: 1,  grade: "A−" },
  { rank: 3, user_id: "u3", display_name: "Jim",  net_ktc:  210, net_production: -40.5, trades: 4, ps_plus: 0,  grade: "B" },
  { rank: 4, user_id: "u4", display_name: "Sarah",net_ktc: -1890, net_production: -420.5, trades: 4, ps_plus: -1, grade: "D" },
];

describe("applyStandingsState", () => {
  it("sort by net_production asc", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "net_production", direction: "asc" }, filters: {},
    });
    expect(out[0].display_name).toBe("Sarah");
    expect(out[3].display_name).toBe("Tom");
  });

  it("filters by name substring", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "net_ktc", direction: "desc" },
      filters: { display_name: ["mi"] },
    });
    expect(out.map((r) => r.display_name)).toEqual(["Mike", "Jim"]);
  });

  it("filters by numeric range", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "net_ktc", direction: "desc" },
      filters: { net_ktc: [0, null] },
    });
    expect(out.map((r) => r.display_name)).toEqual(["Tom", "Mike", "Jim"]);
  });

  it("filters by grade pills", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "net_ktc", direction: "desc" },
      filters: { grade: ["A", "B"] },
    });
    // A− is grade A bucket; B is B bucket.
    expect(out.map((r) => r.display_name)).toEqual(["Tom", "Mike", "Jim"]);
  });

  it("rank renumbers after sort + filter", () => {
    const out = applyStandingsState(ROWS, {
      sort: { column: "trades", direction: "desc" },
      filters: { grade: ["B"] },
    });
    expect(out[0].rank).toBe(1);
  });
});
```

- [ ] **Step 2: Create `web/lib/standings-filter.ts`**

```ts
import { StandingRow } from "./types";
import { SortState } from "./url-state";

export interface StandingsState {
  sort: SortState;
  filters: Record<string, string[] | [number | null, number | null]>;
}

const NUMERIC_COLUMNS = new Set<keyof StandingRow>([
  "rank", "net_ktc", "net_production", "trades", "ps_plus",
]);

function gradeBucket(grade: string): "A" | "B" | "C" | "D" {
  const head = grade.charAt(0).toUpperCase();
  if (head === "A" || head === "B" || head === "C" || head === "D") return head;
  return "C";
}

export function applyStandingsState(
  rows: StandingRow[], state: StandingsState,
): StandingRow[] {
  let out = [...rows];

  for (const [col, val] of Object.entries(state.filters)) {
    if (Array.isArray(val) && typeof val[0] === "string") {
      const sv = (val as string[]).map((s) => s.toLowerCase()).filter(Boolean);
      if (sv.length === 0) continue;
      if (col === "grade") {
        out = out.filter((r) => sv.includes(gradeBucket(r.grade).toLowerCase()));
      } else if (col === "display_name") {
        const term = sv[0];
        out = out.filter((r) => r.display_name.toLowerCase().includes(term));
      }
    } else if (Array.isArray(val) && val.length === 2) {
      const [lo, hi] = val as [number | null, number | null];
      if (NUMERIC_COLUMNS.has(col as keyof StandingRow)) {
        out = out.filter((r) => {
          const n = (r as any)[col] as number;
          if (lo !== null && n < lo) return false;
          if (hi !== null && n > hi) return false;
          return true;
        });
      }
    }
  }

  out.sort((a, b) => {
    const av = (a as any)[state.sort.column];
    const bv = (b as any)[state.sort.column];
    if (av === bv) return 0;
    const cmp = av > bv ? 1 : -1;
    return state.sort.direction === "asc" ? cmp : -cmp;
  });

  return out.map((r, i) => ({ ...r, rank: i + 1 }));
}
```

- [ ] **Step 3: Confirm filter tests pass**

```bash
cd web && npm run test -- --run standings-filter
```

Expected: PASS.

- [ ] **Step 4: Create `web/components/StandingsTable.tsx`**

```tsx
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import Link from "next/link";
import { StandingRow } from "@/lib/types";
import { decodeDashboardState, encodeDashboardState } from "@/lib/url-state";
import { applyStandingsState } from "@/lib/standings-filter";
import { InfoTooltip } from "./InfoTooltip";

interface Props {
  leagueId: string;
  rows: StandingRow[];
}

const COLS: {
  key: keyof StandingRow | "owner_search";
  plain: string;
  jargon: string;
  tooltip?: { title: string; body: string; formula?: string };
}[] = [
  { key: "rank", plain: "#", jargon: "" },
  { key: "display_name", plain: "Owner", jargon: "league member" },
  {
    key: "net_ktc", plain: "Value Swing", jargon: "net ktc · today",
    tooltip: { title: "Snapshot KTC", body: "Sum of value swings across this owner's trades, using today's KTC values.", formula: "Σ(value received) − Σ(value given)" },
  },
  {
    key: "net_production", plain: "Points Scored", jargon: "net production",
    tooltip: { title: "Hindsight production", body: "Sum of points the players received scored for this owner, minus points the players given scored anywhere they ended up." },
  },
  { key: "trades", plain: "Trades", jargon: "total count" },
  {
    key: "ps_plus", plain: "Big Plays", jargon: "playoff starts +",
    tooltip: { title: "Playoff starts gained", body: "Number of times an asset this owner received started during a playoff week, summed across all their trades." },
  },
  {
    key: "grade", plain: "Grade", jargon: "overall",
    tooltip: { title: "Letter grade", body: "Mapped from Net KTC: A ≥ 1500, A− ≥ 500, B+ ≥ 100, B ≥ −100, B− ≥ −500, C ≥ −1500, D below." },
  },
];

const GRADE_BUCKETS = ["A", "B", "C", "D"] as const;

export function StandingsTable({ leagueId, rows }: Props) {
  const router = useRouter();
  const sp = useSearchParams();
  const state = useMemo(() => decodeDashboardState(sp), [sp]);
  const visible = useMemo(
    () => applyStandingsState(rows, { sort: state.sort, filters: state.filters }),
    [rows, state.sort, state.filters],
  );

  function updateState(next: typeof state) {
    const qs = encodeDashboardState(next);
    router.push(`/league/${leagueId}${qs ? `?${qs}` : ""}`);
  }

  function toggleSort(col: string) {
    const next = { ...state };
    if (state.sort.column === col) {
      next.sort = {
        column: col,
        direction: state.sort.direction === "desc" ? "asc" : "desc",
      };
    } else {
      next.sort = { column: col, direction: "desc" };
    }
    updateState(next);
  }

  function updateFilter(col: string, val: any) {
    const next = { ...state, filters: { ...state.filters, [col]: val } };
    if (
      (Array.isArray(val) && (val as any[]).every((x) => x === null || x === "")) ||
      (Array.isArray(val) && val.length === 0)
    ) {
      delete next.filters[col];
    }
    updateState(next);
  }

  return (
    <div className="bg-surface border border-divider rounded-card p-4 px-5">
      <div className="flex justify-between items-baseline mb-3.5">
        <div className="text-[14px] font-bold tracking-tight">Owner Standings</div>
        <div className="font-mono text-[10px] text-dim">{visible.length} rows</div>
      </div>

      <div className="font-mono text-[11px] tabular">
        {/* Header */}
        <div className="grid grid-cols-[24px_1.7fr_1.1fr_1.1fr_0.7fr_0.7fr_60px] gap-2 items-end pb-2.5 border-b border-divider">
          {COLS.map((c) => {
            const sorted = state.sort.column === c.key;
            return (
              <div
                key={String(c.key)}
                className="flex flex-col gap-0.5 cursor-pointer select-none"
                onClick={() => toggleSort(String(c.key))}
              >
                <div className="font-sans text-[11px] font-semibold tracking-tight flex items-center gap-1">
                  {c.plain}
                  {c.tooltip && <InfoTooltip {...c.tooltip} />}
                  {sorted && (
                    <span className="text-[10px]">
                      {state.sort.direction === "desc" ? "↓" : "↑"}
                    </span>
                  )}
                </div>
                {c.jargon && (
                  <div className="font-mono text-[8px] uppercase tracking-widest text-dim">
                    {c.jargon}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Filter row */}
        <div className="grid grid-cols-[24px_1.7fr_1.1fr_1.1fr_0.7fr_0.7fr_60px] gap-2 py-2 border-b border-divider bg-bg">
          <div />
          <input
            type="text"
            placeholder="search"
            defaultValue={(state.filters.display_name as string[] | undefined)?.[0] ?? ""}
            onBlur={(e) => updateFilter("display_name",
              e.target.value ? [e.target.value] : [])}
            className="px-1.5 py-1 text-[10px] border border-divider rounded bg-surface w-full"
          />
          {(["net_ktc", "net_production", "trades", "ps_plus"] as const).map((col) => {
            const cur = (state.filters[col] as [number | null, number | null] | undefined) ?? [null, null];
            return (
              <div key={col} className="flex gap-1">
                <input
                  defaultValue={cur[0] ?? ""}
                  placeholder="min"
                  onBlur={(e) => updateFilter(col, [
                    e.target.value === "" ? null : Number(e.target.value),
                    cur[1],
                  ])}
                  className="w-1/2 px-1 py-1 text-[9px] border border-divider rounded bg-surface text-center"
                />
                <input
                  defaultValue={cur[1] ?? ""}
                  placeholder="max"
                  onBlur={(e) => updateFilter(col, [
                    cur[0],
                    e.target.value === "" ? null : Number(e.target.value),
                  ])}
                  className="w-1/2 px-1 py-1 text-[9px] border border-divider rounded bg-surface text-center"
                />
              </div>
            );
          })}
          <div className="flex gap-0.5 flex-wrap">
            {GRADE_BUCKETS.map((g) => {
              const sel = ((state.filters.grade as string[] | undefined) ?? [])
                .map((x) => x.toUpperCase()).includes(g);
              return (
                <button
                  key={g}
                  onClick={() => {
                    const cur = ((state.filters.grade as string[] | undefined) ?? [])
                      .map((x) => x.toUpperCase());
                    const next = sel
                      ? cur.filter((x) => x !== g)
                      : [...cur, g];
                    updateFilter("grade", next);
                  }}
                  className={`px-1.5 py-0.5 text-[9px] font-bold border rounded ${
                    sel ? "bg-ink text-bg border-ink" : "bg-surface text-dim border-divider"
                  }`}
                >
                  {g}
                </button>
              );
            })}
          </div>
        </div>

        {/* Rows */}
        {visible.map((r) => (
          <Link
            key={r.user_id}
            href={`/league/${leagueId}/owner/${r.user_id}`}
            className="grid grid-cols-[24px_1.7fr_1.1fr_1.1fr_0.7fr_0.7fr_60px] gap-2 py-2.5 border-b border-[var(--divider)] last:border-b-0 hover:bg-bg items-center cursor-pointer"
          >
            <div className="text-dim text-[11px]">{r.rank}</div>
            <div className="font-sans text-[13px] font-medium text-ink">
              {r.display_name}
            </div>
            <div className={r.net_ktc > 0 ? "text-pos font-semibold" : r.net_ktc < 0 ? "text-neg font-semibold" : "text-dim"}>
              {r.net_ktc > 0 ? "+" : ""}{Math.round(r.net_ktc).toLocaleString()}
            </div>
            <div className={r.net_production > 0 ? "text-pos font-semibold" : r.net_production < 0 ? "text-neg font-semibold" : "text-dim"}>
              {r.net_production > 0 ? "+" : ""}{r.net_production.toFixed(1)}
            </div>
            <div>{r.trades}</div>
            <div className={r.ps_plus > 0 ? "text-pos" : r.ps_plus < 0 ? "text-neg" : ""}>
              {r.ps_plus > 0 ? "+" : ""}{r.ps_plus}
            </div>
            <div>
              <span className="px-2 py-0.5 rounded font-bold text-[11px] font-sans"
                style={{
                  background: `var(--pill-${gradePillClass(r.grade)}-bg)`,
                  borderColor: `var(--pill-${gradePillClass(r.grade)}-border)`,
                  color: `var(--pill-${gradePillClass(r.grade)}-text)`,
                  border: "1px solid",
                }}
              >
                {r.grade}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function gradePillClass(grade: string): "a" | "b" | "c" {
  const head = grade.charAt(0).toUpperCase();
  if (head === "A") return "a";
  if (head === "B") return "b";
  return "c";
}
```

- [ ] **Step 5: Modify `web/components/DashboardClient.tsx`** to render the standings table:

```tsx
import { StandingsTable } from "./StandingsTable";

// In the JSX, replace whatever placeholder was there with:
<div className="grid grid-cols-[1.7fr_1fr] gap-6">
  <StandingsTable leagueId={leagueId} rows={data.standings} />
  {/* Sidebar lands in Task 26 */}
</div>
```

- [ ] **Step 6: Verify build + tests**

```bash
cd web && npm run test -- --run standings-filter && npm run build
```

Expected: PASS + build succeeds.

- [ ] **Step 7: Commit**

```bash
git add web/components/StandingsTable.tsx web/lib/standings-filter.ts web/tests/standings-filter.test.ts web/components/DashboardClient.tsx
git commit -m "$(cat <<'EOF'
Add standings table with sort + filter + url state

Two-line column headers (plain English + mono technical name),
tooltip on every metric, click to sort, filter row with
search/min-max/grade pills. State round-trips through URL search
params so any view is shareable. Rows link to owner detail.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 26: Sidebar — latest trades + records

**Files:**
- Create: `web/components/SidebarPanels.tsx`
- Create: `web/components/TradeCard.tsx`
- Create: `web/components/RecordsPanel.tsx`
- Modify: `web/components/DashboardClient.tsx`

- [ ] **Step 1: Create `web/components/TradeCard.tsx`**

```tsx
import Link from "next/link";
import { LatestTrade } from "@/lib/types";

interface Props {
  leagueId: string;
  trade: LatestTrade;
}

export function TradeCard({ leagueId, trade }: Props) {
  const swing = trade.swing_ktc;
  return (
    <Link
      href={`/league/${leagueId}/trade/${trade.trade_id}`}
      className="block p-3 bg-bg border border-divider rounded-md text-[12px] hover:bg-surface transition-colors"
    >
      <div className="font-mono text-[10px] text-dim mb-1 tracking-wide">
        {trade.date} · Week {trade.week}
      </div>
      <div className="font-semibold text-[13px] mb-1">
        {trade.parties.join(" ↔ ")}
      </div>
      <div className="text-[11px] text-dim leading-snug">{trade.assets_short}</div>
      <div className={`mt-2 inline-block font-mono text-[10px] font-semibold ${
        swing > 0 ? "text-pos" : swing < 0 ? "text-neg" : "text-dim"
      }`}>
        Value swing {swing > 0 ? "+" : ""}{Math.round(swing)} · Pts{" "}
        {trade.swing_prod > 0 ? "+" : ""}{trade.swing_prod.toFixed(1)}
      </div>
    </Link>
  );
}
```

- [ ] **Step 2: Create `web/components/RecordsPanel.tsx`**

```tsx
import { Records } from "@/lib/types";

interface Props { records: Records; year: number | "all" }

export function RecordsPanel({ records, year }: Props) {
  const label = year === "all" ? "All-time" : `${year}`;
  const items: { label: string; value: string }[] = [
    {
      label: "Biggest value swing",
      value: `${records.biggest_value_swing > 0 ? "+" : ""}${Math.round(records.biggest_value_swing).toLocaleString()}${records.biggest_value_swing_owner ? ` (${records.biggest_value_swing_owner})` : ""}`,
    },
    {
      label: "Most points gained",
      value: `${records.biggest_production > 0 ? "+" : ""}${records.biggest_production.toFixed(1)}${records.biggest_production_owner ? ` (${records.biggest_production_owner})` : ""}`,
    },
    {
      label: "Most decisive starts",
      value: `${records.most_decisive}${records.most_decisive_owner ? ` (${records.most_decisive_owner})` : ""}`,
    },
    {
      label: "Most trades",
      value: `${records.most_trades}${records.most_trades_owner ? ` (${records.most_trades_owner})` : ""}`,
    },
  ];
  return (
    <div className="bg-surface border border-divider rounded-card p-4 px-5">
      <div className="text-[14px] font-bold tracking-tight mb-3.5">
        {label} Records
      </div>
      {items.map((it) => (
        <div key={it.label} className="flex justify-between py-2 border-b border-divider last:border-b-0 text-[12px]">
          <span className="text-dim">{it.label}</span>
          <span className="font-mono font-semibold">{it.value}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create `web/components/SidebarPanels.tsx`**

```tsx
import { DashboardResp } from "@/lib/types";
import { TradeCard } from "./TradeCard";
import { RecordsPanel } from "./RecordsPanel";

interface Props { leagueId: string; data: DashboardResp }

export function SidebarPanels({ leagueId, data }: Props) {
  return (
    <div className="flex flex-col gap-4">
      <div className="bg-surface border border-divider rounded-card p-4 px-5">
        <div className="flex justify-between items-baseline mb-3.5">
          <div className="text-[14px] font-bold tracking-tight">
            Latest{" "}
            {data.selected_year === "all" ? "" : `· ${data.selected_year}`}
          </div>
          <div className="font-mono text-[10px] text-dim">
            {data.latest_trades.length} shown
          </div>
        </div>
        <div className="flex flex-col gap-2.5">
          {data.latest_trades.map((t) => (
            <TradeCard key={t.trade_id} leagueId={leagueId} trade={t} />
          ))}
        </div>
      </div>
      <RecordsPanel records={data.records} year={data.selected_year} />
    </div>
  );
}
```

- [ ] **Step 4: Modify `web/components/DashboardClient.tsx`** to render the sidebar:

```tsx
import { SidebarPanels } from "./SidebarPanels";

// In the two-column grid:
<div className="grid grid-cols-[1.7fr_1fr] gap-6">
  <StandingsTable leagueId={leagueId} rows={data.standings} />
  <SidebarPanels leagueId={leagueId} data={data} />
</div>
```

- [ ] **Step 5: Verify build**

```bash
cd web && npm run build
```

Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add web/components/SidebarPanels.tsx web/components/TradeCard.tsx web/components/RecordsPanel.tsx web/components/DashboardClient.tsx
git commit -m "$(cat <<'EOF'
Add sidebar: latest trades + records panels

Latest trades show date, parties, short asset string, KTC + production
swings; click → trade detail. Records panel shows top-line stats for
the selected window with explicit owner attribution.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 27: Owner detail page (`/league/[id]/owner/[uid]`)

**Files:**
- Create: `web/app/league/[id]/owner/[uid]/page.tsx`
- Create: `web/components/CareerArc.tsx`

- [ ] **Step 1: Create `web/components/CareerArc.tsx`**

```tsx
import { SeasonArc } from "@/lib/types";

interface Props { arc: SeasonArc[] }

export function CareerArc({ arc }: Props) {
  if (arc.length === 0) {
    return <p className="text-dim text-[12px]">No trades yet.</p>;
  }
  // Simple inline bar chart: per-season net KTC. Avoids a chart lib
  // dependency for v1; we can swap for recharts later if we want.
  const max = Math.max(...arc.map((s) => Math.abs(s.net_ktc)), 1);
  return (
    <div className="bg-surface border border-divider rounded-card p-5">
      <div className="text-[14px] font-bold tracking-tight mb-4">
        Net KTC by season
      </div>
      <div className="flex items-end gap-3 h-32">
        {arc.map((s) => {
          const heightPct = (Math.abs(s.net_ktc) / max) * 100;
          const positive = s.net_ktc >= 0;
          return (
            <div key={s.season} className="flex flex-col items-center flex-1">
              <div className="font-mono text-[10px] text-dim mb-1 tabular">
                {positive ? "+" : ""}{Math.round(s.net_ktc).toLocaleString()}
              </div>
              <div
                className={`w-full ${positive ? "bg-pos" : "bg-neg"} rounded-sm`}
                style={{ height: `${heightPct}%`, minHeight: 4 }}
              />
              <div className="font-mono text-[10px] mt-1.5 text-dim">{s.season}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `web/app/league/[id]/owner/[uid]/page.tsx`**

```tsx
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { CareerArc } from "@/components/CareerArc";
import { ownerDetail } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function OwnerPage({
  params,
}: {
  params: { id: string; uid: string };
}) {
  let data;
  try {
    data = await ownerDetail(params.id, params.uid);
  } catch {
    return (
      <Shell>
        <TopBar />
        <section className="mt-16">
          <h1 className="text-3xl font-extrabold tracking-tight">Owner not found.</h1>
          <Link href={`/league/${params.id}`} className="text-dim underline mt-4 inline-block">
            ← Back to league
          </Link>
        </section>
      </Shell>
    );
  }
  return (
    <Shell>
      <TopBar activeNav="owners" />
      <section className="mt-2">
        <Link href={`/league/${params.id}`}
              className="font-mono text-[11px] text-dim hover:text-ink">
          ← All standings
        </Link>
        <p className="mt-6 font-mono text-[10px] uppercase tracking-widest text-dim">
          Owner
        </p>
        <h1 className="mt-2 text-4xl font-extrabold tracking-tight">
          {data.display_name}
        </h1>

        <div className="grid grid-cols-3 gap-3 mt-8">
          {[
            { label: "Value Today", sub: "net ktc · all years",
              v: `${data.totals_by_lens.ktc > 0 ? "+" : ""}${Math.round(data.totals_by_lens.ktc).toLocaleString()}` },
            { label: "Points Scored", sub: "net production",
              v: `${data.totals_by_lens.production > 0 ? "+" : ""}${data.totals_by_lens.production.toFixed(1)}` },
            { label: "Impact", sub: "DS + PS · all received",
              v: String(Math.round(data.totals_by_lens.impact)) },
          ].map((it) => (
            <div key={it.label}
                 className="bg-surface border border-divider rounded-card p-4">
              <div className="text-[13px] font-bold tracking-tight">{it.label}</div>
              <div className="font-mono text-[9px] uppercase tracking-widest text-dim mt-0.5">
                {it.sub}
              </div>
              <div className="tabular text-[28px] font-extrabold tracking-tight mt-2">
                {it.v}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-8">
          <CareerArc arc={data.career_arc} />
        </div>

        <div className="grid grid-cols-2 gap-3 mt-8">
          {data.best_trade_id && (
            <Link href={`/league/${params.id}/trade/${data.best_trade_id}`}
                  className="bg-surface border border-divider rounded-card p-5 hover:bg-bg">
              <div className="font-mono text-[10px] uppercase tracking-widest text-dim">
                Best trade
              </div>
              <div className="mt-1 font-mono text-[12px] underline">
                {data.best_trade_id}
              </div>
            </Link>
          )}
          {data.worst_trade_id && (
            <Link href={`/league/${params.id}/trade/${data.worst_trade_id}`}
                  className="bg-surface border border-divider rounded-card p-5 hover:bg-bg">
              <div className="font-mono text-[10px] uppercase tracking-widest text-dim">
                Worst trade
              </div>
              <div className="mt-1 font-mono text-[12px] underline">
                {data.worst_trade_id}
              </div>
            </Link>
          )}
        </div>
      </section>
    </Shell>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
cd web && npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add web/app/league/[id]/owner/[uid]/page.tsx web/components/CareerArc.tsx
git commit -m "$(cat <<'EOF'
Add owner detail page

Three lens-explicit total cards, inline CSS bar chart for net KTC
by season (no chart-lib dependency for v1), best/worst trade
shortcut cards.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 28: Trade detail page (`/league/[id]/trade/[tid]`)

**Files:**
- Create: `web/app/league/[id]/trade/[tid]/page.tsx`
- Create: `web/components/AssetRender.tsx`
- Create: `web/components/TradeSidePanel.tsx`

- [ ] **Step 1: Create `web/components/AssetRender.tsx`**

```tsx
interface Asset {
  kind?: string;
  name?: string;
  player_id?: string;
  season?: number;
  round?: number;
  via_pick?: { season: number; round: number; original_owner_user_id?: string };
  original_owner_user_id?: string;
  amount?: number;
}

interface Props {
  asset: Asset;
  displayNames: Record<string, string>;
}

function ordinal(n: number): string {
  if (n % 100 >= 11 && n % 100 <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" }[n % 10 as 1 | 2 | 3]) ?? "th"}`;
}

export function AssetRender({ asset, displayNames }: Props) {
  // Player with via_pick = resolved pick → emphasize pick origin.
  if (asset.name && asset.via_pick) {
    const orig = displayNames[asset.via_pick.original_owner_user_id ?? ""] ??
      (asset.via_pick.original_owner_user_id ?? "?");
    return (
      <span>
        {asset.via_pick.season} {ordinal(asset.via_pick.round)} pick (orig: {orig}){" "}
        <span className="text-dim">→</span> <span className="font-medium">{asset.name}</span>
      </span>
    );
  }
  // Plain player.
  if (asset.name && !asset.season && !asset.round) {
    return <span className="font-medium">{asset.name}</span>;
  }
  // Unresolved pick.
  if (asset.season !== undefined && asset.round !== undefined) {
    const orig = displayNames[asset.original_owner_user_id ?? ""] ??
      (asset.original_owner_user_id ?? "?");
    return (
      <span>
        {asset.season} {ordinal(asset.round)} pick (orig: {orig})
      </span>
    );
  }
  // FAAB.
  if (asset.amount !== undefined) {
    return <span>${asset.amount} FAAB</span>;
  }
  return <span>?</span>;
}
```

- [ ] **Step 2: Create `web/components/TradeSidePanel.tsx`**

```tsx
import { TradeSideView } from "@/lib/types";
import { AssetRender } from "./AssetRender";

interface Props {
  side: TradeSideView;
  displayNames: Record<string, string>;
}

export function TradeSidePanel({ side, displayNames }: Props) {
  return (
    <div className="bg-surface border border-divider rounded-card p-5">
      <div className="font-mono text-[10px] uppercase tracking-widest text-dim">
        Side
      </div>
      <div className="mt-1 text-[18px] font-bold tracking-tight">
        {side.display_name}
      </div>

      <div className="mt-5">
        <div className="font-mono text-[10px] uppercase tracking-widest text-dim mb-2">
          Received
        </div>
        <ul className="space-y-1.5">
          {side.received.length === 0 && (
            <li className="text-dim text-[12px]">—</li>
          )}
          {side.received.map((a, i) => (
            <li key={i} className="text-[13px]">
              <AssetRender asset={a} displayNames={displayNames} />
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-5">
        <div className="font-mono text-[10px] uppercase tracking-widest text-dim mb-2">
          Gave
        </div>
        <ul className="space-y-1.5">
          {side.given.length === 0 && (
            <li className="text-dim text-[12px]">—</li>
          )}
          {side.given.map((a, i) => (
            <li key={i} className="text-[13px]">
              <AssetRender asset={a} displayNames={displayNames} />
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3">
        {[
          { label: "Value Swing", sub: "ktc · today",
            v: `${side.snapshot_ktc_swing > 0 ? "+" : ""}${Math.round(side.snapshot_ktc_swing).toLocaleString()}`,
            color: side.snapshot_ktc_swing > 0 ? "text-pos" : side.snapshot_ktc_swing < 0 ? "text-neg" : "text-dim" },
          { label: "Points Scored", sub: "hindsight",
            v: `${side.hindsight_production_swing > 0 ? "+" : ""}${side.hindsight_production_swing.toFixed(1)}`,
            color: side.hindsight_production_swing > 0 ? "text-pos" : side.hindsight_production_swing < 0 ? "text-neg" : "text-dim" },
        ].map((it) => (
          <div key={it.label} className="border border-divider rounded p-3">
            <div className="text-[12px] font-semibold">{it.label}</div>
            <div className="font-mono text-[9px] uppercase tracking-widest text-dim mt-0.5">
              {it.sub}
            </div>
            <div className={`tabular text-[20px] font-extrabold mt-1 ${it.color}`}>
              {it.v}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-5 gap-2 text-center">
        {[
          { k: "starter_weeks", l: "SW" },
          { k: "starter_points_contributed", l: "SPC" },
          { k: "win_share_points", l: "WSP" },
          { k: "decisive_starts", l: "DS" },
          { k: "playoff_starts", l: "PS" },
        ].map((m) => (
          <div key={m.k} className="border border-divider rounded p-2.5">
            <div className="font-mono text-[9px] text-dim uppercase tracking-widest">
              {m.l}
            </div>
            <div className="tabular text-[14px] font-bold mt-1">
              {Math.round((side.realized as any)[m.k])}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `web/app/league/[id]/trade/[tid]/page.tsx`**

```tsx
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { TradeSidePanel } from "@/components/TradeSidePanel";
import { tradeDetail } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function TradePage({
  params,
}: {
  params: { id: string; tid: string };
}) {
  let data;
  try {
    data = await tradeDetail(params.id, params.tid);
  } catch {
    return (
      <Shell>
        <TopBar />
        <h1 className="mt-16 text-3xl font-extrabold tracking-tight">
          Trade not found.
        </h1>
        <Link href={`/league/${params.id}`} className="text-dim underline">
          ← Back
        </Link>
      </Shell>
    );
  }
  const displayNames: Record<string, string> = Object.fromEntries(
    data.sides.map((s) => [s.user_id, s.display_name]),
  );
  return (
    <Shell>
      <TopBar activeNav="trades" />
      <section>
        <Link href={`/league/${params.id}`}
              className="font-mono text-[11px] text-dim hover:text-ink">
          ← All trades
        </Link>
        <div className="mt-6 font-mono text-[10px] uppercase tracking-widest text-dim">
          Trade · {data.date} · Week {data.week} · {data.league_name} · {data.season}
        </div>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight">
          {data.sides.map((s) => s.display_name).join(" ↔ ")}
        </h1>
        <div className={`mt-8 grid gap-5 grid-cols-${Math.min(data.sides.length, 3)}`}>
          {data.sides.map((s) => (
            <TradeSidePanel key={s.user_id} side={s} displayNames={displayNames} />
          ))}
        </div>
      </section>
    </Shell>
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd web && npm run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web/app/league/[id]/trade/[tid]/page.tsx web/components/AssetRender.tsx web/components/TradeSidePanel.tsx
git commit -m "$(cat <<'EOF'
Add trade detail page with per-side panels + asset renderer

AssetRender handles plain players, resolved picks (pick origin →
drafted player), unresolved picks, and FAAB consistently. Side panel
shows Received / Gave / two value cards / five realized-impact tiles.
Grid columns adapt to 2 or 3-team trades.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 29: Methodology page

**Files:**
- Create: `web/app/methodology/page.tsx`

- [ ] **Step 1: Create the page**

```tsx
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";

export default function MethodologyPage() {
  return (
    <Shell>
      <TopBar activeNav="methodology" />
      <section className="prose-styled">
        <p className="font-mono text-[10px] uppercase tracking-widest text-dim">
          How this works
        </p>
        <h1 className="mt-2 text-4xl font-extrabold tracking-tight">
          Three lenses on every trade
        </h1>
        <p className="mt-6 text-[14px] text-dim max-w-2xl leading-relaxed">
          Most fantasy trade graders ask one question — &ldquo;who won?&rdquo; —
          and pick one answer. We don&apos;t. Three different lenses give three
          different answers, and the truth usually lives in the tension between
          them.
        </p>

        {[
          {
            eyebrow: "Lens 1",
            title: "Value Today (Snapshot KTC)",
            body: "What each side is worth right now on the KeepTradeCut market, plus FantasyCalc for players KTC doesn't rank. Sum what each owner received minus what they gave; positive numbers favor that owner. This updates as the market updates — a trade can look great today and bad tomorrow.",
            formula: "Σ(value received) − Σ(value given) · today's prices",
          },
          {
            eyebrow: "Lens 2",
            title: "Points Scored (Hindsight Production)",
            body: "Sum of fantasy points the received players have actually scored for the receiving team since the trade — minus what the given players scored anywhere they ended up. Past production is locked in, but the differential evolves as both sides keep playing.",
            formula: "Σ(received points post-trade) − Σ(given phantom points post-trade)",
          },
          {
            eyebrow: "Lens 3",
            title: "Real Impact (Starter Usage + Wins)",
            body: "Five sub-metrics per side, never collapsed into one number: starter weeks the received players actually started, points contributed as a starter, win-share points (those points in winning weeks), decisive starts (player score > margin of victory), and playoff starts. A trade where you 'lost' on value but won three close games has very different impact than the same value loss with the player riding your bench.",
          },
        ].map((s) => (
          <article key={s.title} className="mt-12 max-w-2xl">
            <div className="font-mono text-[10px] uppercase tracking-widest text-dim">
              {s.eyebrow}
            </div>
            <h2 className="mt-2 text-2xl font-bold tracking-tight">{s.title}</h2>
            <p className="mt-3 text-[14px] leading-relaxed">{s.body}</p>
            {s.formula && (
              <div className="mt-4 font-mono text-[11px] bg-surface border border-divider rounded p-3 inline-block">
                {s.formula}
              </div>
            )}
          </article>
        ))}

        <article className="mt-14 max-w-2xl">
          <div className="font-mono text-[10px] uppercase tracking-widest text-dim">
            Sources
          </div>
          <h2 className="mt-2 text-2xl font-bold tracking-tight">
            Where the data comes from
          </h2>
          <ul className="mt-3 list-disc pl-5 text-[14px] leading-relaxed">
            <li>Sleeper API — league chain, trades, matchups, drafts</li>
            <li>KeepTradeCut — current dynasty market values (top ~500 players)</li>
            <li>FantasyCalc — fallback values for players KTC doesn&apos;t rank</li>
          </ul>
        </article>

        <article className="mt-14 max-w-2xl">
          <div className="font-mono text-[10px] uppercase tracking-widest text-dim">
            Known limitations
          </div>
          <h2 className="mt-2 text-2xl font-bold tracking-tight">
            What this gets wrong
          </h2>
          <ul className="mt-3 list-disc pl-5 text-[14px] leading-relaxed">
            <li>
              <strong>Inactive players.</strong> Truly retired / unsigned players
              (no NFL team) sometimes aren&apos;t in KTC or FantasyCalc. Their
              Snapshot value contribution is 0, which is approximately correct
              but can distort grades on old trades involving them.
            </li>
            <li>
              <strong>Draft slot derivation.</strong> When a round-1 pick was
              itself traded before the draft, slot attribution can be off in
              older Sleeper data missing the <code>draft_order</code> field. We
              fall back to a heuristic in those cases.
            </li>
            <li>
              <strong>Waivers and free-agent moves.</strong> Not graded in v1.
            </li>
          </ul>
        </article>

        <p className="mt-16 max-w-2xl text-[12px] text-dim">
          Source on{" "}
          <a className="underline" href="https://github.com/tkeefe66/sleeper-dynasty">
            GitHub
          </a>
          . The CLI version (<code>sleeper-dynasty trades</code>) outputs the
          same data into a Google Sheet for power users.
        </p>
        <Link href="/" className="mt-12 inline-block font-mono text-[11px] underline">
          ← Back to home
        </Link>
      </section>
    </Shell>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd web && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add web/app/methodology/page.tsx
git commit -m "$(cat <<'EOF'
Add /methodology page

Editorial explainer for the three lenses with worked formulas, the
data sources we use, and known limitations. Linked from the TopBar
and the first-visit explainer banner.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 30: Not-found + error handling

**Files:**
- Create: `web/app/not-found.tsx`
- Modify: `web/app/league/[id]/page.tsx` (wrap in error boundary)

- [ ] **Step 1: Create `web/app/not-found.tsx`**

```tsx
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";

export default function NotFound() {
  return (
    <Shell>
      <TopBar />
      <section className="mt-24 text-center">
        <p className="font-mono text-[10px] uppercase tracking-widest text-dim">
          404
        </p>
        <h1 className="mt-2 text-4xl font-extrabold tracking-tight">
          That URL is offsides.
        </h1>
        <Link href="/" className="mt-8 inline-block font-mono text-[12px] underline">
          ← Home
        </Link>
      </section>
    </Shell>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/app/not-found.tsx
git commit -m "$(cat <<'EOF'
Add 404 page

Branded, matches the rest of the app.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 31: Mobile responsive breakpoints

**Files:**
- Modify: `web/components/DashboardClient.tsx`
- Modify: `web/components/HeroStatsRow.tsx`
- Modify: `web/components/StandingsTable.tsx`

- [ ] **Step 1: Make the two-column grid responsive**

In `DashboardClient.tsx`, change:

```tsx
<div className="grid grid-cols-[1.7fr_1fr] gap-6">
```

to:

```tsx
<div className="grid grid-cols-1 lg:grid-cols-[1.7fr_1fr] gap-6">
```

- [ ] **Step 2: Stack hero stats on phone**

In `HeroStatsRow.tsx`, change:

```tsx
<div className="grid grid-cols-4 gap-3.5 mb-7">
```

to:

```tsx
<div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5 mb-7">
```

- [ ] **Step 3: Standings table horizontal scroll on phone**

In `StandingsTable.tsx`, wrap the table content in:

```tsx
<div className="overflow-x-auto">
  {/* existing header / filter / rows */}
</div>
```

And add `min-w-[720px]` to each of the three `grid-cols-[...]` divs so they keep their column layout while the wrapper scrolls.

- [ ] **Step 4: Verify build**

```bash
cd web && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add web/components/DashboardClient.tsx web/components/HeroStatsRow.tsx web/components/StandingsTable.tsx
git commit -m "$(cat <<'EOF'
Add mobile-responsive breakpoints to dashboard

Two-column grid collapses below lg; hero stats go 2-up below lg;
standings table horizontally scrolls inside a wrapper to preserve
column layout on small screens. Standings rows keep their 7-col grid
above 720px wide.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 6 — Railway deployment + polish

### Task 32: Backend Dockerfile

**Files:**
- Create: `api/Dockerfile`
- Create: `api/.dockerignore`

- [ ] **Step 1: Create `api/Dockerfile`**

```dockerfile
FROM python:3.11-slim AS base
WORKDIR /app

# Install the existing grader package + the API service.
COPY pyproject.toml uv.lock* ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY api ./api
RUN pip install --no-cache-dir -e ./api

ENV PYTHONUNBUFFERED=1 \
    TRADE_GRADER_CACHE_DIR=/data/sleeper-dynasty/cache

# Railway provides PORT via env.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.uvicorn_entry:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

- [ ] **Step 2: Create `api/.dockerignore`**

```
__pycache__
*.pyc
.venv
venv
tests
.pytest_cache
```

- [ ] **Step 3: Build locally**

```bash
docker build -f api/Dockerfile -t trade-grader-api:dev .
docker run --rm -p 8000:8000 trade-grader-api:dev &
sleep 3
curl -s http://localhost:8000/api/health
docker kill $(docker ps -q --filter ancestor=trade-grader-api:dev)
```

Expected: `{"status":"ok"}`.

- [ ] **Step 4: Commit**

```bash
git add api/Dockerfile api/.dockerignore
git commit -m "$(cat <<'EOF'
Add backend Dockerfile

Editable-installs the existing grader package from src/ plus the
api/ wrapper. Cache dir set to /data/sleeper-dynasty/cache to
match the Railway volume mount.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 33: Frontend Dockerfile

**Files:**
- Create: `web/Dockerfile`
- Create: `web/.dockerignore`
- Modify: `web/next.config.mjs` (output: 'standalone')

- [ ] **Step 1: Modify `web/next.config.mjs`**

```js
const API_URL = process.env.API_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_URL}/api/:path*` },
    ];
  },
};

export default nextConfig;
```

- [ ] **Step 2: Create `web/Dockerfile`**

```dockerfile
FROM node:20-alpine AS deps
WORKDIR /app
COPY web/package.json web/package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY web ./
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

- [ ] **Step 3: Create `web/.dockerignore`**

```
node_modules
.next
out
.git
tests
e2e
playwright-report
test-results
```

- [ ] **Step 4: Commit**

```bash
git add web/Dockerfile web/.dockerignore web/next.config.mjs
git commit -m "$(cat <<'EOF'
Add frontend Dockerfile + standalone output

Multi-stage Node build using Next.js standalone output for a slim
runtime image. API_URL env var points at the FastAPI service in
production.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 34: Railway configuration

**Files:**
- Create: `railway.json` (project-level metadata)
- Create: `Makefile` (local convenience commands)

- [ ] **Step 1: Create `railway.json`**

```json
{
  "$schema": "https://schema.up.railway.app/railway.schema.json",
  "build": { "builder": "DOCKERFILE" }
}
```

> Note: Railway's UI is the source of truth for service-level config. This file just declares the build strategy default. In Railway, create two services from this repo:
>
> - **api**: dockerfile path `api/Dockerfile`. Persistent volume mounted at `/data`. Env: `TRADE_GRADER_CACHE_DIR=/data/sleeper-dynasty/cache`, `TRADE_GRADER_CORS_ORIGINS=["https://<your-web-domain>"]`.
> - **web**: dockerfile path `web/Dockerfile`. Env: `API_URL=http://${{ api.RAILWAY_PRIVATE_DOMAIN }}:8000`.

- [ ] **Step 2: Create `Makefile`**

```makefile
.PHONY: dev-api dev-web test test-api test-web build clean

dev-api:
	cd api && uvicorn app.main:app --reload --port 8000

dev-web:
	cd web && npm run dev

test: test-api test-web

test-api:
	cd api && pytest -v

test-web:
	cd web && npm run test -- --run

build:
	docker build -f api/Dockerfile -t trade-grader-api:local .
	docker build -f web/Dockerfile -t trade-grader-web:local .

clean:
	rm -rf api/.pytest_cache web/.next web/node_modules
```

- [ ] **Step 3: Commit**

```bash
git add railway.json Makefile
git commit -m "$(cat <<'EOF'
Add Railway config + local Makefile

Railway services configured via the UI per the comments in railway.json
(two services, one persistent volume mounted at /data on the api
service). Makefile gives a single make dev-api / make dev-web entry
point for local work.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 35: Smoke E2E test

**Files:**
- Create: `web/e2e/playwright.config.ts`
- Create: `web/e2e/landing.spec.ts`

This task assumes the user runs the backend separately during E2E (`make dev-api`). It exercises only the static parts of the landing + methodology pages.

- [ ] **Step 1: Create `web/e2e/playwright.config.ts`**

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  use: { baseURL: "http://localhost:3000" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
```

- [ ] **Step 2: Create `web/e2e/landing.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

test("landing page renders hero copy", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Every trade in your dynasty league",
  );
});

test("methodology page is reachable from nav", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /how this works/i }).first().click();
  await expect(page).toHaveURL(/\/methodology/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "Three lenses",
  );
});

test("theme toggle flips data-theme attribute", async ({ page }) => {
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /toggle theme/i }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");
});
```

- [ ] **Step 3: Install Playwright + run**

```bash
cd web && npx playwright install --with-deps chromium
npm run test:e2e
```

Expected: all 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add web/e2e/playwright.config.ts web/e2e/landing.spec.ts
git commit -m "$(cat <<'EOF'
Add Playwright E2E smoke tests

Landing hero text, methodology nav link, theme toggle flip. Real
data flow (lookup → dashboard) is covered separately once the
backend is running.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

**Spec coverage:**
- Backend routes (lookup/league/owner/trade/refresh/health) → Tasks 2, 8, 9, 10, 11, 12
- ChainCache + GraderService + GraderIO + aggregations → Tasks 4, 5, 6, 7
- Pydantic response models matching spec shape → Task 3
- Next.js skeleton + theme + tokens → Tasks 14, 17
- Landing → Task 19
- League picker (single-league redirect) → Task 20
- Dashboard shell + cold-start SSE → Task 21
- Year tabs + lens switcher + share URL → Task 22
- First-visit explainer banner → Task 24
- Hero stats with lens-aware labels + tooltips → Task 23
- Standings table with sort + filter + URL state → Task 25
- Sidebar (latest + records) → Task 26
- Owner detail → Task 27
- Trade detail with AssetRender → Task 28
- Methodology → Task 29
- 404 → Task 30
- Mobile responsive → Task 31
- Backend / frontend Dockerfiles + Railway config → Tasks 32, 33, 34
- E2E smoke → Task 35

**Placeholder scan:** Every step has a concrete file, code block, or command. The `totalTrades` "placeholder" in Task 22's `LeagueHeader` props is corrected in Task 23 (when HeroStatsRow lands and `activityCount` becomes available).

**Type consistency:**
- `Lens` and `Year` types appear in both `web/lib/types.ts` and `api/app/models/league.py` with matching values.
- `StandingRow` field names match between Pydantic model + TS interface + StandingsTable.tsx column keys.
- `DashboardState` field names match between url-state.ts and standings-filter.ts.

**Known v1 known-acceptable trade-offs:**
- No backend tests for refresh streaming beyond stage emission.
- Inline CSS bar chart for career arc (no chart-lib dep).
- Mobile layout is reasonable but not pixel-perfect.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-trade-grader-web-app.md` + `docs/superpowers/plans/2026-05-28-trade-grader-web-app-part2.md`. Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task with spec-compliance + code-quality review between each.
2. **Inline Execution** — Execute tasks in this session with checkpoints.

Which approach?
