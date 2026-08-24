---
target: web/components/OwnerDeepDive.tsx (owner franchise page)
total_score: 22
p0_count: 1
p1_count: 3
timestamp: 2026-07-10T12-54-44Z
slug: web-components-ownerdeepdive-tsx
---
Method: dual-agent (A: aa513061447521805 · B: ad7e182aec9b8ba1a)
*Code-level critique. Browser inspection/overlay injection skipped: no dev server running and the app is login-gated (NextAuth). Detector ran deterministically; run is dual-agent, not degraded.*

**Target:** owner franchise page — `web/components/OwnerDeepDive.tsx` + `web/components/ownerdeepdive/` children (HeroBand, OverviewTab, TrackRecordTab, TradesTab, FutureDraftTab, PastPicksTable) and composed shared UI.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 1 | No `loading.tsx` anywhere in `web/app` on a `force-dynamic` server-fetched route — arrival is dead air; no skeletons despite the register's explicit bar |
| 2 | Match System / Real World | 3 | League vocabulary is superb ("Best heist," "Toilet Bowl," rings) — but the page speaks second person ("your trades") to viewers usually looking at someone else's franchise |
| 3 | User Control and Freedom | 2 | `?tab=` deep-link reads in (`page.tsx:29-32`) but `setTab` never writes back — back button and copy-link lose state |
| 4 | Consistency and Standards | 2 | Three chip dialects for the same single-select control; tooltips on one table's headers, not the other's; four duplicated `ordinal`/`ord` helpers |
| 5 | Error Prevention | 3 | Read-only surface; tab param whitelisted — little to prevent |
| 6 | Recognition Rather Than Recall | 2 | Trades ledger headers (`Value/Total/Reg/Playoff/Toilet`) unexplained; "Avg Pick Value" column is mislabeled (shows a delta) |
| 7 | Flexibility and Efficiency | 2 | Year filter + metric toggles + whole-row links are good; no column sorting, no keyboard shortcuts, no shareable filtered state |
| 8 | Aesthetic and Minimalist Design | 3 | Genuinely restrained hierarchy (letter → rings → tabs); docked for 9px labels and an orphan fifth stat tile at tablet width |
| 9 | Error Recovery | 1 | `catch {}` in `page.tsx:37-48` collapses 409 cold-cache / 401 / 500 into "Franchise not found." — actively misleading, no retry |
| 10 | Help and Documentation | 3 | InfoTooltips, rating footnote, RatingReceipt explainer — right level for insiders |
| **Total** | | **22/40** | **Acceptable — significant improvements needed before users are happy** |

## Anti-Patterns Verdict

**Does this look AI-generated? No.**

**LLM assessment (Assessment A):** Passes the product slop test — a Linear/Stripe-fluent user would trust this surface. One type family with a systematic mono micro-label signature (`font-mono text-[10px] uppercase tracking-widest` across every card), semantic token discipline (`--pos/--neg/--dim/--divider`), no gradients, no load choreography (only a 200ms disclosure + 120ms tooltip fade, both neutralized under `prefers-reduced-motion`). The craft moments — `whenLabel()` compressing dates to `'24 W3`, the sticky-first-column table with scroll-revealed edge shadow — read as deliberate, not templated. Residual tells: three chip grammars for one control type, off-token color leaks (`PLAYOFF = "#b8860b"` in `ProductionTimeline.tsx:15`, raw `hsl()` age ramp in `RosterHealthTab.tsx:12-14`), and 9px type in several spots.

**Deterministic scan (Assessment B):** **0 findings, exit 0 (clean)** across all 8 files (~1,050 lines) — no rule fired (no AI palette, gradient text, buzzwords, bounce easing, flat hierarchy, em-dash overuse, etc.). Assessment B validated the detector with a canary (a planted gradient correctly fired) and spot-grepped top trigger patterns, so the clean result is credible. Process note: the originally-specified paths were stale for 5 of 7 files (children live in `web/components/ownerdeepdive/`); Assessment B corrected the paths and the corrected run is authoritative. Detector and LLM agree: no slop. The LLM's residual findings (chip inconsistency, off-token colors, tiny type) are below the detector's rule granularity — expected, not a contradiction.

**Visual overlays:** not attempted — no dev server, login-gated app. No user-visible overlay exists.

## Overall Impression

A well-crafted, on-register surface whose biggest failures aren't visual at all. The verdict-first hero (giant tone-coded letter, roast quote, trophy row) and the dense-but-legible tables deliver the "receipts over opinions" brief. But the two things the product's own success metric depends on — the arrival moment (paste a link mid-argument) and shareability of a specific view — are precisely what's broken: dead-air loading, a lying error state, and tab/filter state that evaporates from the URL. The single biggest opportunity: make the *claim* the shareable unit.

## What's Working

1. **The hero letter as a tappable receipt** (`HeroBand.tsx:84-98`). Verdict first, evidence one tap away, full breakdown one tab away — a textbook progressive-disclosure ladder with `aria-expanded` and the rank beside the letter so the claim is never naked.
2. **Past-picks table scroll craft** (`PastPicksTable.tsx:54-77`): sticky player column, shadow edge only once scrolled, `swipe →` hint hidden at `lg`, totals row, per-column teaching tooltips. "Density without clutter," executed.
3. **Adaptive trades ledger** (`TradesTab.tsx:86-155`): a real 7-column desktop table and a genuinely redesigned stacked mobile card (Value headlined, production metrics as labeled chips) — not a squished table with a scrollbar.

## Priority Issues

**[P0] The arrival path fails silently and lies when it errors.**
- **What:** No `loading.tsx` for the route (none exists in `web/app`); `page.tsx:37-48` catches all exceptions and renders "Franchise not found." for 404, 409 cold-cache, 401, and 500 alike.
- **Why it matters:** The success metric is "someone pastes a link mid-argument." That person gets seconds of nothing, then possibly a false "not found" for a league that merely needs a refresh — the worst possible moment for the product to feel broken.
- **Fix:** Add `web/app/league/[id]/owner/[uid]/loading.tsx` with a skeleton of hero band + tab bar + card outlines. In `page.tsx`, branch on the error: 409 cold → "This league hasn't been graded yet — refresh it" with a link to the refresh flow; real 404 → current copy; else → "Something broke on our end" + retry.
- **Suggested command:** `/impeccable harden`

**[P1] Tab and filter state is not shareable or back-button-safe.**
- **What:** `OwnerDeepDive.tsx:31,86` holds `tab` in `useState`; the trades year filter (`TradesTab.tsx:14`) and chart metric are local-only. `?tab=` is read once, never written.
- **Why it matters:** The argument is "your trades have been trash since 2023"; the receipt is *Trades tab, filtered*. The arguer copies the URL — the rival lands on Overview. The product's core interaction silently drops its payload.
- **Fix:** Write tab (and at minimum the trades year filter) to the URL via shallow `router.replace`; `?tab=trades&year=2023` must reproduce the exact view.
- **Suggested command:** `/impeccable harden`

**[P1] Second-person copy on a third-person page.**
- **What:** "did your trades pan out?" (`ProductionProgressionCard.tsx:29,54`), "What you got / What you gave up" (`:37,40`), "More of your picks…" (`FutureDraftTab.tsx:34-41`), "weeks you started this player" (`PastPicksTable.tsx:112`).
- **Why it matters:** ~10 of 11 viewers are looking at someone *else's* franchise. Second person makes every verdict read as being about the viewer — and wastes the trash-talk register: "Did **Mike's** trades pan out?" is the actual product.
- **Fix:** Thread `detail.owner.owner_name` into these strings; third person by default, second person only if the session user *is* the owner.
- **Suggested command:** `/impeccable clarify`

**[P1] Screen-reader structure is missing: no headings, half-built tab pattern, keyboard-unreachable scroll regions.**
- **What:** Zero `h1`–`h3` on the success path (`CardHead` is a `div`, `ui.tsx:19`; owner name is a `span`, `OwnerLabel.tsx:47`). Tabs have `role="tablist"/"tab"` + `aria-selected` (`OwnerDeepDive.tsx:83-93`) but no `tabpanel`, no `aria-controls`/`id`, no arrow-key roving tabindex. Horizontal scroll containers (`PastPicksTable.tsx:75-79`, `TradesTab.tsx:88`) lack `tabindex="0"` — a keyboard user cannot scroll the 920px table at all.
- **Why it matters:** WCAG AA is an explicit commitment (PRODUCT.md); a screen-reader user gets one flat run of text with a broken widget in the middle.
- **Fix:** `h1` = owner name in `HeroBand`, `h2` = card titles via `CardHead`; complete the ARIA tab pattern (or drop the roles and ship honest buttons); add `tabindex={0}` + `role="region"` + `aria-label` to both scroll wrappers.
- **Suggested command:** `/impeccable audit`

**[P2] One component vocabulary, three chip dialects.**
- **What:** Year filter: bordered pill with `aria-pressed` (`TradesTab.tsx:70-74`). Past-picks season tabs: bordered pill, no ARIA state, different padding (`PastPicksTable.tsx:63-70`). Metric/view switches: borderless inverted `bg-ink text-bg`, no ARIA state (`ProductionTimeline.tsx:123-135`, `ProductionProgressionCard.tsx:11-13`).
- **Why it matters:** Same interaction, three appearances, three accessibility behaviors — the register's "inconsistent component vocabulary" ban, verbatim.
- **Fix:** Extract one `<SegmentControl>` in `ownerdeepdive/ui.tsx` with `role="group"` + `aria-pressed`; use it in all four places.
- **Suggested command:** `/impeccable polish`

**[P2] Mislabeled column: "Avg Pick Value" shows a delta, not an average.**
- **What:** Header reads "Avg Pick Value" (`PastPicksTable.tsx:96-98`) but the cell renders `current_value − avg_slot_value` as a signed delta (`:133`).
- **Why it matters:** A rival auditing "+412" against the Current column will conclude the table is wrong; one apparently-wrong number poisons every other receipt on the page.
- **Fix:** Rename to "vs Slot" (the tooltip already explains the comparison); keep the delta.
- **Suggested command:** `/impeccable clarify`

## Persona Red Flags

**Alex (Power User):**
- No keyboard shortcuts anywhere — no `1–4` tab switching; everything is click-only (`OwnerDeepDive.tsx:85`).
- `PastPicksTable`: 13 columns, no sorting — finding "worst pick ever" means eyeball-scanning Total Pts across seasons.
- `CareerArc` bar values live only in `title` attributes (`CareerArc.tsx:49`) — hover-per-bar to read five charts; unreadable on touch, period.
- Good: whole-row links from ledger to trade detail; rank shown beside the letter without a tap.

**Sam (Accessibility):**
- Everything in the P1 accessibility issue (headings, tab pattern, scroll regions).
- `InfoTooltip` body never announced: `role="tooltip"` without `aria-describedby`; button label is only `info: {title}` (`InfoTooltip.tsx:68-80`); no Escape-to-dismiss (WCAG 1.4.13).
- Contrast: `text-dim/60` ≈ 2.4:1 on light — used for the rank denominator `/{fr.of}` (`HeroBand.tsx:96`) and the " pg" unit (`TrackRecordTab.tsx:80`); `hsl()` age numbers at 11px ≈ 3:1 (`RosterHealthTab.tsx:66`). Base tokens clear AA (`--dim` ≈ 5.1:1, `--pos` ≈ 4.8:1, `--neg` ≈ 6.2:1).
- `ProductionTimeline` SVG is `role="img"` with a label but no non-visual alternative — the chart's entire argument is invisible.
- Good: global `:focus-visible` ring; signed numbers mean color never carries sign alone; win-share bar `aria-hidden` with a text ledger beside it.

**The League Rival (project persona — arrived from the group chat to check "your trades have been trash since 2023"):**
- Lands on Overview (a rating breakdown), not Trades — must discover the tab; the URL-state P1 is this persona's whole problem.
- Once on Trades: fast — career totals, year chips, per-year ledger, one click to any trade's story. Genuinely strong.
- Trust gaps: ledger headers (`Value`, `Toilet`) have no tooltips (`TradesTab.tsx:90-94`) — a semi-lapsed member won't know Value's unit or that Playoff is title-bracket only; `assets_short` truncates (`TradesTab.tsx:106`), hiding which players a deal involved without a click.
- On the phone (a stated primary context): `ProductionTimeline`'s 1060-unit viewBox at ~350px scales its 9–11px SVG labels to ~3–4px — axis, "PLAYOFFS," and departure labels illegible exactly where this user lives (`ProductionTimeline.tsx:24,144,206`).
- Good: OG metadata puts the owner's net value in the link unfurl (`page.tsx:15`) — the trash talk starts before the click.

## Cognitive Load & Emotional Journey

**Cognitive load: moderate (2–3 failures of 8).** Fails: ≤4-options-per-decision — `ProductionProgressionCard` stacks a 3-option view switch above a 5-option metric switch (8 chips governing one chart), and the trades year filter renders All + one chip per season (7 for a 6-year league). Working-memory bridge: RatingReceipt says "See **Overview** for what drives it" as plain text, not a control (`HeroBand.tsx:24`); ledger columns assume the five-metric taxonomy is memorized. Passes: single focus, grouping, hierarchy (the 34px letter is unambiguous), one-thing-at-a-time, progressive disclosure.

**Emotional journey:** Peaks land — the hero (letter, roast quote, rivals, trophies) and "▲ Best heist / ▼ Worst beat" (`TradesTab.tsx:168`) are exactly the brand. The end is flat: the page exits on a spreadsheet, and the draft verdict ("More of your picks have outperformed their draft slot than missed," `FutureDraftTab.tsx:36`) is analyst-brief hedging where "Best heist" swagger belongs. The valley is the entrance: dead-air load, possibly followed by a false "Franchise not found." — the highest-stakes emotional beat in the product is its worst moment.

## Minor Observations

- RatingReceipt's "See Overview" should be a button that switches the tab (`HeroBand.tsx:24`) — the setter is one component up.
- Five stat tiles at `grid-cols-2` orphan the fifth tile at tablet widths (`TradesTab.tsx:30`).
- Four duplicated `ordinal`/`ord` helpers (`HeroBand.tsx:60`, `TrackRecordTab.tsx:7`, `FutureDraftTab.tsx:9`, `PastPicksTable.tsx:8`) — one will drift.
- 9px `Vital` labels (`ui.tsx:28`) and an 8px mobile "Value" label (`TradesTab.tsx:136`) are below any comfortable floor.
- `aria-label="…Tap for the breakdown"` (`HeroBand.tsx:89`) — device-specific verb; "Show" is neutral.
- `Acquired` column mixes casing ("via trade" vs "Owned"), and "Owned" should probably be "Drafted" (`PastPicksTable.tsx:125`).
- Hardcoded `PLAYOFF = "#b8860b"` and theme-blind band fills belong in the token set beside `--pos/--neg/--info`.
- Mobile H2H hides both the win-share bar and the margin column (`TrackRecordTab.tsx:70,77`), losing the "6-6 but a beatdown on points" insight the comment itself brags about.
- Emoji as data (🏆, 🚽) is on-brand and paired with text — keep it. (Detector agrees: no flags.)

## Questions to Consider

1. If success is "someone pastes a link that ends the argument," why isn't the *claim* the shareable unit? Every view state could be URL-addressable — or go further: a "copy receipt" action producing a one-line summary + link formatted for the group chat.
2. The letter is the verdict, but the "why" takes a tap and a tab. What would it cost to put the strongest driver and biggest drag — already computed in `RatingDrivers` (`OverviewTab.tsx:44-45`) — directly under the letter? "B, carried by Championships, dragged by Lineup Skill" settles more arguments than "B."
3. The page grades the owner, but the rival wants the *matchup*. H2H data exists in Track Record — what if the page knew the viewer and led with me-vs-you: head-to-head record, trades between the two of you, margin per game?
