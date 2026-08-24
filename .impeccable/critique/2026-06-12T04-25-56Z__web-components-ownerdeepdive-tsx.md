---
target: owner page
total_score: 22
p0_count: 2
p1_count: 2
timestamp: 2026-06-12T04-25-56Z
slug: web-components-ownerdeepdive-tsx
---
# Critique: Owner page (web/components/OwnerDeepDive.tsx)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Career arc shows no axis/values; semantics only in hover-only title tooltip (CareerArc.tsx:49) |
| 2 | Match System / Real World | 2 | Swing-language (+ prefixes, "Worst beat", "net value" title) over gross received-only data; Toilet Bowl bad-when-high yet green |
| 3 | User Control and Freedom | 2 | Year filter is component state only — not URL-synced, lost on back/share; no column sort |
| 4 | Consistency and Standards | 2 | swing_ktc carries realized received value while trade pages use "Trade Value" for the swing — same label, two semantics |
| 5 | Error Prevention | 3 | Little to prevent; profile save failure and cold-cache 409 handled |
| 6 | Recognition Rather Than Recall | 2 | No metric definitions; Reg/Playoff/Toilet recall-only while /gm has rich inline help |
| 7 | Flexibility and Efficiency | 3 | Rows deep-link to trade pages; no sort, filter not shareable |
| 8 | Aesthetic and Minimalist Design | 2 | Same five metrics rendered three times on one screen (tiles, charts, table columns) |
| 9 | Error Recovery | 3 | "Owner not found" page with back-link adequate |
| 10 | Help and Documentation | 1 | Methodology page exists but unlinked from the most semantics-laden page in the product |
| **Total** | | **22/40** | **Acceptable — significant improvements needed** |

## Anti-Patterns Verdict

LLM assessment: register mostly clean (tokens, mono labels, dense receipts read as deliberate Linear/Vercel craft). But the five metric tiles are the banned hero-metric template verbatim, and the page renders the five-metric vocabulary three times. Second tell: a wall of green + numbers — received-only data still styled as swings, including a "Worst beat" card showing a green positive number.

Deterministic scan: 1 finding across 6 files — broken-image at OwnerLabel.tsx:28 — FALSE POSITIVE (regex matched `<img>` inside a code comment; real tag conditionally rendered with valid src + initial fallback). Owner-page code is detector-clean.

Visual overlays: skipped — no browser automation available; dev server not running. Evidence is source-derived.

## Overall Impression

The receipts table is the right product; everything above it is scaffolding from an earlier version of the app. The page predates realized Trade Value, became-grades, the rich trade detail page, and GM Rating, and absorbed none of them. Craft works; meaning fails. Biggest opportunity: decide what question this page answers now that /gm owns "how good is this manager."

## What's Working

1. Receipts table is the right object, well-made for desktop — dense, mono, tabular nums, every row deep-links, newest-first.
2. Disciplined token system — one CSS-variable palette for light/dark, real :focus-visible ring, year chips with aria-pressed + live count.
3. Restraint — chips hide for single-season; avatar alt="" with adjacent name is correct decorative pattern.

## Priority Issues

- [P0] Career arc semantics unlabeled and structurally misleading. Lifetime production bucketed by trade-made season (owner_view.py:53-65); old seasons always dwarf recent. User misread it this session; the misreading is the natural one. Fix: relabel honestly as vintage view with subcaption + visible values, or recompute points-realized-per-season; demote below receipts. (/impeccable shape)
- [P0] Valence system contradicts received-only data model. signed()/tone() paint gross tallies as net swings: all-green tiles, green "Worst beat", green Toilet Bowl. swing_* field names are lies; ktc_at_trade/ktc_aged dropped at frontend type boundary. Fix: neutral ink for received tallies, green/red only for true comparisons, rename swing_* → received_*, fix "net value" metadata. (/impeccable clarify + API/type alignment)
- [P1] IA predates the app. Receipts come fifth under two screens of aggregates /gm does better. Proposed: GM Rating chip in header (linked), best/worst directly under header, kill five-tile grid → TOTAL footer row on receipts table, surface flipped/became indicator per row, career arc fixed then demoted. (/impeccable shape then craft)
- [P1] Receipts table collapses on phones — fixed columns ≈470px vs 390px viewports; TradeStatTable already has a mobile layout pattern this lacks. (/impeccable adapt)
- [P2] Table and chart invisible to assistive tech — div/Link grid with no header-cell association; chart has zero ARIA, hover-only values, sign by color alone (Math.abs heights). (/impeccable harden)

## Persona Red Flags

- Alex (power user): scrolls past tiles + 25 bars every visit; no sort; filter not URL-synced; "Loading owner…" text instead of existing skeleton (OwnersTab.tsx:131).
- Sam (SR/keyboard): rows announce as text streams; career arc 100% inaccessible; keep a non-color channel when + prefixes are removed.
- League rival on phone (pasted link): crushed 7-column grid, truncated assets, no share-ready verdict block, link preview says "net value" over a gross number.

## Minor Observations

- Best/worst picked by gross received (owner_view.py:88-93) — "Worst beat" = smallest haul; margin-vs-counterparty or realized-vs-at-trade delta would be honest.
- CareerArc doc comment says "three small-multiples" (it's five); !lens.signed branch is dead code.
- assets_short truncates with no expansion affordance.
- Rows could telegraph drillability (quiet chevron on hover).

## Questions to Consider

1. If /gm answers "how good is this manager," what does this page answer that nothing else does? If "show me the receipts," why are receipts fifth?
2. Is best/worst well-defined by received-only value? Should it run on realized-vs-at-trade delta (computed and discarded today)?
3. Is the career arc a vintage chart or a performance chart — would anyone screenshot it? What earns its 25 bars?
