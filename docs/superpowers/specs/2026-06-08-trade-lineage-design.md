# Trade Lineage (Phase 1: Visualization) — Design Spec

**Date:** 2026-06-08
**Epic:** Lineage (#2 of the roadmap). This spec is **Phase 1 (visualization)**; Phase 2 (re-grading that follows flipped assets) is a separate spec, informed by what these trees reveal.
**Status:** Design — pending user review before implementation plan

## Problem

When a traded asset gets **flipped**, our grades and stories don't follow it.
Bobster traded for Saquon Barkley and the grade reads "got nothing" because he
flipped Barkley 9 days later; a pick that became Makai Lemon only credits the
final owner. **What a trade ultimately became is invisible.** That's both a
correctness gap and a missed trash-talk payoff ("he turned Saquon into a rookie
and a backup WR").

## Goal

On the trade detail page, show a **"what this trade became" tree**: for each
asset a side received, follow that owner's subsequent flips forward in time and
show what it turned into, down to the players they hold today (and whether they
still hold them).

## Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| Direction | **C: both** — visualization first (this spec), re-grading later (Phase 2). |
| Phase-1 hero | **Trade-outcome tree on the trade detail page.** (A standalone per-asset journey page is a Phase-1.5 follow-on.) |
| Presentation | **Indented tree** — nested vertical outline, mobile-friendly. |
| Semantics | **Owner-anchored, forward in time.** For each asset a side *received*, follow *that owner's* flips: when they flip it, its children are what *they got back*. |
| On-roster vs dropped | **In scope for Phase 1** — terminal players show whether the owner still rosters them. |

## Semantics (the core model)

A node is one asset in one owner's possession. Starting from each asset a side
**received** in this trade:
- If the owner **later traded it away**, in that later trade the owner gave this
  asset and received others; those others are this node's **children** (what it
  "became" for this owner). Recurse on each child.
- A branch is **terminal** when the owner did not flip the asset again:
  - **player** the owner still rosters → `on_roster`
  - **player** no longer on the owner's roster → `dropped`
  - **pick** that has been drafted (resolved to a player) → recurse into that
    player (which is then `on_roster`/`dropped`)
  - **pick** not yet drafted → `undrafted`

Traversal is strictly forward in time (trades ordered by date), so it always
terminates and cannot cycle.

**Multi-asset flips (package semantics):** when an owner moves asset A in a trade
where they also gave other assets and got back several, A's children are the
*full set* of assets the owner received in that flip, and the flip edge is
labeled with what they gave ("flipped Barkley + 2026 2nd, got C, D"). If two of
this trade's roots leave in the same flip, both show that same return package
(it is the truthful "this package became C + D"). Precise 1:1 attribution within
a package is not attempted in Phase 1; collapsing duplicate packages is a later
refinement.

## Engine — `src/sleeper_dynasty/engine/lineage.py` (pure, net-new)

- `build_trade_lineage(trade, resolved_trades, current_holders) -> dict[user_id, list[LineageNode]]`
  - `trade`: the `ResolvedTrade` to root on.
  - `resolved_trades`: the full chain (already in the cache).
  - `current_holders: dict[str, str]` — `player_id -> current owner user_id`.
- **Asset identity** for matching across trades: players by `player_id`; picks by
  the `(original_owner_user_id, season, round)` tuple (the same identity the
  resolver already uses).
- **Algorithm:** build an index of "later given-by-owner" events per asset
  identity (ordered by trade date). For each received asset on each side, walk
  forward through the *same owner's* later flips; at each flip, the children are
  the assets that owner received in that flip; recurse. A pick resolved to a
  player (the engine already annotates `drafted_player_id`/`via_pick`) becomes a
  one-child transition into that player. Terminal labeling uses `current_holders`.
- `LineageNode` (new dataclass, `to_dict()`):
  ```
  label: str                 # "Saquon Barkley" | "2026 2nd pick"
  kind: "player" | "pick"
  flipped_at: str | None      # date the owner flipped it, else None (terminal)
  terminal_state: "on_roster" | "dropped" | "undrafted" | None  # None when flipped
  became_player: str | None   # for a pick that resolved to a player
  children: list[LineageNode]
  ```
- Computed entirely from data already in the cache plus the new `current_holders`
  map — no per-request data pull. Fully unit-testable on fixtures.

## Current-holder data — refresh + cache

- During refresh, fetch the **current league's** rosters
  (`SleeperClient.get_rosters(current_league_id)` — each `Roster` already carries
  `owner_id` and `players`) and build `current_holders: dict[player_id, owner_user_id]`.
- Store `current_holders` on `ChainCacheEntry` (new field, `field(default_factory=dict)`,
  backward compatible: a pre-migration cache lacks it and lineage simply labels
  every terminal player `dropped` until the next refresh — acceptable, and the
  cold-start contract is unchanged).

## API

- New recursive Pydantic model `LineageNode` mirroring the dataclass.
- `TradeDetailResp` gains `lineage: dict[str, list[LineageNode]]` (keyed by
  user_id), built in `trade_view.build_trade_detail` from the cache entry's
  `resolved_trades` + `current_holders`. No new endpoint; the page already
  fetches the trade detail.

## Frontend — `web/components/TradeLineage.tsx`

- A new **"Where it went"** section on the trade detail page (below the story /
  receipts), rendering the indented tree per side: each node a chip, children
  nested one level deeper, with `flipped_at` as a dim mono note on flip edges and
  a terminal badge per leaf:
  - `on_roster` → green "on roster"
  - `dropped` → dim "dropped"
  - `undrafted` → dim "not drafted yet"
  - pick→player shows "→ {became_player}".
- Non-interactive in Phase 1 (chip click-through to a full asset-journey page is
  the Phase-1.5 follow-on). Stacks cleanly on mobile.
- If a side's lineage is just the received assets with no flips, it renders a
  flat list of terminal nodes (still useful: shows kept/dropped/undrafted).

## Testing

- **Engine** (pure, fixtures):
  - a flip produces children = what the owner received back;
  - a multi-hop chain (flip → flip) nests correctly;
  - a pick that resolved to a player becomes a `became_player` transition that
    then carries the player's `on_roster`/`dropped` state;
  - terminal labeling: `on_roster` when `current_holders[pid] == owner`,
    `dropped` otherwise, `undrafted` for an unresolved pick;
  - an asset never flipped → a single terminal node;
  - date ordering and no infinite loop on contrived inputs.
- **Cache:** `current_holders` round-trips; a pre-migration entry (no field)
  still loads.
- **Frontend:** vitest render of a fixture tree — nesting depth, the three
  terminal badges, the pick→player label.

## Out of scope (this phase)

- **Phase 2 re-grading** — changing the trade grade to follow flipped assets.
- Standalone **per-asset journey page** + chip click-through (Phase 1.5).
- Lineage for picks/players acquired outside trades (waivers/FA) — only
  trade-to-trade lineage is followed.

## Open questions

None blocking. Exact terminal-badge copy and how deep to auto-expand vs collapse
very long chains are tuned during implementation.
