# Trade Page Redesign — Design Spec

**Date:** 2026-06-25
**Branch:** `trade-redesign`
**Status:** Approved design, pre-implementation

## Goal

Make the trade detail page tell the *ongoing story* of a trade in a sharp,
ESPN-style, head-to-head format. Replace today's plain LLM paragraph with a
scannable hero (a clear "call," data callouts, and formatted narrative), keep
the loved "Did it pan out?" chart, and reframe the receipts around a new
**Started vs Total + deployment %** lens.

Today's page (`web/app/league/[id]/trade/[tid]/page.tsx`):
`TradeStory` (verdict h1 + paragraph body) → "Show the receipts" → grid of
`TradeSidePanel`/`TradeStatTable` → `TradeProductionCard` (the chart).

## Non-goals / deferred

- **Full Owner Point Start% surface** (aggregate deployment efficiency across all
  acquired players, possible GM-rating signal) is a **separate owner-page
  sub-project**, not in this spec. This page only *borrows one number* per side.
- No change to the cold-start contract, refresh cadence, or the skip-hash bands.
- No new value lens beyond surfacing existing at-trade value when present.

## The three zones

### Zone 1 — Hero (replaces the plain blurb)

A single hero block at the top of the page, in the app's real palette
(Instrument Serif headline, mono labels, `--pos`/`--neg`/`--accent`).

1. **Matchup bar** — both owners head-to-head: avatar, name, seed + record,
   winner tagged `▲ Winner`. Winner name in `--pos`. (Two-party trades; for 3+
   party trades, fall back to a stacked list — winner still tagged.)
2. **Call badge** — `LOPSIDED` / `EDGE` / `TOO CLOSE` / `TOO EARLY`, derived
   **deterministically** from existing `lopsidedness` bands (≥0.6 lopsided,
   0.3–0.6 edge, <0.3 too close; "too early" when production is a wash and value
   is the only signal). Not LLM-authored.
3. **Verdict headline** — LLM-authored, one line, Instrument Serif.
4. **Data callouts** — three cards, **engine-computed, never LLM**:
   - *Started points margin* (winner +N) — the default "what counted" call
   - *Trade Value · today* (winner +N)
   - *The twist* — a notable lineage/deployment fact (dropped asset, low start%,
     flip), chosen by a small deterministic selector. Both the fact and its short
     label are engine-derived; no LLM involvement.
   - When at-trade value exists (post-May-2026 trade), show it as a secondary
     line under the Trade Value callout; omit otherwise.
5. **Story** — LLM-authored, **structured**: a bold `lede` sentence + 2–4
   scannable `›` `beats`. Replaces the paragraph body.

### Zone 2 — "Did it pan out?" chart (kept)

`TradeProductionCard` / `ProductionTimeline` essentially unchanged, except:
- **Default lens = Started** (what counted), not Total.
- Toggle = `Started · Total · Regular · Playoff · Toilet` (Started added; Total
  labeled "+bench").
- Playoff bands, OUT bands, drop/trade markers unchanged.

### Zone 3 — Receipts, head-to-head (winner shaded)

Two side panels side by side (`grid-cols-1 sm:grid-cols-2`), winner panel tinted
`--pos`. Each panel is a **lean table**:

Columns: **Player · Value · Total · Started · %**

- `%` = `Started ÷ Total` (deployment) per row and on the totals.
- **Nested lineage rollup** (preserve today's behavior): a flipped pick expands
  to its became-players with a **became-subtotal** line, and then the bottom
  **Total realized** row sums everything the side ended up with (kept assets +
  became-players). The deployment % "keeps" through the lineage — a pick flipped
  for 2 players folds both into the side's % .
- Per-side header carries a **% badge** ("85% started").
- **Phase points (Regular/Playoff/Toilet) are NOT table columns** — they live in
  the chart (side-level) + the timeline's playoff bands.
- `for <given>` exchange footer retained.

## Engine / data changes

### New metric: `production_started`

`production_total` is bench-inclusive (all weeks); `production_regular/playoff/
toilet` are started-only *by phase*. Their sum is **not** started-all (placement/
consolation started weeks fall outside all three buckets).

Add `production_started = _points_while_owned(starters_only=True)` with **no
phase filter** (all weeks, starters only) in `engine/trade_grader.py` — alongside
the existing four. One additional call per asset in `build_asset_breakdown` and
`grade_trade`. Add `production_started` to `TradeGrade`, `AssetLine`, and the
trade-detail API/response shapes.

### Deployment % rollup

Per side: `start_pct = production_started / production_total` (guard /0 → null
when total is 0). Computed over **realized/terminal** assets so flipped picks'
became-players contribute (reuse the existing lineage rollup in
`api/app/services/trade_view.py` + `engine/lineage.py`). Per-row % for player
rows; subtotal % on became-subtotals; overall % on the Total-realized row.

### Data-driven callouts

Compute callout values server-side (engine/API), surfaced on the trade-detail
response:
- `started_margin` (winner + value) from `production_started`
- `value_margin` from `received_ktc` (today's realized value, already computed)
- `twist` — a small deterministic selector (e.g., highest-value dropped asset,
  or lowest start% side) returning `{kind, label, detail}`.
- `at_trade_value` swing per side when `at_trade.py` has a snapshot for the date.

## LLM changes

The writer stays (Haiku, grounded facts). **Output shape changes** from
`{verdict, body}` to **structured** `{verdict, lede, beats[]}`:

- `models/trade_story.py` — story result gains `lede: str`, `beats: list[str]`.
  **Keep `body`** as a backward-compat fallback so stories cached before the
  regen still render (FE prefers `lede`+`beats`, falls back to `body`). Facts
  packet unchanged in spirit; persona instructs the new structure (headline + one
  lede + 2–4 beats, each a single grounded sentence).
- `llm/trade_story_writer.py::parse_story` — parse the structured output (the
  model returns labeled sections or a small JSON; prefer a forced structured
  format). `sanitize_prose` + `repair_prose` run over verdict, lede, and each
  beat.
- `llm/story_validation.py::find_violations` — run over the concatenation of
  verdict + lede + beats (direction reversal, epithet, headline length checks all
  still apply). The deterministic backstop + regeneration loop are preserved.
- `api/app/services/story_gen.py::STORY_PROMPT_VERSION` — **bump** (forces a
  one-time regen of all stories into the new shape on next refresh).

The **call badge** and **callout numbers** are NOT in the LLM output — they are
engine-derived (see above).

## Frontend changes

- New `web/components/TradeHero.tsx` — matchup bar + call badge + verdict +
  callouts + lede/beats. Consumes structured story + callout data.
- `web/components/TradeStory.tsx` — becomes structured (renders lede + beats), or
  is absorbed into `TradeHero`.
- `web/components/TradeStatTable.tsx` — new columns (Value · Total · Started · %),
  per-side % badge, retain nested became-subtotal + total-realized; drop the
  Reg/Ply/Toi columns.
- `TradeProductionCard` — default lens Started; add Started toggle pill.
- `web/app/league/[id]/trade/[tid]/page.tsx` — recompose: Hero → chart → receipts
  (receipts no longer hidden behind "Show the receipts").
- `lib/types.ts` — story shape (`lede`, `beats`), `production_started`,
  `start_pct`, callout fields.

## Testing

- **Engine:** unit-test `production_started` (starters-only, all weeks; verify it
  ≠ reg+playoff+toilet when a placement started week exists) and the start%
  rollup through a flipped-pick-became-multiple-players lineage (the % "keeps").
- **API:** trade-detail response carries `production_started`, `start_pct`,
  callouts, at-trade value.
- **LLM:** `parse_story` handles the structured shape; `find_violations` runs
  over verdict+lede+beats; story_gen regenerates on the version bump.
- **Frontend:** `next build` (RSC/'use client'); the hero renders verdict/lede/
  beats; the receipts table shows Started/% and the nested rollup.

## Rollout

- `STORY_PROMPT_VERSION` bump → one-time regen of all trade stories into the new
  structured shape on next refresh (Haiku cost, one-time; same pattern as prior
  bumps). Deploy + force-refresh to verify.
- Engine metric + FE are backward-compatible reads; old cached stories without
  `lede/beats` should degrade gracefully (render verdict + body fallback until
  regen completes).

## Open decisions (defaults chosen; flag at review)

- Verdict typeface: **Instrument Serif** (on-brand) vs sharp bold sans. Default:
  serif.
- Exact 3 callouts: **Started margin / Trade Value / Twist**. Default as listed.
- `%` label wording: "85% started" vs "deployed". Default: "started".
- Whether per-row % shows on individual players or only on totals. Default: show
  per row + totals (can hide later if noisy).
