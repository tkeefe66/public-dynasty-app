# Group-Chat Receipts — Design

**Date:** 2026-07-10
**Status:** Approved
**Origin:** `/impeccable critique` of the owner franchise page (snapshot
`.impeccable/critique/2026-07-10T12-54-44Z__web-components-ownerdeepdive-tsx.md`),
"Questions to Consider" 1–3. The product's success metric is "an argument in
the group chat ends with someone pasting a link" — these three features make
the claim itself the shareable unit.

Three features, one spec (they share primitives). **Build order: 2 → 1 → 3.**

---

## Feature 2 — Driver/drag line under the hero letter

**What:** one line under the Franchise letter/rank in `HeroBand`:
`carried by Championships · dragged by Lineup Skill`.

**Data:** deterministic, computed client-side from the `FranchiseRating`
breakdown already in the owner-detail payload. No API changes. No LLM.

**Design:**

- Extract the top-contributor logic from `OverviewTab`'s `RatingDrivers`
  into a pure helper in `web/components/ownerdeepdive/util.tsx`:
  `ratingDrivers(breakdown) → { driver: string | null, drag: string | null }`.
  Driver = signal with the largest positive contribution; drag = most
  negative. Reuse the signal display-name map `OverviewTab` already uses
  (export it; do not duplicate). `OverviewTab` switches to the shared helper.
- **Omission rules:** no positive signal → no driver half; no negative
  signal → no drag half; both missing or no rating → no line at all.
- **Render:** `HeroBand`, directly under the letter/rank, Whisper-Label
  voice (10px uppercase mono, `text-dim`). Static text — the letter's
  RatingReceipt and the Overview tab remain the drill-ins. Both themes,
  no new tokens.

**Tests:** unit tests on `ratingDrivers` (both-present / driver-only /
drag-only / empty breakdown); one `HeroBand` render assertion; existing
`OverviewTab` tests keep passing after the extraction.

---

## Feature 1 — Copy receipt (owner page + trade detail)

**What:** a one-tap action that copies `<claim>\n<url>` formatted for the
group chat. The claim tracks the current view — the receipt IS what you're
pointing at.

**Approach:** deterministic template builders + one shared copy primitive.
(LLM-composed receipts rejected: latency/cost for a paste action, and
receipts must match the on-screen numbers exactly.)

**Components:**

1. **`ReceiptButton`** (new, `web/components/ReceiptButton.tsx`, client):
   - Props: `claim: string` (or a `() => string` getter so composition
     happens at tap time), plus optional `label`.
   - On tap: compose `claim + "\n" + window.location.href`. On
     coarse-pointer devices with `navigator.share`, share-sheet the text;
     else `navigator.clipboard.writeText` with a ~2s `Copied ✓` state;
     if clipboard is unavailable/rejected, show the text pre-selected in a
     small popover for manual copy (no toast infrastructure).
   - Styling: quiet mono action (`⧉ copy receipt`), token-only, both
     themes, focus-visible ring inherited from globals.

2. **Owner-page builder** (pure, `web/lib/receipts.ts`):
   `ownerReceipt(detail, activeTab, filters) → string`, one template per tab:
   - **Overview:** `Mike: B franchise, 3rd of 11 — carried by Championships`
     (reuses `ratingDrivers`).
   - **Trades** (respects the year filter): `Mike's 2023 trades: −1,240
     Trade Value across 6 deals` — sums the same filtered ledger rows the
     five-metric strip shows.
   - **Track Record:** titles / all-time record / best finish line.
   - **Outlook:** roster-value rank line (only when `detail.outlook`
     exists; otherwise fall back to the Overview claim).
   - **Cold/missing rating:** neutral fallback — owner name + league line.
   - Five-metric vocabulary only; the string "KTC" never appears.
   - URL comes from the live location — the tab/year query params are
     already URL-synced, so the link reproduces the exact view.
3. **Trade-detail builder:** `tradeReceipt(view) → string` from the trade
   response's existing verdict data: sides + headline head-to-head
   (`104 vs 56`) + grade and became-grade.

**Placement:** owner page — one `ReceiptButton` at the right end of the tab
bar (claim recomputes as tab/filters change); trade detail — beside the
verdict headline.

**Tests:** builders are pure — unit-test every tab/filter shape including
cold fallback; component test for `ReceiptButton` with mocked
clipboard/share (success, rejection, share-path selection).

---

## Feature 3 — "vs You" matchup band

**What:** a slim card between `HeroBand` and the tab bar answering the
rival's actual question: me vs you. Auto-resolves the viewer; falls back to
a picker.

**Data:** zero backend changes. `head_to_head: list[H2HView]` and
`OwnerTradeRow.counterparties: list[OwnerRef]` are already on the
owner-detail response.

**Components:**

1. **`useViewerOwner(detail)`** (client hook): calls the existing `getMe()`
   (same as `DashboardClient`), matches `me.sleeper_user_id` against the
   league's owners, returns the viewer-as-owner or `null`. No new API.
2. **`VsYouBand`** (new, `web/components/ownerdeepdive/`):
   - **Rival selection:** auto = resolved viewer when viewer ≠ page owner;
     otherwise an owner picker (`SegmentControl`-style, "compare vs…").
     Viewer *is* the page owner → collapse to the picker framed as
     "size up a rival". Manual pick always available to override auto.
   - **Content rows:**
     - H2H: W-L, avg margin per game (from `H2HView` PF/PA/games),
       direction-aware copy — "You own Mike: 9–3, +14.2 a game" vs
       "Mike owns you…".
     - Trades between the pair: count + net Trade Value swing, sign
       flipped so it reads from the viewer's side.
     - "Full head-to-head →" button jumping to the Track Record tab
       (same `selectTab` mechanism as "See Overview").
   - **Empty handling:** no games between → trades row only; no trades →
     H2H row only; both empty → hide the band entirely. Unresolved viewer
     and no pick yet → render the picker row only (no placeholder stats).
   - Accessible: real headings hierarchy under the page h1, the picker
     carries `aria-pressed` via `SegmentControl`, band is plain content
     (no live regions needed).
3. **Pure selectors** (in `ownerdeepdive/util.tsx` or `web/lib/`):
   H2H lookup by opponent uid, counterparty filter + swing sum, and the
   direction-copy formatter — all unit-testable without render.

**Tests:** unit tests for the three selectors (win/lose/tie direction,
sign flipping, empty cases); render tests for auto-resolved, picker,
viewer-is-owner, and hidden-band states; `getMe()` mocked.

---

## Cross-cutting

- **Voice:** candid, insider, numbers-first (PRODUCT.md). Receipts and
  vs-copy state facts with swagger, never hedge.
- **Error handling:** every new fetch-dependent piece (`getMe()` in the
  hook) fails silent to the picker path — the page never degrades below
  today's behavior. Clipboard failures surface on the button itself.
- **No new tokens, no new routes, no backend changes.** All new UI from
  existing tokens/primitives (`SegmentControl`, Whisper Labels, One Ink
  Button recipe where a CTA is needed).
- **Order of work:** Feature 2 (helper feeds Feature 1's Overview
  template) → Feature 1 → Feature 3. Each lands with its tests; one
  branch (`group-chat-receipts`), sequential commits.
