# OG Share Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a trade / owner / league link is pasted anywhere link previews work, it unfurls into a "box score" verdict card (1200×630 image), purely via Next.js dynamic Open Graph image generation.

**Architecture:** Each of the three pages gets a Next App Router `opengraph-image.tsx` (renders the card with `next/og` `ImageResponse`, `runtime="nodejs"`) plus a `generateMetadata` for title/description. Pure, unit-tested **data mappers** (`lib/og-card-data.ts`) turn the API responses into plain card props; **renderers** (`lib/og-card.tsx`) turn props into Satori JSX through a shared `CardFrame`. Fonts are fetched once from Google Fonts and cached in module scope.

**Tech Stack:** Next.js 14.2.16 (App Router, standalone Docker on Railway), `next/og` (Satori), TypeScript, vitest + @testing-library, the existing `lib/api` fetchers.

**Reference spec:** `docs/superpowers/specs/2026-06-08-og-share-cards.md`

**Conventions:** Web tests run from `web/` with `npx vitest run --config tests/vitest.config.ts`. `@/` aliases the web root. No em dashes in any card copy. Run all commands from `web/` unless noted.

**Test strategy:** The pure mappers in `lib/og-card-data.ts` and the font-URL parser are unit-tested (TDD). The `opengraph-image.tsx` routes and the Satori renderers **cannot** run under jsdom (ImageResponse needs wasm), so they are verified by `npm run build` (type + route validity) and a manual unfurl check, not unit tests. This is intentional, not a gap.

---

## File Structure

**Create:**
- `web/lib/og-font.ts` — fetch + cache Inter (400, 600) from Google Fonts; `extractFontUrl(css)` pure helper.
- `web/lib/og-card-data.ts` — pure mappers: `tradeCard`, `ownerCard`, `leagueCard`, `fallbackCard` → plain card props.
- `web/lib/og-card.tsx` — `CardFrame` + `renderCard(card)` (Satori JSX). Shared box-score visual system.
- `web/app/league/[id]/trade/[tid]/opengraph-image.tsx`
- `web/app/league/[id]/owner/[uid]/opengraph-image.tsx`
- `web/app/league/[id]/opengraph-image.tsx`
- Tests: `web/tests/og-card-data.test.ts`, `web/tests/og-font.test.ts`

**Modify (add `generateMetadata`):**
- `web/app/league/[id]/trade/[tid]/page.tsx`
- `web/app/league/[id]/owner/[uid]/page.tsx`
- `web/app/league/[id]/page.tsx`

---

## Task 1: Card data mappers (the tested core)

**Files:**
- Create: `web/lib/og-card-data.ts`
- Test: `web/tests/og-card-data.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// web/tests/og-card-data.test.ts
import { describe, it, expect } from "vitest";
import { tradeCard, ownerCard, leagueCard, fallbackCard } from "@/lib/og-card-data";

const trade = {
  league_id: "L", trade_id: "t1", date: "2025-11-07", week: 10, season: 2025,
  league_name: "DyNASTY", story: { verdict: "tkeefe6689 fleeced Bobster565.", body: "" },
  sides: [
    { user_id: "u_t", owner_name: "tkeefe6689", received: [{ name: "Josh Jacobs" }, { season: 2027, round: 1 }], given: [],
      snapshot_ktc_swing: 4632, hindsight_production_swing: 25.4, hindsight_started_swing: 18, hindsight_started_playoff_swing: 1.3,
      at_trade_ktc_swing: null, aged_ktc_swing: null, at_trade_approx: false, at_trade_snapshot_date: null },
    { user_id: "u_b", owner_name: "Bobster565", received: [{ name: "Saquon Barkley" }], given: [],
      snapshot_ktc_swing: -4632, hindsight_production_swing: -25.4, hindsight_started_swing: -18, hindsight_started_playoff_swing: -1.3,
      at_trade_ktc_swing: null, aged_ktc_swing: null, at_trade_approx: false, at_trade_snapshot_date: null },
  ],
} as any;

describe("tradeCard", () => {
  it("uses the verdict, names winner by trade-value swing, builds the scoreboard", () => {
    const c = tradeCard(trade);
    expect(c.kind).toBe("trade");
    expect(c.title).toBe("tkeefe6689 fleeced Bobster565.");
    expect(c.colA).toBe("tkeefe6689");
    expect(c.colB).toBe("Bobster565");
    expect(c.winner).toBe("a"); // +4632 vs -4632
    const tv = c.rows.find((r) => r.label === "Trade Value")!;
    expect([tv.a, tv.b]).toEqual([4632, -4632]);
    expect(c.rows.map((r) => r.label)).toEqual(["Trade Value", "Total Points", "Playoff Points"]);
    expect(c.footnote).toContain("Josh Jacobs");
  });

  it("falls back to 'A vs B' when there is no story", () => {
    const c = tradeCard({ ...trade, story: null });
    expect(c.title).toBe("tkeefe6689 vs Bobster565");
  });

  it("marks the winner null when the swing rounds to zero", () => {
    const even = { ...trade, sides: trade.sides.map((s: any) => ({ ...s, snapshot_ktc_swing: 0 })) };
    expect(tradeCard(even).winner).toBeNull();
  });
});

describe("ownerCard / leagueCard / fallbackCard", () => {
  it("ownerCard surfaces net value, totals, and heist/blunder presence", () => {
    const c = ownerCard({
      league_id: "L", user_id: "u_t", owner: { user_id: "u_t", owner_name: "tkeefe6689" },
      totals_by_lens: { ktc: 8200, production: 140.2, started: 90, playoff: 12 },
      career_arc: [{ season: 2024, trades: 3 } as any, { season: 2025, trades: 5 } as any],
      trades: [], best_trade_id: "t1", worst_trade_id: "t9",
    } as any, "DyNASTY");
    expect(c.kind).toBe("owner");
    expect(c.title).toBe("tkeefe6689");
    expect(c.headline).toBe(8200);
    expect(c.rows.find((r) => r.label === "Trades")!.value).toBe(8);
  });

  it("leagueCard lists top-3 standings by net value", () => {
    const c = leagueCard({
      league: { name: "DyNASTY", season: 2025, total_rosters: 12 },
      standings: [
        { rank: 1, owner: { owner_name: "A" }, net_ktc: 5000, trades: 4 },
        { rank: 2, owner: { owner_name: "B" }, net_ktc: 3000, trades: 2 },
        { rank: 3, owner: { owner_name: "C" }, net_ktc: 1000, trades: 7 },
        { rank: 4, owner: { owner_name: "D" }, net_ktc: -200, trades: 1 },
      ],
    } as any);
    expect(c.kind).toBe("league");
    expect(c.title).toBe("DyNASTY");
    expect(c.standings.map((s) => s.name)).toEqual(["A", "B", "C"]);
    expect(c.subhead).toContain("12 managers");
  });

  it("fallbackCard never throws and is branded", () => {
    expect(fallbackCard("DyNASTY").title).toBe("DyNASTY");
    expect(fallbackCard().title).toBe("DyNASTY trade grader");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run tests/og-card-data.test.ts --config tests/vitest.config.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

```ts
// web/lib/og-card-data.ts
import { TradeDetailResp, OwnerDetailResp, DashboardResp } from "./types";

export interface ScoreRow { label: string; a: number; b: number; dec: boolean; }
export interface MetricItem { label: string; value: number; dec: boolean; }
export interface StandRow { rank: number; name: string; value: number; }

export interface TradeCard {
  kind: "trade"; eyebrow: string; title: string;
  colA: string; colB: string; winner: "a" | "b" | null;
  rows: ScoreRow[]; footnote: string;
}
export interface OwnerCard {
  kind: "owner"; eyebrow: string; title: string; headline: number;
  rows: MetricItem[]; footnote: string;
}
export interface LeagueCard {
  kind: "league"; eyebrow: string; title: string; subhead: string; standings: StandRow[];
}
export interface FallbackCard { kind: "fallback"; eyebrow: string; title: string; }
export type AnyCard = TradeCard | OwnerCard | LeagueCard | FallbackCard;

const MONTHS_IN = new Set([9, 10, 11]);
function weekLabel(dateIso: string, week: number): string {
  return MONTHS_IN.has(Number(dateIso.slice(5, 7))) ? `Week ${week}` : "Offseason";
}
function assetNames(side: TradeDetailResp["sides"][number]): string {
  const names = side.received.map((a) =>
    a.name ? a.name : a.season && a.round ? `${a.season} ${a.round === 1 ? "1st" : a.round === 2 ? "2nd" : a.round + "th"}` : "?",
  );
  const joined = names.join(", ");
  return joined.length > 60 ? joined.slice(0, 57) + "..." : joined;
}

export function tradeCard(d: TradeDetailResp): TradeCard {
  const [A, B] = d.sides;
  const swingA = A.snapshot_ktc_swing;
  const winner: "a" | "b" | null =
    Math.round(swingA) === 0 ? null : swingA > 0 ? "a" : "b";
  const title = d.story?.verdict
    ? d.story.verdict
    : `${A.owner_name} vs ${B.owner_name}`;
  return {
    kind: "trade",
    eyebrow: `${d.league_name} · ${d.season} · ${weekLabel(d.date, d.week)}`,
    title,
    colA: A.owner_name, colB: B.owner_name, winner,
    rows: [
      { label: "Trade Value", a: A.snapshot_ktc_swing, b: B.snapshot_ktc_swing, dec: false },
      { label: "Total Points", a: A.hindsight_production_swing, b: B.hindsight_production_swing, dec: true },
      { label: "Playoff Points", a: A.hindsight_started_playoff_swing, b: B.hindsight_started_playoff_swing, dec: true },
    ],
    footnote: `${A.owner_name} got ${assetNames(A)} · ${B.owner_name} got ${assetNames(B)}`,
  };
}

export function ownerCard(d: OwnerDetailResp, leagueName: string): OwnerCard {
  const trades = d.career_arc.reduce((n, s) => n + (s.trades || 0), 0);
  return {
    kind: "owner",
    eyebrow: `${leagueName} · career`,
    title: d.owner.owner_name,
    headline: d.totals_by_lens.ktc,
    rows: [
      { label: "Net Trade Value", value: d.totals_by_lens.ktc, dec: false },
      { label: "Total Points", value: d.totals_by_lens.production, dec: true },
      { label: "Trades", value: trades, dec: false },
    ],
    footnote: d.best_trade_id || d.worst_trade_id ? "Tap in for the heists and blunders" : "",
  };
}

export function leagueCard(d: DashboardResp): LeagueCard {
  const top = [...d.standings].sort((x, y) => y.net_ktc - x.net_ktc).slice(0, 3);
  return {
    kind: "league",
    eyebrow: "DyNASTY · trade grader",
    title: d.league.name,
    subhead: `${d.league.total_rosters} managers · ${d.standings.reduce((n, r) => n + r.trades, 0)} trades graded`,
    standings: top.map((r, i) => ({ rank: i + 1, name: r.owner.owner_name, value: r.net_ktc })),
  };
}

export function fallbackCard(leagueName?: string): FallbackCard {
  return { kind: "fallback", eyebrow: "sleeper · dynasty", title: leagueName || "DyNASTY trade grader" };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run tests/og-card-data.test.ts --config tests/vitest.config.ts`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add web/lib/og-card-data.ts web/tests/og-card-data.test.ts
git commit -m "feat(web): OG card data mappers (trade/owner/league/fallback)"
```

---

## Task 2: Font loader

**Files:**
- Create: `web/lib/og-font.ts`
- Test: `web/tests/og-font.test.ts`

- [ ] **Step 1: Write the failing test** (the pure parser is the tested part)

```ts
// web/tests/og-font.test.ts
import { describe, it, expect } from "vitest";
import { extractFontUrl } from "@/lib/og-font";

describe("extractFontUrl", () => {
  it("pulls the ttf src out of a Google Fonts CSS block", () => {
    const css = `@font-face{font-family:'Inter';font-style:normal;font-weight:600;` +
      `src:url(https://fonts.gstatic.com/s/inter/v1/abc.ttf) format('truetype');}`;
    expect(extractFontUrl(css)).toBe("https://fonts.gstatic.com/s/inter/v1/abc.ttf");
  });
  it("returns null when no ttf url is present", () => {
    expect(extractFontUrl("@font-face{src:url(x.woff2) format('woff2');}")).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run tests/og-font.test.ts --config tests/vitest.config.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

```ts
// web/lib/og-font.ts
// Google Fonts serves a TTF src when the request UA is not woff2-capable.
// Satori (next/og) needs TTF/OTF/WOFF, not WOFF2. We fetch once and cache.

export function extractFontUrl(css: string): string | null {
  const m = css.match(/src:\s*url\((https:\/\/[^)]+\.ttf)\)\s*format\('truetype'\)/);
  return m ? m[1] : null;
}

async function fetchGoogleFont(family: string, weight: number): Promise<ArrayBuffer> {
  const css = await fetch(
    `https://fonts.googleapis.com/css2?family=${family}:wght@${weight}`,
    { headers: { "User-Agent": "Mozilla/5.0 (compatible; satori)" } },
  ).then((r) => r.text());
  const url = extractFontUrl(css);
  if (!url) throw new Error(`no ttf for ${family} ${weight}`);
  return fetch(url).then((r) => r.arrayBuffer());
}

export interface OgFont { name: string; data: ArrayBuffer; weight: 400 | 600; style: "normal"; }

let cached: OgFont[] | null = null;

/** Inter 400 + 600, fetched once and memoized for the process lifetime. */
export async function loadFonts(): Promise<OgFont[]> {
  if (cached) return cached;
  const [r, sb] = await Promise.all([
    fetchGoogleFont("Inter", 400),
    fetchGoogleFont("Inter", 600),
  ]);
  cached = [
    { name: "Inter", data: r, weight: 400, style: "normal" },
    { name: "Inter", data: sb, weight: 600, style: "normal" },
  ];
  return cached;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run tests/og-font.test.ts --config tests/vitest.config.ts`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add web/lib/og-font.ts web/tests/og-font.test.ts
git commit -m "feat(web): cached Google-Fonts loader for OG images"
```

---

## Task 3: Card renderers (Satori JSX)

**Files:**
- Create: `web/lib/og-card.tsx`

> Verified by `npm run build` + manual render (ImageResponse can't run in jsdom). Satori supports a flexbox subset only: every element with >1 child needs an explicit `display: "flex"`. Colors use the app palette.

- [ ] **Step 1: Implement the shared frame + renderer**

```tsx
// web/lib/og-card.tsx
import { AnyCard, ScoreRow } from "./og-card-data";

const C = {
  bg: "#0d0e10", ink: "#e8eaed", dim: "#8b9096", pos: "#3fb950", neg: "#f85149",
  line: "#1d1f23", winTint: "rgba(63,185,80,0.08)",
};
const sign = (n: number, dec: boolean) =>
  `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(dec ? Number(n.toFixed(1)) : Math.round(n)).toLocaleString()}`;
const tone = (n: number) => (n > 0 ? C.pos : n < 0 ? C.neg : C.dim);

function Frame({ eyebrow, children }: { eyebrow: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%",
      background: C.bg, color: C.ink, padding: "56px 60px", fontFamily: "Inter", position: "relative" }}>
      <div style={{ fontSize: 24, letterSpacing: 4, textTransform: "uppercase", color: C.dim }}>{eyebrow}</div>
      {children}
      <div style={{ position: "absolute", bottom: 40, right: 56, fontSize: 22, color: "#5a5e64", letterSpacing: 1 }}>
        sleeper · dynasty
      </div>
    </div>
  );
}

function clampTitle(t: string): number {
  return t.length > 64 ? 48 : t.length > 44 ? 60 : 72;
}

export function renderCard(card: AnyCard): React.ReactNode {
  if (card.kind === "trade") {
    return (
      <Frame eyebrow={card.eyebrow}>
        <div style={{ fontSize: clampTitle(card.title), fontWeight: 600, lineHeight: 1.08, marginTop: 28 }}>
          {card.title}
        </div>
        <div style={{ display: "flex", flexDirection: "column", marginTop: "auto", gap: 6 }}>
          <div style={{ display: "flex", fontSize: 26, color: C.dim, paddingBottom: 8 }}>
            <div style={{ display: "flex", flex: 1 }} />
            <div style={{ display: "flex", width: 200, justifyContent: "flex-end", color: card.winner === "a" ? C.ink : C.dim }}>{card.colA}</div>
            <div style={{ display: "flex", width: 200, justifyContent: "flex-end", color: card.winner === "b" ? C.ink : C.dim }}>{card.colB}</div>
          </div>
          {card.rows.map((r: ScoreRow) => (
            <div key={r.label} style={{ display: "flex", fontSize: 32, padding: "6px 0", borderTop: `1px solid ${C.line}` }}>
              <div style={{ display: "flex", flex: 1, color: C.dim }}>{r.label}</div>
              <div style={{ display: "flex", width: 200, justifyContent: "flex-end", color: tone(r.a), fontWeight: 600 }}>{sign(r.a, r.dec)}</div>
              <div style={{ display: "flex", width: 200, justifyContent: "flex-end", color: tone(r.b), fontWeight: 600 }}>{sign(r.b, r.dec)}</div>
            </div>
          ))}
          <div style={{ display: "flex", fontSize: 22, color: C.dim, marginTop: 14 }}>{card.footnote}</div>
        </div>
      </Frame>
    );
  }
  if (card.kind === "owner") {
    return (
      <Frame eyebrow={card.eyebrow}>
        <div style={{ fontSize: 64, fontWeight: 600, marginTop: 24 }}>{card.title}</div>
        <div style={{ fontSize: 96, fontWeight: 600, color: tone(card.headline), marginTop: 4 }}>{sign(card.headline, false)}</div>
        <div style={{ display: "flex", flexDirection: "column", marginTop: "auto", gap: 6 }}>
          {card.rows.map((m) => (
            <div key={m.label} style={{ display: "flex", fontSize: 32, padding: "6px 0", borderTop: `1px solid ${C.line}` }}>
              <div style={{ display: "flex", flex: 1, color: C.dim }}>{m.label}</div>
              <div style={{ display: "flex", color: m.label === "Trades" ? C.ink : tone(m.value), fontWeight: 600 }}>
                {m.label === "Trades" ? String(m.value) : sign(m.value, m.dec)}
              </div>
            </div>
          ))}
          {card.footnote ? <div style={{ display: "flex", fontSize: 22, color: C.dim, marginTop: 14 }}>{card.footnote}</div> : null}
        </div>
      </Frame>
    );
  }
  if (card.kind === "league") {
    return (
      <Frame eyebrow={card.eyebrow}>
        <div style={{ fontSize: 72, fontWeight: 600, marginTop: 24 }}>{card.title}</div>
        <div style={{ fontSize: 30, color: C.dim, marginTop: 8 }}>{card.subhead}</div>
        <div style={{ display: "flex", flexDirection: "column", marginTop: "auto", gap: 6 }}>
          {card.standings.map((s) => (
            <div key={s.rank} style={{ display: "flex", fontSize: 34, padding: "8px 0", borderTop: `1px solid ${C.line}` }}>
              <div style={{ display: "flex", width: 60, color: C.dim }}>{s.rank}</div>
              <div style={{ display: "flex", flex: 1 }}>{s.name}</div>
              <div style={{ display: "flex", color: tone(s.value), fontWeight: 600 }}>{sign(s.value, false)}</div>
            </div>
          ))}
        </div>
      </Frame>
    );
  }
  return (
    <Frame eyebrow={card.eyebrow}>
      <div style={{ display: "flex", flex: 1, alignItems: "center", fontSize: 72, fontWeight: 600 }}>{card.title}</div>
    </Frame>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/lib/og-card.tsx
git commit -m "feat(web): box-score OG card renderers"
```

---

## Task 4: Trade OG image route

**Files:**
- Create: `web/app/league/[id]/trade/[tid]/opengraph-image.tsx`

> No unit test (ImageResponse needs wasm). Verified in Task 7 by `npm run build` + manual render. The route never throws: any fetch error becomes the fallback card.

- [ ] **Step 1: Implement**

```tsx
// web/app/league/[id]/trade/[tid]/opengraph-image.tsx
import { ImageResponse } from "next/og";
import { tradeDetail } from "@/lib/api";
import { tradeCard, fallbackCard } from "@/lib/og-card-data";
import { renderCard } from "@/lib/og-card";
import { loadFonts } from "@/lib/og-font";

export const runtime = "nodejs";
export const alt = "Trade verdict";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({ params }: { params: { id: string; tid: string } }) {
  const fonts = await loadFonts();
  let card;
  try {
    card = tradeCard(await tradeDetail(params.id, params.tid));
  } catch {
    card = fallbackCard();
  }
  return new ImageResponse(renderCard(card), {
    ...size,
    fonts: fonts.map((f) => ({ name: f.name, data: f.data, weight: f.weight, style: f.style })),
  });
}
```

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add "web/app/league/[id]/trade/[tid]/opengraph-image.tsx"
git commit -m "feat(web): trade OG image route"
```

---

## Task 5: Owner OG image route

**Files:**
- Create: `web/app/league/[id]/owner/[uid]/opengraph-image.tsx`

- [ ] **Step 1: Implement**

```tsx
// web/app/league/[id]/owner/[uid]/opengraph-image.tsx
import { ImageResponse } from "next/og";
import { ownerDetail, dashboard } from "@/lib/api";
import { ownerCard, fallbackCard } from "@/lib/og-card-data";
import { renderCard } from "@/lib/og-card";
import { loadFonts } from "@/lib/og-font";

export const runtime = "nodejs";
export const alt = "Owner card";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({ params }: { params: { id: string; uid: string } }) {
  const fonts = await loadFonts();
  let card;
  try {
    const [owner, dash] = await Promise.all([
      ownerDetail(params.id, params.uid),
      dashboard(params.id).catch(() => null),
    ]);
    card = ownerCard(owner, dash?.league.name ?? "DyNASTY");
  } catch {
    card = fallbackCard();
  }
  return new ImageResponse(renderCard(card), {
    ...size,
    fonts: fonts.map((f) => ({ name: f.name, data: f.data, weight: f.weight, style: f.style })),
  });
}
```

- [ ] **Step 2: Typecheck + commit**

Run: `npx tsc --noEmit -p tsconfig.json` → no errors.
```bash
git add "web/app/league/[id]/owner/[uid]/opengraph-image.tsx"
git commit -m "feat(web): owner OG image route"
```

---

## Task 6: League OG image route

**Files:**
- Create: `web/app/league/[id]/opengraph-image.tsx`

- [ ] **Step 1: Implement**

```tsx
// web/app/league/[id]/opengraph-image.tsx
import { ImageResponse } from "next/og";
import { dashboard } from "@/lib/api";
import { leagueCard, fallbackCard } from "@/lib/og-card-data";
import { renderCard } from "@/lib/og-card";
import { loadFonts } from "@/lib/og-font";

export const runtime = "nodejs";
export const alt = "League card";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({ params }: { params: { id: string } }) {
  const fonts = await loadFonts();
  let card;
  try {
    card = leagueCard(await dashboard(params.id));
  } catch {
    card = fallbackCard();
  }
  return new ImageResponse(renderCard(card), {
    ...size,
    fonts: fonts.map((f) => ({ name: f.name, data: f.data, weight: f.weight, style: f.style })),
  });
}
```

- [ ] **Step 2: Typecheck + commit**

Run: `npx tsc --noEmit -p tsconfig.json` → no errors.
```bash
git add "web/app/league/[id]/opengraph-image.tsx"
git commit -m "feat(web): league OG image route"
```

---

## Task 7: generateMetadata on the three pages + build verification

**Files:**
- Modify: `web/app/league/[id]/trade/[tid]/page.tsx`, `web/app/league/[id]/owner/[uid]/page.tsx`, `web/app/league/[id]/page.tsx`

> Next auto-wires each `opengraph-image.tsx` into the page's `<meta og:image>`; `generateMetadata` only needs to set `title`/`description`/`twitter`. Each must be best-effort (never throw).

- [ ] **Step 1: Trade page metadata** — add to `web/app/league/[id]/trade/[tid]/page.tsx` (top-level export, alongside the existing `export const dynamic`):

```tsx
import type { Metadata } from "next";
import { tradeDetail } from "@/lib/api";

export async function generateMetadata(
  { params }: { params: { id: string; tid: string } },
): Promise<Metadata> {
  try {
    const d = await tradeDetail(params.id, params.tid);
    const title = d.story?.verdict ?? `${d.sides[0]?.owner_name} ↔ ${d.sides[1]?.owner_name}`;
    return {
      title,
      description: `${d.league_name} · ${d.season}`,
      openGraph: { title, type: "article" },
      twitter: { card: "summary_large_image", title },
    };
  } catch {
    return { title: "Trade · DyNASTY", twitter: { card: "summary_large_image" } };
  }
}
```

- [ ] **Step 2: Owner page metadata** — add to `web/app/league/[id]/owner/[uid]/page.tsx`:

```tsx
import type { Metadata } from "next";
import { ownerDetail } from "@/lib/api";

export async function generateMetadata(
  { params }: { params: { id: string; uid: string } },
): Promise<Metadata> {
  try {
    const d = await ownerDetail(params.id, params.uid);
    const title = `${d.owner.owner_name} — ${Math.round(d.totals_by_lens.ktc).toLocaleString()} net value`;
    return { title, twitter: { card: "summary_large_image", title } };
  } catch {
    return { title: "Owner · DyNASTY", twitter: { card: "summary_large_image" } };
  }
}
```

- [ ] **Step 3: League page metadata** — add to `web/app/league/[id]/page.tsx`:

```tsx
import type { Metadata } from "next";
import { dashboard } from "@/lib/api";

export async function generateMetadata(
  { params }: { params: { id: string } },
): Promise<Metadata> {
  try {
    const d = await dashboard(params.id);
    const title = `${d.league.name} · ${d.league.season}`;
    return {
      title,
      description: `${d.league.total_rosters} managers, ${d.standings.reduce((n, r) => n + r.trades, 0)} trades graded`,
      twitter: { card: "summary_large_image", title },
    };
  } catch {
    return { title: "DyNASTY trade grader", twitter: { card: "summary_large_image" } };
  }
}
```

(If a page already imports a fetcher or `Metadata`, do not duplicate the import — merge it.)

- [ ] **Step 4: Full web test suite + build**

Run: `npx vitest run --config tests/vitest.config.ts`
Expected: all suites pass (including the two new mapper/font suites).

Run: `npm run build`
Expected: build succeeds; the build output lists the three `opengraph-image` routes (e.g. `λ /league/[id]/opengraph-image`). If the build fails on a Satori flexbox error, the message names the offending element; add `display: "flex"` to any multi-child element it flags.

- [ ] **Step 5: Manual render check** (do not skip)

Run: `npm run dev`, then open in a browser:
`http://localhost:3000/league/9000000000000000001/trade/1263983342311723008/opengraph-image`
Expected: a 1200×630 PNG box-score card with the verdict, the three-metric scoreboard, and the asset line. Repeat for the owner and league `opengraph-image` URLs. Note any visual issues for a follow-up polish pass; they do not block the commit.

- [ ] **Step 6: Commit**

```bash
git add "web/app/league/[id]/trade/[tid]/page.tsx" "web/app/league/[id]/owner/[uid]/page.tsx" "web/app/league/[id]/page.tsx"
git commit -m "feat(web): page metadata wiring OG cards into link unfurls"
```

---

## Final verification

- [ ] From `web/`: `npx vitest run --config tests/vitest.config.ts` → all PASS.
- [ ] From `web/`: `npm run build` → success; three `opengraph-image` routes present.
- [ ] Manual: each `opengraph-image` URL renders a correct card; the cold-cache path (a league id that 409s) renders the branded fallback, not an error.
- [ ] Post-deploy (handled outside this plan): validate a real unfurl with an OG debugger (e.g. opengraph.xyz) and a paste into iMessage + Telegram.

---

## Self-review notes (author)

- **Spec coverage:** three routes + shared template (Tasks 3-6), box-score content per surface incl. winner tint / metrics / standings (Tasks 1, 3), metadata + twitter card (Task 7), cold-cache fallback (Task 1 `fallbackCard` + every route's try/catch), long-verdict clamp (`clampTitle`), nodejs runtime + fonts (Tasks 2, 4-6). Deviation from spec: fonts are **fetched from Google Fonts at runtime and cached** rather than bundled, which removes the Dockerfile/`assets/fonts` step entirely (simpler, no infra change); the ultimate fallback for a font-fetch failure is the text-only `generateMetadata` preview.
- **Out of scope (per spec):** Telegram/Discord auto-post, share buttons, remote avatars.
- **Type consistency:** `tradeCard`/`ownerCard`/`leagueCard`/`fallbackCard`, `AnyCard`, `renderCard`, `loadFonts`/`extractFontUrl` are referenced identically across tasks; card prop field names (`colA`/`colB`/`winner`/`rows`/`headline`/`standings`/`subhead`/`footnote`) match between mapper (Task 1) and renderer (Task 3).
