# Owner Deep-Dive — design

Date: 2026-06-07
Branch: `feat/owner-section`
Status: approved (pending spec review)

## Problem

The Owners tab (`web/components/OwnersTab.tsx`) is a 3-column grid of ~10-12
identical owner cards. Two problems:

1. **Redundant with the dashboard.** The dashboard's `StandingsTable` is already
   a denser, sortable, ranked leaderboard with more columns, and it already
   links to each owner's detail page. The Owners tab shows a strict subset of
   the same numbers in a less useful form.
2. **Hits an "identical card grid" anti-pattern** and uses sub-legible type
   (8px uppercase labels), against PRODUCT.md's "density without clutter /
   tabular / Linear-Vercel restraint."

The owner detail page (`web/app/league/[id]/owner/[uid]/page.tsx`) is the actual
deep dive but is currently bare: three stat tiles, a KTC-only career chart, and
best/worst trades rendered as raw ID strings.

## Goal

Reframe the Owners surface from a shallow index into a **deep-dive workspace**.
The spine, decided with the user, is **(A) the career story + (B) every trade,
drillable** — the page you open to understand an owner's trading history and to
win an argument about a specific deal.

## Structure

Master-detail.

- **Desktop:** two panes. Left: roster rail (~240px). Right: deep-dive pane.
- **Mobile:** collapses to a roster list; tapping an owner navigates to the
  full-page deep dive (no side-by-side). This is the natural responsive
  degradation of master-detail.
- **Shareable URL:** `/league/[id]/owner/[uid]` stays and renders the *same*
  deep-dive pane component, so a link pasted into the group chat still works.
  Selecting an owner in the Owners tab updates the route as well.

This honors the cold-start contract unchanged: the deep-dive data comes from the
already-graded `ChainCache`; no new refresh flow.

## Roster rail (left pane)

Replaces the card grid. Compact selectable rows, sorted by rank:

`#rank · avatar · name · grade pill`

The currently-selected owner is highlighted. No search/filter (≈12 owners; YAGNI).
Each row is a real link/button with a visible focus ring (reuse the existing
`--ringfocus` pattern).

## Deep-dive pane (right pane) — top to bottom

1. **Identity header** — avatar, name, team, rank, grade pill, and the voice
   layer: archetype, roast, rivals (from `OwnerProfile`). The profile **Edit**
   button moves here and opens the existing `ProfileEditor` for this owner.
   (This is where the old card's edit affordance relocates.)
2. **Three-lens totals** — KTC / Production / Impact tiles
   (`totals_by_lens.ktc / .production / .impact`). Honors "three lenses,
   never one."
3. **Career arc** — three small per-season bar charts side by side
   (KTC / Production / Impact), all visible at once (small-multiples, not a
   toggle). Replaces today's KTC-only `CareerArc`.
4. **Best & worst deal** — a highlight pair (best heist / worst beat), rendered
   as real cards linking to the trade page (not raw ID strings).
5. **Every trade (receipts)** — a drillable table of every trade this owner
   made. Each row: date/season + week, counterparty(ies) + short assets, and
   **this owner's** KTC swing / production swing / impact. Default sort newest
   first. Rows link to the existing `/league/[id]/trade/[id]` page. No inline
   expand.

## Backend changes (`api/`)

All in `api/app/services/owner_view.py` + `api/app/models/owner.py`.

- **Per-season impact.** The `by_season` aggregation currently tracks
  `net_ktc`, `net_production`, `trades`. Add per-season `impact` (the loop
  already computes per-trade `impact = decisive_starts + playoff_starts`; add it
  to the season row). Extend `SeasonArc` with an `impact` field. This powers the
  3rd small-multiple.
- **Per-owner trade list.** While looping the owner's resolved trades, build a
  list of trade rows from *this owner's* perspective. Each row:
  - `trade_id`, `date` (`traded_at[:10]`), `season`, `week`
  - `counterparties`: the other parties' `owner_ref`s (exclude this user)
  - `assets_short`: what **this owner received** in the trade, via
    `_format_assets_short(side)` for this user's side (more meaningful on a
    per-owner row than the dashboard's generic two-side summary)
  - `swing_ktc`: `snapshot_value_swing[user_id]`
  - `swing_prod`: `hindsight_production_swing[user_id]`
  - `impact`: `decisive_starts + playoff_starts` for this user
  > Note: the dashboard's `_latest_trades` computes swings for the *first* party
  > only (`first_uid`), so it cannot be reused directly here — the deep-dive
  > rows must key swings to this `user_id`.
- New Pydantic model `OwnerTradeRow` and a `trades: list[OwnerTradeRow]` field
  on `OwnerDetailResp`. Keep `best_trade_id` / `worst_trade_id`.
- Mirror the new shapes in `web/lib/types.ts` (`SeasonArc.impact`,
  `OwnerTradeRow`, `OwnerDetailResp.trades`).

## Frontend changes (`web/`)

- **`OwnerDeepDive`** — new pane component containing the 5 sections above.
  Reused by both the Owners tab and the `/owner/[uid]` page. Takes the
  owner-detail data + the owner's `StandingRow` (for rank/grade) + profile +
  an `onProfilesChange` callback for the inline editor.
- **`OwnersTab`** — rebuilt as roster-rail + pane master-detail; the card grid
  is deleted. On desktop, selecting a rail row swaps the pane and updates the
  route; on mobile the rail rows link to the full owner page.
- **Career small-multiples** — new component (extend or replace `CareerArc`)
  rendering three compact per-season bar charts.
- **Receipts table** — new component; reuse `OwnerLabel variant="compact"` for
  counterparties and the existing pos/neg tone conventions.
- **Identity header** — new component with the inline Edit affordance wrapping
  `ProfileEditor`.
- **Legibility fixes** — replace the old 8px labels with readable sizes; verify
  body/label contrast ≥ 4.5:1 (≥ 3:1 for large) in both light and dark themes.
- The standalone owner page (`app/league/[id]/owner/[uid]/page.tsx`) is
  simplified to render `OwnerDeepDive`.

## Testing

- **Backend (pytest):** `owner_view` builds per-season impact and a per-owner
  trade list with swings keyed to the right `user_id`; an owner who never traded
  returns empty arc + empty trades; counterparties exclude the owner.
- **Frontend (vitest):** `OwnerDeepDive` renders all five sections from a
  fixture; receipts rows link to the correct trade URL; empty-trades owner shows
  an empty state; roster rail marks the selected owner. Reuse existing
  testing-library setup (`tests/vitest.config.ts`).
- **E2E (Playwright, optional):** Owners tab → select owner → pane updates;
  deep-link to `/owner/[uid]` renders the same pane.

## Out of scope

- Head-to-head / rivalry win-loss records between owners (the user's "C").
- Sorting/filtering the receipts table beyond the default newest-first sort.
- Any changes to the Dashboard or Trades tabs.
- Changes to the cold-start / refresh flow or cache contract.

## Key files

- `web/components/OwnersTab.tsx` — rebuilt
- `web/components/OwnerDeepDive.tsx` — new
- `web/components/CareerArc.tsx` — extended/replaced (small-multiples)
- `web/components/ProfileEditor.tsx` — reused, invoked from the new header
- `web/app/league/[id]/owner/[uid]/page.tsx` — simplified to use `OwnerDeepDive`
- `web/lib/types.ts` — new shapes
- `api/app/services/owner_view.py` — per-season impact + per-owner trade list
- `api/app/models/owner.py` — `OwnerTradeRow`, extended `SeasonArc` / `OwnerDetailResp`
