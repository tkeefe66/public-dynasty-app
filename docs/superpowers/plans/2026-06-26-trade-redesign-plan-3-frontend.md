# Trade Redesign — Plan 3: Frontend (ESPN hero + Started/% receipts)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. This plan touches `web/` — after FE edits, ALWAYS run `cd web && npm run build` (tsc + vitest miss missing `'use client'`; only `next build` catches RSC/client errors). Do NOT run `next build` while a `next dev` server is live (corrupts `web/.next`).

**Goal:** Render the redesigned trade page: an ESPN-style hero (matchup bar + deterministic call badge + engine-computed callouts + structured verdict/lede/beats) replacing the plain blurb; the kept "Did it pan out?" chart defaulting to the **Started** lens; and head-to-head receipts whose lean table shows **Value · Total · Started · %** with the deployment % rolling through the flip lineage.

**Architecture:** Consume the Plan 1 + Plan 2 backend (`production_started`, `start_pct`, `twist`, `lede`, `beats`). Add a `started` cumulative line to the production-series payload so the chart can default to it. New `TradeHero` component owns the top of the page; `TradeStatTable` is restructured; the page is recomposed Hero → chart → receipts (receipts no longer hidden behind "Show the receipts").

**Tech Stack:** Next.js 14 (App Router, RSC), TypeScript, Tailwind against `globals.css` tokens, vitest + Testing Library; Python engine for the series payload.

## Global Constraints

- Design tokens (verbatim, from `web/app/globals.css`): `--bg #fafaf7`, `--surface #fff`, `--ink #0e0e0e`, `--dim #6b6b6b`, `--divider #e5e5e0`, `--pos #15803d`, `--neg #b91c1c`, `--info #2563eb`, `--accent #7c3aed`. Fonts: Geist Sans (body), Geist Mono (labels), Instrument Serif (display). Light + dark; never hardcode colors — use the Tailwind token classes already in use (`text-pos`, `bg-surface`, `text-dim`, etc.).
- **Never show "KTC"** — it is "Trade Value" / "Value".
- The **call badge** is deterministic from `lopsidedness` bands: `>= 0.6` → "LOPSIDED", `0.3–0.6` → "EDGE", `< 0.3` → "TOO CLOSE", and when production is the only signal and it's early → "TOO EARLY". NOT LLM-authored.
- **Callout numbers are engine-derived, never from the LLM.** Started margin = winner's `production_started` − loser's; Value margin = winner's `received_ktc` − loser's; the twist comes from the API `twist` object. At-trade value shows only when present.
- The chart default lens is **Started**; the toggle is `Started · Total · Regular · Playoff · Toilet`.
- Receipts table columns: **Player · Value · Total · Started · %**; `%` = started ÷ total (per row, became-subtotal, and total-realized). Preserve the nested **became-subtotal** then **total-realized** rollup. Phase points (Reg/Playoff/Toilet) are NOT table columns — they live in the chart.
- Back-compat: old cached stories have only `verdict`/`body` (no lede/beats) until the v5 regen — `TradeHero` must render `body` as a fallback when `beats` is empty. Bump `ChainCache` `SCHEMA_VERSION` so the new graded fields (`production_started`, etc.) are present after deploy rather than served as 0 from stale cache (see the schema-migration hazard).
- After any `web/` change run `cd web && npm run build`. Commit after each task. Branch: `trade-redesign`.

---

### Task 1: Backend — `started` cumulative line in the production-series payload

**Files:**
- Modify: `src/sleeper_dynasty/engine/grader.py` (`compute_production_series_payload`)
- Modify: `web/lib/types.ts` (`ProductionMetric` :408)
- Modify: `web/components/ProductionTimeline.tsx` (`METRICS` :17, `METRIC_LABEL` :18)
- Test: `tests/test_grader_series.py` (or the existing series test module — find it)

**Interfaces:**
- Produces: every per-side series map gains a `"started"` key (cumulative started-only points by week), so `byMetric["started"]` exists. `ProductionMetric` includes `"started"`.

- [ ] **Step 1: Find the series builder + its test.** Run `grep -rn "def compute_production_series_payload" src/` and open it; run `grep -rln "production_series\|compute_production_series" tests/` to find the test module. Read how it builds the `total`/`regular`/`playoff`/`toilet` cumulative lines (it sums per-week started points per phase; `total` is bench-inclusive).

- [ ] **Step 2: Write the failing test.** In the series test module, add a test asserting the payload includes a `"started"` line and that it equals starters-only across all weeks (≥ any single phase, ≤ total). Model it on the existing series test's fixtures (reuse them — do not invent a new matchup fixture). Assert `"started" in series[uid]` and that the final cumulative `started` value equals the sum of started points across all weeks (not bench).

- [ ] **Step 3: Run it, confirm it fails** (`"started"` key missing). `.venv/bin/python -m pytest <series_test> -v`.

- [ ] **Step 4: Implement.** In `compute_production_series_payload`, add a `started` cumulative line computed starters-only with NO phase filter (mirror how `regular`/`playoff`/`toilet` are built, dropping the phase gate — the same `starters_only=True` per-week basis used by `production_started` in `trade_grader.py`). Add `"started"` to whatever metric list/keys the function emits.

- [ ] **Step 5: Add `"started"` to the FE type + chart toggle.**
  - `web/lib/types.ts:408`: `export type ProductionMetric = "started" | "total" | "regular" | "playoff" | "toilet";`
  - `web/components/ProductionTimeline.tsx:17`: `const METRICS: ProductionMetric[] = ["started", "total", "regular", "playoff", "toilet"];`
  - `METRIC_LABEL` (`:18`): add `started: "Started"` (keep the others; consider labeling `total: "Total"` — the toggle already shows these).

- [ ] **Step 6: Run engine test (green) + `cd web && npm run build`.** Expected: engine PASS; build succeeds (the new union member is exhaustive across `byMetric` usages — fix any TS exhaustiveness error the build surfaces).

- [ ] **Step 7: Commit.** `git add -A && git commit -m "feat(series): add started cumulative line + chart lens"`

---

### Task 2: FE types — structured story + deployment fields

**Files:**
- Modify: `web/lib/types.ts` (`TradeStory` :377; the trade side type with breakdown/AssetLine; the trade detail response type — add `twist`)
- Test: covered by `npm run build` (type-only) + downstream component tests

**Interfaces:**
- Produces: `TradeStory` gains `lede: string` and `beats: string[]`; the side type gains `production_started: number` and `start_pct: number | null`; the AssetLine type gains `production_started: number`; the detail response gains `twist?: { kind: string; owner: string; label: string; detail: string } | null`.

- [ ] **Step 1: Read `web/lib/types.ts`** around the `TradeStory`, trade-side, `AssetLine`, and trade-detail-response interfaces to get exact names.

- [ ] **Step 2: Add the fields** (defaults/optionals so old payloads still type-check):

```ts
export interface TradeStory {
  verdict: string;
  lede?: string;
  beats?: string[];
  body: string;
  generated_at?: string | null;
}
```
Add to the trade side interface: `production_started: number;` and `start_pct: number | null;`. Add to the `AssetLine` interface: `production_started: number;`. Add to the trade-detail response interface:
```ts
  twist?: { kind: string; owner: string; label: string; detail: string } | null;
```

- [ ] **Step 3: `cd web && npm run build`** — confirm types compile (no consumer breaks; new optional fields).

- [ ] **Step 4: Commit.** `git commit -am "feat(types): structured story + deployment + twist fields"`

---

### Task 3: `TradeHero` component

**Files:**
- Create: `web/components/TradeHero.tsx`
- Test: `web/tests/TradeHero.test.tsx`
- Reference: the approved mockup in `docs/superpowers/specs/2026-06-25-trade-page-redesign-design.md` (Zone 1) and the brainstorm mockup `espn-hero-v2`.

**Interfaces:**
- Consumes: `story` (`{verdict, lede?, beats?, body}`), the two sides (`owner_name`, `avatar_url`, `at_trade_standing`, `production_started`, `received_ktc`, `start_pct`), `lopsidedness`, `winner_user_id`, `twist`.
- Produces: `export function TradeHero(props): JSX` — matchup bar, call badge, verdict headline, callout row, lede + beats.

- [ ] **Step 1: Write the render test (vitest + Testing Library).** Assert, from props: the verdict headline renders; the call badge text matches the lopsidedness band (e.g. `lopsidedness: 0.8` → "Lopsided"); both owner names render in the matchup; the winner is marked; the Started-margin and Value-margin callouts render with the computed numbers; the twist detail renders when `twist.kind !== "none"`; beats render as list items when present; and when `beats` is empty the `body` fallback renders.

- [ ] **Step 2: Run it, confirm it fails** (component doesn't exist). `cd web && npm run test -- TradeHero`.

- [ ] **Step 3: Implement `TradeHero`.** Pure presentational (no data fetching). Compute deterministically in-component: the call badge from `lopsidedness` (bands per Global Constraints); started margin = winner.production_started − loser.production_started; value margin = winner.received_ktc − loser.received_ktc (winner = side whose `user_id === winner_user_id`, or "even" when null). Render matchup bar (avatar via `avatar_url` with a neutral fallback, name, `at_trade_standing` seed/record, winner tag), badge, verdict (Instrument Serif via the existing display-font class), 2–3 callout cards (started, value, twist), then `lede` + `beats` (bullets); when `beats?.length` is falsy, render `body` split on blank lines (as the current `TradeStory` does). Use token classes only. Match the spec mockup's structure; you have latitude on exact spacing/classes consistent with the app.

- [ ] **Step 4: Run the test (green) + `cd web && npm run build`.**

- [ ] **Step 5: Commit.** `git commit -am "feat(web): TradeHero — matchup, call badge, callouts, structured story"`

---

### Task 4: Restructure `TradeStatTable` — Value/Total/Started/% with realized rollup

**Files:**
- Modify: `web/components/TradeStatTable.tsx`
- Test: `web/tests/TradeStatTable.test.tsx` (create or extend)

**Interfaces:**
- Consumes: side breakdown rows (each with `ktc`, `production_total`, `production_started`, optional `flip.became[]`), side `start_pct`.
- Produces: a lean table — header `Player · Value · Total · Started · %`; per-row %; nested flipped-asset `became`-subtotal then a `Total realized` row; a per-side `% started` badge. Reg/Playoff/Toilet columns removed.

- [ ] **Step 1: Read the current `TradeStatTable.tsx`** (it currently renders Value/Tot/Reg/Ply/Toi with the InfoTooltip headers and the became/flip journey). Note `realizedTotals` and the became-subtotal rendering already exist.

- [ ] **Step 2: Write/extend the vitest test.** With a side that has a kept player (started/total) and a flipped pick whose `became` has two players, assert: the header shows Value/Total/Started/% (and NOT Reg/Playoff/Toilet); a per-row % renders (started÷total); the became-subtotal row sums the two became players; the `Total realized` row's % equals (Σ started)/(Σ total) over the realized set; the side % badge matches.

- [ ] **Step 3: Run it, confirm it fails.**

- [ ] **Step 4: Implement.** Replace the metric columns with `Value · Total · Started · %`. Compute `%` = `production_started / production_total` per row (blank/"—" when total 0). Keep the existing flip journey (became rows + became-subtotal) but show the new columns; keep `realizedTotals` for the `Total realized` row and compute its % from realized started/total. Update the `InfoTooltip` header copy to the new columns (Value, Total incl. bench, Started, % started). Add the per-side `% started` badge in the panel header. Remove `production_regular/playoff/toilet` columns.

- [ ] **Step 5: Run the test (green) + `cd web && npm run build`.**

- [ ] **Step 6: Commit.** `git commit -am "feat(web): receipts table — Value/Total/Started/% with realized rollup"`

---

### Task 5: Chart default lens = Started

**Files:**
- Modify: `web/components/TradeProductionCard.tsx` (`useState<ProductionMetric>("total")` :25)
- Test: extend an existing TradeProductionCard/ProductionTimeline test if present, else `npm run build` + a focused render test.

- [ ] **Step 1: Write/extend a test** asserting the card defaults to the `started` metric (the Started toggle is active on first render, and the `started` series is charted).

- [ ] **Step 2: Run it, confirm it fails** (defaults to "total").

- [ ] **Step 3: Implement.** Change the default to `useState<ProductionMetric>("started")`. Confirm `verdict?.[metric]` and `byMetric[metric]` handle `"started"` (the series from Task 1 provides it; the verdict map may not have a "started" entry — guard so a missing verdict key renders nothing rather than crashing).

- [ ] **Step 4: Run test (green) + `cd web && npm run build`.**

- [ ] **Step 5: Commit.** `git commit -am "feat(web): chart defaults to the Started lens"`

---

### Task 6: Page recompose + cache schema bump

**Files:**
- Modify: `web/app/league/[id]/trade/[tid]/page.tsx`
- Modify: `web/components/TradeStory.tsx` (delete or reduce — its role moves into `TradeHero`)
- Modify: `api/app/services/chain_cache.py` (`SCHEMA_VERSION`)
- Test: `cd web && npm run build`; backend `cd api && ../.venv/bin/python -m pytest tests/test_trade_view_story.py -q`

**Interfaces:**
- Produces: the page renders `TradeHero` (replacing the `TradeStory` verdict/body block) → the chart → the receipts (head-to-head, no longer collapsed).

- [ ] **Step 1: Read the current `page.tsx`** (it wraps the side panels + chart inside `TradeStory`'s "Show the receipts" details).

- [ ] **Step 2: Recompose.** Render `TradeHero` (passing story, sides, lopsidedness, winner_user_id, twist) at the top; then the `TradeProductionCard` chart; then the receipts grid of `TradeSidePanel`/`TradeStatTable` directly (remove the `<details>`/"Show the receipts" wrapper). Remove the `TradeStory` wrapper usage. Keep the breadcrumb + meta line.

- [ ] **Step 3: Handle `TradeStory.tsx`.** If nothing else imports it, delete it; otherwise reduce it to whatever still uses it. Verify with `grep -rn "TradeStory" web/`.

- [ ] **Step 4: Bump cache schema.** In `api/app/services/chain_cache.py`, increment `SCHEMA_VERSION` (so post-deploy reads re-grade and include `production_started` rather than serving 0 from stale entries). This pairs with the v5 story regen on first refresh.

- [ ] **Step 5: `cd web && npm run build`** (the integration check — catches any `'use client'`/RSC error from the new component tree) + run the backend trade_view test.

- [ ] **Step 6: Commit.** `git commit -am "feat(web): recompose trade page (hero -> chart -> receipts); bump cache schema"`

---

## Self-Review

**Spec coverage:** hero (matchup/badge/callouts/lede+beats) → Task 3; chart default Started + started series → Tasks 1+5; receipts Value/Total/Started/% with rollup → Task 4; page recompose → Task 6; FE types → Task 2; cache migration → Task 6. Engine-computed callouts (started/value margins from data, twist from API) → Task 3 (computed in-component from props, no LLM). Back-compat body fallback → Task 3.

**Placeholder scan:** Tasks 1, 4, 5 say "find/read the existing test/file" rather than pasting full current source — acceptable because the implementer must read real current code (it's large and evolving) and the *new* behavior + assertions are specified concretely. FE component styling references the approved mockup rather than dictating every Tailwind class — intentional: pixel-class dictation would be guessing, and the tokens/structure are constrained in Global Constraints. No TBD/TODO.

**Type consistency:** `ProductionMetric` gains `"started"` (Task 1) used by the chart (Task 5); `TradeStory.lede?/beats?`, side `production_started`/`start_pct`, AssetLine `production_started`, response `twist` (Task 2) are consumed by `TradeHero` (Task 3) and `TradeStatTable` (Task 4) with matching names/types.

**Deploy:** ships together — `SCHEMA_VERSION` bump (re-grade for `production_started`) + the Plan-2 `STORY_PROMPT_VERSION`=5 regen happen on the first post-deploy refresh. Force-refresh after deploy to verify (story regen needs a refresh, per the cache-migration + story-version notes).
