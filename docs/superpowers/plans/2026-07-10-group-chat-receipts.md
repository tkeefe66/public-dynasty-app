# Group-Chat Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the claim the shareable unit on the owner franchise page: a driver/drag line under the hero letter, a copy-receipt action on the owner page + trade detail, and a "vs You" matchup band.

**Architecture:** All client-side; zero backend changes. Feature 2 extracts the existing top-contributor logic into a pure helper; Feature 1 adds pure receipt-builder functions plus one clipboard/share button component; Feature 3 adds a viewer-identity hook (reusing `getMe()`) and a matchup band assembled from `head_to_head` + trade `counterparties` already in the owner payload.

**Tech Stack:** Next.js 14 App Router, React 18, Tailwind + CSS custom-property tokens, vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-07-10-group-chat-receipts-design.md`. Deviations pinned during planning (payload reality): the H2H type is `H2H` (not `H2HView`); there is no league-wide owners list on `OwnerDetailResp`, so vs-picker candidates = H2H opponents ∪ trade counterparties; trade responses carry no grade strings, so the trade receipt uses started-points + Trade Value margins + `story.verdict`.

## Global Constraints

- Branch: `group-chat-receipts`. Commit after every task.
- Five-metric vocabulary only: Trade Value / Total Points / Regular Season Points / Playoff Points / Toilet Bowl Points. The string "KTC" NEVER appears in UI or receipts.
- Tokens only (`text-dim`, `border-divider`, `bg-surface`, …), both themes; no hex, no shadows (Hairline Rule).
- Whisper-Label recipe for small captions: `font-mono text-[10px] uppercase tracking-widest text-dim`.
- Voice: candid, insider, numbers-first. No hedging.
- Verification per task: `cd web && npm test -- --run` (all green) and `npx tsc --noEmit` (only the two PRE-EXISTING errors in `tests/FutureDraftTab.test.tsx` and `tests/proxy.test.ts` are acceptable).
- Test commands run from `web/`. Test file for most tasks: extend `web/tests/OwnerDeepDive.test.tsx`'s fixture pattern (inline `DETAIL` object literal, spread to vary).

---

### Task 1: Extract `ratingDrivers` + `SIGNAL_LABELS` into util

**Files:**
- Modify: `web/components/ownerdeepdive/util.tsx` (append)
- Modify: `web/components/ownerdeepdive/OverviewTab.tsx` (remove module-private copies, import shared)
- Test: `web/tests/ownerdeepdive/util.test.ts` (create)

**Interfaces:**
- Consumes: `FranchiseRating` from `@/lib/types` (`pillars: Record<string, PillarBreakdown>`, each with `signals: Record<string, SignalBreakdown>`, each with `contribution: number`).
- Produces: `export const SIGNAL_LABELS: Record<string, string>` and `export function ratingDrivers(fr: FranchiseRating): { driver: string | null; drag: string | null }` in `web/components/ownerdeepdive/util.tsx`. Tasks 2 and 3 import both.

- [ ] **Step 1: Write the failing test**

Create `web/tests/ownerdeepdive/util.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { ratingDrivers } from "../../components/ownerdeepdive/util";
import { FranchiseRating } from "../../lib/types";

function fr(signals: Record<string, number>): FranchiseRating {
  const sig = Object.fromEntries(
    Object.entries(signals).map(([k, contribution]) => [k, { raw: 0, z: 0, weight: 0.1, contribution }]),
  );
  return {
    letter: "B", rating: 1550, rank: 3, of: 12, trend: 0,
    pillars: { results: { weight: 0.5, z: 0, contribution: 10, signals: sig } },
  };
}

describe("ratingDrivers", () => {
  it("picks the most positive signal as driver and most negative as drag, using display labels", () => {
    const r = ratingDrivers(fr({ championships: 42, lineup_skill: -31, youth: 5 }));
    expect(r).toEqual({ driver: "Championships", drag: "Lineup Skill" });
  });

  it("returns null halves when no signal crosses the ±1 point threshold on that side", () => {
    expect(ratingDrivers(fr({ championships: 42, youth: 0.5 }))).toEqual({ driver: "Championships", drag: null });
    expect(ratingDrivers(fr({ lineup_skill: -31, youth: -0.5 }))).toEqual({ driver: null, drag: "Lineup Skill" });
  });

  it("returns both null for an empty breakdown", () => {
    expect(ratingDrivers(fr({}))).toEqual({ driver: null, drag: null });
  });

  it("falls back to the raw signal key when unmapped", () => {
    expect(ratingDrivers(fr({ mystery_signal: 9 })).driver).toBe("mystery_signal");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/ownerdeepdive/util.test.ts`
Expected: FAIL — `ratingDrivers` is not exported.

- [ ] **Step 3: Implement in util.tsx**

Append to `web/components/ownerdeepdive/util.tsx` (and add `FranchiseRating` to the existing `@/lib/types` import):

```tsx
/** Display names for rating-breakdown signal keys — shared by the Overview
 *  contribution bars, the hero driver/drag line, and receipts. */
export const SIGNAL_LABELS: Record<string, string> = {
  championships: "Championships", playoff_depth: "Playoff Depth",
  made_playoffs: "Made Playoffs", final_seed: "Final Seed",
  points_for_rank: "Points-For Rank",
  trade_value: "Trade Value", trade_production: "Trade Production",
  lineup_skill: "Lineup Skill",
  playoff: "Playoff Points", regular: "Regular Season",
  value: "Trade Value", toilet: "Toilet Bowl",
  roster_value: "Roster Value", draft_capital: "Draft Capital",
  draft_skill: "Draft Skill", youth: "Youth",
};

/** The single loudest positive and negative signal across every pillar —
 *  same ±1-point noise floor the Overview bars use. Either half is null
 *  when nothing crosses the floor on that side. */
export function ratingDrivers(fr: FranchiseRating): { driver: string | null; drag: string | null } {
  let top: { label: string; points: number } | null = null;
  let bottom: { label: string; points: number } | null = null;
  for (const p of Object.values(fr.pillars)) {
    for (const [k, s] of Object.entries(p.signals)) {
      if (Math.abs(s.contribution) < 1) continue;
      const entry = { label: SIGNAL_LABELS[k] ?? k, points: s.contribution };
      if (entry.points > 0 && (!top || entry.points > top.points)) top = entry;
      if (entry.points < 0 && (!bottom || entry.points < bottom.points)) bottom = entry;
    }
  }
  return { driver: top?.label ?? null, drag: bottom?.label ?? null };
}
```

Note the intentional behavior refinement vs `OverviewTab`'s old inline logic: `driver` is null when the most-positive signal isn't actually positive (old `top` could be a negative signal if all were negative; the old render guarded with `top.points > 0` — the guard now lives inside the helper).

- [ ] **Step 4: Switch OverviewTab to the shared helper**

In `web/components/ownerdeepdive/OverviewTab.tsx`:
1. Delete the module-private `SIGNAL_LABELS` constant (lines ~14-24) and import it instead: add `SIGNAL_LABELS` to the existing import from `./util` (or create `import { SIGNAL_LABELS } from "./util";`).
2. Keep `RatingDrivers`' internal `allSignals`/`scale`/`top`/`bottom` computation as-is (it feeds the bars' shared scale) — only the label map moves. Do NOT rewire its top/bottom to `ratingDrivers()`; the bars need the full signal list anyway.

- [ ] **Step 5: Run all tests + typecheck**

Run: `cd web && npm test -- --run && npx tsc --noEmit`
Expected: all green (new util tests + existing OwnerDeepDive tests); only the two pre-existing tsc errors.

- [ ] **Step 6: Commit**

```bash
git add web/components/ownerdeepdive/util.tsx web/components/ownerdeepdive/OverviewTab.tsx web/tests/ownerdeepdive/util.test.ts
git commit -m "feat(owner): extract ratingDrivers + SIGNAL_LABELS into shared util"
```

---

### Task 2: Driver/drag line under the hero letter

**Files:**
- Modify: `web/components/ownerdeepdive/HeroBand.tsx`
- Test: `web/tests/OwnerDeepDive.test.tsx` (extend)

**Interfaces:**
- Consumes: `ratingDrivers` from `./util` (Task 1). `HeroBand` already receives `detail: OwnerDetailResp`; `fr = detail.franchise_rating`.
- Produces: no new exports — pure render addition.

- [ ] **Step 1: Write the failing test**

In `web/tests/OwnerDeepDive.test.tsx`, the existing `DETAIL.franchise_rating.pillars` uses `pillar(n)` which has empty `signals` — the line must NOT render for it (add that assertion). Add a variant with real signals. Append to the file:

```tsx
describe("hero driver/drag line", () => {
  it("renders carried-by/dragged-by from the rating breakdown", () => {
    const detail: OwnerDetailResp = {
      ...DETAIL,
      franchise_rating: {
        ...DETAIL.franchise_rating!,
        pillars: {
          results: {
            weight: 0.5, z: 0, contribution: 40,
            signals: {
              championships: { raw: 2, z: 1.5, weight: 0.4, contribution: 42 },
              lineup_skill: { raw: 0.9, z: -1.2, weight: 0.3, contribution: -31 },
            },
          },
        },
      },
    };
    render(<OwnerDeepDive leagueId="L" detail={detail} />);
    expect(screen.getByText(/carried by Championships/i)).toBeInTheDocument();
    expect(screen.getByText(/dragged by Lineup Skill/i)).toBeInTheDocument();
  });

  it("renders nothing when no signal crosses the noise floor", () => {
    render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    expect(screen.queryByText(/carried by/i)).toBeNull();
    expect(screen.queryByText(/dragged by/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx -t "driver/drag"`
Expected: first test FAILS (`carried by` not found); second passes vacuously.

- [ ] **Step 3: Implement in HeroBand**

In `web/components/ownerdeepdive/HeroBand.tsx`:
1. Import: `import { franchiseLetterTone, ratingDrivers } from "./util";` (extend the existing util import).
2. Inside `HeroBand`, after `const [showReceipt, setShowReceipt] = useState(false);` add:

```tsx
const drivers = fr ? ratingDrivers(fr) : { driver: null, drag: null };
const driversLine = [
  drivers.driver ? `carried by ${drivers.driver}` : null,
  drivers.drag ? `dragged by ${drivers.drag}` : null,
].filter(Boolean).join(" · ");
```

3. Wrap the existing letter `<button>` (the `flex items-baseline gap-1.5 …` one at ~:94-109) in a column so the line sits directly under the letter/rank, right-aligned:

```tsx
<div className="flex flex-col items-end gap-1">
  {/* existing letter <button> unchanged */}
  {driversLine && (
    <div className="font-mono text-[10px] uppercase tracking-widest text-dim text-right max-w-[180px]">
      {driversLine}
    </div>
  )}
</div>
```

(The wrapper replaces the button's position inside the existing `flex items-center gap-2 shrink-0` container; `editAffordance` stays a sibling of the new column.)

- [ ] **Step 4: Run tests + typecheck**

Run: `cd web && npm test -- --run && npx tsc --noEmit`
Expected: all green; no new tsc errors.

- [ ] **Step 5: Commit**

```bash
git add web/components/ownerdeepdive/HeroBand.tsx web/tests/OwnerDeepDive.test.tsx
git commit -m "feat(owner): driver/drag line under the hero Franchise letter"
```

---

### Task 3: Receipt builders (pure)

**Files:**
- Create: `web/lib/receipts.ts`
- Test: `web/tests/receipts.test.ts` (create)

**Interfaces:**
- Consumes: `OwnerDetailResp`, `TradeDetailResp`, `OwnerTradeRow` from `@/lib/types`; `TabKey` from `@/components/ownerdeepdive/OverviewTab`; `ratingDrivers` + `ordinal` + `signed` from `@/components/ownerdeepdive/util`.
- Produces (Tasks 5 and 6 rely on these exact signatures):
  - `export function ownerReceipt(detail: OwnerDetailResp, tab: TabKey, tradesYear: number | "all"): string`
  - `export function ownerPath(leagueId: string, uid: string, tab: TabKey, tradesYear: number | "all"): string` — same canonical-URL rules as `OwnerDeepDive.syncQuery` (omit `tab` when `"overview"`, omit `year` unless tab is `"trades"` and a year is set).
  - `export function tradeReceipt(data: TradeDetailResp): string`

- [ ] **Step 1: Write the failing test**

Create `web/tests/receipts.test.ts`. Build fixtures with the same shapes as `OwnerDeepDive.test.tsx`'s `DETAIL` (copy the fixture inline — this file must stand alone):

```ts
import { describe, it, expect } from "vitest";
import { ownerReceipt, ownerPath, tradeReceipt } from "../lib/receipts";
import { OwnerDetailResp, TradeDetailResp } from "../lib/types";

const DETAIL = {
  league_id: "L", user_id: "u_a",
  owner: { user_id: "u_a", owner_name: "Mike", team_name: "Team M" },
  totals_by_lens: { ktc: 600, production: 70, regular: 60, playoff: 20, toilet: 5 },
  career_arc: [],
  trades: [
    { trade_id: "t1", date: "2023-10-01", season: 2023, week: 4, counterparties: [{ user_id: "u_b", owner_name: "Dave" }], assets_short: "X", swing_ktc: -800, swing_prod: 10, swing_regular: 5, swing_playoff: 0, swing_toilet: 0 },
    { trade_id: "t2", date: "2023-11-01", season: 2023, week: 9, counterparties: [{ user_id: "u_b", owner_name: "Dave" }], assets_short: "Y", swing_ktc: -440, swing_prod: 4, swing_regular: 4, swing_playoff: 0, swing_toilet: 0 },
    { trade_id: "t3", date: "2024-09-12", season: 2024, week: 2, counterparties: [{ user_id: "u_c", owner_name: "Cara" }], assets_short: "Z", swing_ktc: 1840, swing_prod: 60, swing_regular: 50, swing_playoff: 15, swing_toilet: 3 },
  ],
  best_trade_id: null, worst_trade_id: null,
  franchise_rating: {
    letter: "B", rating: 1620, rank: 3, of: 11, trend: 1,
    pillars: { results: { weight: 0.5, z: 0, contribution: 40, signals: { championships: { raw: 2, z: 1.5, weight: 0.4, contribution: 42 } } } },
  },
  track_record: {
    seasons: [], titles: 2, runner_ups: 1, playoff_appearances: 5, seasons_played: 6,
    best_finish: 1, career_wins: 89, career_losses: 67, career_ties: 0,
  },
} as OwnerDetailResp;

describe("ownerReceipt", () => {
  it("overview: letter, rank, driver", () => {
    expect(ownerReceipt(DETAIL, "overview", "all")).toBe(
      "Mike: B franchise, 3rd of 11 — carried by Championships",
    );
  });
  it("trades with a year filter: sums that year's ledger rows", () => {
    expect(ownerReceipt(DETAIL, "trades", 2023)).toBe(
      "Mike's 2023 trades: -1,240 Trade Value across 2 deals",
    );
  });
  it("trades all-time: sums every row, singular/plural handled", () => {
    expect(ownerReceipt(DETAIL, "trades", "all")).toBe(
      "Mike's trades: +600 Trade Value across 3 deals",
    );
  });
  it("record: titles, record, best finish", () => {
    expect(ownerReceipt(DETAIL, "record", "all")).toBe(
      "Mike all-time: 2 titles, 89-67, best finish 1st",
    );
  });
  it("falls back to a neutral line when the rating is missing", () => {
    const cold = { ...DETAIL, franchise_rating: null } as OwnerDetailResp;
    expect(ownerReceipt(cold, "overview", "all")).toBe("Mike — franchise receipts");
  });
});

describe("ownerPath", () => {
  it("canonical URL rules match the page's query sync", () => {
    expect(ownerPath("L", "u_a", "overview", "all")).toBe("/league/L/owner/u_a");
    expect(ownerPath("L", "u_a", "trades", 2023)).toBe("/league/L/owner/u_a?tab=trades&year=2023");
    expect(ownerPath("L", "u_a", "trades", "all")).toBe("/league/L/owner/u_a?tab=trades");
    expect(ownerPath("L", "u_a", "record", 2023)).toBe("/league/L/owner/u_a?tab=record");
  });
});

describe("tradeReceipt", () => {
  const TRADE = {
    league_id: "L", trade_id: "t1", date: "2024-09-12", week: 2, season: 2024, league_name: "Dynasty",
    sides: [
      { user_id: "u_a", production_started: 104.2, received_ktc: 1200 },
      { user_id: "u_b", production_started: 56.4, received_ktc: 400 },
    ],
    owner_names: { u_a: "Mike", u_b: "Dave" },
    winner_user_id: "u_a",
    lopsidedness: 0.7,
  } as unknown as TradeDetailResp;

  it("names winner, started-points head-to-head, and the Trade Value margin", () => {
    expect(tradeReceipt(TRADE)).toBe(
      "'24 W2 — Mike beat Dave: 104-56 started pts, +800 Trade Value",
    );
  });
  it("too-close trades get neutral copy", () => {
    const even = { ...TRADE, winner_user_id: null } as TradeDetailResp;
    expect(tradeReceipt(even)).toBe("'24 W2 — Mike vs Dave: 104-56 started pts");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/receipts.test.ts`
Expected: FAIL — module `../lib/receipts` does not exist.

- [ ] **Step 3: Implement `web/lib/receipts.ts`**

```ts
import { OwnerDetailResp, TradeDetailResp } from "@/lib/types";
import { TabKey } from "@/components/ownerdeepdive/OverviewTab";
import { ordinal, ratingDrivers, signed } from "@/components/ownerdeepdive/util";

/** Group-chat receipt builders. Deterministic, numbers-first, no hedging.
 *  Vocabulary rule: the string "KTC" never appears — it is "Trade Value". */

function deals(n: number): string {
  return `${n} deal${n === 1 ? "" : "s"}`;
}

export function ownerReceipt(
  detail: OwnerDetailResp, tab: TabKey, tradesYear: number | "all",
): string {
  const name = detail.owner.owner_name;
  const fr = detail.franchise_rating;
  switch (tab) {
    case "trades": {
      const rows = tradesYear === "all"
        ? detail.trades
        : detail.trades.filter((t) => t.season === tradesYear);
      const value = rows.reduce((s, t) => s + t.swing_ktc, 0);
      const scope = tradesYear === "all" ? `${name}'s trades` : `${name}'s ${tradesYear} trades`;
      return `${scope}: ${signed(value)} Trade Value across ${deals(rows.length)}`;
    }
    case "record": {
      const tr = detail.track_record;
      if (!tr) break;
      const rec = `${tr.career_wins}-${tr.career_losses}${tr.career_ties ? `-${tr.career_ties}` : ""}`;
      const best = tr.best_finish != null ? `, best finish ${ordinal(tr.best_finish)}` : "";
      return `${name} all-time: ${tr.titles} title${tr.titles === 1 ? "" : "s"}, ${rec}${best}`;
    }
    case "outlook": {
      const o = detail.outlook;
      if (!o) break;
      const rank = detail.roster_rank ? `, roster #${detail.roster_rank.rank} of ${detail.roster_rank.of}` : "";
      return `${name}'s outlook: ${o.window}${rank}`;
    }
  }
  // Overview + every fallback path.
  if (fr) {
    const { driver } = ratingDrivers(fr);
    const carried = driver ? ` — carried by ${driver}` : "";
    return `${name}: ${fr.letter} franchise, ${ordinal(fr.rank)} of ${fr.of}${carried}`;
  }
  return `${name} — franchise receipts`;
}

/** Canonical owner-page path — mirrors OwnerDeepDive.syncQuery's rules
 *  (omit defaults so the link matches the address bar). */
export function ownerPath(
  leagueId: string, uid: string, tab: TabKey, tradesYear: number | "all",
): string {
  const sp = new URLSearchParams();
  if (tab !== "overview") sp.set("tab", tab);
  if (tab === "trades" && tradesYear !== "all") sp.set("year", String(tradesYear));
  const qs = sp.toString();
  return `/league/${leagueId}/owner/${uid}${qs ? `?${qs}` : ""}`;
}

export function tradeReceipt(data: TradeDetailResp): string {
  const when = `'${String(data.season).slice(2)}${data.week ? ` W${data.week}` : ""}`;
  const names = data.owner_names ?? {};
  const [a, b] = data.sides;
  const nameOf = (uid: string) => names[uid] ?? "—";
  const ptsPair = (x: typeof a, y: typeof b) =>
    `${Math.round(x.production_started)}-${Math.round(y.production_started)} started pts`;
  const winner = data.winner_user_id ? data.sides.find((s) => s.user_id === data.winner_user_id) : undefined;
  const loser = winner ? data.sides.find((s) => s.user_id !== winner.user_id) : undefined;
  if (winner && loser) {
    const margin = signed(Math.round(winner.received_ktc - loser.received_ktc));
    return `${when} — ${nameOf(winner.user_id)} beat ${nameOf(loser.user_id)}: ${ptsPair(winner, loser)}, ${margin} Trade Value`;
  }
  return `${when} — ${nameOf(a.user_id)} vs ${nameOf(b.user_id)}: ${ptsPair(a, b)}`;
}
```

Before running: open `web/lib/types.ts` and confirm the `TradeSideView` field names used above (`user_id`, `production_started`, `received_ktc`) — they are the fields `TradeHero.tsx:383-391` already reads. If a name differs, match the type, not this plan.

- [ ] **Step 4: Run tests + typecheck**

Run: `cd web && npx vitest run tests/receipts.test.ts && npx tsc --noEmit`
Expected: all receipt tests PASS; no new tsc errors.

- [ ] **Step 5: Commit**

```bash
git add web/lib/receipts.ts web/tests/receipts.test.ts
git commit -m "feat(receipts): pure owner/trade receipt builders + canonical owner path"
```

---

### Task 4: `ReceiptButton` component

**Files:**
- Create: `web/components/ReceiptButton.tsx`
- Test: `web/tests/ReceiptButton.test.tsx` (create)

**Interfaces:**
- Consumes: nothing project-specific (pure UI + browser APIs).
- Produces (Tasks 5-6 rely on this): `export function ReceiptButton({ claim, path }: { claim: () => string; path: () => string })` — both getters run at tap time. Composes `` `${claim()}\n${new URL(path(), window.location.origin).href}` ``; prefers `navigator.share({ text })` on coarse-pointer devices when available, else `navigator.clipboard.writeText`; shows `Copied ✓` for 2s on clipboard success, `Copy failed` for 2s on rejection.

- [ ] **Step 1: Write the failing test**

Create `web/tests/ReceiptButton.test.tsx`:

```tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReceiptButton } from "../components/ReceiptButton";

afterEach(() => vi.unstubAllGlobals());

function mockClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText }, share: undefined });
  return writeText;
}

describe("ReceiptButton", () => {
  it("copies claim + absolute URL and confirms", async () => {
    const writeText = mockClipboard();
    render(<ReceiptButton claim={() => "Mike: B franchise"} path={() => "/league/L/owner/u_a"} />);
    await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
    expect(writeText).toHaveBeenCalledWith(
      `Mike: B franchise\n${window.location.origin}/league/L/owner/u_a`,
    );
    expect(await screen.findByText(/copied/i)).toBeInTheDocument();
  });

  it("shows an error state when the clipboard rejects", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("nope")) },
      share: undefined,
    });
    render(<ReceiptButton claim={() => "x"} path={() => "/p"} />);
    await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
    expect(await screen.findByText(/failed/i)).toBeInTheDocument();
  });

  it("evaluates the getters at tap time, not render time", async () => {
    const writeText = mockClipboard();
    let n = 1;
    render(<ReceiptButton claim={() => `claim ${n}`} path={() => "/p"} />);
    n = 2;
    await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("claim 2"));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/ReceiptButton.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `web/components/ReceiptButton.tsx`**

```tsx
"use client";

import { useRef, useState } from "react";

/** One-tap group-chat receipt: composes `claim\nabsolute-url` at tap time.
 *  Coarse-pointer devices with the Web Share API get the share sheet
 *  (straight to the group chat); everyone else gets the clipboard with a
 *  brief inline confirmation. Quiet mono affordance per the receipts voice. */
export function ReceiptButton({ claim, path }: { claim: () => string; path: () => string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout>>();

  function flash(next: "copied" | "failed") {
    setState(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  }

  async function onTap() {
    const text = `${claim()}\n${new URL(path(), window.location.origin).href}`;
    const coarse = typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
    if (coarse && typeof navigator.share === "function") {
      // Share-sheet cancel is not a failure — no state change either way.
      navigator.share({ text }).catch(() => {});
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      flash("copied");
    } catch {
      flash("failed");
    }
  }

  return (
    <button
      type="button"
      onClick={onTap}
      className="shrink-0 whitespace-nowrap font-mono text-[10px] uppercase tracking-widest text-dim hover:text-ink transition-colors px-2 py-2"
    >
      {state === "copied" ? (
        <span className="text-pos" role="status">Copied ✓</span>
      ) : state === "failed" ? (
        <span className="text-neg" role="status">Copy failed</span>
      ) : (
        <>⧉ copy receipt</>
      )}
    </button>
  );
}
```

- [ ] **Step 4: Run tests + typecheck**

Run: `cd web && npx vitest run tests/ReceiptButton.test.tsx && npx tsc --noEmit`
Expected: PASS; no new tsc errors.

- [ ] **Step 5: Commit**

```bash
git add web/components/ReceiptButton.tsx web/tests/ReceiptButton.test.tsx
git commit -m "feat(receipts): ReceiptButton share/clipboard primitive"
```

---

### Task 5: Wire the receipt into the owner tab bar

**Files:**
- Modify: `web/components/OwnerDeepDive.tsx`
- Test: `web/tests/OwnerDeepDive.test.tsx` (extend)

**Interfaces:**
- Consumes: `ReceiptButton` (Task 4), `ownerReceipt` + `ownerPath` (Task 3). Existing state: `activeTab: TabKey`, `tradesYear: number | "all"`, prop `leagueId`, `detail`.
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

Append to `web/tests/OwnerDeepDive.test.tsx` (the file already stubs/mutates location for URL-sync tests; clipboard mock mirrors `ReceiptButton.test.tsx`):

```tsx
describe("owner receipt button", () => {
  it("copies the claim for the current tab + filter", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText }, share: undefined });
    render(<OwnerDeepDive leagueId="L" detail={DETAIL} />);
    // Switch to Trades and filter to '23 (chip labeled '23 exists in DETAIL).
    await userEvent.click(screen.getByRole("tab", { name: "Trades" }));
    await userEvent.click(screen.getByRole("button", { name: "'23" }));
    await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
    const text = writeText.mock.calls[0][0] as string;
    expect(text).toContain("Alice's 2023 trades:");
    expect(text).toContain("/league/L/owner/u_a?tab=trades&year=2023");
    vi.unstubAllGlobals();
  });
});
```

(Import `vi` in the test file's vitest import if not already there.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/OwnerDeepDive.test.tsx -t "receipt"`
Expected: FAIL — no copy-receipt button.

- [ ] **Step 3: Implement**

In `web/components/OwnerDeepDive.tsx`:
1. Imports: `import { ReceiptButton } from "./ReceiptButton";` and `import { ownerReceipt, ownerPath } from "@/lib/receipts";`.
2. Wrap the tablist so the button sits at the right end without joining the scroll region. Replace the current `role="tablist"` div (which owns `border-b border-divider`) with:

```tsx
<div className="flex items-center border-b border-divider">
  <div role="tablist" aria-label="Franchise sections" onKeyDown={onTablistKeyDown}
    className="flex gap-1 flex-1 min-w-0 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
    {/* existing TABS.map(...) buttons — note the tab buttons keep `-mb-px border-b-2`;
        the bottom border moved to this wrapper, so change `-mb-px` to `-mb-[1px]`? No —
        keep `-mb-px` exactly as-is; it now overlaps the wrapper's border identically. */}
  </div>
  <ReceiptButton
    claim={() => ownerReceipt(detail, activeTab, tradesYear)}
    path={() => ownerPath(leagueId, detail.user_id, activeTab, tradesYear)}
  />
</div>
```

The inner tablist loses its own `border-b border-divider` (moved to the wrapper); everything else about the tab buttons is untouched.

- [ ] **Step 4: Run the full suite + typecheck**

Run: `cd web && npm test -- --run && npx tsc --noEmit`
Expected: new test passes; the existing URL-sync and roving-tabindex tests still pass (the tablist moved one level deeper — if a test queried the tablist's className for the border, update that assertion); no new tsc errors.

- [ ] **Step 5: Commit**

```bash
git add web/components/OwnerDeepDive.tsx web/tests/OwnerDeepDive.test.tsx
git commit -m "feat(receipts): copy-receipt action on the owner tab bar"
```

---

### Task 6: Wire the receipt into the trade detail page

**Files:**
- Modify: `web/components/TradeHero.tsx`
- Modify: `web/app/league/[id]/trade/[tid]/page.tsx`
- Test: `web/tests/TradeHero.test.tsx` if it exists, else extend the trade-page test that renders `TradeHero` (check `web/tests/` first; if none renders it, add the assertion to a new minimal test in `web/tests/TradeHero.test.tsx` using the fixture shapes from Task 3's `TRADE`).

**Interfaces:**
- Consumes: `ReceiptButton` (Task 4), `tradeReceipt` (Task 3).
- Produces: `TradeHeroProps` gains `receipt?: React.ReactNode` rendered beside the verdict headline.

- [ ] **Step 1: Add the `receipt` slot to TradeHero**

In `web/components/TradeHero.tsx`, add to `TradeHeroProps`:

```ts
/** Optional share affordance (the copy-receipt button) rendered by the verdict. */
receipt?: React.ReactNode;
```

Render it adjacent to the verdict `h1` block (~:431-435). The verdict is conditional, so anchor the slot outside the conditional — wrap:

```tsx
<div className="flex items-start justify-between gap-3">
  <div className="min-w-0">
    {/* existing story?.verdict h1 block unchanged */}
  </div>
  {receipt && <div className="shrink-0 mt-1">{receipt}</div>}
</div>
```

- [ ] **Step 2: Pass it from the page**

In `web/app/league/[id]/trade/[tid]/page.tsx`, at the `<TradeHero …/>` call (~:91-98), add:

```tsx
receipt={
  <ReceiptButton
    claim={() => tradeReceipt(data)}
    path={() => `/league/${params.id}/trade/${params.tid}`}
  />
}
```

with imports `import { ReceiptButton } from "@/components/ReceiptButton";` and `import { tradeReceipt } from "@/lib/receipts";`. Check the page's actual param names (`params.id` / `params.tid`) at the top of the file and match them. Note: the page is a server component but `claim`/`path` are closures evaluated inside the client `ReceiptButton` — since `data` is serialized into the closure, this works only if the page passes plain values. If Next complains about passing functions from a server component, instead compute the strings server-side and change nothing else: `receipt={<ReceiptButton claim={tradeReceiptText} path={tradePath} />}` won't typecheck — so in that case add a tiny client wrapper `web/components/TradeReceiptButton.tsx`:

```tsx
"use client";
import { ReceiptButton } from "./ReceiptButton";

export function TradeReceiptButton({ claim, path }: { claim: string; path: string }) {
  return <ReceiptButton claim={() => claim} path={() => path} />;
}
```

and pass `receipt={<TradeReceiptButton claim={tradeReceipt(data)} path={`/league/${params.id}/trade/${params.tid}`} />}` — strings serialize fine across the server/client boundary. **Use the wrapper approach by default; it is the one that always works.**

- [ ] **Step 3: Test**

If no existing test renders `TradeHero`, create `web/tests/TradeHero.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeHero } from "../components/TradeHero";

describe("TradeHero receipt slot", () => {
  it("renders the receipt affordance next to the verdict", () => {
    render(
      <TradeHero
        sides={[]}
        story={{ verdict: "A heist in broad daylight", body: "" }}
        lopsidedness={0.7}
        winner_user_id={"u_a"}
        receipt={<button>⧉ copy receipt</button>}
      />,
    );
    expect(screen.getByRole("button", { name: /copy receipt/i })).toBeInTheDocument();
  });
});
```

(If `TradeHero` requires non-empty `sides` to render, reuse the two-side fixture from Task 3's `TRADE.sides` with whatever extra fields the type demands — inspect `TradeSideView` and fill required fields minimally.)

- [ ] **Step 4: Run tests + typecheck**

Run: `cd web && npm test -- --run && npx tsc --noEmit`
Expected: all green; no new tsc errors.

- [ ] **Step 5: Commit**

```bash
git add web/components/TradeHero.tsx web/components/TradeReceiptButton.tsx web/app/league/[id]/trade/[tid]/page.tsx web/tests/TradeHero.test.tsx
git commit -m "feat(receipts): copy-receipt on the trade verdict"
```

---

### Task 7: vs-You selectors + viewer-identity hook

**Files:**
- Modify: `web/components/ownerdeepdive/util.tsx` (append selectors)
- Create: `web/components/ownerdeepdive/useViewerOwner.ts`
- Test: `web/tests/ownerdeepdive/util.test.ts` (extend)

**Interfaces:**
- Consumes: `H2H`, `OwnerRef`, `OwnerTradeRow`, `OwnerDetailResp` from `@/lib/types`; `getMe` from `@/lib/api`.
- Produces (Task 8 relies on these exact signatures):
  - `export function h2hFor(headToHead: H2H[] | undefined, uid: string): H2H | null`
  - `export function tradesBetween(trades: OwnerTradeRow[], uid: string): { count: number; value: number }` — value is the PAGE OWNER's net Trade Value swing across those deals.
  - `export function vsCopy(h: H2H, pageOwnerName: string, viewerIsRival: boolean): string` — direction-aware line FROM THE VIEWER'S SIDE when `viewerIsRival` (H2H rows are stored from the page owner's perspective, so flip wins/losses/margin), otherwise neutral third-person.
  - `export function vsCandidates(detail: OwnerDetailResp): OwnerRef[]` — H2H opponents first (sorted by games desc), then trade-only counterparties, deduped by `user_id`, page owner excluded.
  - Hook: `export function useViewerOwner(detail: OwnerDetailResp): { viewer: OwnerRef | null; isPageOwner: boolean; loaded: boolean }`

- [ ] **Step 1: Write the failing tests**

Append to `web/tests/ownerdeepdive/util.test.ts`:

```ts
import { h2hFor, tradesBetween, vsCopy, vsCandidates } from "../../components/ownerdeepdive/util";
import { H2H, OwnerDetailResp } from "../../lib/types";

const H: H2H = {
  opponent: { user_id: "u_b", owner_name: "Dave" },
  wins: 9, losses: 3, ties: 0, points_for: 1500, points_against: 1330,
};

describe("vs-you selectors", () => {
  it("h2hFor finds the rivalry row", () => {
    expect(h2hFor([H], "u_b")).toBe(H);
    expect(h2hFor([H], "u_z")).toBeNull();
    expect(h2hFor(undefined, "u_b")).toBeNull();
  });

  it("tradesBetween counts and sums the page owner's value swing", () => {
    const trades = [
      { trade_id: "1", date: "", season: 2023, week: 1, counterparties: [{ user_id: "u_b", owner_name: "Dave" }], assets_short: "", swing_ktc: -800, swing_prod: 0, swing_regular: 0, swing_playoff: 0, swing_toilet: 0 },
      { trade_id: "2", date: "", season: 2024, week: 1, counterparties: [{ user_id: "u_c", owner_name: "Cara" }], assets_short: "", swing_ktc: 500, swing_prod: 0, swing_regular: 0, swing_playoff: 0, swing_toilet: 0 },
    ];
    expect(tradesBetween(trades, "u_b")).toEqual({ count: 1, value: -800 });
  });

  it("vsCopy speaks from the viewer's side when the viewer is the rival", () => {
    // H is page-owner Mike's row vs Dave (Mike 9-3, +14.2/gm). Dave viewing:
    expect(vsCopy(H, "Mike", true)).toBe("Mike owns you: 9-3, +14.2 a game");
    // Dave leading from Dave's side:
    const daveUp: H2H = { ...H, wins: 3, losses: 9, points_for: 1330, points_against: 1500 };
    expect(vsCopy(daveUp, "Mike", true)).toBe("You own Mike: 9-3, +14.2 a game");
    // Dead even:
    const even: H2H = { ...H, wins: 6, losses: 6, points_for: 1400, points_against: 1396 };
    expect(vsCopy(even, "Mike", true)).toBe("Dead even with Mike: 6-6, -0.3 a game");
  });

  it("vsCopy is neutral third-person for a picked (non-viewer) rival", () => {
    expect(vsCopy(H, "Mike", false)).toBe("Mike vs Dave: 9-3 Mike, +14.2 a game");
  });

  it("vsCandidates unions H2H opponents and trade counterparties, deduped", () => {
    const detail = {
      user_id: "u_a",
      owner: { user_id: "u_a", owner_name: "Mike" },
      head_to_head: [H],
      trades: [
        { trade_id: "1", date: "", season: 2023, week: 1, counterparties: [{ user_id: "u_b", owner_name: "Dave" }, { user_id: "u_c", owner_name: "Cara" }], assets_short: "", swing_ktc: 0, swing_prod: 0, swing_regular: 0, swing_playoff: 0, swing_toilet: 0 },
      ],
    } as unknown as OwnerDetailResp;
    expect(vsCandidates(detail).map((o) => o.user_id)).toEqual(["u_b", "u_c"]);
  });
});
```

Direction-copy rules pinned by these tests: viewer side flips H2H (viewer record = `losses-wins` of the stored row, margin negated); leader's record is always stated leader-first; margin is per-game, one decimal, signed from the speaking side; even records use "Dead even".

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/ownerdeepdive/util.test.ts`
Expected: FAIL — selectors not exported.

- [ ] **Step 3: Implement selectors in util.tsx**

Append to `web/components/ownerdeepdive/util.tsx` (extend the types import with `H2H, OwnerRef, OwnerDetailResp`):

```tsx
export function h2hFor(headToHead: H2H[] | undefined, uid: string): H2H | null {
  return headToHead?.find((h) => h.opponent.user_id === uid) ?? null;
}

/** Deals with this rival, from the page owner's side of the ledger. */
export function tradesBetween(trades: OwnerTradeRow[], uid: string): { count: number; value: number } {
  const rows = trades.filter((t) => t.counterparties.some((c) => c.user_id === uid));
  return { count: rows.length, value: rows.reduce((s, t) => s + t.swing_ktc, 0) };
}

function marginText(pf: number, pa: number, games: number): string {
  const m = games ? (pf - pa) / games : 0;
  return `${m >= 0 ? "+" : "-"}${Math.abs(m).toFixed(1)} a game`;
}

/** One candid line for the rivalry. H2H rows are stored from the page
 *  owner's perspective; when the viewer IS the rival, flip to speak from
 *  the viewer's side ("You own Mike" / "Mike owns you"). */
export function vsCopy(h: H2H, pageOwnerName: string, viewerIsRival: boolean): string {
  const games = h.wins + h.losses + h.ties;
  if (viewerIsRival) {
    const you = { wins: h.losses, losses: h.wins, pf: h.points_against, pa: h.points_for };
    const rec = (w: number, l: number) => `${w}-${l}${h.ties ? `-${h.ties}` : ""}`;
    if (you.wins > you.losses) return `You own ${pageOwnerName}: ${rec(you.wins, you.losses)}, ${marginText(you.pf, you.pa, games)}`;
    if (you.wins < you.losses) return `${pageOwnerName} owns you: ${rec(h.wins, h.losses)}, ${marginText(h.points_for, h.points_against, games)}`;
    return `Dead even with ${pageOwnerName}: ${rec(you.wins, you.losses)}, ${marginText(you.pf, you.pa, games)}`;
  }
  const rec = `${h.wins}-${h.losses}${h.ties ? `-${h.ties}` : ""}`;
  return `${pageOwnerName} vs ${h.opponent.owner_name}: ${rec} ${pageOwnerName}, ${marginText(h.points_for, h.points_against, games)}`;
}

/** Rival-picker candidates: H2H opponents (most games first), then
 *  trade-only counterparties; deduped; the page owner never appears. */
export function vsCandidates(detail: OwnerDetailResp): OwnerRef[] {
  const seen = new Set<string>([detail.user_id]);
  const out: OwnerRef[] = [];
  const h2h = [...(detail.head_to_head ?? [])].sort(
    (a, b) => b.wins + b.losses + b.ties - (a.wins + a.losses + a.ties),
  );
  for (const h of h2h) {
    if (!seen.has(h.opponent.user_id)) { seen.add(h.opponent.user_id); out.push(h.opponent); }
  }
  for (const t of detail.trades) {
    for (const c of t.counterparties) {
      if (!seen.has(c.user_id)) { seen.add(c.user_id); out.push(c); }
    }
  }
  return out;
}
```

- [ ] **Step 4: Implement the hook**

Create `web/components/ownerdeepdive/useViewerOwner.ts`:

```ts
"use client";

import { useEffect, useState } from "react";
import { getMe } from "@/lib/api";
import { OwnerDetailResp, OwnerRef } from "@/lib/types";
import { vsCandidates } from "./util";

/** Resolve the signed-in viewer to a league owner via their soft Sleeper
 *  link (same mechanism as the dashboard's youUserId). Fails silent to
 *  null — the vs band then falls back to its picker. */
export function useViewerOwner(detail: OwnerDetailResp): {
  viewer: OwnerRef | null;
  isPageOwner: boolean;
  loaded: boolean;
} {
  const [sleeperId, setSleeperId] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let alive = true;
    getMe()
      .then((me) => { if (alive) setSleeperId(me.sleeper_user_id); })
      .catch(() => {})
      .finally(() => { if (alive) setLoaded(true); });
    return () => { alive = false; };
  }, []);
  if (!sleeperId) return { viewer: null, isPageOwner: false, loaded };
  if (sleeperId === detail.user_id) return { viewer: null, isPageOwner: true, loaded };
  const viewer = vsCandidates(detail).find((o) => o.user_id === sleeperId) ?? null;
  return { viewer, isPageOwner: false, loaded };
}
```

- [ ] **Step 5: Run tests + typecheck**

Run: `cd web && npm test -- --run && npx tsc --noEmit`
Expected: all selector tests PASS (hook is covered via Task 8's render tests); no new tsc errors.

- [ ] **Step 6: Commit**

```bash
git add web/components/ownerdeepdive/util.tsx web/components/ownerdeepdive/useViewerOwner.ts web/tests/ownerdeepdive/util.test.ts
git commit -m "feat(vs-you): rivalry selectors + viewer-identity hook"
```

---

### Task 8: `VsYouBand` component, mounted in OwnerDeepDive

**Files:**
- Create: `web/components/ownerdeepdive/VsYouBand.tsx`
- Modify: `web/components/OwnerDeepDive.tsx` (mount between HeroBand and the tab bar)
- Test: `web/tests/ownerdeepdive/VsYouBand.test.tsx` (create)

**Interfaces:**
- Consumes: `useViewerOwner` (Task 7), `h2hFor` / `tradesBetween` / `vsCopy` / `vsCandidates` / `signed` / `tone` from `./util`, `SegmentControl` from `@/components/SegmentControl`, `CardHead`? — no: this band is its own slim card, not a `Card` section (visual weight below the hero).
- Produces: `export function VsYouBand({ detail, onSeeRecord }: { detail: OwnerDetailResp; onSeeRecord: () => void })`.

- [ ] **Step 1: Write the failing tests**

Create `web/tests/ownerdeepdive/VsYouBand.test.tsx`. Mock `getMe` at the module level (the hook imports it from `@/lib/api`):

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VsYouBand } from "../../components/ownerdeepdive/VsYouBand";
import { OwnerDetailResp } from "../../lib/types";

const getMe = vi.fn();
vi.mock("@/lib/api", () => ({ getMe: (...a: unknown[]) => getMe(...a) }));

const DETAIL = {
  league_id: "L", user_id: "u_a",
  owner: { user_id: "u_a", owner_name: "Mike" },
  totals_by_lens: { ktc: 0, production: 0, regular: 0, playoff: 0, toilet: 0 },
  career_arc: [],
  best_trade_id: null, worst_trade_id: null,
  head_to_head: [
    { opponent: { user_id: "u_b", owner_name: "Dave" }, wins: 9, losses: 3, ties: 0, points_for: 1500, points_against: 1330 },
  ],
  trades: [
    { trade_id: "1", date: "2023-10-01", season: 2023, week: 4, counterparties: [{ user_id: "u_b", owner_name: "Dave" }], assets_short: "X", swing_ktc: -800, swing_prod: 0, swing_regular: 0, swing_playoff: 0, swing_toilet: 0 },
  ],
} as unknown as OwnerDetailResp;

beforeEach(() => getMe.mockReset());

describe("VsYouBand", () => {
  it("auto-resolves the viewer and speaks from their side", async () => {
    getMe.mockResolvedValue({ sleeper_user_id: "u_b" });
    render(<VsYouBand detail={DETAIL} onSeeRecord={() => {}} />);
    expect(await screen.findByText(/Mike owns you: 9-3, \+14\.2 a game/)).toBeInTheDocument();
    // Trades row, flipped to the viewer's side (page owner -800 => viewer +800):
    expect(screen.getByText(/1 deal between you/i)).toBeInTheDocument();
    expect(screen.getByText(/\+800 Trade Value/)).toBeInTheDocument();
  });

  it("falls back to a picker when the viewer is unlinked", async () => {
    getMe.mockResolvedValue({ sleeper_user_id: null });
    render(<VsYouBand detail={DETAIL} onSeeRecord={() => {}} />);
    expect(await screen.findByRole("group", { name: /compare vs/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dave" }));
    expect(screen.getByText(/Mike vs Dave: 9-3 Mike/)).toBeInTheDocument();
  });

  it("offers the picker framed as sizing up a rival when the viewer IS the page owner", async () => {
    getMe.mockResolvedValue({ sleeper_user_id: "u_a" });
    render(<VsYouBand detail={DETAIL} onSeeRecord={() => {}} />);
    expect(await screen.findByText(/size up a rival/i)).toBeInTheDocument();
  });

  it("hides entirely when there are no candidates", async () => {
    getMe.mockResolvedValue({ sleeper_user_id: null });
    const empty = { ...DETAIL, head_to_head: [], trades: [] } as OwnerDetailResp;
    const { container } = render(<VsYouBand detail={empty} onSeeRecord={() => {}} />);
    await Promise.resolve();
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd web && npx vitest run tests/ownerdeepdive/VsYouBand.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `web/components/ownerdeepdive/VsYouBand.tsx`**

```tsx
"use client";

import { useState } from "react";
import { SegmentControl } from "@/components/SegmentControl";
import { OwnerDetailResp } from "@/lib/types";
import { useViewerOwner } from "./useViewerOwner";
import { h2hFor, signed, tone, tradesBetween, vsCandidates, vsCopy } from "./util";

/** The rival's actual question, answered on arrival: me vs you. Auto-locks
 *  to the signed-in viewer when their Sleeper link matches a league-mate;
 *  otherwise a picker. Hidden when there is nobody to compare against. */
export function VsYouBand({ detail, onSeeRecord }: { detail: OwnerDetailResp; onSeeRecord: () => void }) {
  const { viewer, isPageOwner, loaded } = useViewerOwner(detail);
  const [pickedUid, setPickedUid] = useState<string | null>(null);
  const candidates = vsCandidates(detail);
  if (candidates.length === 0) return null;

  // Manual pick always beats auto-resolution; auto only counts once loaded.
  const rivalUid = pickedUid ?? (loaded && viewer ? viewer.user_id : null);
  const rival = candidates.find((o) => o.user_id === rivalUid) ?? null;
  const viewerIsRival = rival != null && viewer != null && rival.user_id === viewer.user_id && pickedUid == null;

  const h = rival ? h2hFor(detail.head_to_head, rival.user_id) : null;
  const t = rival ? tradesBetween(detail.trades, rival.user_id) : { count: 0, value: 0 };
  // Ledger swings are the page owner's; flip when speaking from the viewer's side.
  const tradeValue = viewerIsRival ? -t.value : t.value;
  if (rival && !h && t.count === 0) return null;

  return (
    <section className="mt-3 bg-surface border border-divider rounded-card px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-dim shrink-0">
          {isPageOwner && !pickedUid ? "size up a rival" : "vs you"}
        </span>
        {rival ? (
          <>
            {h && (
              <span className="text-[13px] font-semibold text-ink">
                {vsCopy(h, detail.owner.owner_name, viewerIsRival)}
              </span>
            )}
            {t.count > 0 && (
              <span className="font-mono text-[11px] text-dim">
                {t.count} deal{t.count === 1 ? "" : "s"} between you ·{" "}
                <span className={`tabular ${tone(tradeValue)}`}>{signed(tradeValue)} Trade Value</span>
              </span>
            )}
            <button
              type="button"
              onClick={onSeeRecord}
              className="ml-auto shrink-0 font-mono text-[10px] uppercase tracking-widest text-dim hover:text-ink transition-colors"
            >
              full head-to-head →
            </button>
          </>
        ) : (
          <SegmentControl<string>
            aria-label="Compare vs"
            options={candidates.map((o) => ({ key: o.user_id, label: o.owner_name }))}
            value={"" as string}
            onChange={(uid) => setPickedUid(uid)}
          />
        )}
      </div>
      {rival && (
        <div className="mt-1.5">
          <SegmentControl<string>
            aria-label="Compare vs"
            options={candidates.map((o) => ({ key: o.user_id, label: o.owner_name }))}
            value={rival.user_id}
            onChange={(uid) => setPickedUid(uid)}
          />
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Mount in OwnerDeepDive**

In `web/components/OwnerDeepDive.tsx`, import `VsYouBand` from `./ownerdeepdive/VsYouBand` and render it between `<HeroBand …/>` and the tab-bar wrapper:

```tsx
<VsYouBand detail={detail} onSeeRecord={() => selectTab("record")} />
```

- [ ] **Step 5: Run the full suite + typecheck**

Run: `cd web && npm test -- --run && npx tsc --noEmit`
Expected: all green — including the existing `OwnerDeepDive` tests (they don't mock `getMe`; the hook's `.catch(() => {})` absorbs the unmocked rejection and the band falls back to picker/hidden — if a test asserts on exact DOM between hero and tabs, update it); no new tsc errors.

- [ ] **Step 6: Commit**

```bash
git add web/components/ownerdeepdive/VsYouBand.tsx web/components/OwnerDeepDive.tsx web/tests/ownerdeepdive/VsYouBand.test.tsx
git commit -m "feat(vs-you): matchup band with auto viewer resolution + rival picker"
```

---

### Task 9: Full verification + docs touch

**Files:**
- Modify: `CLAUDE.md` (repo root — one line in the owner-page bullet noting the receipts/vs-you additions)

- [ ] **Step 1: Full suite**

Run from repo root: `make test`
Expected: backend + frontend both green (backend untouched — this confirms no accidental coupling).

- [ ] **Step 2: Manual smoke (if a dev server is practical)**

`make dev-web` + `make dev-api`, open an owner page: verify the driver/drag line, copy a receipt on two tabs and paste the text, check the vs band as a linked and an unlinked user, and confirm both themes. If no dev server is practical in the execution environment, state that explicitly in the report instead of claiming visual verification.

- [ ] **Step 3: Update CLAUDE.md**

In the repo-root `CLAUDE.md`, in the "Owner franchise page" bullet, append one sentence:

```
A "vs You" band (auto viewer resolution via the soft Sleeper link, rival picker fallback) sits between the hero and the tabs, and a copy-receipt action (`web/lib/receipts.ts` + `ReceiptButton`) on the owner tab bar and trade verdict composes claim + deep link for the group chat.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note vs-you band + copy-receipt in CLAUDE.md"
```

---

## Self-Review (done during planning)

- **Spec coverage:** F2 → Tasks 1-2; F1 → Tasks 3-6; F3 → Tasks 7-8; cross-cutting voice/tokens/tests → Global Constraints + per-task tests; "no KTC" enforced in builders and tested copy.
- **Deviations from spec, pinned:** H2H type name; vs-candidates from H2H ∪ counterparties (no owners list exists); trade receipt without grade strings (none exist in the payload).
- **Type consistency:** `ratingDrivers` (T1) used by T2/T3; `ownerReceipt/ownerPath/tradeReceipt` (T3) used by T5/T6; `ReceiptButton {claim, path}` getters (T4) used by T5/T6 (T6 via string-wrapping client component); selectors + hook (T7) used by T8 with matching signatures.
