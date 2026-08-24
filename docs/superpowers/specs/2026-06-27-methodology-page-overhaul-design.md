# Methodology Page Overhaul — "How the grade is built" — Design

**Date:** 2026-06-27
**Route:** `web/app/methodology/page.tsx` (`/methodology`, the "How it works" tab)
**Status:** Approved design — ready for implementation plan

## Problem

The methodology page is trade-first and stale relative to the shipped product. It opens
with "Five reads on every trade" and only covers the Franchise Rating briefly at the
bottom — yet the **Franchise Rating is now the product's headline verdict**, and the
redesign added a Skill pillar (with a brand-new **lineup-skill** signal) that the page
barely explains. The "Grade" it describes is the demoted Trade Grade, not the Franchise
letter.

We want a **massive overhaul**: a complete, trust-building reference for the whole
platform, organized **top-down from the verdict** so a skeptical league-mate can trace
their Franchise letter all the way down to the box scores. Every number on the page
should be traceable; trust comes from traceability.

## Goals & non-goals

**Goals**
- Teach the whole platform: the Franchise Rating, its pillars and signals, the five trade
  metrics, the became-grade/lineage/timeline, the dashboard columns, how the LLM prose is
  grounded, and the data sources/limits.
- Build trust through a **concrete worked example**: one fictional sample owner whose grade
  is decomposed with internally-coherent numbers as the reader descends.
- Look like one system with the app — reuse the live "Why this grade" visual language
  (diverging contribution bars) and the existing Tailwind token system.

**Non-goals (out of scope)**
- No live/personalized "your grade" mode (deferred; the static page is designed so it
  could slot in later, but we do not wire league data now).
- No backend/engine/rating changes. No new routes. No top-nav label change.
- No mobile-specific redesign beyond the existing responsive patterns.

## Architecture

Single-file rewrite of `web/app/methodology/page.tsx`. The page is a server component
(static content) wrapped in the existing `Shell` + `TopBar activeNav="methodology"`.
Section content is expressed as small **data-driven arrays/subcomponents** (mirroring the
current `METRICS`/`PILLARS` pattern) so the long page stays maintainable and each section
is independently editable.

Layout: a **sticky left in-page table of contents** (the 8 sections, active section
highlighted on scroll) beside a single content rail with a thin vertical "spine" visually
connecting verdict → pillars → signals as one continuous descent.

If interactivity is needed (sticky-TOC scroll-spy, the recurring sample card), factor that
into a small `'use client'` child component; keep the page shell static. Extract the
diverging contribution-bar into a small shared component (e.g.
`web/components/methodology/ContributionBar.tsx`) and, if low-risk, have the live
`OverviewTab` reuse it too (otherwise mirror its markup — do not break OverviewTab).

### Components / files

- `web/app/methodology/page.tsx` — the page; section data arrays; composes the sections.
- `web/components/methodology/MethodologyToc.tsx` (`'use client'`) — sticky TOC + scroll-spy.
- `web/components/methodology/ContributionBar.tsx` — diverging bar (points above/below a
  league-average C), reused for pillar and signal rows.
- `web/components/methodology/SampleOwnerCard.tsx` — the recurring "Marcus" card.
- (Section bodies can be inline subcomponents in `page.tsx` or split per section if a
  section grows large.)

## The sample owner (worked example)

Fictional owner **"Marcus"**, a **B+ at 1,664** (illustrative; numbers are hardcoded and
chosen to be internally coherent, not pulled from live data). The descent shows his grade
assembling. Coherence rule the implementer must honor: `rating = 1500 + SCALE · Σ(w_pillar
· z_pillar)`, `SCALE = 275`; each pillar contribution `= round(SCALE · w_pillar · z_pillar)`;
each signal contribution `= round(SCALE · w_pillar · w_signal · z_signal)`; signal
contributions sum (to rounding) to their pillar's contribution; `1500 + Σ pillar
contributions = rating`.

Worked pillar values for Marcus — **these exact numbers are the source of truth for the
page**:

| Pillar | weight | z (illustrative) | contribution |
|---|---|---|---|
| Results | 0.43 | +0.79 | **+93** |
| Skill | 0.43 | +0.50 | **+59** |
| Outlook | 0.14 | +0.30 | **+12** |

`1500 + 93 + 59 + 12 = 1,664` → **B+** (band ≥ +150). Use **1,664 / B+** consistently
everywhere on the page.

The **Skill** pillar is the showcase; give Marcus illustrative signal rows that sum to +59,
e.g. `trade_value` (w 0.25), `trade_production` (w 0.20), `draft_skill` (w 0.30),
`lineup_skill` (w 0.25) — pick z-values so `Σ round(275·0.43·w_signal·z_signal) ≈ 59`. The
`lineup_skill` row carries a tiny worked mini-example (below).

## Page sections (top-down)

Exact, engine-accurate content. Weights/bands are pinned; do not paraphrase them wrong.

1. **The verdict — the Franchise letter.** The letter is the platform-wide owner verdict.
   It is a number centered at **1,500** (exactly league-average = a **C**), clamped
   **800–2,200**, mapped to a letter by fixed bands, **all-time** (not year-scoped), and
   **league-relative** (z-scored within your league — a B in one league ≠ a B in another).
   Letter bands (delta from 1500, inclusive lower bound): A+ ≥ +340, A ≥ +270, A− ≥ +210,
   B+ ≥ +150, B ≥ +100, B− ≥ +60, C+ ≥ +20, C ≥ −20, C− ≥ −60, D+ ≥ −100, D ≥ −150,
   D− ≥ −210, else F. Introduce Marcus.

2. **The three pillars.** A franchise is measured by its **Results**; **Skill** is the
   engine that produces them; **Outlook** is where it's headed.
   - **Results — 0.43** — what the franchise has achieved.
   - **Skill — 0.43** — how well the owner operates it (trades, drafts, weekly lineups).
   - **Outlook — 0.14** — future health.
   Render Marcus's three pillar contributions as diverging bars (the live "Why this grade"
   visual). One line on *why two equal axes*: results are noisy in fantasy (schedule/playoff
   luck), so skill — measured over far more events — is an equally-weighted, more stable read.

3. **Inside each pillar — the signals.** For every signal: plain-English definition + how
   it's measured + Marcus's `raw → z → contribution`.
   - **Results signals:** `championships` (w 0.35), `playoff_depth` (rounds won, 0.25),
     `made_playoffs` (rate, 0.15), `final_seed` (avg inverted, 0.15), `points_for_rank`
     (avg inverted, 0.10).
   - **Skill signals (the showcase):**
     - `trade_value` (0.25) — did you win the deal on dynasty market value? Zero-sum swing
       per trade, **averaged** across your trades (not summed — volume ≠ skill), shrunk
       toward neutral for small samples (`n/(n+2)`), so a non-trader sits neutral.
     - `trade_production` (0.20) — did it pan out on the field? Per-trade head-to-head of
       what each side's received assets actually scored, recentered to zero-sum, same
       averaging + shrinkage.
     - `draft_skill` (0.30) — how your rookie picks panned out vs their draft slot.
     - `lineup_skill` (0.25) — **NEW, give it the most room.** Did you start your best
       players? Weekly optimal lineup vs what you actually started, summed across every
       roster-week: `efficiency = Σ actual-started / Σ optimal`. Include a tiny worked
       mini-example for Marcus: a week where the optimal lineup scored e.g. 142 but he
       started 128 → 14 points left on the bench; rolled up across the season into his
       efficiency number.
   - **Outlook signals:** `roster_value` (0.45), `draft_capital` (tier-adjusted value of
     held future picks, 0.30), `youth` (negated avg age, 0.25).

4. **The raw materials — the five trade metrics.** Skill leans on trades, so define them
   here with formulas. **Trade Value is a zero-sum swing; the four production metrics are
   received-only tallies.**
   - **Trade Value** — `Σ realized value of received assets` (today's dynasty market value).
   - **Total Points** — `Σ received pts post-trade` (bench included).
   - **Regular Season Points** — `Σ received started reg-season pts`.
   - **Playoff Points** — `Σ received started title-bracket pts` (byes/eliminated/placement
     games = 0; most predictive).
   - **Toilet Bowl Points** — `Σ received started losers-bracket pts`.
   Then a short "**how a trade's real outcome is traced**" block: the **asset journey**
   (kept / dropped / **flipped**), the **became-grade** (the same five metrics recomputed on
   the *terminal* players your haul turned into via a bounded lineage walk), the **"did it
   pan out" production timeline** (cumulative production over tenure, chain-aware), and
   **injury context** (games missed by phase). Keep this tight — one paragraph + small list.

5. **The math.** Each signal is **z-scored across your league** before weighting (puts
   Trade Value and fantasy points on one scale); a pillar's z is the weighted sum of its
   signal z's; the composite is the weighted sum of pillar z's;
   `rating = clamp(1500 + 275 · Σ(weight_pillar · z_pillar), 800, 2200)`. Show Marcus's
   final assembly (`1500 + 93 + 59 + 12 = 1,664 → B+`). Note **Total Points stays out of
   the rating** (it's visible per trade but the rating rewards production that hit a lineup),
   and the ▲▼ on the board is rank change vs the most recent earlier NFL week on file.

6. **The supporting columns** (dashboard stats *not* in the rating).
   - **Window** — dynasty stage from Strength (60% Trade-Value roster rank + 40% all-time
     playoff rate) × Trajectory (40% draft skill + 30% draft-capital value + 15% youth +
     15% year-over-year momentum). Stages: Competing now · Peaking · Ascending · Descending
     · Rebuilding.
   - **Draft Capital** — `Σ value(held future picks, tier-adjusted)`; weaker teams' earlier
     picks worth more; always today's holdings.
   - **Trade Grade** — **distinct from the Franchise letter.** A letter from your *realized
     Trade Value* z-scored vs leaguemates (A ≥ +1.25σ · A− ≥ +0.75σ · B+ ≥ +0.25σ · B ≈ 0 ·
     B− ≥ −0.75σ · C ≥ −1.25σ · D below). Call out explicitly that this grades *trading
     only* and is not the platform verdict.
   - **Record / finishes & standings** — as-of-week regular-season standings reconstructed
     from each roster-week's points, self-validated against Sleeper's record.

7. **How the words are written.** The trade verdicts/stories and the per-pillar GM
   highlights are LLM-written but **grounded**: the model is fed the exact facts above and
   instructed to use only them (and "KTC" is deterministically scrubbed). A trust point:
   the prose narrates the numbers, it doesn't invent them. One short paragraph.

8. **Data sources & limitations.** Sources: Sleeper API (league chain, trades, matchups,
   drafts), KeepTradeCut (dynasty market values), FantasyCalc (fallback). Limitations:
   inactive/retired players absent from value sources default to 0 (can distort old
   grades); older Sleeper data missing `draft_order` falls back to a heuristic; waivers not
   graded; market-value history only goes back a limited window. Keep the existing
   GitHub/back-home footer.

## Visual treatment

- **Sticky left TOC** with scroll-spy highlighting the active section.
- **Vertical spine** down the content rail connecting verdict → pillars → signals.
- **Diverging contribution bars** (points above/below a league-average C) for pillar and
  signal rows — same idiom as the live "Why this grade."
- **Recurring sample-owner card** ("Marcus — B+ — 1,664; Results +93 · Skill +59 · Outlook
  +12") pinned at the top of sections 1–5 so the thread is never lost.
- **Signal rows**: definition + mono formula chip + `raw → z → contribution`. The
  `lineup_skill` row includes the optimal-vs-actual mini-example.
- Existing Tailwind tokens (`--bg/--ink/--pos/--neg/--dim/--surface/--divider`), light +
  dark. No new design language — a richer application of the current one.
- Hero: **"How the grade is built"** with the line "Every number on this page traces back
  to the box scores." (Replaces "Five reads on every trade.")

## Testing

- Vitest (`web/tests/Methodology.test.tsx` or extend existing): the page renders all 8
  section headings; the pillar weights read **43% / 43% / 14%**; the sample owner's
  headline (B+ / 1,664) and the three pillar contributions (+93 / +59 / +12) are present;
  the `lineup_skill` section renders; no "KTC" string appears anywhere on the page.
- `cd web && npm run build` (catches missing `'use client'` / RSC issues) — ensure no
  `next dev` is running against the tree.

## Accuracy checklist (hard requirement)

Before done, cross-check every pinned value against the engine: pillar weights
(`REDESIGN_PILLAR_WEIGHTS["equal_axes"]` = 0.43/0.43/0.14), signal weights
(`REDESIGN_SIGNAL_WEIGHTS`), BASE/SCALE/CLAMP (1500/275/800–2200), `LETTER_BANDS`, the five
trade-metric definitions (CLAUDE.md "Five metrics"), and the Trade Grade z-buckets
(`aggregations.py::_letter_grade`). Never render "KTC" as a user-facing term.
